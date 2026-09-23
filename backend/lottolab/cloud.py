"""Configuration for the Vercel deployment.

Default is public read + public write (no admin token). When LOTTOLAB_ADMIN_TOKEN
holds at least 32 characters, the deployment switches to public read + private
write: GET stays open (require_read_auth=False) while POST requires the token.
Host/CORS/size guards are kept in both modes."""

import os
import re
import tempfile
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import urlsplit

from pydantic_settings import SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

from .config import Settings


class VercelSettings(Settings):
    model_config = SettingsConfigDict(env_prefix="LOTTOLAB_", env_file=None, extra="ignore")


def postgres_url(value: str) -> str:
    """Accept provider URLs without exposing credentials in validation errors."""
    try:
        url = make_url(value.replace("postgres://", "postgresql://", 1))
    except (ArgumentError, ValueError):
        raise ValueError("请配置有效的 PostgreSQL 连接，连接字符串不会写入日志") from None
    if url.get_backend_name() != "postgresql" or not url.host or not url.database:
        raise ValueError("云端必须配置外部 PostgreSQL，不能使用临时 SQLite 文件")
    if url.host in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("云端数据库不能指向本机地址")
    sslmode = url.query.get("sslmode", "require")
    if not isinstance(sslmode, str) or sslmode not in {"require", "verify-ca", "verify-full"}:
        raise ValueError("云端 PostgreSQL 连接必须启用 TLS")
    return (
        url.set(drivername="postgresql+psycopg")
        .update_query_dict({"sslmode": sslmode})
        .render_as_string(hide_password=False)
    )


def vercel_settings(environ: Mapping[str, str] | None = None) -> Settings:
    env = os.environ if environ is None else environ
    database = postgres_url(env.get("LOTTOLAB_DATABASE_URL", ""))
    hosts = set(env.get("LOTTOLAB_ALLOWED_HOSTS", "").split(","))
    hosts.update(
        env.get(name, "") for name in ("VERCEL_URL", "VERCEL_PROJECT_PRODUCTION_URL", "VERCEL_BRANCH_URL")
    )
    hosts = {host.strip().lower() for host in hosts if host.strip()}
    if not hosts or any(not re.fullmatch(r"[a-z0-9]+(?:[a-z0-9.-]*[a-z0-9])?", host) for host in hosts):
        raise ValueError("请配置实际部署域名 LOTTOLAB_ALLOWED_HOSTS，不含协议、端口或通配符")
    origins = {f"https://{host}" for host in hosts}
    for origin in env.get("LOTTOLAB_ALLOWED_ORIGINS", "").split(","):
        origin = origin.strip()
        if not origin:
            continue
        parsed = urlsplit(origin)
        if parsed.scheme != "https" or not parsed.hostname or origin != f"https://{parsed.netloc}":
            raise ValueError("云端允许来源必须是完整的 HTTPS 来源地址，不含路径")
        origins.add(origin)
    timeout = env.get("LOTTOLAB_JOB_TIMEOUT_SECONDS", "240")
    if not timeout.isdigit() or not 1 <= int(timeout) <= 240:
        raise ValueError("云端单任务运行上限须为 1–240 秒，为函数收尾保留时间")
    token = (env.get("LOTTOLAB_ADMIN_TOKEN", "") or "").strip()
    if token and len(token) < 32:
        raise ValueError("LOTTOLAB_ADMIN_TOKEN 已设置但不足 32 字符；请加长或删除以启用公开写")
    if len(token) >= 32:
        admin_token, public_mode = token, False
    else:
        admin_token, public_mode = "", True
    return VercelSettings(
        database_url=database,
        admin_token=admin_token,
        data_dir=Path(tempfile.gettempdir()) / "lottolab",
        frontend_dir=Path(__file__).resolve().parents[2] / "frontend/dist",
        allowed_hosts=",".join(sorted(hosts)),
        allowed_origins=",".join(sorted(origins)),
        allow_local_writes=False,
        require_read_auth=False,
        public_mode=public_mode,
        execution_mode="request",
        snapshot_storage="database",
        job_timeout_seconds=int(timeout),
        source_timeout_seconds=20,
        max_active_jobs=1,
        max_csv_bytes=4 * 1024 * 1024,
    )
