"""核心判定逻辑测试：首次恒重、终点锁定、回潮率裁决、逐字段校验。"""

from decimal import Decimal

import pytest

from app.judge import adjudicate, judge_payload, validate


def D(text: str) -> Decimal:
    return Decimal(text)


def judge(wet: str, dries: list[str]) -> dict:
    result, errors = judge_payload(wet, dries)
    assert errors is None, f"合法输入不应有错误，实际：{errors}"
    assert result is not None
    return result


# ---------- 首次恒重与终点锁定 ----------

def test_first_round_hit_locks_endpoint():
    # 第 1 轮：0.004 / 10 = 0.0004 <= 0.0005，第 1 次→第 2 次即恒重
    r = judge("11", ["10.000", "9.996", "9.996", "9.996"])
    assert r["constant"] is True
    assert r["hit_round"] == 1
    assert r["endpoint_index"] == 2
    assert r["endpoint_mass"] == "9.996"
    statuses = [x["status"] for x in r["rounds"]]
    assert statuses == ["hit", "ignored", "ignored"]


def test_threshold_boundary_is_hit_inclusive():
    # 恰好 0.0005：10.000 → 9.995（题目要求“小于或等于”）
    r = judge("11", ["10.000", "9.995", "9.995", "9.995"])
    assert r["constant"] is True
    assert r["hit_round"] == 1
    assert r["rounds"][0]["ratio_display"] == "0.000500"


def test_just_above_threshold_is_miss_then_hit_later():
    # 第 1 轮 0.006/10 ≈ 0.00060 > 0.0005（miss）；
    # 第 2 轮 0.005/9.994 ≈ 0.0005003 > 0.0005（miss）；第 3 轮 0.004/9.989≈0.0004（hit）
    r = judge("11", ["10.000", "9.994", "9.989", "9.985"])
    assert r["constant"] is True
    assert r["hit_round"] == 3
    assert r["endpoint_mass"] == "9.985"
    assert [x["status"] for x in r["rounds"]] == ["miss", "miss", "hit"]


def test_never_hit_returns_not_constant():
    # 每轮降幅 0.01/10 = 0.001 > 0.0005，始终未命中
    r = judge("11", ["10.000", "9.990", "9.980", "9.970"])
    assert r["constant"] is False
    assert r["hit_round"] is None
    assert r["endpoint_mass"] is None
    assert all(x["status"] == "miss" for x in r["rounds"])
    assert r["conclusion"] == "尚未恒重"
    assert r["regain"] is None
    assert r["regain_exact"] is None
    assert r["qualified"] is None
    assert r["formula"] is None


def test_equal_readings_hit_with_zero_ratio():
    r = judge("11", ["10.000", "10.000", "10.000"])
    assert r["constant"] is True
    assert r["rounds"][0]["ratio_display"] == "0.000000"
    assert r["endpoint_mass"] == "10.000"


def test_three_readings_minimum_allowed():
    r = judge("11", ["10.000", "9.999", "9.999"])
    assert r["constant"] is True
    assert len(r["rounds"]) == 2


def test_eight_readings_maximum_allowed():
    r = judge("12", ["11.000"] * 8)
    assert r["constant"] is True
    assert r["hit_round"] == 1
    assert len(r["rounds"]) == 7


# ---------- 回潮率与合格区间（未舍入裁决，显示两位小数） ----------

def test_regain_qualified_middle():
    # 恒重 8.000，湿重 8.64 → 8.0% 合格
    r = judge("8.640", ["8.000", "8.000", "8.000"])
    assert r["constant"] is True
    assert r["qualified"] is True
    assert r["conclusion"] == "合格"
    assert r["regain"] == "8.00"
    assert "8.640 − 8.000" in r["formula"]


def test_regain_lower_bound_inclusive_qualified():
    # 0.600/8.000*100 = 7.5 恰好下界 → 合格（闭区间）
    r = judge("8.600", ["8.000", "8.000", "8.000"])
    assert r["qualified"] is True
    assert r["regain"] == "7.50"


def test_regain_upper_bound_inclusive_qualified():
    # 0.680/8.000*100 = 8.5 恰好上界 → 合格（闭区间）
    r = judge("8.680", ["8.000", "8.000", "8.000"])
    assert r["qualified"] is True
    assert r["regain"] == "8.50"


def test_regain_below_lower_bound_out_of_range():
    # 0.599/8.000*100 = 7.4875 → 越界，结论唯一
    r = judge("8.599", ["8.000", "8.000", "8.000"])
    assert r["qualified"] is False
    assert r["conclusion"] == "越界"
    assert r["regain"] == "7.49"


