"""
Citrinitas Watch Folder — 文件处理管线。

逐页提取 → WLNK 决策 → AI 分类 → 置信度路由 → 摄入 → 保留/删除。
依赖 state.py（全局状态）和 failures.py（故障处理）。
"""

import os
import json
import time
import threading
import shutil
import multiprocessing
from queue import Full

import requests

from config.settings import (
    WATCH_V2_MAX_FILE_SIZE_MB,
    WATCH_V2_MAX_AUTO_RETRIES,
    WATCH_V2_AUTO_RETRY_DELAY,
    WATCH_V2_TEXT_DENSITY_THRESHOLD,
    WATCH_V2_OCR_CONF_THRESHOLD,
    WATCH_V2_PROCESSING_TIMEOUT,
    WATCH_V2_PROGRESS_STALL_TIMEOUT,
    WATCH_V2_QUEUE_PUT_TIMEOUT,
)
from text_pipeline import (
    analyze_page_content,
    ocr_image as _ocr_image,
    extract_text as _extract_text,
    parse_frontmatter as _parse_frontmatter,
)
from classify_pipeline import classify_document, route_by_confidence
from qconst import CONFIDENCE_LOW, CONFIDENCE_HIGH, BOOKS_DIR
from utils.activity_log import log_activity
from services.ingest_service import ingest

from watcher.state import (
    _watch_stats, _stats_lock,
    _append_state, _remove_state, _get_file_state,
    _queued_files, _in_flight, _queue,
    _register_child, _unregister_child,
)
from watcher.utils import (
    _check_ocr_ready, _check_infra, _check_disk_space, _is_write_complete,
)
from watcher.failures import _handle_failure, _classify_failure


# 书类文件扩展名（按格式判定归档，不依赖分类猜测）。单一真相源，供归档 / 保留 / 重复跳过共用。
BOOK_EXTS = {".epub", ".pdf", ".docx", ".pptx"}


# ═══════════════════════════════════════════
# 心跳看门狗（#308）：子进程逐页/逐嵌入上报进度到 sidecar 文件，
# 父进程轮询——无进度 > 停滞阈值 或 超绝对上限 才强杀。慢但在动的大文件永不误杀。
# ═══════════════════════════════════════════

# 心跳目录：library/.progress/<filename>.json（与 library/books/ 同级）
_PROGRESS_DIR = os.path.join(os.path.dirname(BOOKS_DIR), ".progress")


def _progress_path(filename: str) -> str:
    return os.path.join(_PROGRESS_DIR, f"{filename}.json")


def _write_progress(filename: str, stage: str, page: int = None, total_pages: int = None):
    """子进程上报心跳：绝对墙钟 time.time()，跨进程可比（不可用 monotonic）。"""
    if not filename:
        return
    try:
        os.makedirs(_PROGRESS_DIR, exist_ok=True)
        data = {
            "filename": filename,
            "stage": stage,
            "page": page,
            "total_pages": total_pages,
            "last_progress_ts": time.time(),
        }
        tmp = _progress_path(filename) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, _progress_path(filename))  # 原子替换，避免父进程读到半截
    except (OSError, ValueError):
        pass


