"""Consistent SQLite backup plus raw snapshots and private local configuration."""

import hashlib
import json
import os
import shutil
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

from lottolab.config import get_settings
from sqlalchemy.engine import make_url

root = Path(__file__).resolve().parents[1]
os.chdir(root)
settings = get_settings()
url = make_url(settings.database_url)
if url.get_backend_name() != "sqlite" or not url.database or url.database == ":memory:":
    raise SystemExit("This command backs up SQLite. See docs/deployment.md for PostgreSQL backups.")
database = Path(url.database).resolve()
if not database.is_file():
    raise SystemExit("The local database does not exist; no backup created.")
target = root / ".local" / "backups" / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
target.mkdir(parents=True, exist_ok=False)
with (
    closing(sqlite3.connect(database)) as source,
    closing(sqlite3.connect(target / "lottolab.db")) as destination,
):
    source.backup(destination)
    assert destination.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
# Closing both connections checkpoints the destination and removes transient
# WAL/SHM files before checksums are calculated.
raw = settings.data_dir / "raw"
if raw.is_dir():
    shutil.copytree(raw, target / "raw")
if (root / ".env").is_file():
    shutil.copy2(root / ".env", target / ".env")
checksums = {
    path.relative_to(target).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
    for path in sorted(target.rglob("*"))
    if path.is_file() and path.name != ".env"
}
(target / "manifest.json").write_text(
    json.dumps({"database": "sqlite", "integrity_check": "PASS", "sha256": checksums}, indent=2) + "\n",
    encoding="utf-8",
)
print(f"Backup verified: {target}\nContains private configuration; keep the backup private.")
