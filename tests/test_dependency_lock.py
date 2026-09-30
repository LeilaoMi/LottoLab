"""pyproject.toml 与 requirements.lock 的版本必须一致。

背景（2026-09-30）
CI 的 backend job 依次跑：
    pip install -r requirements.lock && pip install --no-deps -e .
前者按 requirements.lock 装，后者按 pyproject.toml 的 `dependencies` 声明安装自身，
随后 `pip check` 校验两者一致。

而 Dependabot 的 pip 更新器只改 pyproject.toml，不会碰 requirements.lock
（后者不在它的默认更新目标里）。于是升级 PR 一律在 `pip check` 处失败：

    lottolab 1.1.1 has requirement uvicorn==0.54.0, but you have uvicorn 0.52.4
    lottolab 1.1.1 has requirement sqlalchemy==2.1.1, but you have sqlalchemy 2.0.52
    ...共 4 项

这条测试在合并前就会发现该问题，不必等 CI。CI 保留 `pip check` 作为第二道防线
（它能发现本测试看不见的传递依赖错配）。

注意 psycopg[binary] 会被 pip 拆成 psycopg + psycopg-binary 两个包，
两者必须同版本 —— 只改其中一个同样会让 pip check 失败。
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def pyproject_pins() -> dict[str, str]:
    """从 pyproject.toml 的 dependencies 里取出 包名 -> 版本。

    只取 [project].dependencies 那一段（第一个 `dependencies = [` 到对应的 `]`），
    避免把 optional-dependencies（dev 工具链）也拉进来 —— dev 依赖不在
    requirements.lock 里，按设计就不该出现。
    """
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    m = re.search(r"^dependencies = \[(.*?)^\]", text, re.M | re.S)
    assert m, "pyproject.toml 里找不到 [project].dependencies"
    pins: dict[str, str] = {}
    for spec in re.findall(r'"([^"]+)"', m.group(1)):
        mm = re.match(r"([A-Za-z0-9._-]+)(\[[^\]]*\])?==([\d][\w.]*)", spec.strip())
        if mm:
            pins[mm.group(1).lower()] = mm.group(3)
    return pins


def lock_pins() -> dict[str, str]:
    pins: dict[str, str] = {}
    for line in (ROOT / "requirements.lock").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith(("#", "-")):
            continue
        mm = re.match(r"([A-Za-z0-9._-]+)(\[[^\]]*\])?==([\d][\w.]*)", line)
        if mm:
            pins[mm.group(1).lower()] = mm.group(3)
    return pins


def test_every_runtime_dependency_is_pinned_in_lock() -> None:
    """pyproject 里声明的每个运行时依赖都必须在 requirements.lock 里出现。"""
    locked = lock_pins()
    missing = sorted(set(pyproject_pins()) - set(locked))
    assert not missing, f"pyproject 声明了但 requirements.lock 缺：{missing}"


def test_runtime_dependency_versions_match() -> None:
    """两边版本必须逐项相同 —— 这正是 pip check 会报的那几条。"""
    declared = pyproject_pins()
    locked = lock_pins()
    mismatch = {
        name: (ver, locked[name]) for name, ver in declared.items() if name in locked and locked[name] != ver
    }
    assert not mismatch, (
        f"pyproject 与 requirements.lock 版本不一致：{mismatch}。"
        "CI 的 pip check 会因此失败（它先按 lock 装、再按 pyproject 装自身）。"
        "修法：把 lock 里对应项改成与 pyproject 相同的版本。"
    )


def test_psycopg_binary_split_shares_version_with_psycopg() -> None:
    """psycopg[binary] 会被拆成 psycopg + psycopg-binary，两者必须同版本。

    Dependabot 与手工升级都容易只改一个 —— 而 `pip check` 只会在 CI 里报出来。
    """
    locked = lock_pins()
    assert "psycopg" in locked, "lock 应含 psycopg"
    if "psycopg-binary" in locked:
        assert locked["psycopg"] == locked["psycopg-binary"], (
            f"psycopg=={locked['psycopg']} 与 psycopg-binary=={locked['psycopg-binary']} "
            "版本不一致；pyproject 声明的是 psycopg[binary]，pip 会拆成这两个包"
        )
    # pyproject 侧同样应保持一致
    declared = pyproject_pins()
    assert "psycopg" in declared, "pyproject 应声明 psycopg[binary]"


def test_lock_has_no_unpinned_entries() -> None:
    """requirements.lock 里不该出现未固定版本的条目 —— 「lock」的前提就是全钉死。"""
    loose = [
        line.strip()
        for line in (ROOT / "requirements.lock").read_text(encoding="utf-8").splitlines()
        if line.strip()
        and not line.strip().startswith(("#", "-"))
        and not re.match(r"[A-Za-z0-9._-]+(\[[^\]]*\])?==[\d][\w.]*", line.strip())
    ]
    assert not loose, f"requirements.lock 里有未固定版本的条目：{loose}"
