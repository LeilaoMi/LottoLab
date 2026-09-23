from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LOTTOLAB_", env_file=".env", extra="ignore")
    database_url: str = Field(default="sqlite:///./.local/lottolab.db", repr=False)
    data_dir: Path = Path(".local")
    admin_token: str = Field(default="", repr=False)
    allow_local_writes: bool = False
    allowed_origins: str = (
        "http://127.0.0.1:8000,http://localhost:8000,http://127.0.0.1:5173,http://localhost:5173"
    )
    allowed_hosts: str = "localhost,127.0.0.1,testserver"
    frontend_dir: Path = Path("frontend/dist")
    poll_seconds: float = 1.0
    job_timeout_seconds: int = Field(default=600, ge=1, le=3600)
    source_timeout_seconds: float = 20.0
    execution_mode: Literal["worker", "request"] = "worker"
    snapshot_storage: Literal["filesystem", "database"] = "filesystem"
    require_read_auth: bool = False
    public_mode: bool = False
    max_active_jobs: int = Field(default=8, ge=1, le=8)
    max_csv_bytes: int = Field(default=8 * 1024 * 1024, ge=1024, le=8 * 1024 * 1024)
    rate_limit_posts_per_minute: int = Field(default=120, ge=0, le=6000)
    rate_limit_heavy_gets_per_minute: int = Field(default=60, ge=0, le=6000)
    trusted_proxies: str = (
        ""  # extra proxy IPs allowed to set X-Forwarded-For; loopback/private always trusted
    )

    @model_validator(mode="after")
    def admin_token_strength(self) -> "Settings":
        # Local tests may pass short tokens with allow_local_writes; enforce only for real write auth.
        if self.admin_token and len(self.admin_token) < 32 and not self.allow_local_writes:
            raise ValueError("LOTTOLAB_ADMIN_TOKEN 已设置但不足 32 字符；请加长或删除以启用公开写")
        return self

    @property
    def origins(self) -> list[str]:
        return [s.strip() for s in self.allowed_origins.split(",") if s.strip()]

    @property
    def hosts(self) -> list[str]:
        return [s.strip() for s in self.allowed_hosts.split(",") if s.strip()]

    @property
    def proxy_list(self) -> list[str]:
        return [s.strip() for s in self.trusted_proxies.split(",") if s.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
