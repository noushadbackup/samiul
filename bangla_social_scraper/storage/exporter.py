"""Raw JSONL streaming + accepted/rejected exports (CSV, JSONL, Parquet)."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Optional

from core.logging_setup import get_logger, log_event
from core.models import OUTPUT_FIELDS, REJECTED_EXTRA_FIELDS
from processing.anonymize import mask_mentions
from storage.database import Database

log = get_logger("export")

INT_FIELDS = {"like_count", "reply_count"}


class RawWriter:
    """Append-only JSONL of everything fetched, BEFORE quality filtering.

    Rows are already anonymised (no usernames). One file per batch and platform:
    data/raw/<batch_id>/<platform>.jsonl
    """

    def __init__(self, raw_dir: Path, batch_id: str):
        self.dir = raw_dir / batch_id
        self.dir.mkdir(parents=True, exist_ok=True)
        self._handles: dict[str, object] = {}

    def write(self, platform: str, row: dict) -> None:
        fh = self._handles.get(platform)
        if fh is None:
            fh = open(self.dir / f"{platform}.jsonl", "a", encoding="utf-8")
            self._handles[platform] = fh
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    def flush(self) -> None:
        for fh in self._handles.values():
            fh.flush()

    def close(self) -> None:
        for fh in self._handles.values():
            fh.close()
        self._handles.clear()


def _rows(db: Database, batch_id: str, status: str, mask: bool) -> list[dict]:
    out = []
    for r in db.iter_records(batch_id, status):
        rec = json.loads(r["record_json"])
        if mask:
            rec["comment_text"] = mask_mentions(rec.get("comment_text"))
            rec["context_text"] = mask_mentions(rec.get("context_text"))
        if status == "rejected":
            rec["rejection_reason"] = r["rejection_reason"]
            rec["rejection_detail"] = r["rejection_detail"]
        out.append(rec)
    return out


def _write_csv(path: Path, rows: list[dict], fields: list[str], encoding: str) -> None:
    with open(path, "w", encoding=encoding, newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore", quoting=csv.QUOTE_MINIMAL)
        w.writeheader()
        for row in rows:
            w.writerow({k: ("" if row.get(k) is None else row.get(k)) for k in fields})


def _write_jsonl(path: Path, rows: list[dict], fields: list[str]) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps({k: row.get(k) for k in fields}, ensure_ascii=False) + "\n")


def _write_parquet(path: Path, rows: list[dict], fields: list[str]) -> bool:
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError:
        log_event(log, "parquet_skipped", reason="pyarrow not installed")
        return False
    schema = pa.schema([(f, pa.int64() if f in INT_FIELDS else pa.string()) for f in fields])
    columns = {f: [row.get(f) for row in rows] for f in fields}
    table = pa.table(columns, schema=schema)
    pq.write_table(table, path, compression="snappy")
    return True


def export_batch(
    db: Database,
    batch_id: str,
    accepted_dir: Path,
    rejected_dir: Path,
    output_name: Optional[str] = None,
    formats: tuple[str, ...] = ("csv", "jsonl", "parquet"),
    csv_encoding: str = "utf-8-sig",
    include_rejected: bool = True,
    mask: bool = False,
) -> dict[str, list[str]]:
    name = output_name or batch_id
    for suffix in (".csv", ".jsonl", ".parquet"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
    accepted_dir.mkdir(parents=True, exist_ok=True)
    rejected_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, list[str]] = {"accepted": [], "rejected": []}

    acc = _rows(db, batch_id, "accepted", mask)
    for fmt in formats:
        path = accepted_dir / f"{name}.{fmt}"
        if fmt == "csv":
            _write_csv(path, acc, OUTPUT_FIELDS, csv_encoding)
        elif fmt == "jsonl":
            _write_jsonl(path, acc, OUTPUT_FIELDS)
        elif fmt == "parquet":
            if not _write_parquet(path, acc, OUTPUT_FIELDS):
                continue
        else:
            raise ValueError(f"Unknown export format: {fmt}")
        written["accepted"].append(str(path))

    if include_rejected:
        rej = _rows(db, batch_id, "rejected", mask)
        fields = OUTPUT_FIELDS + REJECTED_EXTRA_FIELDS
        for fmt in ("csv", "jsonl"):
            path = rejected_dir / f"{name}_rejected.{fmt}"
            if fmt == "csv":
                _write_csv(path, rej, fields, csv_encoding)
            else:
                _write_jsonl(path, rej, fields)
            written["rejected"].append(str(path))

    log_event(log, "export_done", batch_id=batch_id, accepted=len(acc), files=written["accepted"] + written["rejected"])
    return written
