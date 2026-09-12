"""API 层测试：真实 FastAPI TestClient，不使用任何假接口。"""

import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    """每条记录测试用独立的临时 SQLite 文件，互不影响。"""
    db_file = tmp_path / "records.db"
    monkeypatch.setenv("RECORDS_DB_PATH", str(db_file))
    return db_file


def test_health():
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_judge_qualified_returns_full_payload():
    resp = client.post(
        "/api/judge",
        json={"wet_mass": "8.640", "dry_masses": ["8.000", "8.000", "8.000"]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["constant"] is True
    assert body["hit_round"] == 1
    assert body["endpoint_mass"] == "8.000"
    assert body["regain"] == "8.00"
    assert body["qualified"] is True
    assert body["conclusion"] == "合格"
    assert body["formula"].startswith("(8.640 − 8.000)")
    # 完整轮次信息
    assert body["rounds"][0]["status"] == "hit"
    assert body["rounds"][0]["ratio_display"] == "0.000000"


def test_judge_not_constant_payload():
    resp = client.post(
        "/api/judge",
        json={"wet_mass": "11", "dry_masses": ["10.000", "9.990", "9.980"]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["constant"] is False
    assert body["conclusion"] == "尚未恒重"
    assert body["regain"] is None
    assert body["qualified"] is None
    assert body["formula"] is None


def test_422_has_field_keyed_errors():
    resp = client.post(
        "/api/judge",
        json={
            "wet_mass": "0",
            "dry_masses": ["10.000", "10.001", "abc", "9.0000"],
        },
    )
    assert resp.status_code == 422
    body = resp.json()
    assert "errors" in body
    errors = body["errors"]
    assert errors["wet_mass"] is not None
    assert "大于零" in errors["wet_mass"]
    # 首个回升轮次挂在第 2 次读数上
    assert "第 1 轮" in errors["dry_masses"][1]
    # 第 3 次不是数字
    assert "数字" in errors["dry_masses"][2]
    # 第 4 次超过三位小数
    assert "三位小数" in errors["dry_masses"][3]


def test_422_when_wet_not_greater_than_dry():
    resp = client.post(
        "/api/judge",
        json={"wet_mass": "10.000", "dry_masses": ["10.000", "9.990", "9.980"]},
    )
    assert resp.status_code == 422
    assert "小于烘前湿样质量" in resp.json()["errors"]["dry_masses"][0]


def test_422_dry_count_out_of_range():
    resp = client.post(
        "/api/judge",
        json={"wet_mass": "11", "dry_masses": ["10.000", "9.990"]},
    )
    assert resp.status_code == 422
    assert resp.json()["errors"]["dry_count"] is not None


def test_missing_body_is_422():
    resp = client.post("/api/judge", content=b"not-json",
                       headers={"content-type": "application/json"})
    assert resp.status_code == 422
    assert "errors" in resp.json()


def test_integer_masses_accepted():
    resp = client.post(
        "/api/judge",
        json={"wet_mass": 11, "dry_masses": [10, 10, 10]},
    )
    assert resp.status_code == 200
    assert resp.json()["endpoint_mass"] == "10"


def test_boolean_mass_rejected():
    resp = client.post(
        "/api/judge",
        json={"wet_mass": True, "dry_masses": [10, 10, 10]},
    )
    assert resp.status_code == 422
    assert resp.json()["errors"]["wet_mass"] is not None


# ---------- 试样记录：保存与查询 ----------

QUALIFIED_PAYLOAD = {"wet_mass": "8.640", "dry_masses": ["8.000", "8.000", "8.000"]}
OUT_OF_RANGE_PAYLOAD = {"wet_mass": "8.681", "dry_masses": ["8.000", "8.000", "8.000"]}
NOT_CONSTANT_PAYLOAD = {"wet_mass": "11", "dry_masses": ["10.000", "9.990", "9.980"]}


def test_save_and_get_roundtrip_qualified(isolated_db):
    judge_body = client.post("/api/judge", json=QUALIFIED_PAYLOAD).json()

    resp = client.post(
        "/api/records", json={"sample_id": "CF-0001", **QUALIFIED_PAYLOAD}
    )
    assert resp.status_code == 201
    saved = resp.json()
    assert saved["sample_id"] == "CF-0001"
    assert saved["saved_at"]
    # 快照与裁决响应逐字段一致（仅多出编号与保存时间）
    assert {k: v for k, v in saved.items() if k not in ("sample_id", "saved_at")} == judge_body
    assert saved["conclusion"] == "合格"

    got = client.get("/api/records/CF-0001")
    assert got.status_code == 200
    # 查询返回与保存时同一响应结构，原样查回
    assert got.json() == saved


def test_save_and_get_roundtrip_out_of_range(isolated_db):
    resp = client.post(
        "/api/records", json={"sample_id": "CF-0002", **OUT_OF_RANGE_PAYLOAD}
    )
    assert resp.status_code == 201
    saved = resp.json()
    assert saved["qualified"] is False
    assert saved["conclusion"] == "越界"
    assert saved["regain"] == "8.51"

    got = client.get("/api/records/CF-0002")
    assert got.status_code == 200
    assert got.json() == saved


def test_unrounded_regain_stored_as_decimal_string(isolated_db):
    # 未舍入 7.4989... < 7.5 越界，显示 7.50：未舍入值必须以十进制字符串入库
    resp = client.post(
        "/api/records",
        json={"sample_id": "CF-0003", "wet_mass": "7.526",
              "dry_masses": ["7.002", "7.001", "7.001"]},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["regain"] == "7.50"
    assert body["regain_exact"].startswith("7.4989")
    assert body["qualified"] is False

    # 落库的质量与未舍入回潮率均为十进制定点字符串
    conn = sqlite3.connect(str(isolated_db))
    try:
        row = conn.execute(
            "SELECT wet_mass, dry_masses, regain_exact FROM sample_records"
            " WHERE sample_id = 'CF-0003'"
        ).fetchone()
    finally:
        conn.close()
    assert row[0] == "7.526"
    assert json.loads(row[1]) == ["7.002", "7.001", "7.001"]
    assert row[2].startswith("7.4989")


def test_duplicate_sample_id_conflict_keeps_first_snapshot(isolated_db):
    first = client.post("/api/records", json={"sample_id": "DUP", **QUALIFIED_PAYLOAD})
    assert first.status_code == 201
    first_body = first.json()

    # 同一编号、不同数据：必须冲突且不改写首份快照
    conflict = client.post("/api/records", json={"sample_id": "DUP", **OUT_OF_RANGE_PAYLOAD})
    assert conflict.status_code == 409
    assert "DUP" in conflict.json()["detail"]

    got = client.get("/api/records/DUP")
    assert got.status_code == 200
    assert got.json() == first_body
    assert got.json()["wet_mass"] == "8.640"


def test_save_not_constant_rejected_and_not_stored(isolated_db):
    resp = client.post("/api/records", json={"sample_id": "NC-1", **NOT_CONSTANT_PAYLOAD})
    assert resp.status_code == 422
    assert "尚未恒重" in resp.json()["detail"]
    # 未入库
    assert client.get("/api/records/NC-1").status_code == 404


def test_save_invalid_masses_returns_field_errors(isolated_db):
    resp = client.post(
        "/api/records",
        json={"sample_id": "BAD-1", "wet_mass": "0",
              "dry_masses": ["10.000", "10.001", "abc"]},
    )
    assert resp.status_code == 422
    errors = resp.json()["errors"]
    assert "大于零" in errors["wet_mass"]
    assert "第 1 轮" in errors["dry_masses"][1]
    assert "数字" in errors["dry_masses"][2]
    assert errors["sample_id"] is None


def test_save_missing_or_blank_sample_id(isolated_db):
    for bad_id in (None, "", "   ", 123, "x" * 65):
        resp = client.post(
            "/api/records", json={"sample_id": bad_id, **QUALIFIED_PAYLOAD}
        )
        assert resp.status_code == 422, bad_id
        assert resp.json()["errors"]["sample_id"] is not None
    assert client.get("/api/records/x").status_code == 404


def test_save_malformed_body_is_422(isolated_db):
    resp = client.post("/api/records", content=b"not-json",
                       headers={"content-type": "application/json"})
    assert resp.status_code == 422
    assert "errors" in resp.json()


def test_get_missing_record_404(isolated_db):
    resp = client.get("/api/records/NO-SUCH-ID")
    assert resp.status_code == 404
    assert "NO-SUCH-ID" in resp.json()["detail"]


def test_sample_id_saved_with_whitespace_trimmed(isolated_db):
    resp = client.post(
        "/api/records", json={"sample_id": "  TRIM-1  ", **QUALIFIED_PAYLOAD}
    )
    assert resp.status_code == 201
    assert resp.json()["sample_id"] == "TRIM-1"
    assert client.get("/api/records/TRIM-1").status_code == 200
