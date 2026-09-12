"""棉纤维烘后质量恒重裁决核心逻辑。

全部计算使用 Decimal，避免二进制浮点误差；
恒重阈值与回潮率区间均以未舍入值比较。
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

# 恒重阈值：(前次 - 后次) / 前次 <= 0.0005
THRESHOLD = Decimal("0.0005")
# 阈值比较时去分母用的整数等价式：loss * 10000 <= 5 * prev
THRESHOLD_DEN = Decimal(10000)
THRESHOLD_NUM = Decimal(5)

# 回潮率合格闭区间（未舍入值）7.5% ~ 8.5%
REGAIN_LOW = Decimal("7.5")
REGAIN_HIGH = Decimal("8.5")

RATIO_QUANT = Decimal("0.000001")  # 相邻比值展示：六位小数
REGAIN_QUANT = Decimal("0.01")     # 回潮率展示：两位小数

MIN_READINGS = 3
MAX_READINGS = 8


@dataclass
class FieldErrors:
    """逐字段错误，dry_masses 与读数列表等长、逐位对应。"""

    wet_mass: str | None = None
    dry_count: str | None = None
    dry_masses: list[str | None] | None = None

    def as_dict(self) -> dict:
        return {
            "wet_mass": self.wet_mass,
            "dry_count": self.dry_count,
            "dry_masses": self.dry_masses or [],
        }


def _to_decimal(raw: object) -> Decimal | None:
    """把 JSON 来的值解析为有限 Decimal；无法识别返回 None。

    接受字符串与整数（前端按字符串提交以保留三位小数形态），
    拒绝布尔值、NaN/Infinity 及其他非数字类型。
    """
    if isinstance(raw, bool):
        return None
    if isinstance(raw, Decimal):
        value = raw
    elif isinstance(raw, int):
        value = Decimal(raw)
    elif isinstance(raw, float):
        value = Decimal(str(raw))
    elif isinstance(raw, str):
        text = raw.strip()
        if not text:
            return None
        try:
            value = Decimal(text)
        except InvalidOperation:
            return None
    else:
        return None
    if not value.is_finite():
        return None
    return value


def _check_mass(raw: object) -> tuple[Decimal | None, str | None]:
    """单个质量字段的独立校验：必填数字、大于零、至多三位小数。"""
    value = _to_decimal(raw)
    if value is None:
        return None, "必须填写数字"
    if value <= 0:
        return None, "质量必须大于零"
    if value.as_tuple().exponent < -3:
        return None, "最多允许三位小数"
    return value, None


def validate(
    wet_raw: object, dry_raw: object
) -> tuple[Decimal | None, list[Decimal], FieldErrors]:
    """校验入参，返回 (湿重, 烘后序列, 逐字段错误)。

    跨字段规则：
    - 湿样质量必须大于每次烘后质量（违规挂到该次读数上）；
    - 烘后序列不得回升，只指出首个回升轮次。
    """
    errors = FieldErrors()

    wet_mass, wet_err = _check_mass(wet_raw)
    errors.wet_mass = wet_err

    if not isinstance(dry_raw, list):
        errors.dry_masses = []
        errors.dry_count = "烘后质量必须是 3 至 8 次读数组成的数组"
        return None, [], errors

    n = len(dry_raw)
    dry_errors: list[str | None] = []
    dries: list[Decimal | None] = []
    for item in dry_raw:
        mass, err = _check_mass(item)
        dries.append(mass)
        dry_errors.append(err)

    if n < MIN_READINGS or n > MAX_READINGS:
        errors.dry_count = f"烘后质量需要 {MIN_READINGS} 至 {MAX_READINGS} 次读数，当前为 {n} 次"

    # 湿重必须大于每一次烘后质量
    if wet_mass is not None:
        for idx, mass in enumerate(dries):
            if mass is not None and mass >= wet_mass:
                suffix = "相等" if mass == wet_mass else "更大"
                dry_errors[idx] = (
                    f"烘后质量必须小于烘前湿样质量（{wet_mass} g），"
                    f"第 {idx + 1} 次读数{suffix}"
                )

    # 序列不得回升：只标记首个回升轮次（第 i 轮 = 第 i 次→第 i+1 次，i 从 1 起）
    for idx in range(1, n):
        prev_mass, curr_mass = dries[idx - 1], dries[idx]
        if prev_mass is not None and curr_mass is not None and curr_mass > prev_mass:
            if dry_errors[idx] is None:
                dry_errors[idx] = (
                    f"烘后序列不得回升：第 {idx} 轮 {prev_mass} g → "
                    f"第 {idx + 1} 次 {curr_mass} g，后者更大（首个回升轮次）"
                )
            break

    errors.dry_masses = dry_errors
    valid_dries = [m for m in dries if m is not None]
    if wet_mass is None or any(err is not None for err in dry_errors) or errors.dry_count:
        return None, [], errors
    return wet_mass, valid_dries, errors  # type: ignore[return-value]


def adjudicate(wet_mass: Decimal, dries: list[Decimal]) -> dict:
    """对合法输入裁决恒重与回潮率。

    从第一对相邻读数起按先后顺序计算比值，首次 <= 0.0005 即恒重，
    以后次质量为终点；之后的读数仍返回但不改变终点。
    """
    rounds: list[dict] = []
    endpoint: Decimal | None = None
    hit_round: int | None = None
    endpoint_index: int | None = None

    for i in range(1, len(dries)):
        prev_mass, curr_mass = dries[i - 1], dries[i]
        loss = prev_mass - curr_mass  # 已保证非负
        ratio = loss / prev_mass
        considered = endpoint is None
        # loss/prev <= 0.0005 等价于 loss*10000 <= 5*prev，全程精确比较
        hit = considered and (
            loss * THRESHOLD_DEN <= THRESHOLD_NUM * prev_mass
        )
        if hit:
            endpoint = curr_mass
            hit_round = i  # 第 i 轮：第 i 次读数 → 第 i+1 次读数
            endpoint_index = i + 1

        if hit:
            status = "hit"
        elif considered:
            status = "miss"
        else:
            status = "ignored"

        rounds.append(
            {
                "round": i,
                "prev_index": i,
                "curr_index": i + 1,
                "prev_mass": str(prev_mass),
                "curr_mass": str(curr_mass),
                "loss": str(loss),
                "ratio": str(ratio),
                "ratio_display": str(ratio.quantize(RATIO_QUANT, rounding=ROUND_HALF_UP)),
                "threshold": str(THRESHOLD),
                "status": status,  # hit=首次恒重 / miss=未达 / ignored=终点之后仅展示
            }
        )

    result: dict = {
        "wet_mass": str(wet_mass),
        "dry_masses": [str(d) for d in dries],
        "constant": endpoint is not None,
        "hit_round": hit_round,
        "endpoint_index": endpoint_index,
        "endpoint_mass": str(endpoint) if endpoint is not None else None,
        "rounds": rounds,
    }

    if endpoint is None:
        result.update(
            {
                "regain": None,
                "regain_exact": None,
                "qualified": None,
                "conclusion": "尚未恒重",
                "formula": None,
            }
        )
        return result

    # 回潮率 = (湿重 - 恒重) / 恒重 * 100，按未舍入值裁决区间
    regain = (wet_mass - endpoint) / endpoint * Decimal(100)
    qualified = REGAIN_LOW <= regain <= REGAIN_HIGH
    regain_display = regain.quantize(REGAIN_QUANT, rounding=ROUND_HALF_UP)
    formula = (
        f"({wet_mass} − {endpoint}) ÷ {endpoint} × 100 "
        f"= {regain.quantize(RATIO_QUANT, rounding=ROUND_HALF_UP)}%"
        f"（未舍入裁决，页面显示 {regain_display}%）"
    )
    result.update(
        {
            "regain": str(regain_display),
            "regain_exact": str(regain),
            "qualified": qualified,
            "conclusion": "合格" if qualified else "越界",
            "formula": formula,
        }
    )
    return result


def judge_payload(
    wet_raw: object, dry_raw: object
) -> tuple[dict | None, dict | None]:
    """API 入口：成功返回 (裁决结果, None)，失败返回 (None, 逐字段错误)。"""
    wet_mass, dries, errors = validate(wet_raw, dry_raw)
    if errors.wet_mass or errors.dry_count or any(errors.dry_masses or []):
        return None, errors.as_dict()
    return adjudicate(wet_mass, dries), None
