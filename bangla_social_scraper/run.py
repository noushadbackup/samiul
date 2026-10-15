#!/usr/bin/env python3
"""Bangla / Banglish social-media research collector — command line interface.

Examples
--------
  python run.py discover --domain sports --platform youtube
  python run.py collect  --platform youtube --domain sports --target 50
  python run.py collect  --platform all     --domain sports --target 1000
  python run.py collect  --domain sports --target 1000 --resume
  python run.py resume   --batch sports_001
  python run.py stats    --batch sports_001
  python run.py export   --batch sports_001 --output sports_round1
  python run.py batches
  python run.py check
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.collector import Collector  # noqa: E402
from core.config import ConfigError, load_config  # noqa: E402
from core.logging_setup import get_logger, log_event, setup_logging  # noqa: E402
from core.pipeline import Pipeline  # noqa: E402
from core.stats import batch_stats, format_stats  # noqa: E402
from discovery.keyword_manager import KeywordManager  # noqa: E402
from discovery.source_discovery import SourceDiscovery  # noqa: E402
from processing.anonymize import Anonymizer, load_salt  # noqa: E402
from scraper import build_scrapers, resolve_platforms  # noqa: E402
from storage.database import Database  # noqa: E402
from storage.exporter import RawWriter, export_batch  # noqa: E402

log = get_logger("cli")


def _split(value: str | None) -> list[str] | None:
    if not value:
        return None
    return [v.strip() for v in value.split(",") if v.strip()]


def _open(args):
    cfg = load_config(args.config)
    log_file = setup_logging(cfg.path("log_dir"), verbose=args.verbose)
    db = Database(cfg.path("database"))
    return cfg, db, log_file


def _export(cfg, db, batch_id: str, output: str | None, formats=None) -> dict:
    batch = db.get_batch(batch_id)
    return export_batch(
        db,
        batch_id,
        cfg.path("accepted_dir"),
        cfg.path("rejected_dir"),
        output_name=output or (batch or {}).get("output_name") or batch_id,
        formats=tuple(formats or cfg.get("export.formats", ["csv", "jsonl", "parquet"])),
        csv_encoding=cfg.get("export.csv_encoding", "utf-8-sig"),
        include_rejected=bool(cfg.get("export.export_rejected", True)),
        mask=bool(cfg.get("privacy.mask_mentions_in_export", False)),
    )


def _print_skipped(skipped: dict) -> None:
    for name, reason in skipped.items():
        print(f"  [skipped] {name}: {reason}", file=sys.stderr)


# ---------------------------------------------------------------- commands
def cmd_discover(args) -> int:
    cfg, db, _ = _open(args)
    domain = cfg.validate_domain(args.domain or cfg.get("collection.domain"))
    platforms = resolve_platforms(cfg, args.platform)
    scrapers, skipped = build_scrapers(cfg, db, platforms)
    _print_skipped(skipped)
    if not scrapers:
        print("No usable platform connectors (see reasons above).", file=sys.stderr)
        return 2
    km = KeywordManager(cfg, _split(args.keywords))
    for name, scraper in scrapers.items():
        kws = km.keywords(domain, name)
        try:
            summary = SourceDiscovery(db, scraper, domain, kws).run(args.steps)
        except Exception as exc:  # one platform failing must not stop the others
            db.log_error(None, name, "discover", type(exc).__name__, str(exc), getattr(exc, "status", None))
            print(f"  [error] {name}: {exc}", file=sys.stderr)
            continue
        print(json.dumps(summary, ensure_ascii=False))
    return 0


def _usable_scrapers(cfg, db, platforms: list[str]):
    scrapers, skipped = build_scrapers(cfg, db, platforms)
    _print_skipped(skipped)
    if not scrapers:
        print("No usable platform connectors (see reasons above). Nothing collected.", file=sys.stderr)
    return scrapers


def _run_batch(args, cfg, db, batch: dict, scrapers: dict, keywords: dict, log_file) -> int:
    salt = load_salt(cfg.root / "checkpoints" / "anon_salt.key")
    raw = RawWriter(cfg.path("raw_dir"), batch["batch_id"])
    pipeline = Pipeline(cfg, db, batch["batch_id"], batch["domain"], Anonymizer(salt), raw)
    collector = Collector(cfg, db, pipeline, batch["batch_id"], batch["domain"], int(batch["target"]), scrapers, keywords)
    print(
        f"Batch {batch['batch_id']} | domain={batch['domain']} | target={batch['target']} | "
        f"platforms={','.join(scrapers)} | already accepted={collector.accepted_total()} | "
        f"post cap={collector.limits.post_cap} creator cap={collector.limits.creator_cap}\nLog: {log_file}",
        file=sys.stderr,
    )
    try:
        summary = collector.run()
    except KeyboardInterrupt:
        raw.close()
        print(f"\nInterrupted. Progress is saved. Resume with:\n  python run.py resume --batch {batch['batch_id']}", file=sys.stderr)
        return 130
    finally:
        raw.close()
    files = _export(cfg, db, batch["batch_id"], args.output if hasattr(args, "output") else None)
    print(format_stats(batch_stats(db, batch["batch_id"])))
    print("\nPer-platform this run:")
    for name, p in summary["platforms"].items():
        print(
            f"  {name:<10} fetched={p['fetched']:<6} accepted={p['accepted']:<6} rejected={p['rejected']:<6} "
            f"requests={p['http'].get('requests', 0)} retries={p['http'].get('retries', 0)} "
            f"rate_limited={p['http'].get('rate_limited', 0)} stop={p['stop_reason'] or '-'}"
        )
    print("\nExported:")
    for path in files["accepted"] + files["rejected"]:
        print(f"  {path}")
    if summary["outcome"] != "completed":
        capped = sum(p.get("posts_skipped_creator_cap", 0) for p in summary["platforms"].values())
        if capped:
            print(
                f"\nNote: {capped} discovered post(s) were skipped because their creator reached the "
                f"per-creator cap ({summary['limits']['creator_cap']}). Add keywords/sources for more creators, "
                "or raise diversity.max_per_creator / lower diversity.min_distinct_creators.",
                file=sys.stderr,
            )
        print(
            f"\nTarget not reached ({summary['accepted']}/{summary['target']}, outcome={summary['outcome']}). "
            f"Resume later with:\n  python run.py resume --batch {batch['batch_id']}",
            file=sys.stderr,
        )
        return 3
    return 0


def cmd_collect(args) -> int:
    cfg, db, log_file = _open(args)
    domain = cfg.validate_domain(args.domain or cfg.get("collection.domain"))
    km = KeywordManager(cfg, _split(args.keywords))

    batch = None
    if args.batch:
        batch = db.get_batch(args.batch)
        if batch is None:
            print(f"Unknown batch {args.batch}", file=sys.stderr)
            return 2
    elif args.resume:
        batch = db.latest_batch(domain, unfinished_only=True)
        if batch is None:
            latest = db.latest_batch(domain)
            if latest is not None and args.target and int(args.target) > int(latest["target"]):
                batch = latest  # extend a completed batch to a larger target
            else:
                msg = f"No unfinished batch for domain '{domain}' to resume."
                if latest is not None:
                    msg += f" Latest batch {latest['batch_id']} is complete; pass a larger --target to extend it."
                print(msg, file=sys.stderr)
                return 2

    if batch is not None:
        if batch["domain"] != domain and not args.batch:
            print("Domain mismatch with the batch being resumed.", file=sys.stderr)
            return 2
        platforms = batch["platforms"].split(",")
        if args.platform:
            platforms = resolve_platforms(cfg, args.platform)
            db.update_batch(batch["batch_id"], platforms=",".join(platforms))
        if args.target and int(args.target) != int(batch["target"]):
            db.update_batch(batch["batch_id"], target=int(args.target))
        if args.output:
            db.update_batch(batch["batch_id"], output_name=args.output)
        keywords = json.loads(batch["keywords_json"] or "{}")
        if args.keywords:
            keywords = km.snapshot(batch["domain"], platforms)
            db.update_batch(batch["batch_id"], keywords_json=json.dumps(keywords, ensure_ascii=False))
        for p in platforms:
            keywords.setdefault(p, km.keywords(batch["domain"], p))
        scrapers = _usable_scrapers(cfg, db, platforms)
        if not scrapers:
            return 2
        db.update_batch(batch["batch_id"], status="running")
        batch = db.get_batch(batch["batch_id"])
        log_event(log, "batch_resumed", batch_id=batch["batch_id"])
    else:
        platforms = resolve_platforms(cfg, args.platform)
        target = int(args.target or cfg.get("collection.target", 1000))
        if target <= 0:
            raise ValueError("--target must be a positive integer")
        keywords = km.snapshot(domain, platforms)
        scrapers = _usable_scrapers(cfg, db, platforms)
        if not scrapers:
            return 2
        batch_id = db.next_batch_id(domain)
        db.reset_capped_posts(domain)
        db.create_batch(batch_id, domain, platforms, target, keywords, cfg.snapshot(), args.output)
        batch = db.get_batch(batch_id)
        log_event(log, "batch_created", batch_id=batch_id, domain=domain, target=target, platforms=platforms)
    return _run_batch(args, cfg, db, batch, scrapers, keywords, log_file)


def cmd_resume(args) -> int:
    args.resume = False
    args.domain = None
    args.platform = None
    args.target = None
    args.keywords = None
    cfg, db, _ = _open(args)
    batch = db.get_batch(args.batch)
    if batch is None:
        print(f"Unknown batch {args.batch}", file=sys.stderr)
        return 2
    args.domain = batch["domain"]
    db.close()
    return cmd_collect(args)


def cmd_stats(args) -> int:
    cfg, db, _ = _open(args)
    try:
        s = batch_stats(db, args.batch)
    except KeyError as exc:
        print(exc, file=sys.stderr)
        return 2
    print(json.dumps(s, ensure_ascii=False, indent=2) if args.json else format_stats(s))
    return 0


def cmd_export(args) -> int:
    cfg, db, _ = _open(args)
    if db.get_batch(args.batch) is None:
        print(f"Unknown batch {args.batch}", file=sys.stderr)
        return 2
    files = _export(cfg, db, args.batch, args.output, _split(args.formats))
    for path in files["accepted"] + files["rejected"]:
        print(path)
    return 0


def cmd_batches(args) -> int:
    cfg, db, _ = _open(args)
    rows = db.list_batches()
    if not rows:
        print("No batches yet.")
    for b in rows:
        acc = db.count_comments(b["batch_id"], "accepted")
        print(f"{b['batch_id']:<24} {b['domain']:<22} {b['status']:<12} {acc:>6}/{b['target']:<6} {b['platforms']}")
    return 0


def cmd_check(args) -> int:
    """Validate configuration and credentials without collecting anything."""
    cfg, db, _ = _open(args)
    platforms = resolve_platforms(cfg, args.platform or "all")
    scrapers, skipped = build_scrapers(cfg, db, platforms)
    for name in platforms:
        if name in scrapers:
            print(f"  [ok]      {name}: credentials present, connector enabled")
        else:
            print(f"  [skipped] {name}: {skipped.get(name)}")
    print("Domains:", ", ".join(cfg.domains))
    return 0 if scrapers else 2


# ------------------------------------------------------------------- parser
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Bangla/Banglish public social-media research collector")
    p.add_argument("--config", default=None, help="path to config.yaml")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="command", required=True)

    d = sub.add_parser("discover", help="discover public sources/posts for a domain")
    d.add_argument("--domain")
    d.add_argument("--platform", default=None, help="youtube|facebook|instagram|tiktok|all (default from config)")
    d.add_argument("--keywords", help="comma-separated keywords overriding config")
    d.add_argument("--steps", type=int, default=3, help="discovery requests per platform (YouTube: 100 quota units each)")
    d.set_defaults(func=cmd_discover)

    c = sub.add_parser("collect", help="collect until N accepted unique records")
    c.add_argument("--platform", default=None)
    c.add_argument("--domain")
    c.add_argument("--target", type=int)
    c.add_argument("--keywords", help="comma-separated keywords overriding config")
    c.add_argument("--output", help="output file base name (default: batch id)")
    c.add_argument("--resume", action="store_true", help="continue the latest unfinished batch of this domain")
    c.add_argument("--batch", help="continue a specific batch id")
    c.set_defaults(func=cmd_collect)

    r = sub.add_parser("resume", help="resume a batch")
    r.add_argument("--batch", required=True)
    r.add_argument("--output")
    r.set_defaults(func=cmd_resume)

    s = sub.add_parser("stats", help="print batch statistics")
    s.add_argument("--batch", required=True)
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_stats)

    e = sub.add_parser("export", help="export accepted/rejected records")
    e.add_argument("--batch", required=True)
    e.add_argument("--output")
    e.add_argument("--formats", help="comma-separated: csv,jsonl,parquet")
    e.set_defaults(func=cmd_export)

    b = sub.add_parser("batches", help="list batches")
    b.set_defaults(func=cmd_batches)

    k = sub.add_parser("check", help="check configuration and credentials")
    k.add_argument("--platform", default=None)
    k.set_defaults(func=cmd_check)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
