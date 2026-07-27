"""
Citrinitas Watch Folder — 公开 API 层

v1.0.1 重构：单体 1509 行拆分为 5 个模块。
├── state.py      全局状态 + 状态文件 + 锁文件
├── utils.py      路径定义 + 基础设施检查
├── failures.py   15 种故障 × 5 种策略
├── processor.py  文件处理管线
├── listener.py   文件监听 + 处理循环
├── migration.py  旧版 v1 迁移
└── __init__.py   公开 API（本文档）

用法:
    from watcher import start_watcher, stop_watcher
    start_watcher()
    # ... app runs ...
    stop_watcher()
"""

import os
import signal as _signal
import threading
import time
from queue import Queue

from watchdog.observers import Observer

from config.settings import (
    WATCH_V2_INBOX_DIR,
    WATCH_V2_STATE_FILE,
    WATCH_V2_QUEUE_MAX_SIZE,
    WATCH_V2_QUEUE_PUT_TIMEOUT,
    WATCH_V2_PROCESS_TIMEOUT,
)
from utils.activity_log import log_activity

import watcher.state as _state
from watcher.utils import INBOX_DIR, STATE_FILE, _ensure_dir
from watcher.listener import WatchHandler, _processing_loop
from watcher.migration import _migrate_from_v1


# ═══════════════════════════════════════════
# 信号处理
# ═══════════════════════════════════════════

def _signal_handler(signum, frame):
    """SIGINT/SIGTERM 信号处理器 — 设置 stop_event，让处理循环优雅退出。"""
    if _state._stop_event:
        _state._stop_event.set()
        log_activity(action="watch_signal", detail=f"收到信号 {signum}，开始优雅关闭")


# ═══════════════════════════════════════════
# 公开 API
# ═══════════════════════════════════════════

def start_watcher() -> threading.Thread | None:
    """启动守望文件夹 守护进程。"""
    try:
        _signal.signal(_signal.SIGINT, _signal_handler)
        _signal.signal(_signal.SIGTERM, _signal_handler)
    except (ValueError, OSError):
        pass

    if not _state._check_lock_file():
        log_activity(
            action="watch_multiple_instance",
            detail="已有守望进程 在运行，拒绝重复启动",
        )
        print("[watcher] 已有守望进程在运行，跳过启动。")
        return None

    _ensure_dir(INBOX_DIR)
    _ensure_dir(os.path.dirname(STATE_FILE))

    _migrate_from_v1()

    _state._queue = Queue(maxsize=WATCH_V2_QUEUE_MAX_SIZE)
    _state._stop_event = threading.Event()

    _state._observer = Observer()
    handler = WatchHandler(_state._queue, _state._stop_event)
    _state._observer.schedule(handler, INBOX_DIR, recursive=False)
    _state._observer.start()

    _state._worker_thread = threading.Thread(
        target=_processing_loop,
        args=(_state._queue, _state._stop_event),
        daemon=True,
        name="citrinitas-watcher",
    )
    _state._worker_thread.start()

    with _state._stats_lock: _state._watch_stats["running"] = True
    _state._write_lock_file()

    log_activity(action="watch_started", detail="守望文件夹 已启动")
    print("[watcher] 守望文件夹 已启动，监控目录:", INBOX_DIR)

    return _state._worker_thread


def stop_watcher():
    """停止守望文件夹 守护进程（优雅关闭）。"""
    if _state._stop_event:
        _state._stop_event.set()

    # #302 兜底：真杀所有仍存活的 Y2 处理子进程，避免其变孤儿继续霸占 Ollama/Qdrant；
    # 同时让下方 worker 线程的 proc.join 立即返回，关停不会卡在等待子进程。
    _state._kill_all_children()

    if _state._observer:
        _state._observer.stop()
        _state._observer.join(timeout=5)

    if _state._worker_thread and _state._worker_thread.is_alive():
        _state._worker_thread.join(timeout=WATCH_V2_PROCESS_TIMEOUT)
        if _state._worker_thread.is_alive():
            log_activity(
                action="watch_stop_timeout",
                detail=f"处理线程在 {WATCH_V2_PROCESS_TIMEOUT}s 内未退出，强制退出",
            )

    with _state._stats_lock: _state._watch_stats["running"] = False
    _state._remove_lock_file()
    log_activity(action="watch_stopped", detail="守望文件夹 已停止")


def is_watcher_alive() -> bool:
    """检查 watcher 线程是否存活（心跳检测）。"""
    with _state._heartbeat_lock:
        last_beat = _state._heartbeat_time
    if last_beat == 0:
        return False
    return (time.time() - last_beat) < 60


def get_watch_stats() -> dict:
    """获取守望文件夹 运行统计。"""
    inbox_stats = _state.get_inbox_stats()
    with _state._stats_lock:
        _state._watch_stats["pending"] = inbox_stats["pending"]
        return _state._watch_stats.copy()


def retry_file(filename: str) -> bool:
    """手动触发重试某个文件。清除其状态记录，然后放入队列。"""
    filepath = os.path.join(INBOX_DIR, filename)
    if not os.path.isfile(filepath):
        return False

    _state._remove_state(filename)

    if _state._queue is not None:
        try:
            _state._queued_files.add(filepath)
            _state._queue.put(filepath, timeout=WATCH_V2_QUEUE_PUT_TIMEOUT)
            log_activity(
                action="watch_manual_retry",
                detail=f"手动重试: {filename}",
                source=filename,
            )
            return True
        except Exception as e:
            log_activity(
                action="watch_manual_retry_failed",
                detail=f"手动重试入队失败 (队列满): {filename}",
                source=filename,
            )
    return False


# 重导出（通过 _state 访问，避免 Python import binding 问题）
get_all_states = _state.get_all_states
get_inbox_stats = _state.get_inbox_stats


__all__ = [
    "start_watcher",
    "stop_watcher",
    "is_watcher_alive",
    "get_watch_stats",
    "retry_file",
    "get_all_states",
    "get_inbox_stats",
]
