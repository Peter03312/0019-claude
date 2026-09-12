# 棉纤维烘干恒重与回潮率裁决

Vue 3 + Vite 前端、FastAPI 后端的全栈应用：录入烘前湿样质量与 3–8 次按先后顺序取得的烘后质量，API 负责寻找**首次恒重**并裁决回潮率是否合格。已恒重的裁决可填写试样编号**保存为试样记录**（SQLite 不可变快照），之后按编号只读查询。

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
- 尚未恒重时不计算、**不显示回潮率**，且页面禁用“保存为试样记录”。
- 修改任一读数（或增减读数行）立即清除旧裁决，需重新点击“开始裁决”。

## 试样记录

- 裁决完成且**已恒重**后，可填写试样编号（去空白后 1–64 字符）保存；保存时服务端按
  与 `/api/judge` 完全相同的规则**重新裁决**，只有恒重结果才入库——客户端无法伪造快照。
- 记录以 SQLite 保存：质量与未舍入回潮率按**十进制定点字符串**落库，完整裁决响应作为
  **不可变快照**一并写入（无更新路径）；重复编号返回 `409` 冲突，首份快照保持不变。
- 页面“试样记录查询”区按编号查询，回显原始湿重、完整烘后序列、首次恒重对、回潮率算式
  与结论；查询结果**只读**，不覆盖当前录入内容；编号不存在时在查询区提示未找到，表单保持原样。
- 数据库路径由 `RECORDS_DB_PATH` 覆盖（默认 `./records.db`）；Compose 中固定为
  `/data/records.db` 并挂载命名卷 `api-data`，容器重建后记录仍在。

全部质量计算使用 Python `Decimal`，阈值比较用去分母的整数等价式
`损失量 × 10000 ≤ 5 × 前次质量`，杜绝二进制浮点误差。

## 目录结构

```
.
├── backend/              FastAPI 后端
│   ├── app/
│   │   ├── judge.py      # 核心判定：校验、首次恒重、回潮率裁决
│   │   ├── store.py      # 试样记录：SQLite 不可变快照存取
│   │   └── main.py       # API 路由（health / judge / records）
│   ├── tests/
│   │   ├── test_core.py       # 核心判定单元测试
│   │   ├── test_api.py        # FastAPI 接口测试（TestClient，含记录保存/查询）
│   │   └── test_integration.py# 对存活服务的一次性集成验收
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/             Vue 3 + Vite 前端
│   ├── src/
│   │   ├── App.vue       # 录入、逐字段错误、记录保存与查询
│   │   ├── components/
│   │   │   └── ResultView.vue # 裁决/记录共用的只读结果展示
│   │   ├── main.js
│   │   └── style.css
│   ├── Dockerfile        # 多阶段构建 → Nginx 静态宿主 + /api 反代
│   ├── nginx.conf
│   └── vite.config.js
├── docker-compose.yml    # api / web / verify 三个服务 + api-data 数据卷
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

### `POST /api/records`

把一次已恒重的裁决固化为试样记录。请求在裁决入参基础上多一个 `sample_id`：

```json
{ "sample_id": "CF-2026-0001", "wet_mass": "8.640", "dry_masses": ["8.000", "8.000", "8.000"] }
```

服务端按与 `POST /api/judge` 相同的规则**重新裁决**，仅恒重结果入库。成功返回 `201`，
响应为裁决结构附加 `sample_id` 与 `saved_at`（UTC，ISO 8601）：

```json
{
  "wet_mass": "8.640",
  "dry_masses": ["8.000", "8.000", "8.000"],
  "constant": true,
  "hit_round": 1,
  "endpoint_index": 2,
  "endpoint_mass": "8.000",
  "rounds": [ "…同 /api/judge…" ],
  "regain": "8.00",
  "regain_exact": "8",
  "qualified": true,
  "conclusion": "合格",
  "formula": "(8.640 − 8.000) ÷ 8.000 × 100 = 8.000000%（未舍入裁决，页面显示 8.00%）",
  "sample_id": "CF-2026-0001",
  "saved_at": "2026-09-12T22:42:09+00:00"
}
```

- `409`：试样编号已存在，首份快照保持不变（`detail` 说明冲突）。
- `422`：质量/编号校验失败（逐字段 `errors`，含 `sample_id` 键），或裁决**尚未恒重**
  （`detail` 为“裁决尚未恒重，不能保存为试样记录”），均不入库。

### `GET /api/records/{sample_id}`

按编号查询试样记录。命中返回 `200`，响应结构与保存时完全相同（裁决结构 + `sample_id`
+ `saved_at`），只读；不存在返回 `404` 与 `{"detail": "未找到试样编号「…」的记录"}`。

## 用 Docker Compose 发布

宿主端口必须由 `WEB_PORT` 覆盖（默认 8080）：

```bash
WEB_PORT=9090 docker compose up -d --build web
# 浏览器访问 http://localhost:9090
```

- `web`：Nginx 提供前端静态资源，并把 `/api/` 反代到 `api` 服务。
- `api`：uvicorn 承载 FastAPI（不对宿主机暴露端口），试样记录 SQLite 落在命名卷
  `api-data`（容器内 `/data/records.db`），容器重建后记录仍在。
- 两个服务都带 healthcheck，`web` 等 `api` 健康后才启动。

## 一次性验收 verify

仓库根目录提供 `verify` 一次性验收服务：构建镜像、拉起 `api` 与 `web`（健康通过后），
在容器网络内对**真实服务**跑 `tests/test_integration.py`（含首页可访问性、Nginx `/api`
反代，以及试样记录“保存→原样查回、重复编号不改写、未恒重不入库”全链路），
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
