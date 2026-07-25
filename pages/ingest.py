"""
Citrinitas · 熔知 — 文档注入页面

此模块包含文档注入页面（/）的函数。
从 main.py 拆分出来以降低主文件复杂度。
"""

import os
import sys
import asyncio
import json
import uuid
from datetime import datetime, timezone

from nicegui import ui

import classify_pipeline
from classify_pipeline import route_by_confidence
import config.classifications as classifications
from field_cfg import FIELD_DISPLAY_CFG, SOURCE_ICON, PANEL_VALUES
from panel_funcs import build_result_panel, build_advanced_panel
from services.ingest_service import ingest
from text_pipeline import ocr_image
from utils.file_handler import (
    detect_file_type, extract_text, extract_auto_metadata,
    SIZE_LIMIT_MB, FORMAT_DISPLAY_NAMES,
)
from utils.state import STATE
from utils.ui_shared import build_left_drawer, refresh_system_state


@ui.page("/")
def page_ingest():
    """文档注入页面（/）—— 两阶段智能摄入：内容准备 → AI 分析 + 人工确认 → 入库"""

    build_left_drawer()

    with ui.column().classes("w-full p-6"):
        ui.markdown("# 📥 文档注入")
        ui.markdown("*两阶段智能摄入：内容准备 → AI 分析 + 人工确认 → 入库*")

        if not STATE["qdrant_online"]:
            ui.badge("⚠️ Qdrant 离线，无法摄入。请启动 Qdrant。", color="red")
            return

        # ── 阶段一：内容输入 ──
        tabs = ui.tabs().props("align=left")
        with tabs:
            upload_tab = ui.tab("📎 文件上传")
            manual_tab = ui.tab("✏️ 手动输入")
        tab_panels = ui.tab_panels(tabs, value=upload_tab).classes("w-full")

        content_text = ui.textarea(label="已提取的文本内容").props("outlined rows=10").classes("w-full")
        content_text_area = content_text
        source_label = ui.label("来源：--").classes("text-sm text-gray-500")

        ingest_content = ""
        ingest_source = ""
        ingest_method = ""
        ocr_temp_path = None   # 图片 OCR 的临时文件路径
        ocr_fname = None      # 图片文件名

        def _cleanup_ocr_temp():
            """页面关闭时清理可能遗留的图片 OCR 临时文件。"""
            if ocr_temp_path and os.path.exists(ocr_temp_path):
                try:
                    os.unlink(ocr_temp_path)
                except OSError:
                    pass
        ui.context.client.on_disconnect(_cleanup_ocr_temp)

        # ── Tab 1: 文件上传 ──
        with tab_panels:
            with ui.tab_panel(upload_tab):
                # 动态生成支持格式列表（从 FORMAT_DISPLAY_NAMES）
                text_formats = [k for k in FORMAT_DISPLAY_NAMES if k not in ("jpeg","png","tiff","bmp","webp")]
                img_formats = [k for k in FORMAT_DISPLAY_NAMES if k in ("jpeg","png","tiff","bmp","webp")]
                fmt_parts = [f"**{f}** ({FORMAT_DISPLAY_NAMES[f]})" for f in text_formats]
                img_parts = [f"**{f}** ({FORMAT_DISPLAY_NAMES[f]})" for f in img_formats]
                ui.markdown(f"📄 文本格式：{' · '.join(fmt_parts)}").classes("text-sm text-gray-500")
                ui.markdown(f"🖼️ 图片格式（OCR）：{' · '.join(img_parts)}").classes("text-sm text-gray-400")
                upload = ui.upload(
                    label="拖拽或点击上传文件（支持多选）",
                    auto_upload=True,
                    max_file_size=SIZE_LIMIT_MB * 1024 * 1024,
                    multiple=True,
                ).classes("w-full").props("accept='.txt,.md,.json,.csv,.pdf,.epub,.html,.htm,.srt,.docx,.pptx,.png,.jpg,.jpeg,.bmp,.webp,.tiff'")

                up_result = ui.label("").classes("text-sm")
                batch_result_panel = ui.column().classes("w-full mt-2 gap-1")
                batch_summary = ui.label("").classes("text-sm font-bold mt-2")
                ocr_btn_container = ui.row().classes("w-full gap-2 mt-1")

                async def on_ocr_start():
                    """「开始识别」按钮回调：执行 OCR 并填结果到编辑区"""
                    nonlocal ocr_temp_path, ocr_fname, ingest_content, ingest_source, ingest_method
                    if not ocr_temp_path or not os.path.exists(ocr_temp_path):
                        ui.notify("⚠️ 没有待识别的图片，请重新上传", type="warning")
                        ocr_btn_container.clear()
                        return
                    up_result.set_text(f"🔍 {ocr_fname} · OCR 识别中...")
                    ocr_btn_container.clear()
                    with ocr_btn_container:
                        ui.label("⏳ 识别中...").classes("text-sm text-blue-500")
                    tmp = ocr_temp_path
                    fname = ocr_fname
                    ocr_temp_path = None
                    ocr_fname = None
                    ocr_btn_container.clear()
                    try:
                        ocr_result = await asyncio.to_thread(ocr_image, tmp)
                        if ocr_result.get("ok"):
                            text = ocr_result.get("ocr_text", "")
                            char_count = len(text)
                            up_result.set_text(f"✅ {fname} · OCR 识别完成，{char_count} 字")
                            if ocr_result.get("needs_correction"):
                                ui.notify("⚠️ 图片识别质量较低，建议人工核对", type="warning")
                            ingest_method = "ocr"
                            STATE["ingest_method"] = "ocr"
                            STATE["source_path"] = f"ocr:{fname}"
                            ingest_content = text
                            content_text.set_value(text)
                            ingest_source = f"OCR: {fname}"
                            source_label.set_text(f"来源：{fname}（OCR）")
                            STATE["ingest_content"] = text
                            confirm_label.set_text(f"✅ {fname} · OCR 完成 · 请确认内容")
                        else:
                            error_msg = ocr_result.get("error", "未知错误")
                            ui.notify(f"❌ OCR 识别失败: {error_msg}", type="negative")
                            up_result.set_text(f"❌ {fname} · OCR 失败: {error_msg}")
                    except Exception as ex:
                        ui.notify(f"❌ OCR 异常: {ex}", type="negative")
                        up_result.set_text(f"❌ OCR 异常: {ex}")
                    finally:
                        if tmp and os.path.exists(tmp):
                            try:
                                os.unlink(tmp)
                            except OSError:
                                pass

                async def on_upload(e):
                    nonlocal ingest_content, ingest_source, ingest_method, ocr_temp_path, ocr_fname
                    temp_path = None
                    try:
                        import tempfile
                        file_bytes = await e.file.read()
                        fname = e.file.name
                        fsize = len(file_bytes)
                        if fsize > SIZE_LIMIT_MB * 1024 * 1024:
                            ui.notify(f"⚠️ 文件 {fname} 超过 {SIZE_LIMIT_MB}MB 上限", type="warning")
                            return

                        # 保存到临时文件
                        suffix = os.path.splitext(fname)[1] or ".tmp"
                        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix, mode="wb") as tf:
                            tf.write(file_bytes)
                            temp_path = tf.name

                        # 检测文件类型（轻量操作，同步执行）
                        file_type = detect_file_type(temp_path)
                        STATE["file_info"] = file_type
                        ext_label = ".".join(file_type.get("extensions", ["?"]))

                        up_result.set_text(f"📎 {fname} · {fsize/1024:.1f}KB · {ext_label} · {file_type.get('format_name', '?')}")

                        # 格式识别预览（显示层级 + 元数据能力）
                        tier = file_type.get("tier", "?")
                        tier_name = file_type.get("tier_name", "")
                        has_meta = file_type.get("has_auto_metadata", False)
                        tier_badge = {1: "green", 2: "blue", 3: "orange", 4: "gray"}.get(tier, "gray")
                        meta_badge = "✅ 自带元数据" if has_meta else "🤖 需 AI 标注"
                        ui.badge(f"T{tier}: {tier_name}", color=tier_badge)
                        ui.badge(meta_badge, color="teal" if has_meta else "blue")

                        # 提取文本（后台线程执行，避免阻塞事件循环）
                        extract_result = await asyncio.to_thread(extract_text, temp_path)
                        is_ocr = isinstance(extract_result, dict) and extract_result.get("ocr_required")

                        if is_ocr:
                            # 图片文件：保存路径，显示「开始识别」按钮，不自动 OCR
                            # 若之前有未清理的图片临时文件，先删掉，避免泄漏
                            if ocr_temp_path and os.path.exists(ocr_temp_path):
                                try:
                                    os.unlink(ocr_temp_path)
                                except OSError:
                                    pass
                            ocr_temp_path = temp_path
                            ocr_fname = fname
                            temp_path = None  # 防止 finally 删除临时文件
                            up_result.set_text(f"🖼️ {fname} · {fsize/1024:.1f}KB · 上传完成，点击「开始识别」")
                            ocr_btn_container.clear()
                            with ocr_btn_container:
                                ui.button("🚀 开始识别", on_click=on_ocr_start, color="blue")
                            return
                        else:
                            _fm = {}
                            if isinstance(extract_result, dict):
                                text = extract_result.get("text", "")
                            else:
                                text = str(extract_result)
                            # 解析 Markdown frontmatter（标题/作者等），剥除正文元数据噪音行
                            from text_pipeline import parse_frontmatter
                            text, _fm = parse_frontmatter(text)
                            if len(text) > 5000:
                                ui.notify(
                                    f"文本较长 ({len(text)} 字)，AI 分类仅取前 5000 字分析，但全文会完整入库",
                                    type="info",
                                )

                        # 提取自动元数据（后台线程执行）
                        auto_meta_result = await asyncio.to_thread(extract_auto_metadata, temp_path, file_type)
                        auto_meta = auto_meta_result.get("flat", {}) if isinstance(auto_meta_result, dict) else {}
                        STATE["auto_metadata"] = auto_meta

                        # 将 frontmatter 的标题/作者并入文件元数据（file 来源，最高优先级，抑制 LLM 漂移）
                        if _fm:
                            if _fm.get("title"):
                                auto_meta["title"] = _fm["title"]
                            if _fm.get("up_name"):
                                auto_meta["author"] = _fm["up_name"]
                            if _fm.get("source_url"):
                                auto_meta["source_url"] = _fm["source_url"]
                            STATE["auto_metadata"] = auto_meta

                        # ═══ 批量自动摄入（v0.9.0 D5） ═══
                        # 直接走全管道：分类 → 置信度检查 → 入库/待审核/死信
                        try:
                            # 1. 分类
                            cls_result = await asyncio.to_thread(
                                classify_pipeline.classify_document,
                                text, auto_meta, STATE.get("current_project", "通用"),
                            )
                            if cls_result and cls_result.get("ok"):
                                annotated = cls_result.get("annotated", {})
                                classification = cls_result.get("classification", {})
                                field_sources = dict(annotated.get("field_sources", {}))
                                overall_conf = annotated.get("overall_confidence", 0.0)
                            else:
                                classification = {"content_type": "other"}
                                field_sources = {}
                                overall_conf = 0.0

                            # 2. 置信度阈值检查（从 pipe_cfg.yaml 读取）
                            from config.settings import CONFIDENCE_LOW, CONFIDENCE_HIGH
                            conf_low = CONFIDENCE_LOW
                            conf_high = CONFIDENCE_HIGH

                            if overall_conf < conf_low:
                                # 死信
                                dlq_entry = {
                                    "timestamp": datetime.now(timezone.utc).isoformat(),
                                "ingest_conf": overall_conf,
                                "reason": f"入库置信度 {overall_conf:.0%} < {conf_low:.0%}",
                                    "content": text[:500],
                                    "metadata": {**auto_meta, **classification},
                                    "source": fname,
                                }
                                dlq_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "local_data", "dead_letter")
                                os.makedirs(dlq_dir, exist_ok=True)
                                dlq_fp = os.path.join(dlq_dir, f"dlq_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}_{fname}.json")
                                with open(dlq_fp, "w", encoding="utf-8") as df:
                                    json.dump(dlq_entry, df, ensure_ascii=False)
                                with batch_result_panel:
                                    with ui.card().classes("w-full p-2"):
                                        ui.label(f"🗑️ {fname}").classes("text-sm font-bold")
                                        ui.badge("死信", color="red").classes("text-xs")
                                        ui.label(f"置信度 {overall_conf:.0%} < {conf_low:.0%}，已入死信队列").classes("text-xs text-gray-500")
                            else:
                                # 入库
                                needs_review = overall_conf < conf_high
                                ingest_result = await asyncio.to_thread(
                                    ingest,
                                    text=text,
                                    metadata={
                                        **classification,
                                        "source_path": fname,
                                        "ingest_method": "upload",
                                        "needs_review": needs_review,
                                    },
                                    collection=STATE["active_collection"],
                                    field_sources=field_sources,
                                    overall_confidence=overall_conf,
                                )
                                if ingest_result.get("ok"):
                                    with batch_result_panel:
                                        with ui.card().classes("w-full p-2"):
                                            with ui.row().classes("items-center gap-2"):
                                                ui.label(f"✅ {fname}").classes("text-sm font-bold text-green-400")
                                                if needs_review:
                                                    ui.badge("待审核", color="orange").classes("text-xs")
                                                ui.label(f"置信度 {overall_conf:.0%}").classes("text-xs text-gray-500")
                                            ui.label(f"分类: {classification.get('content_type', '?')} | 领域: {', '.join(classification.get('domain', []))}").classes("text-xs text-gray-400")
                                    # 检查钩子失败
                                    hook_failures = ingest_result.get("hook_failures", [])
                                    if hook_failures:
                                        msg = "⚠️ 外部钩子执行失败：" + "；".join(hook_failures)
                                        ui.notify(msg, type="warning", multi_line=True)
                                else:
                                    with batch_result_panel:
                                        with ui.card().classes("w-full p-2"):
                                            ui.label(f"❌ {fname}").classes("text-sm font-bold text-red-400")
                                            ui.label(f"入库失败: {ingest_result.get('error', '?')}").classes("text-xs text-gray-500")
                        except Exception as batch_ex:
                            with batch_result_panel:
                                with ui.card().classes("w-full p-2"):
                                    ui.label(f"❌ {fname}").classes("text-sm font-bold text-red-400")
                                    ui.label(f"处理异常: {batch_ex}").classes("text-xs text-gray-500")

                        # 保留单文件模式兼容（填充到编辑区供手动修改后重新摄入）
                        ingest_content = text
                        content_text.set_value(text)
                        ingest_source = f"文件: {fname}"
                        source_label.set_text(f"来源：{fname}")
                        STATE["ingest_content"] = text
                        STATE["ingest_source"] = fname

                        # 显示自动元数据
                        if auto_meta:
                            meta_lines = [f"📎 **{k}**: {v}" for k, v in auto_meta.items() if v]
                            if meta_lines:
                                ui.notify("文件元数据已自动提取", type="positive")

                    except Exception as ex:
                        ui.notify(f"❌ 处理失败: {ex}", type="negative")
                    finally:
                        if temp_path and os.path.exists(temp_path):
                            try:
                                os.unlink(temp_path)
                            except OSError:
                                pass

                upload.on_upload(on_upload)

        # ── Tab 2: 手动输入 ──
        with tab_panels:
            with ui.tab_panel(manual_tab):
                manual_text = ui.textarea(
                    label="粘贴或输入文本",
                    placeholder="直接粘贴内容...",
                ).props("outlined rows=12").classes("w-full")

                def on_manual_fill():
                    txt = manual_text.value or ""
                    if not txt.strip():
                        ui.notify("⚠️ 请先输入内容", type="warning")
                        return
                    # 填入共享编辑区
                    content_text.set_value(txt)
                    source_label.set_text("来源：手动输入")
                    STATE["source_path"] = ""
                    confirm_label.set_text(f"📝 手动输入 · {len(txt)} 字 · 点击下方「确认内容」")
                    confirm_label.classes("text-sm text-blue-500")
                    # T10: 5000 字截断提醒
                    if len(txt) > 5000:
                        ui.notify(f"⚠️ 内容超过 5000 字（{len(txt)} 字），AI 分析将仅使用前 5000 字", type="warning")

                ui.button("📋 填入编辑区", on_click=on_manual_fill, color="blue")

        # ── 确认按钮（共享，两 Tab 外）──
        confirm_row = ui.row().classes("w-full items-center gap-4 mt-2")
        with confirm_row:
            def on_confirm():
                nonlocal ingest_content, ingest_source, ingest_method
                txt = content_text.value or ""
                if not txt.strip():
                    ui.notify("⚠️ 请先输入或上传内容", type="warning")
                    return
                ingest_content = txt
                STATE["ingest_content"] = txt
                # 如果已通过文件上传或手动填入设置了来源，保留；否则默认手动输入
                if not ingest_source:
                    ingest_source = "手动输入"
                    ingest_method = "manual"
                    STATE["ingest_source"] = "手动输入"
                    STATE["ingest_method"] = "manual"
                    STATE["source_path"] = ""
                confirm_label.set_text("✅ 内容已确认")
                confirm_label.classes("text-sm text-green-600")
            ui.button("📥 确认内容", on_click=on_confirm, color="blue")
            confirm_label = ui.label("").classes("text-sm text-gray-400")

        ui.separator()

        # ── 阶段二：AI 分类 + 确认 ──
        ui.markdown("## 阶段二：AI 分析与元数据")
        ui.markdown("*AI 自动推断分类和标签，请确认后摄入。*")

        ai_cols = ui.row().classes("w-full gap-4")
        with ai_cols:
            ai_btn = ui.button("🤖 AI 分析", color="teal")
            ai_status = ui.label("等待分析...").classes("text-sm text-gray-500")

        # 结果面板区（AI 分析后渲染卡片式面板）
        result_container = ui.column().classes("w-full")
        advanced_container = ui.column().classes("w-full")

        ui.separator()

        # ── 强制重录开关（#27：忽略重复检测并覆盖已有相同内容）──
        force_checkbox = ui.checkbox(
            "♻️ 强制重录（忽略重复检测，覆盖已存在的相同内容）"
        ).classes("mt-2 text-sm")

        # ── 摄入按钮 ──
        async def do_ingest():
            nonlocal ingest_content, ingest_method, ingest_source
            if not STATE["qdrant_online"]:
                ui.notify("⚠️ Qdrant 离线", type="negative")
                return
            if not ingest_content.strip():
                ui.notify("⚠️ 没有内容可摄入", type="negative")
                return

            # 从 PANEL_VALUES 读取当前值（用户可能已编辑）
            metadata = dict(PANEL_VALUES)

            # 补充系统字段
            metadata["source_path"] = STATE.get("source_path", "")
            metadata["ingest_method"] = ingest_method or "manual"
            _meta_source_map = {"upload": "file", "ocr": "ocr", "manual": "manual"}
            metadata["metadata_source"] = _meta_source_map.get(ingest_method, "manual")

            # 获取 AI 分析结果
            classify_result = STATE.get("classify_result")
            if classify_result and classify_result.get("ok"):
                annotated = classify_result.get("annotated", {})
                classification = classify_result.get("classification", {})
                field_sources = dict(annotated.get("field_sources", {}))
                overall_conf = annotated.get("overall_confidence", 0.0)

                # 检测用户修改：对比 PANEL_VALUES 与原始 classification
                for field in FIELD_DISPLAY_CFG:
                    panel_val = PANEL_VALUES.get(field)
                    orig_val = classification.get(field)
                    if isinstance(orig_val, list) and isinstance(panel_val, list):
                        if set(orig_val) != set(panel_val):
                            field_sources[field] = "user"
                    elif panel_val != orig_val:
                        field_sources[field] = "user"
            else:
                field_sources = {f: "user" for f in FIELD_DISPLAY_CFG}
                overall_conf = 0.0
                ui.notify("⚠️ 未执行 AI 分析，将使用当前值直接摄入", type="warning")

            # 置信度路由（三档，阈值从 pipe_cfg.yaml 读取）
            _conf_low = CONFIDENCE_LOW
            _conf_high = CONFIDENCE_HIGH
            needs_review, dlq = route_by_confidence(overall_conf, _conf_low, _conf_high)

            if dlq:
                import time
                PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                dlq_dir = os.path.join(PROJECT_DIR, "local_data", "dead_letter")
                os.makedirs(dlq_dir, exist_ok=True)
                dlq_file = os.path.join(dlq_dir, f"{int(time.time()*1000)}_{uuid.uuid4().hex[:8]}.json")
                dlq_data = {
                    "content": ingest_content[:3000],
                    "metadata": metadata,
                    "ingest_conf": overall_conf,
                    "field_sources": field_sources,
                    "reason": f"入库置信度过低（{overall_conf:.2f} < {_conf_low:.2f}），需人工审核",
                    "ingested_at": datetime.now(timezone.utc).isoformat(),
                }
                with open(dlq_file, "w", encoding="utf-8") as f:
                    json.dump(dlq_data, f, ensure_ascii=False, indent=2)
                ui.notify(
                    f"✋ 入库置信度过低（{overall_conf:.0%}），已放入死信队列待审核",
                    type="warning",
                )
                return

            if needs_review:
                metadata["needs_review"] = True

            try:
                result = await asyncio.to_thread(
                    ingest,
                    text=ingest_content,
                    metadata=metadata,
                    collection=STATE["active_collection"],
                    field_sources=field_sources,
                    overall_confidence=overall_conf,
                    force_reingest=bool(force_checkbox.value),
                )
                if result.get("ok"):
                    ui.notify(f"✅ 摄入成功！({result.get('chunks', '?')} 块, 置信度 {overall_conf:.0%})", type="positive")
                    # 检查钩子失败
                    hook_failures = result.get("hook_failures", [])
                    if hook_failures:
                        msg = "⚠️ 外部钩子执行失败：" + "；".join(hook_failures)
                        ui.notify(msg, type="warning", multi_line=True)
                    # 重置表单
                    ingest_content = ""
                    content_text.set_value("")
                    source_label.set_text("来源：--")
                    STATE["source_path"] = ""
                    STATE.pop("classify_result", None)
                    PANEL_VALUES.clear()
                    result_container.clear()
                    advanced_container.clear()
                    await asyncio.to_thread(refresh_system_state)
                else:
                    ui.notify(f"❌ 摄入失败: {result.get('error', '?')}", type="negative")
            except Exception as ex:
                ui.notify(f"❌ 异常: {ex}", type="negative")

        ui.button("🚀 摄入到知识库", on_click=do_ingest).props("color=green size=lg").classes("w-full mt-2")

        # ── AI 分析回调（阶段二：调用 classify_document 三层管道）──
        async def do_ai_analyze():
            nonlocal ingest_content
            if not ingest_content.strip():
                ui.notify("⚠️ 请先输入内容", type="warning")
                return

            ai_status.set_text("正在分析...")
            ai_btn.disable()
            try:
                # 传入文件元数据（classification 不再携带 project_source，溯源改由 hook 写 source_project）
                result = await asyncio.to_thread(
                    classify_pipeline.classify_document,
                    ingest_content,
                    STATE.get("auto_metadata") if isinstance(STATE.get("auto_metadata"), dict) else None,
                )
                if result and result.get("ok"):
                    cls = result.get("classification", {})
                    annotated = result.get("annotated", {})
                    STATE["classify_result"] = result
                    overall = annotated.get("overall_confidence", 0.0)
                    sources = annotated.get("field_sources", {})

                    # 填充 PANEL_VALUES（全局缓存，供面板和摄入使用）
                    PANEL_VALUES.clear()
                    for field in FIELD_DISPLAY_CFG:
                        PANEL_VALUES[field] = cls.get(field)

                    # 渲染卡片式结果面板
                    build_result_panel(annotated, cls, result_container)
                    build_advanced_panel(annotated, cls, advanced_container)

                    ai_status.set_text(f"✅ 分析完成（置信度 {overall:.0%}）")
                    ui.notify("AI 分析结果已渲染为卡片面板，可直接修改", type="positive")
                else:
                    ai_status.set_text("⚠️ 分析返回为空，将使用默认值摄入")
            except Exception as ex:
                ai_status.set_text(f"❌ 分析失败: {ex}")
                ui.notify(f"AI 分析失败: {ex}", type="negative")
            finally:
                ai_btn.enable()

        ai_btn.on_click(do_ai_analyze)
