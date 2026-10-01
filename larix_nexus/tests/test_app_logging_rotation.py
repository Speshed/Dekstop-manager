import os
import time
from datetime import datetime, timedelta

from larix_nexus.utils import app_logging


def test_reset_log_files_rotates_old_active_logs_and_keeps_current(tmp_path, monkeypatch):
    monkeypatch.setattr(app_logging, "_get_log_dir", lambda: str(tmp_path))
    monkeypatch.delenv("LARIX_KEEP_LOGS", raising=False)
    active = tmp_path / "sync.log"
    active.write_text("old diagnostic", encoding="utf-8")
    old = time.time() - 2 * 24 * 60 * 60
    os.utime(active, (old, old))

    result = app_logging.reset_log_files()

    assert result["rotated"]
    assert active.exists()
    assert active.read_text(encoding="utf-8") == ""
    assert any("sync.log." in path for path in result["rotated"])


def test_reset_log_files_prunes_only_archives_older_than_seven_days(tmp_path, monkeypatch):
    monkeypatch.setattr(app_logging, "_get_log_dir", lambda: str(tmp_path))
    archive = tmp_path / "archive"
    archive.mkdir()
    recent = archive / "sync.log.20260101"
    stale = archive / "sync.log.20251201"
    recent.write_text("keep", encoding="utf-8")
    stale.write_text("remove", encoding="utf-8")
    now = time.time()
    os.utime(recent, (now - 2 * 24 * 60 * 60, now - 2 * 24 * 60 * 60))
    os.utime(stale, (now - 8 * 24 * 60 * 60, now - 8 * 24 * 60 * 60))

    result = app_logging.reset_log_files()

    assert recent.exists()
    assert not stale.exists()
    assert str(stale) in result["deleted"]
