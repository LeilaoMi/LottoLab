"""容器健康检查的回归锁（2026-09-30 CI container job 变红事件）。

事故经过
给 docker/Dockerfile 加了一条打 /api/v1/health 的镜像级 HEALTHCHECK 后，
CI 的 container job 红了：第 6 步 `docker compose up -d --build --wait` 以
`container lottolab-ci-worker-1 is unhealthy` + exit 1 失败。

根因：compose.yaml 里 worker 只写 `image: lottolab:local`、没有 `build:`，所以
worker 与 api **共用同一个镜像**。而 worker 跑的是 `python -m lottolab.worker` ——
长驻进程、容器内没有 8000 端口的服务。那条面向 HTTP 端口的健康检查对 worker
永远失败，而 `--wait` 把 unhealthy 当成失败。

难发现的地方：这个错误只在 CI 日志里出现一行 "is unhealthy"，本地 `npm test`/
`pytest` 全绿；而且同样的 `pull access denied for lottolab` 在**成功**的历史 run
日志里也出现过（那是 worker 没有 build 段导致的、compose 随后自行 build api 的
正常噪音），极易误判成根因。我自己就先误判了一次。

所以这里锁住三条：镜像级不带 HEALTHCHECK、worker 不带 healthcheck、
api/db 仍各带自己的。这三条任一被改坏，都会把 container job 弄红而别的测试察觉不到。
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = (ROOT / "compose.yaml").read_text(encoding="utf-8")


def service_block(name: str) -> str:
    """取 compose.yaml 里某个 service 的缩进块。

    刻意不用 PyYAML：requirements.lock 里没有 pyyaml，CI 只装 requirements.lock。
    加一个仅测试用的解析依赖会让「离线可跑、零多余依赖」这个前提破掉
    （2026-09-30 实测踩过：本地装了 yaml 所以没发现，CI 直接 ModuleNotFoundError）。
    这里只需要「缩进 + 少量 key」，正则足够，也省掉一个依赖。
    """
    lines = COMPOSE.splitlines()
    start = None
    for i, line in enumerate(lines):
        if re.match(rf"^  {name}:\s*$", line):
            start = i
            break
    assert start is not None, f"compose.yaml 里找不到 service {name}"
    out = [lines[start]]
    for line in lines[start + 1 :]:
        if line.strip() and not line.startswith("   "):
            break
        out.append(line)
    return "\n".join(out)


def has_healthcheck(name: str) -> bool:
    return re.search(r"^\s+healthcheck:\s*$", service_block(name), re.M) is not None


def healthcheck_lines(name: str) -> str:
    block = service_block(name)
    m = re.search(r"^\s+healthcheck:\n((?:\s{4,}.*\n?)+)", block, re.M)
    return m.group(1) if m else ""


def test_dockerfile_has_no_image_level_healthcheck_instruction() -> None:
    """镜像级不能有 HEALTHCHECK —— worker 与 api 共用它，而 worker 无 HTTP 端口。

    只查指令（行首 HEALTHCHECK），不是文件里出现过这个词就算 ——
    注释里必须能解释「为什么不加」，那个词一定会出现。
    """
    lines = (ROOT / "docker" / "Dockerfile").read_text(encoding="utf-8").splitlines()
    offending = [line.strip() for line in lines if line.strip().upper().startswith("HEALTHCHECK")]
    assert not offending, (
        f"docker/Dockerfile 出现 HEALTHCHECK 指令：{offending}。"
        "worker 与 api 共用此镜像且 worker 容器内没有 8000 端口服务，"
        "会导致 compose --wait 判定 worker unhealthy（2026-09-30 实测让 container job 变红）"
    )


def test_dockerfile_explains_why_healthcheck_is_absent() -> None:
    """必须留下「为什么不加」的解释 —— 否则下一个人会再踩一次。

    这条是给未来的人看的：如果哪天 worker 有了自己的可探测端点，
    这段注释和对应测试都该一起更新。
    """
    text = (ROOT / "docker" / "Dockerfile").read_text(encoding="utf-8")
    assert "unhealthy" in text, "Dockerfile 应解释健康检查为何缺席（提到 unhealthy 的后果）"
    assert "lottolab.worker" in text, "Dockerfile 应说明 worker 无 HTTP 端口这一根因"


def test_worker_has_no_healthcheck() -> None:
    """worker 不配 healthcheck。

    它是长驻进程、不监听端口：探 HTTP 端点会永远失败；探进程名（pgrep）依赖
    python:3.12-slim 未保证安装的 procps；读 /proc/<pid>/cmdline 依赖 Linux，
    等于写一条本机跑不了的检查。而 `--wait` 会把 unhealthy 当失败。
    """
    assert not has_healthcheck("worker"), (
        "worker 不应配 healthcheck：它不监听端口，任何常见写法都会永远 unhealthy，"
        "把 compose --wait 弄失败（2026-09-30 实测）"
    )


def test_worker_still_waits_for_api_to_be_healthy() -> None:
    """没有健康判定不等于失去顺序保证：worker 仍必须等 api healthy 才启动。"""
    block = service_block("worker")
    assert re.search(r"depends_on:\s*\n\s+api:\s*\n\s+condition:\s*service_healthy", block), (
        "worker 仍应等 api healthy 后再启动 —— 那是它唯一的启动顺序保障"
    )


def test_worker_shares_api_image_without_rebuilding() -> None:
    """worker 复用 api 的镜像，不自己 build（否则同一镜像构建两次）。"""
    api, worker = service_block("api"), service_block("worker")
    api_image = re.search(r"^\s+image:\s*(\S+)", api, re.M)
    worker_image = re.search(r"^\s+image:\s*(\S+)", worker, re.M)
    assert api_image and worker_image, "api/worker 都应声明 image"
    assert api_image.group(1) == worker_image.group(1), "worker 应与 api 用同一个镜像名"
    assert not re.search(r"^\s+build:", worker, re.M), "worker 不应有自己的 build 段"
    assert re.search(r"^\s+build:", api, re.M), "api 应保有 build 段（worker 靠它产出共用镜像）"
    assert '"-m", "lottolab.worker"' in worker, "worker 应以 python -m lottolab.worker 启动"


def test_api_and_db_keep_their_own_healthchecks() -> None:
    """api/db 必须有健康检查 —— 它们才是真正被 --wait 等待的服务。"""
    for svc in ("api", "db"):
        assert has_healthcheck(svc), f"{svc} 缺 healthcheck"
    assert "/api/v1/health" in healthcheck_lines("api"), "api 应探 /api/v1/health"
    assert "pg_isready" in healthcheck_lines("db"), "db 应探 pg_isready"


def test_api_healthcheck_uses_exec_form() -> None:
    """api 打的是 HTTP 端点，用 CMD（exec）即可，不该经过 shell。"""
    assert re.search(r'test:\s*\[\s*"CMD"', healthcheck_lines("api")), "api 的健康检查应用 exec 形式"


def test_ci_still_waits_and_builds() -> None:
    """CI 仍用 `--wait` + `--build` —— 前者让健康检查有意义，后者产出 worker 复用的镜像。"""
    ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "--wait" in ci, "CI 的 compose up 应带 --wait"
    assert "--build" in ci, "CI 的 compose up 应带 --build"
    assert "docker compose -p lottolab-ci up -d --build --wait" in ci
