import copy

import pytest
from lottolab.db import Draw, QualityIssue
from lottolab.ingestion import canonical, freeze_dataset, ingest_records, parse_csv
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError


def ingest(session, rows, tmp_path, lottery="ssq"):
    return ingest_records(
        session,
        rows,
        lottery=lottery,
        dataset_kind="real",
        source="test fixture",
        source_url="fixture://unit-test",
        raw=canonical(rows),
        data_dir=tmp_path,
    )


def test_idempotence_conflict_and_invalid_quarantine(session_factory, raw_draw, tmp_path):
    with session_factory() as session:
        result = ingest(session, [raw_draw], tmp_path)
        assert result["accepted"] == 1
        assert ingest(session, [raw_draw], tmp_path)["duplicates"] == 1
        conflict = {**raw_draw, "special_numbers": [1]}
        invalid = {**raw_draw, "issue": "2026104", "main_numbers": [99]}
        result = ingest(session, [conflict, invalid], tmp_path)
        assert (result["conflicts"], result["rejected"], result["accepted"]) == (1, 1, 0)
        assert session.scalar(select(func.count()).select_from(Draw)) == 1
        assert session.scalar(select(Draw)).special_numbers == [8]
        assert session.scalar(select(func.count()).select_from(QualityIssue)) == 2
        assert len(list((tmp_path / "raw").glob("*.snapshot"))) == 2


def test_database_defends_number_constraints(session_factory, raw_draw, tmp_path):
    with session_factory() as session:
        ingest(session, [raw_draw], tmp_path)
        existing = session.scalar(select(Draw))
        existing.main_numbers = [2, 2, 13, 14, 15, 30]
        with pytest.raises(IntegrityError):
            session.commit()


def test_cross_lottery_issue_and_frozen_version(session_factory, raw_draw, tmp_path):
    with session_factory() as session:
        ingest(session, [raw_draw], tmp_path)
        version = freeze_dataset(session, "ssq", "real")
        original = copy.deepcopy(version.draws)
        session.commit()
        dlt = {**raw_draw, "lottery": "dlt", "main_numbers": [1, 4, 8, 23, 35], "special_numbers": [1, 12]}
        assert ingest(session, [dlt], tmp_path, "dlt")["accepted"] == 1
        ingest(session, [{**raw_draw, "issue": "2026104", "draw_date": "2026-09-08"}], tmp_path)
        assert version.draws == original
        assert freeze_dataset(session, "ssq", "real").id != version.id


def test_csv_parsing_preserves_bad_rows_for_audit():
    csv = 'issue,draw_date,main_numbers,special_numbers\n2026105,2026-09-10,"02 04 13 14 15 30",08\n2026104,2026-09-08,bad,03\n'
    rows = parse_csv(csv.encode())
    assert rows[0]["main_numbers"] == [2, 4, 13, 14, 15, 30]
    assert "_parse_error" in rows[1]
    with pytest.raises(ValueError):
        parse_csv(b"wrong,header\n1,2")


def test_csv_empty_special_column_is_accepted():
    """数字型等无附加区彩种：special_numbers 留空不应整行解析失败。"""
    csv = (
        "issue,draw_date,main_numbers,special_numbers\n"
        "2026246,2026-09-13,1 2 3,\n"
        "2026245,2026-09-12,04 05 06,\n"
    )
    rows = parse_csv(csv.encode())
    assert rows[0]["special_numbers"] == []
    assert "_parse_error" not in rows[0]
    assert rows[1]["main_numbers"] == [4, 5, 6]
    assert "_parse_error" not in rows[1]
