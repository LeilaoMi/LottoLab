"""
shadow_parallel.py —— 每日影子并跑作业体（健壮版）。
策略：逐源抓取+解析，**单源失败不拖垮全场**；能拿到的源→交叉校验→只写影子表→以生产 draws 为基准记账。
退出码：仅当发现“真·号码不一致(DIVERGE)”才非零（触发告警）；纯“源够不着”→软告警(::warning)不失败。
安全：只写 collect_shadow / collect_shadow_log；对 draws 仅 SELECT；无 DROP/DELETE。
"""

import datetime
import json
import os
import subprocess
import sys

import collect_core as cc
import parsers as P

DRY = "--dry" in sys.argv
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"

SOURCES = {
    "ssq": [
        (
            "cwl",
            "https://www.cwl.gov.cn/cwl_admin/front/cwlkj/search/kjxx/findDrawNotice?name=ssq&issueCount=8",
            lambda t: P.parse_cwl(t, "ssq"),
        ),
        (
            "500",
            "https://datachart.500.com/ssq/history/newinc/history.php?limit=8&sort=0",
            lambda t: P.parse_500(t, "ssq"),
        ),
        ("17500", "http://data.17500.cn/ssq_asc.txt", lambda t: P.parse_17500(t, "ssq", 6, 1)),
    ],  # 红6+蓝1；cwl 在 GH 美区常不可达时仍有 500+17500 双源
    "dlt": [
        (
            "500",
            "https://datachart.500.com/dlt/history/newinc/history.php?limit=8&sort=0",
            lambda t: P.parse_500(t, "dlt"),
        ),
        ("17500", "http://data.17500.cn/dlt_asc.txt", lambda t: P.parse_17500(t, "dlt", 5, 2)),
    ],  # 前5+后2、5位期号→真第二独立源
    # 以下 6 彩种：17500 官方镜像采集（vs 生产库的逐期比对仍只 ssq/dlt；这里监控“采集健康”）
    "fc3d": [("17500", "http://data.17500.cn/3d_asc.txt", lambda t: P.parse_17500(t, "fc3d", 3, 0))],
    "pl3": [("17500", "http://data.17500.cn/pl3_asc.txt", lambda t: P.parse_17500(t, "pl3", 3, 0))],
    "pl5": [("17500", "http://data.17500.cn/pl5_asc.txt", lambda t: P.parse_17500(t, "pl5", 5, 0))],
    "qlc": [("17500", "http://data.17500.cn/7lc_asc.txt", lambda t: P.parse_17500(t, "qlc", 7, 1))],
    "qxc": [
        ("17500", "http://data.17500.cn/7xc_asc.txt", lambda t: P.parse_17500(t, "qxc", 7, 0))
    ],  # 5 位期号
    "kl8": [("17500", "http://data.17500.cn/kl8_asc.txt", lambda t: P.parse_17500(t, "kl8", 20, 0))],
}


def get(url):
    try:
        r = subprocess.run(
            ["curl", "-k", "--ssl-no-revoke", "--max-time", "60", "-A", UA, "-s", url],
            capture_output=True,
            text=True,
            timeout=75,
        )
        return r.stdout
    except Exception:
        return ""


def collect(kind):
    feeds, dead = {}, []
    for name, url, fn in SOURCES[kind]:
        txt = get(url)
        try:
            recs = fn(txt) if txt.strip() else None
        except Exception:
            recs = None
        if recs:
            feeds[name] = recs[:8]  # 统一到最近 8 期窗口，避免 17500 全量史灌影子表
        else:
            dead.append(name)
    return feeds, dead


def q(s):
    return "'" + str(s).replace("'", "''") + "'"


DDL = (
    "CREATE TABLE IF NOT EXISTS collect_shadow (kind text, issue text, draw_date date, main_numbers json, "
    "special_numbers json, sales numeric, pool_amount numeric, prizes json, source text, collected_at timestamptz, "
    "PRIMARY KEY(kind,issue));"
)
DDL_LOG = (
    "CREATE TABLE IF NOT EXISTS collect_shadow_log (run_date date, kind text, shadow_n int, prod_overlap int, "
    "mismatch int, collector_ahead int, verdict text, checked_at timestamptz DEFAULT now());"
)


