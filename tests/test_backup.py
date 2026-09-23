"""Backup manifests must remain valid after the backup process has exited."""

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path


def test_wal_backup_preserves_committed_rows_and_only_lists_persistent_files(tmp_path):
    root = Path(__file__).resolve().parents[1]
    (tmp_path / "scripts").mkdir()
    shutil.copy2(root / "scripts" / "backup_local.py", tmp_path / "scripts" / "backup_local.py")
    raw_directory = tmp_path / ".local" / "raw"
    raw_directory.mkdir(parents=True)
    raw = b'{"source":"isolated-backup-fixture"}'
    raw_name = hashlib.sha256(raw).hexdigest() + ".snapshot"
    (raw_directory / raw_name).write_bytes(raw)
    (tmp_path / ".env").write_text(
        "LOTTOLAB_ADMIN_TOKEN=isolated-backup-fixture-token-32-chars\n", encoding="utf-8"
    )
    with closing(sqlite3.connect(tmp_path / ".local" / "lottolab.db")) as source:
        source.execute("PRAGMA journal_mode=WAL")
        source.execute("CREATE TABLE samples (value TEXT NOT NULL)")
        source.execute("INSERT INTO samples VALUES ('committed-in-wal')")
        source.commit()
        subprocess.run(
            [sys.executable, "scripts/backup_local.py"],
            cwd=tmp_path,
            env={
                **os.environ,
                "LOTTOLAB_DATABASE_URL": "sqlite:///./.local/lottolab.db",
                "LOTTOLAB_DATA_DIR": ".local",
            },
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
    manifest_path = next((tmp_path / ".local" / "backups").glob("*/manifest.json"))
    backup = manifest_path.parent
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["integrity_check"] == "PASS"
    for name, checksum in manifest["sha256"].items():
        assert (backup / name).is_file(), f"Backup listed a transient or missing file: {name}"
        assert hashlib.sha256((backup / name).read_bytes()).hexdigest() == checksum
    assert (backup / "raw" / raw_name).read_bytes() == raw
    assert (backup / ".env").read_bytes() == (tmp_path / ".env").read_bytes()
    with closing(sqlite3.connect(backup / "lottolab.db")) as restored:
        assert restored.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert restored.execute("SELECT value FROM samples").fetchall() == [("committed-in-wal",)]
