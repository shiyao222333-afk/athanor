"""
Citrinitas Watch Folder — 全局状态管理 + 状态文件操作。

watcher 包最底层模块。无 watcher 内部依赖（仅依赖 utils/config 外部模块）。
所有 watcher 子模块通过 `from watcher.state import ...` 共享全局状态。
"""

import os
import json
import time
import threading
from datetime import datetime, timezone

from config.settings import (
    PROJECT_DIR,
    WATCH_V2_TEMP_PATTERNS,
    WATCH_V2_DLQ_TTL_DAYS,
    WATCH_V2_NOTIFY_ON_FATAL,
)
from watcher.utils import (
    INBOX_DIR, STATE_FILE, LOCK_FILE,
    _is_temp_file, _ensure_dir,
)
from utils.activity_log import log_activity

# ═══════════════════════════════════════════
# 全局状态
# ═══════════════════════════════════════════

_observer = None              # watchdog.observers.Observer | None
_worker_thread = None         # threading.Thread | None
_queue = None                 # queue.Queue | None
_stop_event = None            # threading.Event | None
_heartbeat_time: float = 0.0
_heartbeat_lock = threading.Lock()
_state_lock = threading.Lock()
_stats_lock = threading.Lock()
_pending_removals: set = set()
_watch_stats: dict = {
    "processed": 0,
    "failed": 0,
    "skipped": 0,
    "deleted": 0,
    "pending": 0,
    "needs_review": 0,
    "running": False,
    "infra_ok": True,
}
_queued_files: set = set()
_in_flight: set = set()

# ── 活跃 Y2 子进程登记表（#302 防孤儿）──────────────────────────────
# spawn 出来的处理子进程登记于此；stop_watcher / 主进程关机时遍历真杀，
# 避免子进程变孤儿继续霸占 Ollama / Qdrant，重启后与新 watcher 双开抢同一文件。
_active_children: set = set()       # 存 multiprocessing.Process 对象
_children_lock = threading.Lock()


def _register_child(proc):
    """登记一个正在运行的 Y2 处理子进程（由父进程的 _process_file_with_timeout 调用）。"""
    with _children_lock:
        _active_children.add(proc)


def _unregister_child(proc):
    """子进程结束（正常退出或被强杀）后从登记表移除。"""
    with _children_lock:
        _active_children.discard(proc)


def _kill_all_children():
    """关停兜底：真杀所有仍存活的 Y2 子进程，避免遗留孤儿。

    先 terminate(SIGTERM) 给子进程一次自行清理的机会，超时未退则 kill(SIGKILL) 强杀。
    Windows 上 terminate/kill 均为 TerminateProcess 级强杀，足以断开其 Ollama/Qdrant 连接。
    """
    with _children_lock:
        procs = list(_active_children)
    for proc in procs:
        try:
            if proc.is_alive():
                proc.terminate()
        except Exception:
            pass
    if procs:
        time.sleep(0.3)
    for proc in procs:
        try:
            if proc.is_alive():
                proc.kill()
        except Exception:
            pass
    with _children_lock:
        _active_children.clear()


# ═══════════════════════════════════════════
# 状态文件操作（file_state.jsonl）
# ═══════════════════════════════════════════

def _load_state() -> dict:
    """加载 file_state.jsonl，返回 {filename: latest_entry} 映射。自动过滤 _pending_removals。"""
    state = {}
    if not os.path.isfile(STATE_FILE):
        return state
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    fname = entry.get("file", "")
                    if fname:
                        state[fname] = entry
                except json.JSONDecodeError:
                    pass
    except OSError as e:
        log_activity(
            action="watch_state_load_failed",
            detail=f"读取状态文件失败: {e}",
        )
        return state
    with _state_lock:
        removals_snapshot = _pending_removals.copy()
    for fname in removals_snapshot:
        state.pop(fname, None)
    return state


def _append_state(entry: dict):
    """追加一行到 file_state.jsonl。不修改入参 dict。"""
    try:
        with _state_lock:
            state_dir = os.path.dirname(STATE_FILE)
            os.makedirs(state_dir, exist_ok=True)
            entry_copy = dict(entry)
            entry_copy["ts"] = datetime.now(timezone.utc).isoformat()
            with open(STATE_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry_copy, ensure_ascii=False) + "\n")
    except (OSError, ValueError) as e:
        log_activity(
            action="watch_state_write_failed",
            detail=f"无法写入状态文件: {e}",
        )


def _remove_state(filename: str):
    """标记文件状态为待删除（延迟批量重写，避免每文件全量 I/O）。"""
    with _state_lock:
        _pending_removals.add(filename)


def _get_file_state(filename: str) -> dict | None:
    """获取某个文件的最新状态。"""
    state = _load_state()
    return state.get(filename)


def get_all_states() -> dict:
    """获取所有文件状态（供 UI 使用）。"""
    return _load_state()


def get_inbox_stats() -> dict:
    """获取收件箱统计信息。"""
    state = _load_state()
    stats = {
        "total": 0,
        "failed": 0,
        "needs_review": 0,
        "retry": 0,
        "pending": 0,
    }
    if os.path.isdir(INBOX_DIR):
        for filename in os.listdir(INBOX_DIR):
            filepath = os.path.join(INBOX_DIR, filename)
            if not os.path.isfile(filepath):
                continue
            if _is_temp_file(filename):
                continue
            stats["total"] += 1
            entry = state.get(filename)
            if entry:
                s = entry.get("state", "")
                if s == "failed":
                    stats["failed"] += 1
                elif s == "needs_review":
                    stats["needs_review"] += 1
                elif s == "retry":
                    stats["retry"] += 1
            else:
                stats["pending"] += 1
    return stats


# ═══════════════════════════════════════════
# 锁文件操作
# ═══════════════════════════════════════════

def _check_lock_file() -> bool:
    """检查是否已有 watcher 实例在运行。"""
    if not os.path.isfile(LOCK_FILE):
        return True
    try:
        with open(LOCK_FILE, "r", encoding="utf-8") as f:
            pid = int(f.read().strip())
    except (ValueError, OSError):
        try:
            os.remove(LOCK_FILE)
        except OSError:
            pass
        return True
    try:
        os.kill(pid, 0)
        return False
    except OSError:
        pass
    try:
        os.remove(LOCK_FILE)
    except OSError:
        pass
    return True


def _write_lock_file():
    try:
        with open(LOCK_FILE, "w", encoding="utf-8") as f:
            f.write(str(os.getpid()))
    except OSError:
        log_activity(
            action="watch_lock_failed",
            detail="无法写入锁文件",
        )


def _remove_lock_file():
    try:
        if os.path.isfile(LOCK_FILE):
            os.remove(LOCK_FILE)
    except OSError:
        pass
