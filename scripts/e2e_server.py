"""Isolated browser-test server; never points tests at the real dataset."""

import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / ".local" / "e2e" / uuid4().hex
RUN.mkdir(parents=True)
assert RUN.resolve().is_relative_to((ROOT / ".local" / "e2e").resolve())
os.chdir(ROOT)
cloud = "--cloud" in sys.argv
port = 8012 if cloud else 8011
env = os.environ.copy()
env.update(
    {
        "LOTTOLAB_DATABASE_URL": f"sqlite:///{(RUN / 'test.db').as_posix()}",
        "LOTTOLAB_DATA_DIR": str(RUN),
        "LOTTOLAB_ALLOW_LOCAL_WRITES": "false" if cloud else "true",
        "LOTTOLAB_ADMIN_TOKEN": "isolated-e2e-test-token-32-chars-ok",
        "LOTTOLAB_ALLOWED_ORIGINS": f"http://127.0.0.1:{port},http://localhost:{port}",
        "LOTTOLAB_ALLOWED_HOSTS": "127.0.0.1,localhost",
        "LOTTOLAB_EXECUTION_MODE": "request" if cloud else "worker",
        "LOTTOLAB_SNAPSHOT_STORAGE": "database" if cloud else "filesystem",
        "LOTTOLAB_REQUIRE_READ_AUTH": "true" if cloud else "false",
        "LOTTOLAB_JOB_TIMEOUT_SECONDS": "240" if cloud else "600",
        "LOTTOLAB_MAX_ACTIVE_JOBS": "1" if cloud else "8",
        "LOTTOLAB_MAX_CSV_BYTES": str((4 if cloud else 8) * 1024 * 1024),
    }
)
subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], env=env, check=True)
for lottery in ("ssq", "dlt"):
    subprocess.run(
        [sys.executable, "-m", "lottolab.cli", "demo", "--lottery", lottery, "--count", "240"],
        env=env,
        check=True,
        stdout=subprocess.DEVNULL,
    )
children = []


def stop(_signal=None, _frame=None):
    for child in children:
        if child.poll() is None:
            child.terminate()
    for child in children:
        try:
            child.wait(timeout=8)
        except subprocess.TimeoutExpired:
            child.kill()
    raise SystemExit(0)


signal.signal(signal.SIGTERM, stop)
signal.signal(signal.SIGINT, stop)
try:
    children.append(
        subprocess.Popen([sys.executable, "-m", "lottolab.cli", "serve", "--port", str(port)], env=env)
    )
    if not cloud:
        children.append(subprocess.Popen([sys.executable, "-m", "lottolab.worker"], env=env))
    while all(child.poll() is None for child in children):
        time.sleep(0.5)
finally:
    stop()
