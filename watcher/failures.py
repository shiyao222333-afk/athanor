"""
Citrinitas Watch Folder — 故障分类与处理策略

15 种故障类型 × 5 种处理策略。
此模块由 watcher/__init__.py 导入，使用延迟导入避免循环依赖。
"""

import os

from config.settings import (
    WATCH_V2_MAX_AUTO_RETRIES,
)
from utils.activity_log import log_activity

# 15 种故障类型
FAILURE_TYPES = {
    # 格式/大小检查
    "format_unsupported": {"step": "format_check", "strategy": "dlq_delete"},
    "file_too_large":     {"step": "size_check",    "strategy": "dlq_keep"},   # #304 超限文件保留等人工处理，不再物理删除
    "temp_file":           {"step": "filter",        "strategy": "skip"},

    # 文件读取
    "read_error":          {"step": "extract",       "strategy": "auto_retry"},
    "corrupt_file":        {"step": "extract",       "strategy": "dlq_keep"},

    # 文本提取
    "extract_empty":       {"step": "extract",       "strategy": "needs_review"},
    "extract_error":       {"step": "extract",       "strategy": "auto_retry"},
    "ocr_failed":          {"step": "ocr",           "strategy": "needs_review"},
    "ocr_unavailable":     {"step": "ocr",           "strategy": "retry_later"},

    # AI 分类
    "classify_error":      {"step": "classify",      "strategy": "auto_retry"},
    "classify_low_conf":   {"step": "classify",      "strategy": "needs_review"},

    # 摄入
    "ingest_error":        {"step": "ingest",        "strategy": "auto_retry"},
    "ingest_duplicate":    {"step": "ingest",        "strategy": "skip"},

    # 基础设施
    "infra_down":          {"step": "infra",         "strategy": "retry_later"},
    "disk_full":           {"step": "any",           "strategy": "retry_later"},

    # 通用
    "timeout":             {"step": "any",           "strategy": "auto_retry"},
    "unknown":             {"step": "unknown",       "strategy": "dlq_keep"},
}

# 5 种处理策略说明（文档用途，非程序引用）:
#   auto_retry:   自动重试 N 次，全部失败后入 needs_review
#   retry_later:  等待基础设施恢复，不消耗重试次数
#   dlq_keep:     标记为 failed 保留原文件，等用户手动处理
#   dlq_delete:   标记为 failed 并删除原文件（无价值文件）
#   needs_review: 标记为 needs_review，等用户在 UI 审核
#   skip:         直接跳过，不记录状态


def _classify_failure(step: str, error_msg: str) -> str:
    """根据失败步骤和错误消息，映射到故障类型。"""
    # 格式检查
    if step == "format_check":
        return "format_unsupported"
    if step == "size_check":
        return "file_too_large"
    if step == "filter":
        return "temp_file"

    # 基础设施
    if "infra" in step:
        return "infra_down"
    if "disk" in error_msg.lower() or "space" in error_msg.lower():
        return "disk_full"

    # 文本提取
    if step == "extract":
        if "empty" in error_msg.lower() or "无文本" in error_msg:
            return "extract_empty"
        if "corrupt" in error_msg.lower() or "损坏" in error_msg:
            return "corrupt_file"
        return "extract_error"

    # OCR
    if step == "ocr":
        if "unavailable" in error_msg.lower() or "未安装" in error_msg:
            return "ocr_unavailable"
        return "ocr_failed"

    # 分类
    if step == "classify":
        if "conf" in error_msg.lower() or "置信度" in error_msg:
            return "classify_low_conf"
        return "classify_error"

    # 摄入
    if step == "ingest":
        if "duplicate" in error_msg.lower() or "重复" in error_msg:
            return "ingest_duplicate"
        return "ingest_error"

    # 超时
    if step == "timeout":
        return "timeout"

    # 文件读取
    if "permission" in error_msg.lower() or "权限" in error_msg:
        return "read_error"

    return "unknown"


def _get_strategy(failure_type: str) -> str:
    """获取故障类型对应的处理策略。"""
    return FAILURE_TYPES.get(failure_type, {}).get("strategy", "dlq_keep")


def _handle_failure(filepath: str, filename: str, step: str, error_msg: str, retry_count: int = 0) -> str:
    """
    统一故障处理入口。

    根据故障类型选择策略，执行后返回状态:
      - "retry": 应自动重试
      - "retry_later": 等待基础设施恢复
      - "needs_review": 需要人工审核
      - "failed": 已入失败记录
      - "skip": 已跳过
    """
    # 延迟导入避免循环依赖（此模块由 __init__.py 在 globals 定义之后导入）
    from watcher.state import _append_state, _watch_stats, _stats_lock

    failure_type = _classify_failure(step, error_msg)
    strategy = _get_strategy(failure_type)

    # ── auto_retry ──
    if strategy == "auto_retry":
        if retry_count < WATCH_V2_MAX_AUTO_RETRIES:
            log_activity(
                action="watch_retry",
                detail=f"[{step}] {error_msg} (重试 {retry_count + 1}/{WATCH_V2_MAX_AUTO_RETRIES})",
                source=filename,
            )
            return "retry"
        else:
            # 重试耗尽 → 降级为 needs_review
            _append_state({
                "file": filename,
                "state": "needs_review",
                "step": step,
                "error": f"{error_msg} (已重试{WATCH_V2_MAX_AUTO_RETRIES}次)",
                "retry_count": retry_count,
                "failure_type": failure_type,
            })
            with _stats_lock: _watch_stats["needs_review"] += 1
            log_activity(
                action="watch_retry_exhausted",
                detail=f"[{step}] {error_msg} (重试耗尽)",
                source=filename,
            )
            return "needs_review"

    # ── retry_later（基础设施故障）──
    if strategy == "retry_later":
        _append_state({
            "file": filename,
            "state": "retry",
            "step": step,
            "error": error_msg,
            "retry_count": retry_count,
            "failure_type": failure_type,
        })
        log_activity(
            action="watch_retry_later",
            detail=f"[{step}] {error_msg} (等待基础设施恢复)",
            source=filename,
        )
        return "retry_later"

    # ── needs_review ──
    if strategy == "needs_review":
        _append_state({
            "file": filename,
            "state": "needs_review",
            "step": step,
            "error": error_msg,
            "retry_count": retry_count,
            "failure_type": failure_type,
        })
        with _stats_lock: _watch_stats["needs_review"] += 1
        log_activity(
            action="watch_needs_review",
            detail=f"[{step}] {error_msg}",
            source=filename,
        )
        return "needs_review"

    # ── dlq_keep ──
    if strategy == "dlq_keep":
        _append_state({
            "file": filename,
            "state": "failed",
            "step": step,
            "error": error_msg,
            "retry_count": retry_count,
            "failure_type": failure_type,
        })
        with _stats_lock: _watch_stats["failed"] += 1
        log_activity(
            action="watch_failed",
            detail=f"[{step}] {error_msg}",
            source=filename,
        )
        return "failed"

    # ── dlq_delete ──
    if strategy == "dlq_delete":
        try:
            os.remove(filepath)
        except OSError:
            pass
        log_activity(
            action="watch_deleted",
            detail=f"[{step}] {error_msg} (文件已删除)",
            source=filename,
        )
        with _stats_lock: _watch_stats["deleted"] += 1
        return "skip"

    # ── skip ──
    if strategy == "skip":
        with _stats_lock: _watch_stats["skipped"] += 1
        return "skip"

    return "failed"
