"""Batch statistics computed from the SQLite state (always reflects the true stored data)."""

from __future__ import annotations

from storage.database import Database


def batch_stats(db: Database, batch_id: str) -> dict:
    batch = db.get_batch(batch_id)
    if batch is None:
        raise KeyError(f"Unknown batch: {batch_id}")
    q = db.conn.execute

    def scalar(sql: str, *args) -> float:
        v = q(sql, (batch_id, *args)).fetchone()[0]
        return v or 0

    raw = scalar("SELECT COUNT(*) FROM comments WHERE batch_id=?")
    accepted = scalar("SELECT COUNT(*) FROM comments WHERE batch_id=? AND status='accepted'")
    rejected = scalar("SELECT COUNT(*) FROM comments WHERE batch_id=? AND status='rejected'")
    reasons = {
        r[0]: r[1]
        for r in q(
            "SELECT rejection_reason, COUNT(*) FROM comments WHERE batch_id=? AND status='rejected' GROUP BY 1 ORDER BY 2 DESC",
            (batch_id,),
        )
    }
    platform_dist = {
        r[0]: r[1]
        for r in q(
            "SELECT platform, COUNT(*) FROM comments WHERE batch_id=? AND status='accepted' GROUP BY 1 ORDER BY 2 DESC",
            (batch_id,),
        )
    }
    lang_dist = {
        r[0]: r[1]
        for r in q(
            "SELECT language, COUNT(*) FROM comments WHERE batch_id=? AND status='accepted' GROUP BY 1 ORDER BY 2 DESC",
            (batch_id,),
        )
    }
    record_types = {
        r[0]: r[1]
        for r in q(
            "SELECT record_type, COUNT(*) FROM comments WHERE batch_id=? AND status='accepted' GROUP BY 1",
            (batch_id,),
        )
    }
    unique_posts = scalar(
        "SELECT COUNT(DISTINCT platform || ':' || post_id) FROM comments WHERE batch_id=? AND status='accepted'"
    )
    unique_creators = scalar(
        "SELECT COUNT(DISTINCT platform || ':' || source_id) FROM comments WHERE batch_id=? AND status='accepted' AND source_id IS NOT NULL"
    )
    max_per_post = scalar(
        "SELECT MAX(n) FROM (SELECT COUNT(*) n FROM comments WHERE batch_id=? AND status='accepted' GROUP BY platform, post_id)"
    )
    max_per_creator = scalar(
        "SELECT MAX(n) FROM (SELECT COUNT(*) n FROM comments WHERE batch_id=? AND status='accepted' AND source_id IS NOT NULL GROUP BY platform, source_id)"
    )
    avg_len = scalar("SELECT AVG(text_length) FROM comments WHERE batch_id=? AND status='accepted'")
    errors = db.error_counts(batch_id)
    return {
        "batch_id": batch_id,
        "domain": batch["domain"],
        "platforms_requested": batch["platforms"],
        "status": batch["status"],
        "target": batch["target"],
        "raw_collected": int(raw),
        "accepted": int(accepted),
        "rejected": int(rejected),
        "duplicates_removed": int(reasons.get("duplicate", 0)),
        "near_duplicates_removed": int(reasons.get("near_duplicate", 0)),
        "rejection_reasons": reasons,
        "unique_posts": int(unique_posts),
        "unique_creators": int(unique_creators),
        "max_accepted_from_one_post": int(max_per_post),
        "max_accepted_from_one_creator": int(max_per_creator),
        "platform_distribution": platform_dist,
        "language_distribution": lang_dist,
        "record_types": record_types,
        "average_comment_length_chars": round(float(avg_len), 1),
        "collection_time_seconds": round(float(batch["elapsed_seconds"] or 0), 1),
        "runs": batch["runs"],
        "errors": errors,
        "created_at": batch["created_at"],
        "finished_at": batch["finished_at"],
    }


def format_stats(s: dict) -> str:
    def dist(d: dict) -> str:
        if not d:
            return "  (none)"
        total = sum(d.values()) or 1
        return "\n".join(f"  {k or 'null':<22} {v:>7}  ({100 * v / total:.1f}%)" for k, v in d.items())

    secs = s["collection_time_seconds"]
    lines = [
        f"Batch {s['batch_id']}  domain={s['domain']}  status={s['status']}  target={s['target']}",
        "-" * 64,
        f"raw collected              {s['raw_collected']:>7}",
        f"accepted                   {s['accepted']:>7}",
        f"rejected                   {s['rejected']:>7}",
        f"duplicates removed         {s['duplicates_removed']:>7}",
        f"near duplicates removed    {s['near_duplicates_removed']:>7}",
        f"unique posts               {s['unique_posts']:>7}",
        f"unique creators            {s['unique_creators']:>7}",
        f"max from one post          {s['max_accepted_from_one_post']:>7}",
        f"max from one creator       {s['max_accepted_from_one_creator']:>7}",
        f"average comment length     {s['average_comment_length_chars']:>7} chars",
        f"collection time            {int(secs // 3600):02d}:{int(secs % 3600 // 60):02d}:{int(secs % 60):02d}  ({s['runs']} run(s))",
        "platform distribution:",
        dist(s["platform_distribution"]),
        "language distribution:",
        dist(s["language_distribution"]),
        "rejection reasons:",
        dist(s["rejection_reasons"]),
    ]
    if s["errors"]:
        lines.append("errors:")
        lines += [f"  {k:<40} {v:>5}" for k, v in s["errors"].items()]
    return "\n".join(lines)
