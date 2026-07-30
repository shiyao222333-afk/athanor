"""
文档详情页 — /doc/{id} 独立页面。
"""

import asyncio
from datetime import datetime, timezone
from nicegui import ui
import kb_query
from utils.state import STATE
from utils.ui_shared import build_left_drawer
from utils.activity_log import log_activity
# ═══════════════════════════════════════════

@ui.page("/doc/{doc_id}")
def page_doc_detail(doc_id: str):
    """文档详情页 — 28 字段完整展示 + 分块列表 + 来源追踪。"""

    build_left_drawer(active_page="hub")

    with ui.column().classes("w-full p-6"):
        # 返回按钮
        with ui.row().classes("w-full items-center gap-2 mb-4"):
            ui.link("← 返回知识库管理", "/hub").classes("text-sm text-gray-400 no-underline")

        if not STATE["qdrant_online"]:
            ui.badge("⚠️ Qdrant 离线", color="red")
            return

        # 加载文档元数据与分块（单次查询）
        collection = STATE["active_collection"]
        chunk_result = kb_query.get_document(doc_id, collection=collection)
        chunks = chunk_result.get("chunks", []) if chunk_result.get("ok") else []
        doc_meta = chunk_result.get("metadata", {}) if chunk_result.get("ok") else {}

        if not doc_meta:
            ui.markdown("### 📄 文档不存在")
            ui.label(f"未找到 doc_id={doc_id} 的记录，可能已被删除。").classes("text-gray-500")
            return

        # ════════════════════
        # 标题区
        # ════════════════════
        title = doc_meta.get("title") or doc_meta.get("source") or "未知"
        ui.markdown(f"# 📄 {title}")
        if doc_meta.get("needs_review"):
            ui.badge("⚠️ 待审核", color="orange").classes("mb-2")

        # ════════════════════
        # 元数据卡片
        # ════════════════════
        ui.markdown("### 📋 元数据")
        with ui.card().classes("w-full p-4"):
            # 分组1: 分面
            with ui.row().classes("w-full gap-4 mb-3"):
                ui.markdown("#### 🏷️ 分面分类")
            with ui.row().classes("w-full gap-4 text-sm"):
                ui.label(f"**内容类型**: {doc_meta.get('content_type', 'N/A')}")
                ui.label(f"**领域**: {', '.join(doc_meta.get('domain', [])) or 'N/A'}")
                ui.label(f"**时效属性**: {doc_meta.get('temporal_nature', 'N/A')}")
                ui.label(f"**认知状态**: {doc_meta.get('epistemic_status', 'N/A')}")

            ui.separator()

            # 分组2: 内容
            with ui.row().classes("w-full gap-4 mb-3"):
                ui.markdown("#### 📝 内容信息")
            with ui.row().classes("w-full gap-4 text-sm"):
                ui.label(f"**来源**: {doc_meta.get('source', 'N/A')}")
                ui.label(f"**源路径**: {doc_meta.get('source_path', 'N/A')}")
                ui.label(f"**语言**: {doc_meta.get('language', 'N/A')}")
                ui.label(f"**分块数**: {len(chunks)}")

            ui.separator()

            # 分组3: 知识管理
            with ui.row().classes("w-full gap-4 mb-3"):
                ui.markdown("#### ⚙️ 知识管理")
            with ui.row().classes("w-full gap-4 text-sm"):
                ui.label(f"**入库置信度**: {doc_meta.get('ingest_conf', 0):.0%}")
                ui.label(f"**信任分**: {doc_meta.get('trust_score', 3)}/5")
                ui.label(f"**个人知识**: {'是' if doc_meta.get('is_personal') else '否'}")
                ui.label(f"**待审核**: {'是' if doc_meta.get('needs_review') else '否'}")

            ui.separator()

            # 分组4: 时间
            with ui.row().classes("w-full gap-4 mb-3"):
                ui.markdown("#### 🕐 时间")
            with ui.row().classes("w-full gap-4 text-sm"):
                ui.label(f"**创建时间**: {doc_meta.get('created_at', 'N/A')[:19]}")

        # ════════════════════
        # 分块内容
        # ════════════════════
        if chunks:
            ui.markdown("### 📦 分块内容")
            with ui.card().classes("w-full p-4"):
                for c in chunks:
                    chunk_text = c.get("text", "")
                    chunk_idx = c.get("chunk_index", 0)
                    chunk_title = c.get("title", "") or f"分块 {chunk_idx}"
                    # 默认全部展开，且显示完整内容（不再截断、不再需手动点开）
                    with ui.expansion(f"#{chunk_idx} {chunk_title[:60]}", value=True).classes("w-full"):
                        ui.markdown(f"```\n{chunk_text}\n```")

        # ════════════════════
        # 操作区
        # ════════════════════
        ui.separator()
        with ui.row().classes("gap-2"):
            async def _delete_this():
                try:
                    result = await asyncio.to_thread(
                        kb_query.delete_document,
                        doc_id,
                        collection=collection,
                    )
                    if result.get("ok"):
                        log_activity("delete", doc_id, title, collection)
                        ui.notify("✅ 已删除", type="positive")
                        ui.run_javascript("window.location.href='/hub'")
                    else:
                        ui.notify(f"删除失败: {result.get('error', '?')}", type="negative")
                except Exception as ex:
                    ui.notify(f"操作异常: {ex}", type="negative")

            del_dialog = ui.dialog().props("persistent")
            with del_dialog:
                with ui.card().classes("p-4"):
                    ui.label("⚠️ 确认删除此文档？").classes("text-lg font-bold")
                    ui.label("所有分块将被永久删除，此操作不可撤销。").classes("text-sm text-gray-500")
                    with ui.row().classes("gap-2 mt-4"):
                        ui.button("取消", on_click=del_dialog.close).props("flat")

                        async def _confirm_delete():
                            await _delete_this()
                            del_dialog.close()
                        ui.button("确认删除", on_click=_confirm_delete).props("color=red")

            ui.button("🗑️ 删除此文档", on_click=del_dialog.open).props("color=red flat")