def test_regain_above_upper_bound_out_of_range():
    r = judge("8.681", ["8.000", "8.000", "8.000"])
    assert r["qualified"] is False
    assert r["conclusion"] == "越界"
    assert r["regain"] == "8.51"


def test_unrounded_value_decides_not_display_value():
    # 湿重 7.526、恒重 7.001（均三位小数）：
    # 未舍入 7.4989... < 7.5 越界，四舍五入显示 7.50 —— 必须以未舍入值判越界
    result, _ = judge_payload("7.526", ["7.002", "7.001", "7.001"])
    assert result["endpoint_mass"] == "7.001"
    assert result["qualified"] is False
    assert result["regain"] == "7.50"
    assert result["conclusion"] == "越界"


def test_regain_uses_first_constant_endpoint_not_last_reading():
    # 终点 9.996；后续即使再降（按规则展示但不改变终点）
    r = judge("10.800", ["10.000", "9.996", "9.990", "9.980"])
    assert r["hit_round"] == 1
    assert r["endpoint_mass"] == "9.996"
    # 0.804/9.996*100 ≈ 8.0432
    assert r["qualified"] is True
    assert r["regain"] == "8.04"


# ---------- 逐字段校验 ----------

def test_dry_count_below_minimum_reports_field():
    result, errors = judge_payload("11", ["10.000", "9.999"])
    assert result is None
    assert errors["dry_count"] is not None
    assert "3 至 8" in errors["dry_count"]


def test_dry_count_above_maximum_reports_field():
    result, errors = judge_payload("12", ["11.000"] * 9)
    assert result is None
    assert "3 至 8" in errors["dry_count"]


def test_dry_count_wrong_type():
    result, errors = judge_payload("11", "10.000")
    assert result is None
    assert errors["dry_count"] is not None


@pytest.mark.parametrize(
    "bad",
    ["", "  ", "abc", "0", "-1", "1.2345", None, True, "99,9", "NaN", "Infinity"],
)
def test_invalid_wet_mass_field_errors(bad):
    result, errors = judge_payload(bad, ["10.000", "9.999", "9.999"])
    assert result is None
    assert errors["wet_mass"] is not None


def test_invalid_dry_mass_attached_to_its_index():
    result, errors = judge_payload("11", ["10.000", "0", "9.999"])
    assert result is None
    assert errors["wet_mass"] is None
    assert errors["dry_masses"][0] is None
    assert errors["dry_masses"][1] is not None
    assert errors["dry_masses"][2] is None


def test_four_decimal_dry_mass_rejected():
    result, errors = judge_payload("11", ["10.0000", "9.999", "9.999"])
    assert "三位小数" in errors["dry_masses"][0]


def test_wet_must_exceed_each_dry_reading_attached_per_index():
    result, errors = judge_payload("9.990", ["10.000", "9.990", "9.980"])
    assert result is None
    # 第 1 次更大、第 2 次相等，都挂到对应读数；第 3 次合法
    assert errors["dry_masses"][0] is not None
    assert "更大" in errors["dry_masses"][0]
    assert errors["dry_masses"][1] is not None
    assert "相等" in errors["dry_masses"][1]
    assert errors["dry_masses"][2] is None


def test_rebound_reports_first_round_only():
    # 第 1 轮回升（10.000 → 10.001）；后面还有回升也不再标注
    result, errors = judge_payload("11", ["10.000", "10.001", "9.990", "9.995"])
    assert result is None
    # 回升挂在后次读数（第 2 次，索引 1）
    msg = errors["dry_masses"][1]
    assert msg is not None
    assert "第 1 轮" in msg
    assert "首个回升轮次" in msg
    assert errors["dry_masses"][3] is None


def test_multiple_independent_errors_reported_together():
    # 湿重非法 + 第 2 次读数非法 + 次数不足，三类字段同时返回
    result, errors = judge_payload("0", ["10.000", "abc"])
    assert result is None
    assert errors["wet_mass"] is not None
    assert errors["dry_count"] is not None
    assert errors["dry_masses"][1] is not None


def test_validate_helper_returns_decimals_on_success():
    wet, dries, errors = validate("11.000", ["10.000", "9.999", "9.999"])
    assert wet == D("11.000")
    assert dries == [D("10.000"), D("9.999"), D("9.999")]
    assert errors.wet_mass is None
    assert all(e is None for e in errors.dry_masses)


def test_adjacent_loss_never_negative_under_validation():
    # 直接裁决合法（单调不增）数据时，相邻“前次减后次”非负
    r = adjudicate(D("11"), [D("10"), D("9.99"), D("9.985")])
    for row in r["rounds"]:
        assert Decimal(row["loss"]) >= 0
