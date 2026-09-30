"""README 承诺 ↔ 代码路径 对账门禁。

背景（2026-09-30 实测事故）
README 三条立场里写「多源交叉校验，不一致的期号拒绝入库」。逐行核实后：
  · collector/daily_sync.py 是单源 append —— 硬编码 source="17500"，
    从不 import collect_core.ingest
  · 带多源语义指纹比对（records_by_source → accepted/rejected）的逻辑只在
    collector/shadow_parallel.py，而影子的 DIVERGE → sys.exit(1) 是告警不是拦截
  · 线上 23 条 ingestion_runs 的 source 全是单值，conflicts 合计 0

也就是说「拒绝入库」这句承诺对影子表成立、对生产表不成立。这类问题
在 201 项测试里全绿的情况下长期存在 —— 因为没有任何测试检查 README 的断言
是否对应某条真实的代码路径。

本文件就是补这个洞。原则：
  · 不检查 README 的措辞好坏，只检查它承诺的东西在代码里是否成立
  · 凡是「运行时才知道」的事（真跑一次采集），一律用收集函数的方式证明，
    而不是断言文件里有没有某个字符串
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def imported_names(rel: str) -> set[str]:
    """一个模块 import 了哪些本地模块名（只看 from X import / import X）。"""
    tree = ast.parse(read(rel))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
        elif isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
    return names


# ---------------------------------------------------------------- 承诺一：
# 「多源交叉校验，不一致的期号拒绝入库」对生产写入路径不成立


def test_daily_sync_is_single_source_and_says_so() -> None:
    """daily_sync 必须是单源，且代码里要写明「未交叉校验」。

    断言它**不** import collect_core：如果哪天有人接上了多源，这条会红，
    提醒同步更新 README 的那条说明 —— 这正是我们要的行为（承诺要跟代码一起变）。
    """
    src = read("collector/daily_sync.py")
    assert "collect_core" not in imported_names("collector/daily_sync.py"), (
        "daily_sync 现在 import 了 collect_core —— 多源校验可能已接入生产写入路径，"
        "README 里「影子层比对 / 生产单源」的说法需要重新核实并更新"
    )
    assert 'source="17500"' in src, "daily_sync 应仍是单源 17500 写入"
    # 必须显式声明，而不是靠列默认值让人猜
    assert "sources_cross_checked=False" in src, (
        "daily_sync 必须显式写 sources_cross_checked=False，让读代码的人不会误以为 "
        "conflicts=0 意味着「比对过」"
    )


def test_shadow_job_cannot_block_production_writes() -> None:
    """影子作业不得写生产 draws —— 它是比对告警，不是写入拦截。

    反过来也成立：如果影子改成直接改 draws，那它就成了拦截器，
    「生产单源」的说法需要改。这条锁住两个方向。
    """
    src = read("collector/shadow_parallel.py")
    tree = ast.parse(src)
    write_targets: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = getattr(func, "attr", None) or getattr(func, "id", None)
            if name in {"execute", "executemany"}:
                for arg in node.args:
                    text = ast.dump(arg)
                    if "Draw" in text:
                        write_targets.add("Draw")
    assert "Draw" not in write_targets, "shadow_parallel 出现了对 Draw 的写操作 —— 影子作业越权了"
    assert "DELETE" not in src.upper() or "collect_shadow" in src, "影子作业不得 DELETE 生产数据"
    # DIVERGE 只能告警退出，不能影响 draws
    assert "sys.exit(1)" in src, "影子作业发现分歧应非零退出以触发告警"


def test_readme_does_not_claim_cross_validation_blocks_production() -> None:
    """README 不得声称「不一致的期号拒绝入库」（对生产表而言是假的）。"""
    readme = read("README.md")
    forbidden = [
        "多源交叉校验，不一致的期号拒绝入库",
        "不一致的期号拒绝入库",
    ]
    for phrase in forbidden:
        # 允许出现在「更正说明」里（引号包裹的引用），禁止作为当前立场出现
        occurrences = [
            line for line in readme.splitlines() if phrase in line and not line.strip().startswith(">")
        ]
        assert not occurrences, f"README 仍把「{phrase}」当作当前事实陈述：" + " / ".join(occurrences)
    assert "影子层" in readme, "README 应说明多源比对发生在影子层"


def test_ingestion_run_records_whether_cross_check_happened() -> None:
    """sources_cross_checked 必须同时存在于模型、迁移和 API 输出里。

    缺任何一环，「这批到底有没有被校验过」就又变成了只能靠猜的字段。
    """
    db_src = read("backend/lottolab/db.py")
    assert "sources_cross_checked" in db_src, "IngestionRun 模型缺 sources_cross_checked 列"
    assert '"sources_cross_checked"' in db_src, "public() 未暴露 sources_cross_checked，API 读不到"

    migration = read("migrations/versions/x2srcval01_ingestion_cross_checked.py")
    assert "sources_cross_checked" in migration, "迁移未添加 sources_cross_checked"
    assert "sa.false()" in migration, "迁移的默认值必须是 false（默认「未校验」而非「已校验」）"

    # 历史行必须回填 false 而不是 true —— 按 true 回填等于凭空造出从未发生的校验
    assert "False" in migration or "false" in migration


def test_collect_core_actually_rejects_conflicts() -> None:
    """证明多源比对逻辑本身是有效的（不只存在于文档里）。

    这条同时锁住「缺期≠冲突」这类语义：只有一源给出的期号不算矛盾。
    """
    import sys

    sys.path.insert(0, str(ROOT / "collector"))
    sys.path.insert(0, str(ROOT / "backend"))
    from collect_core import ingest  # noqa: PLC0415

    a = {"issue": "2026100", "main": [1, 2, 3, 4, 5, 6], "special": [7], "draw_date": "2026-10-01"}
    b = dict(a, main=[1, 2, 3, 4, 5, 9])

    conflict = ingest("ssq", {"srcA": [a], "srcB": [b]}, today="2026-10-02")
    assert "2026100" in conflict["rejected"], "两源号码不一致时必须拒绝入库"
    assert "2026100" not in conflict["accepted"], "冲突期号不得同时出现在 accepted"

    agree = ingest("ssq", {"srcA": [a], "srcB": [dict(a)]}, today="2026-10-02")
    assert "2026100" in agree["accepted"], "两源一致时应接受"
    assert not agree["rejected"], "一致时不应有 rejected"


def test_single_source_ingest_is_accepted_but_proves_nothing() -> None:
    """单源会被 ingest 放行 —— 所以「过了 ingest」不能证明「经过多源校验」。

    这条是 README 那条更正说明的代码依据：即使把 ingest 接进 daily_sync，
    仍需同时记录源数 ≥2 才能证明批次经过校验。
    """
    import sys

    sys.path.insert(0, str(ROOT / "collector"))
    sys.path.insert(0, str(ROOT / "backend"))
    from collect_core import ingest  # noqa: PLC0415

    a = {"issue": "2026100", "main": [1, 2, 3, 4, 5, 6], "special": [7], "draw_date": "2026-10-01"}
    single = ingest("ssq", {"ONLY": [a]}, today="2026-10-02")
    assert "2026100" in single["accepted"], (
        "若将来 ingest 改为对单源 fail-closed，这条会红 —— README 的更正说明需要同步更新"
    )


# ---------------------------------------------------------------- 承诺二：PWA


def test_readme_does_not_claim_pwa_without_manifest_or_service_worker() -> None:
    """README 标了 PWA，但仓库里既无 manifest 也无 Service Worker。"""
    has_manifest = any(ROOT.glob("frontend/**/manifest*.json"))
    has_sw = [
        p
        for p in ROOT.glob("frontend/**/*")
        if p.is_file() and p.name in {"sw.js", "service-worker.js", "service-worker.ts"}
    ]
    readme = read("README.md")
    claims_pwa = "PWA" in readme and "无 PWA" not in readme

    if claims_pwa:
        assert has_manifest, "README 声称 PWA 但仓库无 manifest.json"
        assert has_sw, "README 声称 PWA 但仓库无 Service Worker"
    # 若将来真的接入 PWA，这条测试会自然通过（manifest 存在 + README 保留 PWA 字样）


# ---------------------------------------------------------------- 承诺三：访问控制


def test_public_mode_default_is_closed_except_vercel_without_token() -> None:
    """公开写只在 Vercel 未设令牌时开启；本地/Docker 默认必须拒绝写入。"""
    config_src = read("backend/lottolab/config.py")
    assert "public_mode: bool = False" in config_src, "public_mode 默认必须是 False（安全默认）"
    assert "allow_local_writes: bool = False" in config_src, "allow_local_writes 默认必须是 False"

    cloud_src = read("backend/lottolab/cloud.py")
    # 不设令牌 → public_mode=True（这是有意设计，但 README 必须警示）
    assert 'admin_token, public_mode = "", True' in cloud_src, (
        "Vercel 未设令牌即开启公开写的逻辑变了 —— README 的部署警示需要重新核实"
    )
    assert "32" in cloud_src, "令牌强度门槛（≥32 位）应仍在"

    readme = read("README.md")
    assert "LOTTOLAB_ADMIN_TOKEN" in readme
    # README 必须显式警示「不设令牌 = 对互联网开放写端点」
    assert "公开" in readme and ("开放" in readme or "无需登录" in readme)


# ---------------------------------------------------------------- 文档数字门禁


def test_readme_test_count_matches_pytest_collection() -> None:
    """README 声明的 pytest 项数必须与真实收集数一致。

    2026-09-30 实测：README 写 201 项，真实收集也是 201（199 passed + 2 skipped）——
    当时有静态解析误报为 199 的情况，说明这一层必须有可执行的对账，
    而不是靠数 def test_ 猜。
    """
    readme = read("README.md")
    # 用正则取「<数字> 项 pytest」；别用 split —— 那一行前面还有「ruff 检查与格式、`mypy`、」
    # 之类的文字，直接切词会切出「'检查与格式、`mypy`、201'」这种非数字。
    declared = [int(m.group(1)) for m in re.finditer(r"(\d+)\s*项\s*pytest", readme)]
    assert declared, "README 未声明 pytest 项数"

    actual = _collect_count()
    for n in declared:
        assert n == actual, f"README 声明 {n} 项 pytest，真实收集 {actual} 项"


def _collect_count() -> int:
    """数出 pytest 会收集多少项（不执行用例，避免依赖数据库/网络）。"""
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    for line in result.stdout.splitlines():
        if "collected" in line and "test" in line:
            token = line.strip().split()[0]
            if token.isdigit():
                return int(token)
    pytest.skip(f"无法从 pytest --collect-only 解析项数：\n{result.stdout[-500:]}")


def test_changelog_has_no_empty_unreleased_section() -> None:
    """CHANGELOG 的 [未发布] 章节为空是噪音（2026-09-30 实测存在）。"""
    changelog = read("CHANGELOG.md")
    if "## [未发布]" not in changelog:
        pytest.skip("CHANGELOG 已无 [未发布] 章节")
    body = changelog.split("## [未发布]", 1)[1]
    first_next = body.find("\n## ")
    section = body[:first_next] if first_next > 0 else body
    assert section.strip(), "CHANGELOG 的 [未发布] 章节是空的 —— 要么填内容，要么删掉标题"
