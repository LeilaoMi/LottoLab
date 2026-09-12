"""Copy local LottoLab into an empty cloud database; dry run unless --apply."""

import argparse
import json
from pathlib import Path

from dotenv import dotenv_values
from lottolab.cloud import postgres_url
from lottolab.config import get_settings
from lottolab.db import make_engine
from lottolab.transfer import transfer_database


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-env", type=Path, default=Path(".env.cloud.local"))
    parser.add_argument("--apply", action="store_true", help="Write only after all preflight checks pass")
    args = parser.parse_args()
    if not args.target_env.is_file():
        parser.error("缺少私有云配置文件 .env.cloud.local，请参考 docs/deployment.md")
    target_values = dotenv_values(args.target_env)
    source_settings = get_settings()
    source = target = None
    try:
        target_url = postgres_url(target_values.get("LOTTOLAB_DATABASE_URL") or "")
        source = make_engine(source_settings.database_url)
        target = make_engine(target_url, pooled=False)
        report = transfer_database(
            source,
            target,
            raw_dir=source_settings.data_dir / "raw",
            project_dir=Path(__file__).resolve().parents[1],
            apply=args.apply,
        )
        print(json.dumps(report, indent=2, ensure_ascii=False))
    except ValueError as exc:
        raise SystemExit(str(exc)) from None
    except Exception as exc:
        # Database exceptions can contain connection details. Never print credentials.
        raise SystemExit(
            f"迁移未完成（{type(exc).__name__}）；请检查网络、数据库权限及迁移版本，未提交的目标事务已回滚。"
        ) from None
    finally:
        if source is not None:
            source.dispose()
        if target is not None:
            target.dispose()


if __name__ == "__main__":
    main()
