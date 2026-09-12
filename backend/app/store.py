"""试样记录存储：已恒重裁决的不可变快照，SQLite 持久化。

- 质量（湿重、烘后序列）与未舍入回潮率一律按十进制定点字符串（TEXT）保存；
- 完整裁决响应作为快照 JSON 一并写入，写入后不再修改（无 UPDATE 路径）；
- 试样编号为主键，重复写入直接拒绝，首份快照保持不变。

数据库路径由环境变量 RECORDS_DB_PATH 覆盖，默认当前目录 records.db；
每次调用现读环境变量，便于测试用临时文件隔离。
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sample_records (
    sample_id    TEXT PRIMARY KEY,
    wet_mass     TEXT NOT NULL,
    dry_masses   TEXT NOT NULL,
    regain_exact TEXT,
    snapshot     TEXT NOT NULL,
    saved_at     TEXT NOT NULL
)
"""


class DuplicateSampleId(Exception):
    """试样编号已存在：首份快照保持不变，本次写入被拒绝。"""


def _db_path() -> str:
    return os.environ.get("RECORDS_DB_PATH", "records.db")


def _connect() -> sqlite3.Connection:
    path = _db_path()
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10)
    conn.executescript(_SCHEMA)
    return conn


def save_snapshot(sample_id: str, snapshot: dict) -> dict:
    """把裁决快照写入记录，返回附带了编号与保存时间的同一响应结构。

    snapshot 必须是服务端刚按裁决规则重算出的结果（本函数不再校验业务规则，
    只负责持久化）；编号冲突抛 DuplicateSampleId，已存记录不被改写。
    """
    saved_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    record = {**snapshot, "sample_id": sample_id, "saved_at": saved_at}
    conn = _connect()
    try:
        with conn:
            conn.execute(
                "INSERT INTO sample_records"
                " (sample_id, wet_mass, dry_masses, regain_exact, snapshot, saved_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (
                    sample_id,
                    snapshot["wet_mass"],
                    json.dumps(snapshot["dry_masses"], ensure_ascii=False),
                    snapshot["regain_exact"],
                    json.dumps(snapshot, ensure_ascii=False),
                    saved_at,
                ),
            )
    except sqlite3.IntegrityError:
        raise DuplicateSampleId(sample_id) from None
    finally:
        conn.close()
    return record


def load_snapshot(sample_id: str) -> dict | None:
    """按编号取回快照（与保存时同一响应结构），不存在返回 None。"""
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT snapshot, saved_at FROM sample_records WHERE sample_id = ?",
            (sample_id,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    snapshot = json.loads(row[0])
    return {**snapshot, "sample_id": sample_id, "saved_at": row[1]}