def _read_progress(filename: str) -> dict | None:
    """父进程读取心跳。返回 dict 或 None。"""
    if not filename:
        return None
    try:
        with open(_progress_path(filename), "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _clear_progress(filename: str):
    """父进程在处理结束后删除 sidecar（无论成功/强杀）。"""
    if not filename:
        return
    try:
        os.remove(_progress_path(filename))
    except OSError:
        pass


def _embed_progress_cb(filename: str):
    """生成嵌入进度回调：第 i 个块嵌入完成后上报心跳。"""
    def cb(idx: int, total: int):
        _write_progress(filename, stage="embed", page=idx + 1, total_pages=total)
    return cb


def _ticker_interval() -> float:
    """心跳 ticker 间隔：严格小于停滞阈值，确保任何单步同步长调用都不会被判停滞。

    取停滞阈值的 1/3，并夹在 [1s, 30s]：stall=300 → 30s（10 倍余量）；
    stall=30(最小允许值) → 10s（3 倍余量）。下限 1s 仅为避免病态高频写盘，
    上限 30s 避免大文件场景写盘过稀。stall=0(禁用) 时回退 15s。
    关键：interval 恒 < stall（stall>0 时），否则 ticker 自身会触发误杀。
    """
    stall = WATCH_V2_PROGRESS_STALL_TIMEOUT
    if stall and stall > 0:
        return max(1.0, min(stall / 3.0, 30.0))
    return 15.0


def _heartbeat_ticker(filename: str, stage_ref: dict, stop: threading.Event):
    """后台心跳 ticker 线程（#313）。

    处理期间每 ~间隔 写一次「当前 stage」心跳，确保 classify(单 LLM 调用) /
    OCR 回退(逐页) 等「步骤内心跳缺失」的长同步调用不会被看门狗误杀。
    I/O 阻塞调用会释放 GIL，故主线程卡在慢网络调用时本线程仍能持续写心跳。
    daemon 线程：随子进程退出自动结束，无需显式回收；stop 仅用于正常结束时尽快停。
    """
    interval = _ticker_interval()
    while not stop.wait(interval):
        _write_progress(filename, stage=stage_ref.get("value", "processing"))


# ═══════════════════════════════════════════
# WLNK 多页决策
# ═════════════════════════════════════════════

def decide_file_retention(page_analyses: list[dict]) -> dict:
    """
    文件级保留决策 — WLNK 原则：文件可删 = min(每页可删性)。

    任一页不可删 → 保留整个文件。

    返回:
        {
            "keep_file": bool,
            "reason": str,
            "pages_deletable": int,
            "pages_total": int,
        }
    """
    if not page_analyses:
        return {"keep_file": True, "reason": "无页面数据，保守保留", "pages_deletable": 0, "pages_total": 0}

    total = len(page_analyses)
    deletable = sum(1 for p in page_analyses if p["deletable"])
    non_deletable = total - deletable

    if non_deletable > 0:
        reasons = []
        for i, p in enumerate(page_analyses):
            if not p["deletable"]:
                reasons.append(f"第{i+1}页: {p['summary']}")
        return {
            "keep_file": True,
            "reason": f"{non_deletable}/{total} 页含非文本元素 — " + "; ".join(reasons[:3]),
            "pages_deletable": deletable,
            "pages_total": total,
        }

    return {
        "keep_file": False,
        "reason": f"全部 {total} 页均为纯文本，内容已入库，可删除原文件",
        "pages_deletable": deletable,
        "pages_total": total,
    }


# ═══════════════════════════════════════════
# 逐页提取（PDF/多页文档支持）
# ═══════════════════════════════════════════

def _extract_pages(filepath: str, ext: str, filename: str = None) -> list[dict]:
    """逐页提取文档内容。返回 [{"text": "...", "images": [...], "tables": [...], "ocr_conf": None}, ...]"""
    pages = []

    if ext == ".pdf":
        try:
            import pdfplumber
            with pdfplumber.open(filepath) as pdf:
                total = len(pdf.pages)
                _last_beat = time.time()
                for idx, page in enumerate(pdf.pages):
                    page_text = page.extract_text() or ""
                    page_images = []
                    page_tables = []

                    try:
                        img_list = getattr(page, 'images', []) or []
                        page_images = [f"pdf_img_{i}" for i in range(len(img_list))]
                    except (AttributeError, TypeError):
                        pass

                    try:
                        tbl_list = page.extract_tables() or []
                        page_tables = [f"table_{i}" for i in range(len(tbl_list))]
                    except (AttributeError, TypeError):
                        pass

                    pages.append({
                        "text": page_text,
                        "images": page_images,
                        "tables": page_tables,
                        "ocr_conf": None,
                    })
                    # 心跳：每 ~2s 或首/尾页上报，避免大 PDF 逐页时被判停滞
                    if filename and (idx == 0 or idx == total - 1 or time.time() - _last_beat > 2):
                        _write_progress(filename, stage="extract", page=idx + 1, total_pages=total)
                        _last_beat = time.time()
        except ImportError:
            if not getattr(_extract_pages, "_pdfplumber_warned", False):
                _extract_pages._pdfplumber_warned = True
                log_activity(
                    action="watch_pdfplumber_missing",
                    detail="pdfplumber 未安装，PDF 文件将无法提取文本。安装: pip install pdfplumber",
                )
            pages.append({"text": "", "images": [], "tables": [], "ocr_conf": None})
        except (OSError, ValueError):
            pages.append({"text": "", "images": [], "tables": [], "ocr_conf": None})

    elif ext in (".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif"):
        try:
            ocr_result = _ocr_image(filepath)
            ocr_text = ocr_result.get("text", "") if ocr_result.get("ok") else ""
            ocr_conf = ocr_result.get("conf")
            has_images = bool(ocr_result.get("images", []))
            pages.append({
                "text": ocr_text,
                "images": ["ocr_image"] if has_images else [],
                "tables": [],
                "ocr_conf": ocr_conf,
            })
            if filename:
                _write_progress(filename, stage="extract", page=1, total_pages=1)
        except (OSError, UnicodeDecodeError):
            pages.append({"text": "", "images": [], "tables": [], "ocr_conf": None})

    else:
        try:
            result = _extract_text(filepath)
            text = result.get("text", "") if result.get("ok") else ""
        except Exception:
            text = ""
        pages.append({"text": text, "images": [], "tables": [], "ocr_conf": None})
        if filename:
            _write_progress(filename, stage="extract", page=1, total_pages=1)

    return pages


# ═══════════════════════════════════════════
# 处理步骤
# ═══════════════════════════════════════════

def _do_prechecks(filepath: str, ext: str, filename: str, retry_count: int) -> tuple:
    """前置检查（格式/大小/存在/OCR）。返回 (ok, should_retry, new_retry_count)。"""
    supported = {".txt", ".md", ".json", ".csv", ".log", ".pdf", ".docx",
                 ".pptx", ".epub", ".html", ".htm", ".xml", ".jpg", ".jpeg",
                 ".png", ".bmp", ".tiff", ".tif"}
    if ext not in supported:
        _handle_failure(filepath, filename, "format_check", f"不支持的文件格式: {ext}")
        return False, False, retry_count

    if WATCH_V2_MAX_FILE_SIZE_MB > 0:
        try:
            size_mb = os.path.getsize(filepath) / (1024 * 1024)
            if size_mb > WATCH_V2_MAX_FILE_SIZE_MB:
                _handle_failure(filepath, filename, "size_check",
                                f"文件过大 ({size_mb:.1f}MB > {WATCH_V2_MAX_FILE_SIZE_MB}MB)")
                return False, False, retry_count
        except OSError as e:
            result = _handle_failure(filepath, filename, "read_error", str(e), retry_count)
            if result == "retry":
                return False, True, retry_count + 1
            return False, False, retry_count

    if not os.path.isfile(filepath):
        _append_state({
            "file": filename, "state": "failed",
            "step": "read_error", "error": "文件在处理前已不存在",
            "failure_type": "read_error",
        })
        with _stats_lock: _watch_stats["failed"] += 1
        return False, False, retry_count

    image_exts = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif"}
    if ext in image_exts and not _check_ocr_ready():
        result = _handle_failure(filepath, filename, "ocr", "OCR 引擎未安装", retry_count)
        if result == "retry_later":
            return False, False, retry_count
        if result == "retry":
            return False, True, retry_count + 1
        return False, False, retry_count

    return True, False, retry_count


def _do_ocr_fallback(pages: list, filepath: str, filename: str,
                      retry_count: int) -> tuple:
    """当文本提取为空时尝试 OCR 兜底。返回 (success, full_text, should_retry, new_retry_count)。"""
    has_images = any(p.get("images") for p in pages)
    if not has_images or not _check_ocr_ready():
        result = _handle_failure(filepath, filename, "extract", "所有页面提取为空", retry_count)
        if result == "retry":
            return False, None, True, retry_count + 1
        return False, None, False, retry_count

    log_activity(
        action="watch_ocr_fallback",
        detail=f"文本提取为空但存在图片，尝试 OCR: {filename}",
        source=filename,
    )
    ocr_text_parts = []
    _ocr_cache = None
    for p in pages:
        if p.get("images"):
            try:
                if _ocr_cache is None:
                    _ocr_cache = _ocr_image(filepath)
                ocr_result = _ocr_cache
                if ocr_result.get("ok"):
                    page_text = ocr_result.get("text", "")
                    if page_text.strip():
                        p["text"] = page_text
                        p["ocr_conf"] = ocr_result.get("conf")
                        ocr_text_parts.append(page_text)
                elif not ocr_text_parts:
                    ocr_text_parts.append("")
            except (OSError, requests.RequestException, ValueError):
                if not ocr_text_parts:
                    ocr_text_parts.append("")
        else:
            ocr_text_parts.append(p.get("text", ""))

    if not any(t.strip() for t in ocr_text_parts):
        result = _handle_failure(filepath, filename, "extract",
                                "所有页面提取为空（OCR 后仍无文本）", retry_count)
        if result == "retry":
            return False, None, True, retry_count + 1
        return False, None, False, retry_count

    return True, "\n\n".join(ocr_text_parts), False, retry_count


def _do_classify(full_text: str, filepath: str, filename: str,
                 retry_count: int, frontmatter_meta: dict = None) -> tuple:
    """AI 分类 + 置信度路由。返回 (metadata, field_sources, overall_conf, needs_review, should_retry, new_retry_count)。"""
    fm = frontmatter_meta or {}
    file_metadata = {"source_path": filepath}
    if fm.get("title"):
        file_metadata["title"] = fm["title"]
    if fm.get("up_name"):
        file_metadata["author"] = fm["up_name"]
    if fm.get("source_url"):
        file_metadata["source_url"] = fm["source_url"]
    try:
        classify_result = classify_document(full_text, file_metadata=file_metadata)
    except (requests.RequestException, ValueError, KeyError) as e:
        result = _handle_failure(filepath, filename, "classify", str(e), retry_count)
        if result == "retry":
            return None, None, 0.0, False, True, retry_count + 1
        return None, None, 0.0, False, False, retry_count

    if not classify_result.get("ok"):
        error_msg = classify_result.get("error", "分类失败")
        result = _handle_failure(filepath, filename, "classify", error_msg, retry_count)
        if result == "retry":
            return None, None, 0.0, False, True, retry_count + 1
        return None, None, 0.0, False, False, retry_count

    annotated = classify_result.get("annotated", {})
    classification = classify_result.get("classification", {})
    field_sources = annotated.get("field_sources", {})
    overall_conf = annotated.get("overall_confidence", 0.0)

    metadata = dict(classification)
    metadata["source_path"] = filepath
    metadata["ingestion_source"] = "watch"
    if fm.get("source_url"):
        metadata["source_url"] = fm["source_url"]

    needs_review, should_dlq = route_by_confidence(
        overall_conf, CONFIDENCE_LOW, CONFIDENCE_HIGH)
    if should_dlq:
        _handle_failure(filepath, filename, "classify",
                        f"置信度过低 ({overall_conf:.2f} < {CONFIDENCE_LOW})", retry_count)
        return None, None, overall_conf, False, False, retry_count

    return metadata, field_sources, overall_conf, needs_review, False, retry_count


def _do_ingest(full_text: str, metadata: dict, field_sources: dict,
               overall_conf: float, filepath: str, filename: str,
               retry_count: int) -> tuple:
    """摄入知识库。返回 (ingest_result, should_retry, new_retry_count)。"""
    try:
        ingest_result = ingest(
            text=full_text,
            metadata=metadata,
            collection="athanor_v1",
            field_sources=field_sources,
            overall_confidence=overall_conf,
            file_path=filepath,   # 传入永久源路径：保证 doc_id 确定性 + 详情页 source_path 可见
            progress_callback=_embed_progress_cb(filename),  # 心跳：嵌入逐块上报
        )
    except (requests.RequestException, ValueError) as e:
        result = _handle_failure(filepath, filename, "ingest", str(e), retry_count)
        if result == "retry":
            return None, True, retry_count + 1
        return None, False, retry_count

    if not ingest_result.get("ok"):
        error_msg = ingest_result.get("error", "摄入失败")
        if "duplicate" in error_msg.lower() or "重复" in error_msg:
            log_activity(
                action="watch_duplicate_skipped",
                detail=f"文件已存在于知识库: {error_msg}",
                source=filename,
            )
            _append_state({"file": filename, "state": "done"})
            with _stats_lock: _watch_stats["processed"] += 1
            # 书类文件已归档至 library/books/ 永久保留，重复跳过时不得删除永久源
            if os.path.splitext(filepath)[1].lower() not in BOOK_EXTS:
                try:
                    os.remove(filepath)
                except OSError:
                    pass
            return ingest_result, False, retry_count
        result = _handle_failure(filepath, filename, "ingest", error_msg, retry_count)
        if result == "retry":
            return None, True, retry_count + 1
        return None, False, retry_count

    return ingest_result, False, retry_count


def _do_post_ingest(filepath: str, filename: str, retention: dict,
                    needs_review: bool, overall_conf: float) -> None:
    """处理摄入成功后的文件保留/删除和状态更新。"""
    with _stats_lock: _watch_stats["processed"] += 1

    if needs_review:
        _append_state({
            "file": filename,
            "state": "needs_review",
            "step": "classify",
            "error": f"入库置信度 ({overall_conf:.2f}) 低于高阈值 ({CONFIDENCE_HIGH})",
            "ingest_conf": overall_conf,
        })
        with _stats_lock: _watch_stats["needs_review"] += 1

    # 书类文件（epub/pdf/docx/pptx）已归档到 library/books/，永不删除源文件
    _ext = os.path.splitext(filepath)[1].lower()
    if retention["keep_file"]:
        log_activity(
            action="watch_kept",
            detail=f"保留原文件: {retention['reason']}",
            source=filename,
        )
    elif _ext in BOOK_EXTS:
        log_activity(
            action="watch_book_kept",
            detail=f"书类文件已永久保留于 library/books/: {filename}",
            source=filename,
        )
    else:
        # 验收开关：ACCEPTANCE_KEEP_FILES=1 时跳过删除，保留中转②供验收流程读取/复制
        if os.environ.get("ACCEPTANCE_KEEP_FILES", "") in ("1", "true", "yes"):
            log_activity(
                action="watch_kept",
                detail="验收保留：KB_KEEP_INBOX 开启，跳过删除原文件",
                source=filename,
            )
        else:
            try:
                os.remove(filepath)
                log_activity(
                    action="watch_deleted",
                    detail=f"删除原文件: {retention['reason']}",
                    source=filename,
                )
            except OSError as e:
                log_activity(
                    action="watch_delete_failed",
                    detail=f"无法删除原文件: {e}",
                    source=filename,
                )

    log_activity(
        action="watch_processed",
        detail=f"成功处理" + (" [待审核]" if needs_review else ""),
        source=filename,
    )

    if needs_review:
        if not retention["keep_file"]:
            _append_state({
                "file": filename,
                "state": "needs_review",
                "file_deleted": True,
                "step": "classify",
                "ingest_conf": overall_conf,
            })
    else:
        _remove_state(filename)
        if retention["keep_file"]:
            _append_state({"file": filename, "state": "done"})


# ═══════════════════════════════════════════
# 文件处理主流程
# ═══════════════════════════════════════════

def _process_file(filepath: str):
    """处理单个文件：逐页提取 → WLNK 决策 → 分类 → 摄入 → 保留/删除。"""
    filename = os.path.basename(filepath)
    ext = os.path.splitext(filename)[1].lower()

    # 立即上报初始心跳，避免子进程尚未落心跳时被看门狗误判停滞
    _write_progress(filename, stage="init")

    # 后台心跳 ticker（#313）：处理期间每 ~间隔 写一次「当前 stage」心跳，
    # 确保 classify(单 LLM 调用) / OCR 回退(逐页) 等「步骤内心跳缺失」的长同步调用
    # 不会被看门狗误杀。daemon 线程：随子进程退出自动结束，无需显式回收。
    _stage = {"value": "init"}
    _hb_stop = threading.Event()
    _hb_thread = threading.Thread(
        target=_heartbeat_ticker, args=(filename, _stage, _hb_stop),
        name=f"hb-{filename[:20]}", daemon=True,
    )
    _hb_thread.start()

    # ── Albedo 中转② sidecar（{name}_refined.meta.json）：机读元数据，非待摄入正文，直接跳过 ──
    if filename.endswith(".meta.json"):
        return

    # 重复摄入卫士（AI 设计决策，非用户指令，见 FLOWCHART §5）：
    # 文件已为终态(done/failed/needs_review)或处理中(processing)时直接返回，
    # 防止并发/重探测导致同文件被摄入两次（主循环已做状态跳过，此处为防御性双保险）。
    _cur = _get_file_state(filename)
    if _cur and _cur.get("state") in ("done", "failed", "needs_review", "processing"):
        log_activity(
            action="watch_skip_terminal",
            detail=f"文件已为终态/处理中({_cur.get('state')})，跳过重复摄入",
            source=filename,
        )
        return

    # 书类归档逻辑见下方 #307 修复处：已移至 size 预检（_do_prechecks）通过之后，
    # 避免「超限书类先被移入 library/books/ 永久库，再触发 size_check 失败被处置」的数据丢失。

    with _stats_lock: _watch_stats["infra_ok"] = True
    retry_count = 0
    max_retries = WATCH_V2_MAX_AUTO_RETRIES

    while retry_count <= max_retries:
        # 标记「处理中」，让收件箱 UI 实时显示进度（extract → classify → ingest）
        _append_state({
            "file": filename,
            "state": "processing",
            "step": "extract",
        })
        _stage["value"] = "extract"
        _write_progress(filename, stage="extract")  # 心跳：提取阶段开始

        ok, should_retry, retry_count = _do_prechecks(filepath, ext, filename, retry_count)
        if not ok:
            if should_retry:
                time.sleep(WATCH_V2_AUTO_RETRY_DELAY)
                continue
            return

        # ── 书类文件（按格式触发，不靠分类猜测）：size 预检通过后再归档到 library/books/ 永久保留 ──
        # #307 修复：归档必须排在 _do_prechecks(size_check) 之后。否则超限书类会先被移入永久库，
        # 再触发 size_check 失败→被处置（dlq_delete 删永久库原件 / dlq_keep 留永久库僵尸），造成数据丢失或脏数据。
        if ext in BOOK_EXTS:
            try:
                os.makedirs(BOOKS_DIR, exist_ok=True)
                dest = os.path.join(BOOKS_DIR, filename)
                if os.path.abspath(filepath) != os.path.abspath(dest):
                    if os.path.exists(dest):
                        os.remove(dest)  # 重录入场景：覆盖旧归档
                    shutil.move(filepath, dest)
                    filepath = dest
                    log_activity(
                        action="watch_book_archived",
                        detail=f"书类文件已归档至 library/books/: {filename}",
                        source=filename,
                    )
            except OSError as e:
                log_activity(
                    action="watch_book_archive_failed",
                    detail=f"归档书类文件失败，仍按原路径处理: {e}",
                    source=filename,
                )

        try:
            pages = _extract_pages(filepath, ext, filename)
        except Exception as e:
            result = _handle_failure(filepath, filename, "extract", str(e), retry_count)
            if result == "retry":
                retry_count += 1
                time.sleep(WATCH_V2_AUTO_RETRY_DELAY)
                continue
            return

        if not pages or not any(p.get("text", "").strip() for p in pages):
            success, ocr_text, should_retry, retry_count = _do_ocr_fallback(
                pages, filepath, filename, retry_count)
            if not success:
                if should_retry:
                    time.sleep(WATCH_V2_AUTO_RETRY_DELAY)
                    continue
                return
            full_text = ocr_text
        else:
            all_text_parts = [p.get("text", "") for p in pages]
            full_text = "\n\n".join(all_text_parts)

            # 解析中转文件 frontmatter（标题/作者等），剥除正文里的元数据噪音行
            full_text, _fm_meta = _parse_frontmatter(full_text)

        page_analyses = []
        for p in pages:
            analysis = analyze_page_content(
                text=p.get("text", ""),
                page_images=p.get("images"),
                page_tables=p.get("tables"),
                ocr_conf=p.get("ocr_conf"),
                text_density_threshold=WATCH_V2_TEXT_DENSITY_THRESHOLD,
                ocr_conf_threshold=WATCH_V2_OCR_CONF_THRESHOLD,
            )
            page_analyses.append(analysis)

        retention = decide_file_retention(page_analyses)

        _append_state({
            "file": filename,
            "state": "processing",
            "step": "classify",
        })
        _stage["value"] = "classify"
        _write_progress(filename, stage="classify")  # 心跳：分类阶段开始
        metadata, field_sources, overall_conf, needs_review, should_retry, retry_count = _do_classify(
            full_text, filepath, filename, retry_count, _fm_meta)
        if metadata is None:
            if should_retry:
                time.sleep(WATCH_V2_AUTO_RETRY_DELAY)
                continue
            return

        metadata["needs_review"] = needs_review
        _append_state({
            "file": filename,
            "state": "processing",
            "step": "ingest",
        })
        _stage["value"] = "ingest"
        _write_progress(filename, stage="ingest")  # 心跳：摄入阶段开始
        ingest_result, should_retry, retry_count = _do_ingest(
            full_text, metadata, field_sources, overall_conf,
            filepath, filename, retry_count)
        if ingest_result is None:
            if should_retry:
                time.sleep(WATCH_V2_AUTO_RETRY_DELAY)
                continue
            return

        # 重复文件已在 _do_ingest 内部完成处理（标记 done / 删除文件 / 计数），
        # 此处不可再走 _do_post_ingest，否则会重复计数。
        if not ingest_result.get("ok"):
            return

        _do_post_ingest(filepath, filename, retention, needs_review, overall_conf)
        return


def _process_file_with_timeout(filepath: str):
    """带超时保护的文件处理（Y2 加固 + #308 心跳看门狗）。

    把单个文件的处理放到独立子进程执行；超时**不再**用固定秒数硬杀，
    而是「心跳看门狗」：子进程逐页/逐嵌入把进度写到 library/.progress/<filename>.json
    （绝对墙钟 time.time()，跨进程可比）。父进程轮询该文件：
      - 无进度 > WATCH_V2_PROGRESS_STALL_TIMEOUT(默认 300s) → 真杀（判定卡死）
      - 已运行 > WATCH_V2_PROCESSING_TIMEOUT(默认 3600s；0=禁用) → 真杀（绝对上限）
    慢但在动的大文件（大 PDF 逐页 / 大模型逐块嵌入）永不误杀。
    """
    filename = os.path.basename(filepath)

    ctx = multiprocessing.get_context("spawn")
    proc = ctx.Process(target=_process_file_worker, args=(filepath,),
                       name=f"watcher-{filename[:20]}")
    proc.start()
    _register_child(proc)  # 登记：关停时由 stop_watcher / 主进程真杀兜底，避免变孤儿

    stall_timeout = WATCH_V2_PROGRESS_STALL_TIMEOUT
    abs_timeout = WATCH_V2_PROCESSING_TIMEOUT  # 0 = 禁用绝对上限
    start_ts = time.time()
    last_progress_ts = start_ts
    killed = False

    # 心跳看门狗：替代旧的 proc.join(timeout=固定秒数) 硬杀。
    # 子进程在 _process_file 内逐页/逐嵌入写 _write_progress；父进程轮询 sidecar。
    while proc.is_alive():
        now = time.time()
        # 绝对上限：超长跑但始终在动的任务（如超大文件）的兜底熔断
        if abs_timeout > 0 and (now - start_ts) > abs_timeout:
            _kill_child(proc, filename)
            killed = True
            break
        # 读子进程心跳（绝对墙钟），更新「最近有进度」时间戳
        prog = _read_progress(filename)
        if prog and isinstance(prog.get("last_progress_ts"), (int, float)):
            last_progress_ts = float(prog["last_progress_ts"])
        # 停滞判定：太久没动静（卡死 / 死锁 / 无心跳）才强杀
        if (now - last_progress_ts) > stall_timeout:
            _kill_child(proc, filename)
            killed = True
            break
        time.sleep(2)  # 轮询间隔

    try:
        if killed:
            _unregister_child(proc)  # 已强杀，注销

            existing_state = _get_file_state(filename)
            existing_retry_count = existing_state.get("retry_count", 0) if existing_state else 0

            failure_result = _handle_failure(
                filepath, filename, "timeout",
                f"处理超时（心跳停滞 >{stall_timeout}s"
                + (f" 或 超过绝对上限 {abs_timeout}s" if abs_timeout > 0 else "")
                + "）",
                retry_count=existing_retry_count,
            )

            # 超时落盘 retry 状态再重入队（AI 设计决策，非用户指令）：
            # timeout 走 auto_retry 策略，_handle_failure 返回 "retry" 但不写状态，文件仍是 processing 幽灵态；
            # 主循环已跳过 processing，若不补写 retry 则重入队后永久被跳过、永不重试。
            # 同时累计重试次数，超过上限降级 needs_review，避免「永远超时→永远重入队」空转。
            if failure_result == "retry":
                new_retry = existing_retry_count + 1
                if new_retry > WATCH_V2_MAX_AUTO_RETRIES:
                    _append_state({
                        "file": filename,
                        "state": "needs_review",
                        "step": "timeout",
                        "error": f"处理超时重试 {new_retry} 次仍失败，转人工审核",
                        "retry_count": new_retry,
                        "failure_type": "timeout",
                    })
                    with _stats_lock: _watch_stats["needs_review"] += 1
                    log_activity(
                        action="watch_timeout_exhausted",
                        detail=f"超时重试耗尽，转人工审核: {filename}",
                        source=filename,
                    )
                else:
                    _append_state({
                        "file": filename,
                        "state": "retry",
                        "step": "timeout",
                        "error": f"处理超时（心跳停滞 >{stall_timeout}s），重入队重试 {new_retry}/{WATCH_V2_MAX_AUTO_RETRIES}",
                        "retry_count": new_retry,
                        "failure_type": "timeout",
                    })

            if failure_result in ("retry", "retry_later"):
                if _queue is not None:
                    try:
                        _queued_files.add(filepath)
                        _queue.put(filepath, timeout=WATCH_V2_QUEUE_PUT_TIMEOUT)
                    except Full:
                        log_activity(
                            action="watch_requeue_failed",
                            detail=f"超时后重新入队失败: {filename}",
                            source=filename,
                        )
            return

        # 子进程在看门狗超时前已自行结束（非我们强杀）
        _unregister_child(proc)  # 子进程已退出（正常或异常），注销
        if proc.exitcode not in (0, None):
            # 异常自死（如段错误）：避免文件卡在 processing 永不重试。
            # 仅当当前状态非终态时才补写 retry（尊重子进程已写的 done/failed/needs_review）。
            _state = _get_file_state(filename)
            if not _state or _state.get("state") not in ("done", "failed", "needs_review"):
                existing_retry_count = _state.get("retry_count", 0) if _state else 0
                new_retry = existing_retry_count + 1
                if new_retry > WATCH_V2_MAX_AUTO_RETRIES:
                    _append_state({
                        "file": filename,
                        "state": "needs_review",
                        "step": "crash",
                        "error": f"子进程异常退出(code={proc.exitcode})，重试 {new_retry} 次后转人工审核",
                        "retry_count": new_retry,
                        "failure_type": "timeout",
                    })
                    with _stats_lock: _watch_stats["needs_review"] += 1
                else:
                    _append_state({
                        "file": filename,
                        "state": "retry",
                        "step": "crash",
                        "error": f"子进程异常退出(code={proc.exitcode})，重入队重试 {new_retry}/{WATCH_V2_MAX_AUTO_RETRIES}",
                        "retry_count": new_retry,
                        "failure_type": "timeout",
                    })
                    if _queue is not None:
                        try:
                            _queued_files.add(filepath)
                            _queue.put(filepath, timeout=WATCH_V2_QUEUE_PUT_TIMEOUT)
                        except Full:
                            pass
    finally:
        _clear_progress(filename)  # 父进程负责清理 sidecar（成功/强杀皆清）


def _process_file_worker(filepath: str):
    """子进程入口：处理单个文件（无 cancel_event，超时由父进程强杀）。"""
    try:
        _process_file(filepath)
    except Exception as e:
        log_activity(
            action="watch_internal_error",
            detail=f"处理异常: {e}",
            source=os.path.basename(filepath),
        )
        failure_type = _classify_failure("unknown", str(e))
        _append_state({
            "file": os.path.basename(filepath),
            "state": "failed",
            "step": "unknown",
            "error": f"内部异常: {e}",
            "failure_type": failure_type,
        })
        with _stats_lock: _watch_stats["failed"] += 1


def _kill_child(proc, filename: str):
    """真杀子进程：先 terminate(SIGTERM)，超时未退则 kill(SIGKILL)。"""
    try:
        proc.terminate()
    except Exception:
        pass
    proc.join(timeout=3)
    if proc.is_alive():
        try:
            proc.kill()
        except Exception:
            pass
        proc.join(timeout=3)
    log_activity(
        action="watch_timeout_killed",
        detail=f"处理超时，已强杀子进程: {filename}",
        source=filename,
    )