def sql_upsert(kind, accepted):
    now = datetime.datetime.now(datetime.UTC).isoformat()
    vals = []
    for r in accepted.values():
        vals.append(
            f"({q(kind)},{q(r['issue'])},{q(r['draw_date'])},{q(json.dumps(r['main']))}::json,"
            f"{q(json.dumps(r['special']))}::json,"
            f"{(q(r['sales']) if r.get('sales') else 'NULL')},{(q(r['pool']) if r.get('pool') else 'NULL')},"
            f"{q(json.dumps(r.get('prizes') or {}))}::json,{q(r.get('src', ''))},{q(now)})"
        )
    if not vals:
        return None
    return (
        "INSERT INTO collect_shadow (kind,issue,draw_date,main_numbers,special_numbers,sales,pool_amount,prizes,source,collected_at) VALUES "
        + ",".join(vals)
        + " ON CONFLICT (kind,issue) DO NOTHING;"
    )


LOG_SQL = (
    "INSERT INTO collect_shadow_log (run_date,kind,shadow_n,prod_overlap,mismatch,collector_ahead,verdict) "
    "SELECT current_date, s.kind, count(*), count(*) FILTER (WHERE d.issue IS NOT NULL), "
    "count(*) FILTER (WHERE d.issue IS NOT NULL AND (s.m IS DISTINCT FROM d.m OR s.sp IS DISTINCT FROM d.sp OR s.dd IS DISTINCT FROM d.dd)), "
    "count(*) FILTER (WHERE d.issue IS NULL), "
    "CASE WHEN count(*) FILTER (WHERE d.issue IS NOT NULL AND (s.m IS DISTINCT FROM d.m OR s.sp IS DISTINCT FROM d.sp OR s.dd IS DISTINCT FROM d.dd))=0 "
    "THEN 'OK' ELSE 'DIVERGE' END "
    "FROM (SELECT kind,issue,draw_date::text dd, main_numbers::jsonb m, special_numbers::jsonb sp FROM collect_shadow) s "
    "LEFT JOIN (SELECT lottery kind,issue,draw_date::text dd,main_numbers::jsonb m,special_numbers::jsonb sp FROM draws WHERE dataset_kind='real') d "
    "ON d.kind=s.kind AND d.issue=s.issue GROUP BY s.kind;"
)


def main():
    built, unreachable = [], []
    for kind in SOURCES:
        feeds, dead = collect(kind)
        if not feeds:
            unreachable.append(kind)
            print(f"[{kind}] 全部源不可达：{dead}")
            continue
        if dead:
            print(f"[{kind}] 部分源不可达：{dead}（用剩余源继续）")
        res = cc.ingest(kind, feeds)
        s = sql_upsert(kind, res["accepted"])
        if s:
            built.append(s)
        print(f"[{kind}] 接受={len(res['accepted'])} 拒绝={len(res['rejected'])}")

    if DRY:
        print(f"[DRY] 可用影子写入语句 {len(built)} 条；不可达彩种={unreachable}")
        return

    import psycopg

    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        with conn.cursor() as cur:
            cur.execute(DDL)
            cur.execute(DDL_LOG)
            for st in built:
                cur.execute(st)
            cur.execute(LOG_SQL)
            cur.execute(
                "SELECT kind,mismatch,collector_ahead,verdict FROM collect_shadow_log ORDER BY checked_at DESC LIMIT 8;"
            )
            rows = cur.fetchall()
            conn.commit()
    print("最新账本：", rows)
    diverged = [r for r in rows if r[3] == "DIVERGE"]
    if unreachable:
        print(f"::warning::以下彩种源在本网络不可达(不影响数据一致性判定)：{unreachable}")
    if diverged:
        print(f"::error::发现号码不一致 DIVERGE：{diverged}")
        sys.exit(1)  # 只有真·数据分歧才失败


if __name__ == "__main__":
    main()
