"""Runs the real CLI (collect -> interrupt-like stop -> resume -> stats -> export)
against the local MOCK YouTube server. MOCK DATA ONLY."""

import csv

import yaml

import run as cli
from tests.conftest import ROOT
from tests.mock_youtube_server import start_server


def _write_config(tmp_path, api_base):
    data = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    data["paths"] = {
        "database": str(tmp_path / "state.sqlite3"),
        "raw_dir": str(tmp_path / "raw"),
        "accepted_dir": str(tmp_path / "accepted"),
        "rejected_dir": str(tmp_path / "rejected"),
        "log_dir": str(tmp_path / "logs"),
    }
    data["sources"]["youtube"].update({"api_base": api_base, "request_delay_seconds": 0})
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return path


def test_cli_collect_resume_stats_export(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("YOUTUBE_API_KEY", "MOCK_KEY")
    monkeypatch.setenv("ANON_SALT", "MOCK_SALT")
    server, base = start_server()
    try:
        cfg = str(_write_config(tmp_path, base))
        assert cli.main(["--config", cfg, "collect", "--platform", "youtube", "--domain", "sports", "--target", "50"]) == 0
        out = capsys.readouterr().out
        assert "accepted                        50" in out
        rows = list(csv.DictReader(open(tmp_path / "accepted" / "sports_001.csv", encoding="utf-8-sig", newline="")))
        assert len(rows) == 50

        # resume the same batch to a larger target: continues from 50
        assert cli.main(["--config", cfg, "collect", "--domain", "sports", "--target", "100", "--batch", "sports_001"]) == 0
        rows = list(csv.DictReader(open(tmp_path / "accepted" / "sports_001.csv", encoding="utf-8-sig", newline="")))
        assert len(rows) == 100
        assert len({r["comment_id"] for r in rows}) == 100

        assert cli.main(["--config", cfg, "stats", "--batch", "sports_001"]) == 0
        assert cli.main(["--config", cfg, "export", "--batch", "sports_001", "--output", "mock_export"]) == 0
        assert (tmp_path / "accepted" / "mock_export.parquet").exists()
        assert cli.main(["--config", cfg, "resume", "--batch", "sports_001"]) == 0  # already complete
    finally:
        server.shutdown()
