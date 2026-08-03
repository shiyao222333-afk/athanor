"""
Citrinitas · 熔知 — 智能检索页面

此模块包含智能检索页面（/search）的函数。
从 main.py 拆分出来以降低主文件复杂度。
"""

import os
import asyncio

from nicegui import ui

import kb_query
from utils.ui_shared import render_chunk_card, refresh_system_state
from utils.state import STATE
from utils.ui_shared import build_left_drawer
from search_engine import search, answer, OUTPUT_DIR

@ui.page("/search")
def page_search():
    """智能检索页面（/search）—— 语义搜索 + AI 问答"""

    build_left_drawer(active_page="search")

    with ui.column().classes("w-full p-6"):
        ui.markdown("# 💬 智能检索")
        ui.markdown("*语义搜索 + AI 问答：输入问题，勾选选项控制搜索行为。*")

        if not STATE["qdrant_online"]:
            ui.badge("⚠️ Qdrant 离线，无法搜索。", color="red")
            return

        # 搜索范围
        with ui.row().classes("w-full gap-4 items-end"):
            search_col = ui.select(
                label="📚 搜索范围",
                options=STATE["collections"] if STATE["collections"] else [STATE["active_collection"]],
                value=STATE["active_collection"],
            ).classes("w-64")

        # 搜索栏
        with ui.row().classes("w-full gap-2 items-end mt-4"):
            query_input = ui.input(
                label="输入问题或关键词",
                placeholder="例如：齿轮的失效形式有哪些？",
            ).classes("flex-1")

            top_k = ui.number(label="Top K", value=10, min=1, max=20, step=1).classes("w-20")
            use_llm = ui.switch("使用 AI 回答", value=True)

        search_btn = ui.button("🔍 搜索").props("color=blue size=lg")
        results_area = ui.column().classes("w-full mt-6")

        async def do_search():
            results_area.clear()
            query = (query_input.value or "").strip()
            if not query:
                ui.notify("请输入搜索内容", type="warning")
                return

            try:
                if use_llm.value:
                    # 先搜索（较快），显示中间状态
                    with results_area:
                        ui.spinner(size="lg")
                        ui.label("🔍 正在搜索相关文档...").classes("text-sm text-gray-400")

                    search_result = await asyncio.to_thread(
                        search,
                        query,
                        top_k.value,
                        search_col.value,
                        exclude_archived=True,   # UI 搜索默认排除已归档内容
                    )

                    # 再调用 LLM 合成答案（可能较慢）
                    with results_area:
                        results_area.clear()
                        ui.spinner(size="lg")
                        ui.label("🤖 正在调用 AI 合成答案（首次加载模型约需30秒）...").classes("text-sm text-gray-400")

                    result = await asyncio.to_thread(
                        answer,
                        query,
                        top_k.value,
                        search_col.value,
                        output_dir=OUTPUT_DIR,
                        exclude_archived=True,   # AI 回答同样默认排除已归档内容
                    )

                    with results_area:
                        results_area.clear()
                        if result.get("ok"):
                            ui.markdown("### 🤖 AI 回答")
                            answer_text = result.get("synthesis", "无回答")
                            ui.markdown(answer_text)

                            # HTML 报告链接
                            html_path = result.get("html")
                            if html_path and os.path.exists(html_path):
                                with ui.card().classes("w-full bg-blue-50"):
                                    ui.markdown("#### 📄 完整报告已生成")
                                    ui.label(f"文件: {os.path.basename(html_path)}").classes("text-xs text-gray-500")
                                    ui.button("🌐 在浏览器打开", on_click=lambda p=os.path.basename(html_path): ui.run_javascript(f'window.open("/reports/{p}", "_blank")')).props("dense flat color=blue")

                            chunks = result.get("chunks", [])
                            if chunks:
                                ui.separator()
                                ui.markdown("### 📚 来源引用")
                                for i, c in enumerate(chunks):
                                    render_chunk_card(c, i+1)
                        else:
                            # LLM 不可用，回退显示搜索结果
                            error_msg = result.get("error", "")
                            if "LLM API" in error_msg or "未配置" in error_msg:
                                ui.notify("💡 LLM 未配置，已回退为纯搜索模式。在配置页设置 API Key 后可启用 AI 回答。", type="info")
                            else:
                                ui.notify(f"AI 回答失败: {error_msg}", type="warning")

                            # 回退显示搜索结果
                            ui.markdown("### 🔍 搜索结果（AI 未启用）")
                            sr = search_result
                            for i, c in enumerate(sr.get("chunks", [])):
                                render_chunk_card(c, i+1)

                    STATE["last_answer"] = result
                else:
                    with results_area:
                        ui.spinner(size="lg").classes("self-center")
                        ui.label("🔍 正在搜索...").classes("text-sm text-gray-400")
                        await asyncio.sleep(0.1)

                    result = await asyncio.to_thread(
                        search,
                        query,
                        top_k.value,
                        search_col.value,
                        exclude_archived=True,   # 普通搜索同样默认排除已归档
                    )
                    with results_area:
                        results_area.clear()
                        ui.markdown("### 🔍 搜索结果")
                        for i, c in enumerate(result.get("chunks", [])):
                            render_chunk_card(c, i+1)
                    STATE["last_search"] = result

                # ── 相关灵感浮现：用同样的问题搜 idea 类型，取 3 条 ──
                try:
                    idea_result = await asyncio.to_thread(
                        search, query, 3, search_col.value,
                        None, None,                    # score_threshold, model 用默认
                        {"content_type": ["idea"]},    # facet_filter 只看想法/灵感
                        True,                          # exclude_archived 排除已归档
                    )
                    if idea_result.get("ok") and idea_result.get("chunks"):
                        with results_area:
                            ui.separator()
                            ui.markdown("### 💡 相关灵感")
                            ui.markdown("*你之前记下的相关灵感*").classes("text-xs text-gray-400")
                            for i, c in enumerate(idea_result["chunks"]):
                                render_chunk_card(c, i+1)
                except Exception:
                    pass  # 灵感查询失败静默跳过，不影响主搜索

                await asyncio.to_thread(refresh_system_state)
            except Exception as ex:
                with results_area:
                    results_area.clear()
                    ui.notify(f"搜索失败: {ex}", type="negative")

        search_btn.on_click(do_search)
