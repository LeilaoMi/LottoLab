"""
shadow_parallel.py —— 采集器「每日影子并跑」作业体（CI 里跑；本机无 psycopg/凭据时可只 --dry）。
职责：真拉公开源 → 归一+交叉校验 → UPSERT 影子表 → 以生产 draws 为基准写账本 → 偏差才告警。
安全：只写 collect_shadow / collect_shadow_log；对 draws 仅 SELECT。破坏性操作一概不做。
运行（CI，需 secret DATABASE_URL）：  python shadow_parallel.py
本机演练（不落库、仅打印将要执行的）：python shadow_parallel.py --dry
"""
import sys, os, json, subprocess, datetime
import parsers as P
import collect_core as cc
from contract import canonicalize

DRY = "--dry" in sys.argv
URLS = {
    ("ssq", "cwl"): "https://www.cwl.gov.cn/cwl_admin/front/cwlkj/search/kjxx/findDrawNotice?name=ssq&issueCount=8",
    ("ssq", "500"): "https://datachart.500.com/ssq/history/newinc/history.php?limit=8&sort=0",
    ("dlt", "500"): "https://datachart.500.com/dlt/history/newinc/history.php?limit=8&sort=0",
    # 大乐透官方 sporttery 服务端需带 cookie/UA 突破，暂列 500 单源 + 与生产库比对为准
}
def get(url):
    r = subprocess.run(["curl", "-k", "--ssl-no-revoke", "--max-time", "25",
                        "-A", "Mozilla/5.0", "-s", url], capture_output=True, text=True)
    return r.stdout

def collect(kind):
    feeds = {}
    if kind == "ssq":
        feeds["cwl"] = P.parse_cwl(get(URLS[("ssq", "cwl")]), "ssq")
        feeds["500"] = P.parse_500(get(URLS[("ssq", "500")]), "ssq")
    else:
        feeds["500"] = P.parse_500(get(URLS[("dlt", "500")]), "dlt")
    return cc.ingest(kind, feeds)

DDL = ("CREATE TABLE IF NOT EXISTS collect_shadow (kind text, issue text, draw_date date, main_numbers json, "
       "special_numbers json, sales numeric, pool_amount numeric, prizes json, source text, collected_at timestamptz, "
       "PRIMARY KEY(kind,issue));")
DDL_LOG = ("CREATE TABLE IF NOT EXISTS collect_shadow_log (run_date date, kind text, shadow_n int, prod_overlap int, "
           "mismatch int, collector_ahead int, verdict text, checked_at timestamptz DEFAULT now());")

def sql_upsert_shadow(kind, accepted):
    now = datetime.datetime.now(datetime.UTC).isoformat()
    vals = []
    for r in accepted.values():
        mj = json.dumps(r["main"]); sj = json.dumps(r["special"])
        vals.append(f"({q(kind)},{q(r['issue'])},{q(r['draw_date'])},{q(mj)}::json,{q(sj)}::json,{q(r.get('sales')) if r.get('sales') else 'NULL'},"
                    f"{q(r.get('pool')) if r.get('pool') else 'NULL'},{q(json.dumps(r.get('prizes') or {}))}::json,{q(r.get('src',''))},{q(now)})")
    return (f"INSERT INTO collect_shadow (kind,issue,draw_date,main_numbers,special_numbers,sales,pool_amount,prizes,source,collected_at) "
            f"VALUES {','.join(vals)} ON CONFLICT (kind,issue) DO NOTHING;") if vals else None

def q(s):
    s = str(s).replace("'", "''")
    return "'" + s + "'"

LOG_SQL = ("INSERT INTO collect_shadow_log (run_date,kind,shadow_n,prod_overlap,mismatch,collector_ahead,verdict) "
           "SELECT current_date, s.kind, count(*), count(*) FILTER (WHERE d.issue IS NOT NULL), "
           "count(*) FILTER (WHERE d.issue IS NOT NULL AND (s.m IS DISTINCT FROM d.m OR s.sp IS DISTINCT FROM d.sp OR s.dd IS DISTINCT FROM d.dd)), "
           "count(*) FILTER (WHERE d.issue IS NULL), "
           "CASE WHEN count(*) FILTER (WHERE d.issue IS NOT NULL AND (s.m IS DISTINCT FROM d.m OR s.sp IS DISTINCT FROM d.sp OR s.dd IS DISTINCT FROM d.dd))=0 "
           "THEN 'OK' ELSE 'DIVERGE' END "
           "FROM (SELECT kind,issue,draw_date::text dd, main_numbers::jsonb m, special_numbers::jsonb sp FROM collect_shadow) s "
           "LEFT JOIN (SELECT lottery kind,issue,draw_date::text dd,main_numbers::jsonb m,special_numbers::jsonb sp FROM draws WHERE dataset_kind='real') d "
           "ON d.kind=s.kind AND d.issue=s.issue GROUP BY s.kind;")

def run_sql(conn, sql):
    with conn.cursor() as cur:
        cur.execute(sql)

def main():
    accepted = {kind: collect(kind) for kind in ("ssq", "dlt")}
    stmts = [DDL, DDL_LOG]
    for kind, res in accepted.items():
        s = sql_upsert_shadow(kind, res["accepted"])
        if s: stmts.append(s)
    stmts.append(LOG_SQL)
    if DRY:
        print("[DRY] 将执行 %d 条语句（只碰影子表），示例：" % len(stmts))
        print(stmts[2][:300], "...")
        return
    import psycopg  # CI 环境有
    url = os.environ["DATABASE_URL"]
    with psycopg.connect(url) as conn:
        for st in stmts:
            run_sql(conn, st)
        conn.commit()
        with conn.cursor() as cur:
            cur.execute("SELECT kind,mismatch,collector_ahead,verdict FROM collect_shadow_log ORDER BY checked_at DESC LIMIT 5;")
            rows = cur.fetchall()
    print("shadow-parallel done:", rows)
    bad = [r for r in rows if r[3] != "OK"]
    if bad:
        # 偏差才响；正常静默（避免天天喊）
        raise SystemExit(f"DIVERGE detected: {bad}")

if __name__ == "__main__":
    main()
