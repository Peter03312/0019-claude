"""集成验收测试：对已部署服务打真实 HTTP 请求。

BASE_URL 可覆盖；docker compose verify 默认指向 http://api:8000，
经 Nginx 的链路则用 http://web:80。
"""

import os

import httpx
import pytest

BASE_URL = os.environ.get("BASE_URL", "http://api:8000").rstrip("/")

pytestmark = pytest.mark.integration


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
