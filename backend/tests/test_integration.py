"""集成验收测试：对已部署服务打真实 HTTP 请求。

BASE_URL 可覆盖；docker compose verify 默认指向 http://api:8000，
经 Nginx 的链路则用 http://web:80。
"""

import os
import uuid
from urllib.parse import quote

import httpx
import pytest

BASE_URL = os.environ.get("BASE_URL", "http://api:8000").rstrip("/")

pytestmark = pytest.mark.integration


def unique_id(prefix: str) -> str:
    """每次验收生成全新编号，避免落在持久卷上的历史记录造成误冲突。"""
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def test_health_live():
    resp = httpx.get(f"{BASE_URL}/api/health", timeout=10)
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_full_qualified_chain():
    resp = httpx.post(
        f"{BASE_URL}/api/judge",
        json={
            "wet_mass": "8.640",
            "dry_masses": ["8.100", "8.000", "8.000", "7.999"],
        },
        timeout=10,
    )
    assert resp.status_code == 200
    body = resp.json()
    # 第 1 轮 0.1/8.1 ≈ 0.0123 未达；第 2 轮 0 命中 → 终点 8.000，第 4 次仅展示
    assert body["hit_round"] == 2
    assert body["endpoint_mass"] == "8.000"
    assert body["rounds"][2]["status"] == "ignored"
    assert body["qualified"] is True
    assert body["conclusion"] == "合格"
    assert body["regain"] == "8.00"
    assert body["formula"]


def test_not_constant_chain():
    resp = httpx.post(
        f"{BASE_URL}/api/judge",
        json={"wet_mass": "11", "dry_masses": ["10.000", "9.990", "9.980"]},
        timeout=10,
    )
    body = resp.json()
    assert body["constant"] is False
    assert body["conclusion"] == "尚未恒重"
    assert body["regain"] is None


def test_validation_errors_over_http():
    resp = httpx.post(
        f"{BASE_URL}/api/judge",
        json={"wet_mass": "-1", "dry_masses": ["5", "5.001", "4"]},
        timeout=10,
    )
    assert resp.status_code == 422
    errors = resp.json()["errors"]
    assert errors["wet_mass"] is not None
    assert "首个回升轮次" in errors["dry_masses"][1]


def test_frontend_served_and_api_proxied():
    """WEB_PORT 宿主上的 Nginx 必须同时提供页面与 /api 反代。"""
    web_url = os.environ.get("WEB_URL", "http://web:80")
    page = httpx.get(f"{web_url}/", timeout=10)
    assert page.status_code == 200
    assert "<div id=\"app\"></div>" in page.text

    via_proxy = httpx.get(f"{web_url}/api/health", timeout=10)
    assert via_proxy.status_code == 200
    assert via_proxy.json()["status"] == "ok"


# ---------- 试样记录：保存后原样查回、冲突不改写、未恒重不入库 ----------

QUALIFIED_PAYLOAD = {"wet_mass": "8.640", "dry_masses": ["8.000", "8.000", "8.000"]}
OUT_OF_RANGE_PAYLOAD = {"wet_mass": "8.681", "dry_masses": ["8.000", "8.000", "8.000"]}
NOT_CONSTANT_PAYLOAD = {"wet_mass": "11", "dry_masses": ["10.000", "9.990", "9.980"]}


def _save(sample_id: str, payload: dict) -> httpx.Response:
    return httpx.post(
        f"{BASE_URL}/api/records",
        json={"sample_id": sample_id, **payload},
        timeout=10,
    )


