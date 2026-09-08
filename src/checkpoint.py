"""
checkpoint.py — 会话参数快照与回退模块（S5）。

独立于 session_state.py，职责单一：管理 checkpoint 的保存/列表/回退/清理。
线程安全：所有写操作加 _CP_LOCK。

生命周期：内存存储，与会话 TTL（4h）对齐。服务重启后丢失（设计如此）。
若未来需要跨重启保留，可序列化到 PG 的 task_checkpoints 表。
"""

import threading
import time
from typing import Optional


_CP_LOCK = threading.Lock()
_CHECKPOINTS: dict[str, list[dict]] = {}  # thread_id → list of {id, label, params, timestamp}


def save_checkpoint(thread_id: str, params: dict, label: str = "") -> dict:
    """保存当前参数快照。返回快照信息（含 id）。

    Args:
        thread_id: 会话线程 ID
        params: 当前会话参数字典（会被 deepcopy，不引用原对象）
        label: 可选标签（如"高成本率假设"）

    Returns:
        {"id": "cp_1", "label": "...", "timestamp": 1234567890, "param_count": 15}
    """
    import copy
    with _CP_LOCK:
        cps = _CHECKPOINTS.setdefault(thread_id, [])
        cp_id = f"cp_{len(cps) + 1}"
        snapshot = {
            "id": cp_id,
            "label": label or f"快照 #{len(cps) + 1}",
            "params": copy.deepcopy(params),
            "timestamp": time.time(),
        }
        cps.append(snapshot)
        return {
            "id": cp_id,
            "label": snapshot["label"],
            "timestamp": snapshot["timestamp"],
            "param_count": len(params),
        }


def list_checkpoints(thread_id: str) -> list[dict]:
    """列出当前会话的所有快照。

    Returns:
        [{"id": "cp_1", "label": "...", "timestamp": 1234567890, "param_count": 15}, ...]
    """
    with _CP_LOCK:
        cps = _CHECKPOINTS.get(thread_id, [])
        return [
            {
                "id": cp["id"],
                "label": cp["label"],
                "timestamp": cp["timestamp"],
                "param_count": len(cp["params"]),
            }
            for cp in cps
        ]


def rollback_to(thread_id: str, checkpoint_id: str) -> Optional[dict]:
    """回退到指定快照。返回快照中的参数字典（deepcopy），或 None（快照不存在）。

    Args:
        thread_id: 会话线程 ID
        checkpoint_id: 快照 ID（如 "cp_2"）

    Returns:
        参数字典的 deepcopy，或 None
    """
    import copy
    with _CP_LOCK:
        cps = _CHECKPOINTS.get(thread_id, [])
        for cp in cps:
            if cp["id"] == checkpoint_id:
                return copy.deepcopy(cp["params"])
    return None


def clear_checkpoints(thread_id: str) -> int:
    """清除指定会话的所有快照。返回清除数量。

    用于会话过期清理。
    """
    with _CP_LOCK:
        cps = _CHECKPOINTS.pop(thread_id, [])
        return len(cps)


def get_checkpoint_count(thread_id: str) -> int:
    """返回指定会话的快照数量。"""
    with _CP_LOCK:
        return len(_CHECKPOINTS.get(thread_id, []))
