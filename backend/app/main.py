"""FastAPI 应用：棉纤维烘干恒重与回潮率裁决。"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .judge import judge_payload
from .store import DuplicateSampleId, load_snapshot, save_snapshot

# 试样编号：去空白后 1–64 个字符
MAX_SAMPLE_ID_LEN = 64

app = FastAPI(
    title="棉纤维回潮率恒重裁决 API",
    description="录入烘前湿样质量与 3-8 次烘后质量，寻找首次恒重并裁决回潮率。",
    version="1.0.0",
)

# 开发期允许 Vite dev server 直连；生产由同源 Nginx 反代
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/api/judge")
async def judge(request: Request) -> JSONResponse:
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse(
            status_code=422,
            content={
                "detail": "请求体必须是 JSON 对象，字段 wet_mass 与 dry_masses 不得缺失",
                "errors": {
                    "wet_mass": "必须填写数字",
                    "dry_count": None,
                    "dry_masses": [],
                },
            },
        )

    if not isinstance(payload, dict):
        return JSONResponse(
            status_code=422,
            content={
                "detail": "请求体必须是 JSON 对象",
                "errors": {
                    "wet_mass": "必须填写数字",
                    "dry_count": None,
                    "dry_masses": [],
                },
            },
        )

    result, errors = judge_payload(
        payload.get("wet_mass"), payload.get("dry_masses")
    )
    if errors is not None:
        return JSONResponse(
            status_code=422,
            content={
                "detail": "输入校验未通过，请按字段修正后重新裁决",
                "errors": errors,
            },
        )
    return JSONResponse(status_code=200, content=result)


def _clean_sample_id(raw: object) -> str | None:
    """试样编号：去首尾空白后 1–64 个字符，否则返回 None。"""
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if not text or len(text) > MAX_SAMPLE_ID_LEN:
        return None
    return text


def _sample_id_error() -> str:
    return f"必须填写 1–{MAX_SAMPLE_ID_LEN} 个字符的试样编号"


@app.post("/api/records", status_code=201)
async def save_record(request: Request) -> JSONResponse:
    """把一次已恒重的裁决固化为试样记录。

    服务端按与 /api/judge 完全相同的规则对 wet_mass/dry_masses 重新裁决，
    只有恒重的结果才允许入库；响应即入库快照（裁决结构 + 编号 + 保存时间）。
    """
    try:
        payload = await request.json()
    except Exception:
        payload = None
    if not isinstance(payload, dict):
        return JSONResponse(
            status_code=422,
            content={
                "detail": "请求体必须是 JSON 对象，字段 sample_id、wet_mass 与 dry_masses 不得缺失",
                "errors": {
                    "sample_id": _sample_id_error(),
                    "wet_mass": "必须填写数字",
                    "dry_count": None,
                    "dry_masses": [],
                },
            },
        )

    sample_id = _clean_sample_id(payload.get("sample_id"))
    result, errors = judge_payload(
        payload.get("wet_mass"), payload.get("dry_masses")
    )
    sample_id_err = None if sample_id is not None else _sample_id_error()
    if errors is not None:
        errors["sample_id"] = sample_id_err
        return JSONResponse(
            status_code=422,
            content={
                "detail": "输入校验未通过，请按字段修正后重新保存",
                "errors": errors,
            },
        )
    if sample_id_err is not None:
        return JSONResponse(
            status_code=422,
            content={
                "detail": "输入校验未通过，请按字段修正后重新保存",
                "errors": {
                    "sample_id": sample_id_err,
                    "wet_mass": None,
                    "dry_count": None,
                    "dry_masses": [],
                },
            },
        )
    if not result["constant"]:
        return JSONResponse(
            status_code=422,
            content={
                "detail": "裁决尚未恒重，不能保存为试样记录",
                "errors": None,
            },
        )

    try:
        record = save_snapshot(sample_id, result)
    except DuplicateSampleId:
        return JSONResponse(
            status_code=409,
            content={
                "detail": f"试样编号「{sample_id}」已存在，首份快照保持不变，请更换编号后重试",
            },
        )
    return JSONResponse(status_code=201, content=record)


@app.get("/api/records/{sample_id:path}")
def get_record(sample_id: str) -> JSONResponse:
    """按编号查询试样记录，返回与保存时同一响应结构（只读）。

    使用 :path 转换器：合法编号允许包含 “/”（保存时按 1–64 任意字符校验），
    前端对编号做百分号编码后，解码出的 “/” 也必须能命中本路由。
    """
    cleaned = sample_id.strip()
    record = load_snapshot(cleaned)
    if record is None:
        return JSONResponse(
            status_code=404,
            content={"detail": f"未找到试样编号「{cleaned}」的记录"},
        )
    return JSONResponse(status_code=200, content=record)
