"""SQLite scraper state.

Tables
------
meta            schema version + dedup index parameters
batches         one row per collection batch (domain, target, status, timing)
sources         creators / pages / channels / accounts seen
posts           videos / posts / reels discovered per domain + comment cursor
comments        every processed item (accepted + rejected) with its full record
processed_ids   (platform, item_id) already processed => never recollected
text_hashes     exact + skeleton hashes of accepted texts (duplicate detection)
text_hash_authors  distinct anonymous authors per exact hash (bot/copy detection)
lsh_bands       MinHash LSH buckets of accepted texts (near-duplicate detection)
crawl_state     discovery cursors per platform/domain/keyword
quota_usage     API quota units / requests spent per platform per day
errors          API and processing errors
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Optional

from core.models import Post, Source

SCHEMA_VERSION = "1"

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE IF NOT EXISTS batches (
    batch_id TEXT PRIMARY KEY,
    domain TEXT NOT NULL,
    platforms TEXT NOT NULL,
    target INTEGER NOT NULL,
    status TEXT NOT NULL,
    output_name TEXT,
    keywords_json TEXT,
    config_json TEXT,
    created_at TEXT,
    updated_at TEXT,
    finished_at TEXT,
    elapsed_seconds REAL DEFAULT 0,
    runs INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS sources (
    platform TEXT NOT NULL,
    source_id TEXT NOT NULL,
    source_name TEXT,
    source_type TEXT,
    url TEXT,
    first_seen_at TEXT,
    PRIMARY KEY (platform, source_id)
);

CREATE TABLE IF NOT EXISTS posts (
    platform TEXT NOT NULL,
    post_id TEXT NOT NULL,
    domain TEXT NOT NULL,
    source_id TEXT,
    source_name TEXT,
    source_type TEXT,
    title TEXT,
    text TEXT,
    url TEXT,
    created_at TEXT,
    like_count INTEGER,
    comment_count INTEGER,
    discovered_via TEXT,
    extra_json TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    next_cursor TEXT,
    items_seen INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    discovered_at TEXT,
    updated_at TEXT,
    PRIMARY KEY (platform, post_id, domain)
);
CREATE INDEX IF NOT EXISTS idx_posts_status ON posts(platform, domain, status);

CREATE TABLE IF NOT EXISTS comments (
    record_key TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL,
    platform TEXT NOT NULL,
    domain TEXT NOT NULL,
    record_type TEXT,
    post_id TEXT,
    source_id TEXT,
    status TEXT NOT NULL,
    rejection_reason TEXT,
    rejection_detail TEXT,
    language TEXT,
    text_length INTEGER,
    author_anonymous_id TEXT,
    exact_hash TEXT,
    skeleton TEXT,
    record_json TEXT NOT NULL,
    processed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_comments_batch ON comments(batch_id, status);
CREATE INDEX IF NOT EXISTS idx_comments_post ON comments(batch_id, platform, post_id);
CREATE INDEX IF NOT EXISTS idx_comments_source ON comments(batch_id, platform, source_id);

CREATE TABLE IF NOT EXISTS processed_ids (
    platform TEXT NOT NULL,
    item_id TEXT NOT NULL,
    batch_id TEXT,
    status TEXT,
    processed_at TEXT,
    PRIMARY KEY (platform, item_id)
);

CREATE TABLE IF NOT EXISTS text_hashes (
    hash_type TEXT NOT NULL,
    hash TEXT NOT NULL,
    record_key TEXT NOT NULL,
    batch_id TEXT NOT NULL,
    created_at TEXT,
    PRIMARY KEY (hash_type, hash, batch_id)
);

CREATE TABLE IF NOT EXISTS text_hash_authors (
    hash TEXT NOT NULL,
    author TEXT NOT NULL,
    PRIMARY KEY (hash, author)
);

CREATE TABLE IF NOT EXISTS lsh_bands (
    band INTEGER NOT NULL,
    bucket INTEGER NOT NULL,
    record_key TEXT NOT NULL,
    batch_id TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_lsh ON lsh_bands(band, bucket);

CREATE TABLE IF NOT EXISTS crawl_state (
    platform TEXT NOT NULL,
    domain TEXT NOT NULL,
    scope_key TEXT NOT NULL,
    state_json TEXT,
    exhausted INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT,
    PRIMARY KEY (platform, domain, scope_key)
);

CREATE TABLE IF NOT EXISTS quota_usage (
    platform TEXT NOT NULL,
    day TEXT NOT NULL,
    units INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (platform, day)
);

CREATE TABLE IF NOT EXISTS errors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id TEXT,
    platform TEXT,
    scope TEXT,
    error_type TEXT,
    message TEXT,
    http_status INTEGER,
    occurred_at TEXT
);
"""


def utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


class Database:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        if str(path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path), timeout=30)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.executescript(SCHEMA)
        self.set_meta("schema_version", SCHEMA_VERSION)
        self.conn.commit()

    def close(self) -> None:
        self.conn.commit()
        self.conn.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        try:
            yield self.conn
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def commit(self) -> None:
        self.conn.commit()

    def rollback(self) -> None:
        self.conn.rollback()

    # ------------------------------------------------------------------- meta
    def get_meta(self, key: str) -> Optional[str]:
        row = self.conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else None

    def set_meta(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )

    # ---------------------------------------------------------------- batches
    def next_batch_id(self, domain: str) -> str:
        rows = self.conn.execute(
            "SELECT batch_id FROM batches WHERE domain=?", (domain,)
        ).fetchall()
        nums = []
        for r in rows:
            suffix = r["batch_id"].rsplit("_", 1)[-1]
            if suffix.isdigit():
                nums.append(int(suffix))
        return f"{domain}_{(max(nums) + 1) if nums else 1:03d}"

    def create_batch(
        self,
        batch_id: str,
        domain: str,
        platforms: list[str],
        target: int,
        keywords: dict,
        config: dict,
        output_name: Optional[str] = None,
    ) -> None:
        now = utcnow()
        self.conn.execute(
            """INSERT INTO batches(batch_id, domain, platforms, target, status, output_name,
               keywords_json, config_json, created_at, updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (
                batch_id,
                domain,
                ",".join(platforms),
                target,
                "running",
                output_name,
                json.dumps(keywords, ensure_ascii=False),
                json.dumps(config, ensure_ascii=False, default=str),
                now,
                now,
            ),
        )
        self.conn.commit()

    def get_batch(self, batch_id: str) -> Optional[dict]:
        row = self.conn.execute("SELECT * FROM batches WHERE batch_id=?", (batch_id,)).fetchone()
        return dict(row) if row else None

    def latest_batch(self, domain: str, unfinished_only: bool = False) -> Optional[dict]:
        sql = "SELECT * FROM batches WHERE domain=?"
        if unfinished_only:
            sql += " AND status != 'completed'"
        sql += " ORDER BY created_at DESC, batch_id DESC LIMIT 1"
        row = self.conn.execute(sql, (domain,)).fetchone()
        return dict(row) if row else None

    def list_batches(self) -> list[dict]:
        return [dict(r) for r in self.conn.execute("SELECT * FROM batches ORDER BY created_at").fetchall()]

    def update_batch(self, batch_id: str, **fields: Any) -> None:
        if not fields:
            return
        fields["updated_at"] = utcnow()
        cols = ", ".join(f"{k}=?" for k in fields)
        self.conn.execute(f"UPDATE batches SET {cols} WHERE batch_id=?", (*fields.values(), batch_id))
        self.conn.commit()

    def add_batch_elapsed(self, batch_id: str, seconds: float) -> None:
        self.conn.execute(
            "UPDATE batches SET elapsed_seconds = COALESCE(elapsed_seconds,0) + ?, runs = COALESCE(runs,0) + 1, updated_at=? WHERE batch_id=?",
            (seconds, utcnow(), batch_id),
        )
        self.conn.commit()

    # ---------------------------------------------------------- sources/posts
    def upsert_source(self, src: Source) -> None:
        self.conn.execute(
            """INSERT INTO sources(platform, source_id, source_name, source_type, url, first_seen_at)
               VALUES(?,?,?,?,?,?)
               ON CONFLICT(platform, source_id) DO UPDATE SET
                 source_name=COALESCE(excluded.source_name, sources.source_name),
                 source_type=COALESCE(excluded.source_type, sources.source_type),
                 url=COALESCE(excluded.url, sources.url)""",
            (src.platform, src.source_id, src.source_name, src.source_type, src.url, utcnow()),
        )

    def add_post(self, post: Post, domain: str) -> bool:
        """Insert a discovered post. Returns True if it is new for this domain."""
        now = utcnow()
        cur = self.conn.execute(
            """INSERT OR IGNORE INTO posts(platform, post_id, domain, source_id, source_name, source_type,
               title, text, url, created_at, like_count, comment_count, discovered_via, extra_json,
               status, discovered_at, updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,'pending',?,?)""",
            (
                post.platform,
                post.post_id,
                domain,
                post.source_id,
                post.source_name,
                post.source_type,
                post.title,
                post.text,
                post.url,
                post.created_at,
                post.like_count,
                post.comment_count,
                post.discovered_via,
                json.dumps(post.extra, ensure_ascii=False) if post.extra else None,
                now,
                now,
            ),
        )
        return cur.rowcount > 0

    @staticmethod
    def row_to_post(row: sqlite3.Row) -> Post:
        return Post(
            platform=row["platform"],
            post_id=row["post_id"],
            source_id=row["source_id"],
            source_name=row["source_name"],
            source_type=row["source_type"],
            title=row["title"],
            text=row["text"],
            url=row["url"],
            created_at=row["created_at"],
            like_count=row["like_count"],
            comment_count=row["comment_count"],
            discovered_via=row["discovered_via"],
            extra=json.loads(row["extra_json"]) if row["extra_json"] else {},
        )

    def pending_posts(self, platform: str, domain: str, limit: int = 50) -> list[sqlite3.Row]:
        """Posts that still have comments to read (in-progress first, then oldest discovered)."""
        return self.conn.execute(
            """SELECT * FROM posts WHERE platform=? AND domain=? AND status IN ('active','pending')
               ORDER BY CASE status WHEN 'active' THEN 0 ELSE 1 END, discovered_at, rowid LIMIT ?""",
            (platform, domain, limit),
        ).fetchall()

    def update_post(self, platform: str, post_id: str, domain: str, **fields: Any) -> None:
        fields["updated_at"] = utcnow()
        cols = ", ".join(f"{k}=?" for k in fields)
        self.conn.execute(
            f"UPDATE posts SET {cols} WHERE platform=? AND post_id=? AND domain=?",
            (*fields.values(), platform, post_id, domain),
        )

    def reset_capped_posts(self, domain: str) -> int:
        """Per-post caps are per batch: re-open capped posts when a new batch starts."""
        cur = self.conn.execute(
            "UPDATE posts SET status='active' WHERE domain=? AND status='capped'", (domain,)
        )
        self.conn.commit()
        return cur.rowcount

    def count_posts(self, platform: str, domain: str, status: Optional[str] = None) -> int:
        sql = "SELECT COUNT(*) FROM posts WHERE platform=? AND domain=?"
        args: list[Any] = [platform, domain]
        if status:
            sql += " AND status=?"
            args.append(status)
        return self.conn.execute(sql, args).fetchone()[0]

    # ------------------------------------------------------------ crawl state
    def get_crawl_state(self, platform: str, domain: str, scope_key: str) -> tuple[dict, bool]:
        row = self.conn.execute(
            "SELECT state_json, exhausted FROM crawl_state WHERE platform=? AND domain=? AND scope_key=?",
            (platform, domain, scope_key),
        ).fetchone()
        if not row:
            return {}, False
        return (json.loads(row["state_json"]) if row["state_json"] else {}), bool(row["exhausted"])

    def set_crawl_state(self, platform: str, domain: str, scope_key: str, state: dict, exhausted: bool) -> None:
        self.conn.execute(
            """INSERT INTO crawl_state(platform, domain, scope_key, state_json, exhausted, updated_at)
               VALUES(?,?,?,?,?,?)
               ON CONFLICT(platform, domain, scope_key) DO UPDATE SET
                 state_json=excluded.state_json, exhausted=excluded.exhausted, updated_at=excluded.updated_at""",
            (platform, domain, scope_key, json.dumps(state, ensure_ascii=False), int(exhausted), utcnow()),
        )

    def list_scopes(self, platform: str, domain: str, prefix: str) -> list[str]:
        rows = self.conn.execute(
            "SELECT scope_key FROM crawl_state WHERE platform=? AND domain=? AND scope_key LIKE ? ORDER BY rowid",
            (platform, domain, prefix + "%"),
        ).fetchall()
        return [r["scope_key"] for r in rows]

    def add_scope_if_missing(self, platform: str, domain: str, scope_key: str) -> None:
        self.conn.execute(
            """INSERT OR IGNORE INTO crawl_state(platform, domain, scope_key, state_json, exhausted, updated_at)
               VALUES(?,?,?,?,0,?)""",
            (platform, domain, scope_key, "{}", utcnow()),
        )

    # ------------------------------------------------------------------ quota
    def quota_used(self, platform: str, day: Optional[str] = None) -> int:
        row = self.conn.execute(
            "SELECT units FROM quota_usage WHERE platform=? AND day=?", (platform, day or today_utc())
        ).fetchone()
        return int(row["units"]) if row else 0

    def add_quota(self, platform: str, units: int, day: Optional[str] = None) -> None:
        self.conn.execute(
            """INSERT INTO quota_usage(platform, day, units) VALUES(?,?,?)
               ON CONFLICT(platform, day) DO UPDATE SET units = units + excluded.units""",
            (platform, day or today_utc(), units),
        )
        self.conn.commit()

    # -------------------------------------------------------------- processed
    def is_processed(self, platform: str, item_id: str) -> bool:
        return (
            self.conn.execute(
                "SELECT 1 FROM processed_ids WHERE platform=? AND item_id=?", (platform, item_id)
            ).fetchone()
            is not None
        )

    def mark_processed(self, platform: str, item_id: str, batch_id: str, status: str) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO processed_ids(platform, item_id, batch_id, status, processed_at) VALUES(?,?,?,?,?)",
            (platform, item_id, batch_id, status, utcnow()),
        )

    # --------------------------------------------------------------- comments
    def insert_comment(
        self,
        record_key: str,
        batch_id: str,
        record: dict,
        status: str,
        reason: Optional[str],
        detail: Optional[str],
        exact_hash: Optional[str],
        skeleton: Optional[str],
    ) -> None:
        text = record.get("comment_text") or ""
        self.conn.execute(
            """INSERT OR REPLACE INTO comments(record_key, batch_id, platform, domain, record_type, post_id,
               source_id, status, rejection_reason, rejection_detail, language, text_length,
               author_anonymous_id, exact_hash, skeleton, record_json, processed_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                record_key,
                batch_id,
                record["platform"],
                record["domain"],
                record.get("record_type"),
                record.get("post_id"),
                record.get("source_id"),
                status,
                reason,
                detail,
                record.get("language"),
                len(text),
                record.get("author_anonymous_id"),
                exact_hash,
                skeleton,
                json.dumps(record, ensure_ascii=False),
                utcnow(),
            ),
        )

    def retro_reject(self, record_key: str, reason: str, detail: str) -> bool:
        cur = self.conn.execute(
            """UPDATE comments SET status='rejected', rejection_reason=?, rejection_detail=?
               WHERE record_key=? AND status='accepted'""",
            (reason, detail, record_key),
        )
        return cur.rowcount > 0

    def get_comment(self, record_key: str) -> Optional[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM comments WHERE record_key=?", (record_key,)).fetchone()

    def count_comments(self, batch_id: str, status: Optional[str] = None) -> int:
        sql = "SELECT COUNT(*) FROM comments WHERE batch_id=?"
        args: list[Any] = [batch_id]
        if status:
            sql += " AND status=?"
            args.append(status)
        return self.conn.execute(sql, args).fetchone()[0]

    def accepted_counts_by(self, batch_id: str, column: str) -> dict[tuple[str, str], int]:
        assert column in ("post_id", "source_id")
        rows = self.conn.execute(
            f"""SELECT platform, {column} AS k, COUNT(*) AS n FROM comments
                WHERE batch_id=? AND status='accepted' AND {column} IS NOT NULL
                GROUP BY platform, {column}""",
            (batch_id,),
        ).fetchall()
        return {(r["platform"], r["k"]): r["n"] for r in rows}

    def post_counts(self, batch_id: str, platform: str, post_id: str) -> tuple[int, int]:
        """(processed, accepted) for a post in a batch."""
        row = self.conn.execute(
            """SELECT COUNT(*) AS n, SUM(CASE WHEN status='accepted' THEN 1 ELSE 0 END) AS a
               FROM comments WHERE batch_id=? AND platform=? AND post_id=?""",
            (batch_id, platform, post_id),
        ).fetchone()
        return int(row["n"] or 0), int(row["a"] or 0)

    def iter_records(self, batch_id: str, status: str) -> Iterable[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM comments WHERE batch_id=? AND status=? ORDER BY processed_at, rowid",
            (batch_id, status),
        )

    # ----------------------------------------------------------- text hashes
    def find_hash(self, hash_type: str, h: str, batch_id: Optional[str]) -> Optional[str]:
        sql = "SELECT record_key FROM text_hashes WHERE hash_type=? AND hash=?"
        args: list[Any] = [hash_type, h]
        if batch_id is not None:
            sql += " AND batch_id=?"
            args.append(batch_id)
        row = self.conn.execute(sql + " LIMIT 1", args).fetchone()
        return row["record_key"] if row else None

    def add_hash(self, hash_type: str, h: str, record_key: str, batch_id: str) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO text_hashes(hash_type, hash, record_key, batch_id, created_at) VALUES(?,?,?,?,?)",
            (hash_type, h, record_key, batch_id, utcnow()),
        )

    def add_hash_author(self, h: str, author: str) -> int:
        """Record an author for a text hash; returns the number of distinct authors."""
        self.conn.execute("INSERT OR IGNORE INTO text_hash_authors(hash, author) VALUES(?,?)", (h, author))
        return self.conn.execute("SELECT COUNT(*) FROM text_hash_authors WHERE hash=?", (h,)).fetchone()[0]

    def add_lsh(self, bands: list[tuple[int, int]], record_key: str, batch_id: str) -> None:
        self.conn.executemany(
            "INSERT INTO lsh_bands(band, bucket, record_key, batch_id) VALUES(?,?,?,?)",
            [(b, k, record_key, batch_id) for b, k in bands],
        )

    def lsh_candidates(self, bands: list[tuple[int, int]], batch_id: Optional[str], limit: int = 50) -> list[str]:
        found: list[str] = []
        seen = set()
        for b, k in bands:
            sql = "SELECT record_key FROM lsh_bands WHERE band=? AND bucket=?"
            args: list[Any] = [b, k]
            if batch_id is not None:
                sql += " AND batch_id=?"
                args.append(batch_id)
            for r in self.conn.execute(sql, args):
                if r["record_key"] not in seen:
                    seen.add(r["record_key"])
                    found.append(r["record_key"])
                    if len(found) >= limit:
                        return found
        return found

    def skeleton_of(self, record_key: str) -> Optional[str]:
        row = self.conn.execute("SELECT skeleton FROM comments WHERE record_key=?", (record_key,)).fetchone()
        return row["skeleton"] if row else None

    def clear_lsh(self) -> None:
        self.conn.execute("DELETE FROM lsh_bands")

    def iter_hashed_records(self) -> Iterable[sqlite3.Row]:
        return self.conn.execute(
            """SELECT c.record_key, c.batch_id, c.skeleton FROM comments c
               JOIN text_hashes t ON t.record_key = c.record_key AND t.hash_type='exact'"""
        ).fetchall()

    # ----------------------------------------------------------------- errors
    def log_error(
        self,
        batch_id: Optional[str],
        platform: Optional[str],
        scope: Optional[str],
        error_type: str,
        message: str,
        http_status: Optional[int] = None,
    ) -> None:
        self.conn.execute(
            """INSERT INTO errors(batch_id, platform, scope, error_type, message, http_status, occurred_at)
               VALUES(?,?,?,?,?,?,?)""",
            (batch_id, platform, scope, error_type, message[:2000], http_status, utcnow()),
        )
        self.conn.commit()

    def error_counts(self, batch_id: str) -> dict[str, int]:
        rows = self.conn.execute(
            "SELECT platform || ':' || error_type AS k, COUNT(*) AS n FROM errors WHERE batch_id=? GROUP BY k",
            (batch_id,),
        ).fetchall()
        return {r["k"]: r["n"] for r in rows}