def test_record_roundtrip_qualified_and_out_of_range():
    """合格与越界结果都能保存，并按编号原样查回。"""
    for payload, conclusion in ((QUALIFIED_PAYLOAD, "合格"), (OUT_OF_RANGE_PAYLOAD, "越界")):
        sample_id = unique_id("RT")
        saved = _save(sample_id, payload)
        assert saved.status_code == 201, saved.text
        saved_body = saved.json()
        assert saved_body["sample_id"] == sample_id
        assert saved_body["saved_at"]
        assert saved_body["conclusion"] == conclusion
        assert saved_body["constant"] is True

        got = httpx.get(f"{BASE_URL}/api/records/{sample_id}", timeout=10)
        assert got.status_code == 200
        assert got.json() == saved_body


def test_record_snapshot_matches_live_judge():
    """入库快照与同一输入的实时裁决响应逐字段一致。"""
    judged = httpx.post(f"{BASE_URL}/api/judge", json=QUALIFIED_PAYLOAD, timeout=10)
    assert judged.status_code == 200

    sample_id = unique_id("SNAP")
    saved = _save(sample_id, QUALIFIED_PAYLOAD)
    assert saved.status_code == 201
    saved_body = saved.json()
    assert {
        k: v for k, v in saved_body.items() if k not in ("sample_id", "saved_at")
    } == judged.json()


def test_duplicate_sample_id_does_not_overwrite():
    """重复编号返回冲突，首份快照保持不变。"""
    sample_id = unique_id("DUP")
    first = _save(sample_id, QUALIFIED_PAYLOAD)
    assert first.status_code == 201

    conflict = _save(sample_id, OUT_OF_RANGE_PAYLOAD)
    assert conflict.status_code == 409
    assert sample_id in conflict.json()["detail"]

    got = httpx.get(f"{BASE_URL}/api/records/{sample_id}", timeout=10)
    assert got.status_code == 200
    assert got.json() == first.json()
    assert got.json()["conclusion"] == "合格"


def test_not_constant_cannot_be_saved():
    """尚未恒重的输入不能入库。"""
    sample_id = unique_id("NC")
    resp = _save(sample_id, NOT_CONSTANT_PAYLOAD)
    assert resp.status_code == 422
    assert "尚未恒重" in resp.json()["detail"]

    got = httpx.get(f"{BASE_URL}/api/records/{sample_id}", timeout=10)
    assert got.status_code == 404


def test_missing_record_returns_404():
    sample_id = unique_id("MISS")
    resp = httpx.get(f"{BASE_URL}/api/records/{sample_id}", timeout=10)
    assert resp.status_code == 404
    assert sample_id in resp.json()["detail"]


def test_records_chain_via_web_proxy():
    """经 Nginx 反代也能完成保存→查询全链路（WEB_PORT 入口不变）。"""
    web_url = os.environ.get("WEB_URL", "http://web:80").rstrip("/")
    sample_id = unique_id("WEB")
    saved = httpx.post(
        f"{web_url}/api/records",
        json={"sample_id": sample_id, **QUALIFIED_PAYLOAD},
        timeout=10,
    )
    assert saved.status_code == 201, saved.text

    got = httpx.get(f"{web_url}/api/records/{sample_id}", timeout=10)
    assert got.status_code == 200
    assert got.json() == saved.json()


def test_sample_id_with_slash_roundtrips_direct_and_via_proxy():
    """含斜杠的编号必须在真实 HTTP 链路上原样查回（直连与 Nginx 反代均需通过）。"""
    sample_id = unique_id("SLASH/A/B")
    saved = _save(sample_id, QUALIFIED_PAYLOAD)
    assert saved.status_code == 201, saved.text
    encoded = quote(sample_id, safe="")
    assert "%2F" in encoded

    got = httpx.get(f"{BASE_URL}/api/records/{encoded}", timeout=10)
    assert got.status_code == 200
    assert got.json() == saved.json()
    assert got.json()["sample_id"] == sample_id

    web_url = os.environ.get("WEB_URL", "http://web:80").rstrip("/")
    via_proxy = httpx.get(f"{web_url}/api/records/{encoded}", timeout=10)
    assert via_proxy.status_code == 200
    assert via_proxy.json() == saved.json()
