# 棉纤维烘干恒重与回潮率裁决

Vue 3 + Vite 前端、FastAPI 后端的全栈应用：录入烘前湿样质量与 3–8 次按先后顺序取得的烘后质量，API 负责寻找**首次恒重**并裁决回潮率是否合格。

## 业务规则

- 所有质量单位为克，允许至多三位小数且必须 **大于零**。
- 烘前湿样质量必须 **大于每一次** 烘后质量。
- 烘后质量序列必须单调不增（**不得回升**）；若回升，错误只指出**首个回升轮次**。
- 恒重判定（从第一对相邻读数起按先后顺序）：

  ```
  比值 = (前次质量 − 后次质量) ÷ 前次质量
  首次满足 比值 ≤ 0.0005 时，以后次质量作为恒重终点；
  其后的读数仍然展示，但不再改变终点。
  始终未命中则结果为“尚未恒重”。
  ```

- 回潮率：

  ```
  回潮率 = (湿样质量 − 恒重质量) ÷ 恒重质量 × 100
  ```

  以**未舍入值**判断合格闭区间 **[7.5%, 8.5%]**，页面显示两位小数（四舍五入）。
  因此会出现“显示 7.50% 但未舍入值低于 7.5% → 仍判越界”的情况，这是刻意行为。
- 尚未恒重时不计算、**不显示回潮率**。
- 修改任一读数（或增减读数行）立即清除旧裁决，需重新点击“开始裁决”。

全部质量计算使用 Python `Decimal`，阈值比较用去分母的整数等价式
`损失量 × 10000 ≤ 5 × 前次质量`，杜绝二进制浮点误差。

## 目录结构

```
.
├── backend/              FastAPI 后端
│   ├── app/
│   │   ├── judge.py      # 核心判定：校验、首次恒重、回潮率裁决
│   │   └── main.py       # API 路由（/api/health、POST /api/judge）
│   ├── tests/
│   │   ├── test_core.py       # 核心判定单元测试
│   │   ├── test_api.py        # FastAPI 接口测试（TestClient）
│   │   └── test_integration.py# 对存活服务的一次性集成验收
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/             Vue 3 + Vite 前端
│   ├── src/
│   │   ├── App.vue       # 录入、逐字段错误、恒重对/算式/结论展示
│   │   ├── main.js
│   │   └── style.css
│   ├── Dockerfile        # 多阶段构建 → Nginx 静态宿主 + /api 反代
│   ├── nginx.conf
│   └── vite.config.js
├── docker-compose.yml    # api / web / verify 三个服务
└── verify                # 一次性验收入口脚本
```

## API

### `POST /api/judge`

请求：

```json
{ "wet_mass": "8.640", "dry_masses": ["8.000", "8.000", "8.000"] }
```

质量以字符串提交以保留三位小数形态；整数也可接受。成功返回 `200`：

```json
{
  "wet_mass": "8.640",
  "dry_masses": ["8.000", "8.000", "8.000"],
  "constant": true,
  "hit_round": 1,
  "endpoint_index": 2,
  "endpoint_mass": "8.000",
  "rounds": [
    {
      "round": 1, "prev_index": 1, "curr_index": 2,
      "prev_mass": "8.000", "curr_mass": "8.000",
      "loss": "0.000", "ratio": "0", "ratio_display": "0.000000",
      "threshold": "0.0005", "status": "hit"
    }
  ],
  "regain": "8.00",
  "regain_exact": "8",
  "qualified": true,
  "conclusion": "合格",
  "formula": "(8.640 − 8.000) ÷ 8.000 × 100 = 8.000000%（未舍入裁决，页面显示 8.00%）"
}
```

- `rounds[].status`：`hit`（首次恒重对）、`miss`（本轮未达阈值）、`ignored`（终点之后仅展示、不改变终点）。
- 尚未恒重时 `constant=false`、`conclusion="尚未恒重"`，`regain / regain_exact / qualified / formula` 均为 `null`。

校验失败返回 `422` 与**逐字段**错误（`dry_masses` 与读数逐位对应；回升错误挂在后次读数上并写明首个轮次）：

```json
{
  "detail": "输入校验未通过，请按字段修正后重新裁决",
  "errors": {
    "wet_mass": "质量必须大于零",
    "dry_count": null,
    "dry_masses": [
      null,
      "烘后序列不得回升：第 1 轮 5 g → 第 2 次 5.001 g，后者更大（首个回升轮次）",
      null
    ]
  }
}
```

`GET /api/health` 返回 `{"status":"ok"}`。

## 用 Docker Compose 发布

宿主端口必须由 `WEB_PORT` 覆盖（默认 8080）：

```bash
WEB_PORT=9090 docker compose up -d --build web
# 浏览器访问 http://localhost:9090
```

- `web`：Nginx 提供前端静态资源，并把 `/api/` 反代到 `api` 服务。
- `api`：uvicorn 承载 FastAPI（不对宿主机暴露端口）。
- 两个服务都带 healthcheck，`web` 等 `api` 健康后才启动。

## 一次性验收 verify

仓库根目录提供 `verify` 一次性验收服务：构建镜像、拉起 `api` 与 `web`（健康通过后），
在容器网络内对**真实服务**跑 `tests/test_integration.py`（含首页可访问性与 Nginx `/api` 反代），
测试结束容器即退出：

```bash
./verify                 # 等价于 WEB_PORT=8080
WEB_PORT=9090 ./verify
./verify --build         # 透传参数给 docker compose run
```

## 本地开发

后端：

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
python -m pytest tests/test_core.py tests/test_api.py   # 核心+接口测试
```

前端：

```bash
cd frontend
npm install
npm run dev          # 5173 端口，/api 已在 vite.config.js 代理到 :8000
npm run build
```
