"""API 层测试：真实 FastAPI TestClient，不使用任何假接口。"""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


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
