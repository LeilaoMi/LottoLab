"""B3-3：经正规 ingestion 通道写入 8 彩种（含 DIGIT）的入库测试——复用 ingest_records，溯源天然正确。"""

from lottolab.db import Draw
from lottolab.ingestion import ingest_records
from sqlalchemy import select


def _ingest(session_factory, tmp_path, lottery, records):
    with session_factory() as s:
        r = ingest_records(
            s,
            records,
            lottery=lottery,
            dataset_kind="real",
            source="test",
            source_url="https://example/x",
            raw=b"fixture-raw",
            data_dir=tmp_path,
            store_in_database=True,
        )
        s.commit()
        return r


def test_ingest_fc3d_digit_persists_with_provenance(session_factory, tmp_path):
    recs = [{"issue": "2026246", "draw_date": "2026-09-13", "main_numbers": [9, 8, 2], "special_numbers": []}]
    r = _ingest(session_factory, tmp_path, "fc3d", recs)
    assert r["accepted"] == 1
    with session_factory() as s:
        d = s.scalars(select(Draw).where(Draw.lottery == "fc3d")).one()
        assert d.main_numbers == [9, 8, 2]  # 有序、不排序
        assert d.identity_hash and d.rule_version == "fc3d-number-space-v1"


def test_ingest_qxc_last14_ok_and_15_rejected(session_factory, tmp_path):
    ok = [
        {
            "issue": "26106",
            "draw_date": "2026-09-13",
            "main_numbers": [5, 1, 9, 5, 8, 5, 11],
            "special_numbers": [],
        }
    ]
    assert _ingest(session_factory, tmp_path, "qxc", ok)["accepted"] == 1
    bad = [
        {
            "issue": "26107",
            "draw_date": "2026-09-14",
            "main_numbers": [5, 1, 9, 5, 8, 5, 15],
            "special_numbers": [],
        }
    ]
    r2 = _ingest(session_factory, tmp_path, "qxc", bad)
    assert r2["accepted"] == 0 and r2["rejected"] >= 1


def test_ingest_kl8_pool(session_factory, tmp_path):
    nums = list(range(1, 21))
    recs = [{"issue": "2026246", "draw_date": "2026-09-13", "main_numbers": nums, "special_numbers": []}]
    assert _ingest(session_factory, tmp_path, "kl8", recs)["accepted"] == 1


def test_ingest_qlc_pool(session_factory, tmp_path):
    recs = [
        {
            "issue": "2026105",
            "draw_date": "2026-09-11",
            "main_numbers": [8, 19, 20, 21, 23, 27, 30],
            "special_numbers": [5],
        }
    ]
    assert _ingest(session_factory, tmp_path, "qlc", recs)["accepted"] == 1
