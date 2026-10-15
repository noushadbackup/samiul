"""Exact and near-duplicate detection, persisted in SQLite.

Three layers, checked in order against already ACCEPTED texts:

1. Exact duplicate – SHA-256 of ``exact_key(text)`` (Unicode NFC, zero-width
   characters removed, whitespace collapsed, spacing around punctuation
   normalised). Nothing else is changed, so this only matches truly identical
   comments.
2. Skeleton near-duplicate – SHA-256 of ``skeleton_key(text)`` (casefolded,
   punctuation/whitespace/emoji removed, long letter runs collapsed). Catches
   "এই লোকটা একদম বোকা" vs "এই লোকটা একদম বোকা।" vs "এই লোক টা একদম বোকা".
3. MinHash-LSH near-duplicate – character n-gram shingles of the skeleton,
   128-permutation MinHash, 32 LSH bands stored in SQLite. Candidates sharing a
   band bucket are verified with exact Jaccard similarity (default >= 0.80).
   Texts shorter than ``near_dup_min_length`` skip this layer because n-gram
   similarity is unreliable for very short strings.

The index is global (all platforms, all batches) by default, so cross-platform
duplicates are caught. Only hashes of accepted texts are stored, so a rejected
comment never blocks a later valid one.
"""

from __future__ import annotations

import hashlib
import json
import random
import struct
from dataclasses import dataclass
from typing import Optional

from processing.normalize import exact_key, skeleton_key
from storage.database import Database

_MERSENNE_PRIME = (1 << 61) - 1
_MAX_HASH = (1 << 32) - 1


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _h64(data: str) -> int:
    return struct.unpack("<Q", hashlib.blake2b(data.encode("utf-8"), digest_size=8).digest())[0]


def shingles(skeleton: str, n: int) -> set[str]:
    if len(skeleton) <= n:
        return {skeleton} if skeleton else set()
    return {skeleton[i : i + n] for i in range(len(skeleton) - n + 1)}


def jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)


class MinHasher:
    """Deterministic MinHash (fixed seed, so persisted LSH buckets stay valid across runs)."""

    def __init__(self, num_perm: int = 128, seed: int = 1729):
        rng = random.Random(seed)
        self.num_perm = num_perm
        self.params = [
            (rng.randrange(1, _MERSENNE_PRIME), rng.randrange(0, _MERSENNE_PRIME)) for _ in range(num_perm)
        ]

    def signature(self, items: set[str]) -> list[int]:
        hashes = [_h64(s) for s in items]
        if not hashes:
            return [_MAX_HASH] * self.num_perm
        sig = []
        for a, b in self.params:
            sig.append(min(((a * h + b) % _MERSENNE_PRIME) & _MAX_HASH for h in hashes))
        return sig


@dataclass
class DedupResult:
    status: Optional[str]  # None | "duplicate" | "near_duplicate"
    matched_key: Optional[str] = None
    detail: Optional[str] = None
    similarity: Optional[float] = None


@dataclass
class TextKeys:
    exact_hash: str
    skeleton: str
    skeleton_hash: str


class DedupIndex:
    def __init__(self, db: Database, cfg: dict | None = None, enabled: bool = True, near_enabled: bool = True):
        cfg = cfg or {}
        self.db = db
        self.enabled = enabled
        self.near_enabled = near_enabled
        self.scope = cfg.get("scope", "global")
        self.n = int(cfg.get("ngram_size", 3))
        self.num_perm = int(cfg.get("num_permutations", 128))
        self.bands = int(cfg.get("bands", 32))
        if self.num_perm % self.bands:
            raise ValueError("dedup.num_permutations must be divisible by dedup.bands")
        self.rows = self.num_perm // self.bands
        self.threshold = float(cfg.get("jaccard_threshold", 0.8))
        self.min_len = int(cfg.get("near_dup_min_length", 12))
        self.hasher = MinHasher(self.num_perm)
        self._ensure_params()

    # The LSH index depends on these parameters; rebuild it if they change.
    def _ensure_params(self) -> None:
        params = json.dumps({"n": self.n, "perm": self.num_perm, "bands": self.bands})
        stored = self.db.get_meta("lsh_params")
        if stored != params:
            if stored is not None:
                self.db.clear_lsh()
                for row in self.db.iter_hashed_records():
                    if row["skeleton"] and len(row["skeleton"]) >= self.min_len:
                        self.db.add_lsh(self._bands(row["skeleton"]), row["record_key"], row["batch_id"])
            self.db.set_meta("lsh_params", params)
            self.db.commit()

    def _scope_batch(self, batch_id: str) -> Optional[str]:
        return batch_id if self.scope == "batch" else None

    def keys(self, text: str) -> TextKeys:
        sk = skeleton_key(text)
        return TextKeys(exact_hash=sha256(exact_key(text)), skeleton=sk, skeleton_hash=sha256(sk))

    def _bands(self, skeleton: str) -> list[tuple[int, int]]:
        sig = self.hasher.signature(shingles(skeleton, self.n))
        out = []
        for b in range(self.bands):
            chunk = sig[b * self.rows : (b + 1) * self.rows]
            bucket = _h64(",".join(map(str, chunk))) & 0x7FFFFFFFFFFFFFFF
            out.append((b, bucket))
        return out

    def check(self, keys: TextKeys, batch_id: str) -> DedupResult:
        if not self.enabled:
            return DedupResult(None)
        scope = self._scope_batch(batch_id)
        hit = self.db.find_hash("exact", keys.exact_hash, scope)
        if hit:
            return DedupResult("duplicate", hit, "exact_normalized_match", 1.0)
        if not self.near_enabled:
            return DedupResult(None)
        if keys.skeleton:
            hit = self.db.find_hash("skeleton", keys.skeleton_hash, scope)
            if hit:
                return DedupResult("near_duplicate", hit, "skeleton_match", 1.0)
        if len(keys.skeleton) >= self.min_len:
            mine = shingles(keys.skeleton, self.n)
            best: tuple[float, Optional[str]] = (0.0, None)
            for cand in self.db.lsh_candidates(self._bands(keys.skeleton), scope):
                other = self.db.skeleton_of(cand)
                if not other:
                    continue
                sim = jaccard(mine, shingles(other, self.n))
                if sim > best[0]:
                    best = (sim, cand)
            if best[1] is not None and best[0] >= self.threshold:
                return DedupResult("near_duplicate", best[1], "minhash_lsh_jaccard", round(best[0], 4))
        return DedupResult(None)

    def register(self, keys: TextKeys, record_key: str, batch_id: str, author: Optional[str]) -> None:
        self.db.add_hash("exact", keys.exact_hash, record_key, batch_id)
        if keys.skeleton:
            self.db.add_hash("skeleton", keys.skeleton_hash, record_key, batch_id)
        if len(keys.skeleton) >= self.min_len:
            self.db.add_lsh(self._bands(keys.skeleton), record_key, batch_id)
        if author:
            self.db.add_hash_author(keys.exact_hash, author)

    def note_copy(self, original_exact_hash: Optional[str], author: Optional[str]) -> int:
        """Record another author posting an already-accepted text (or a near copy of it).

        Returns the number of distinct authors seen for the original text.
        """
        if not author or not original_exact_hash:
            return 0
        return self.db.add_hash_author(original_exact_hash, author)
