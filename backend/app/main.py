"""FastAPI 应用：棉纤维烘干恒重与回潮率裁决。"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .judge import judge_payload

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
