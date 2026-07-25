"""
文档注入 — 卡片式结果面板函数。
由 main.py 通过 `from panel_funcs import *` 导入。
"""

from nicegui import ui
from field_cfg import FIELD_DISPLAY_CFG, SOURCE_ICON, PANEL_VALUES
from classify_pipeline import REQUIRED_FACET_FIELDS

# 全局：当前 AI 分析结果 + 容器引用（供编辑后刷新用）
_CURRENT_ANNOTATED = None
_CURRENT_CLASSIFICATION = None
_RESULT_CONTAINER = None
_ADVANCED_CONTAINER = None


def _format_field_value(field_name: str, val, cfg: dict) -> str:
    """格式化字段值为 HTML 显示字符串。"""
    if val is None or val == "":
        return '<span class="text-gray-400">未设置</span>'
    display_map = cfg.get("display_map", {})
    if isinstance(val, list):
        parts = [display_map.get(v, v) for v in val]
        return "  ".join(str(p) for p in parts)
    return display_map.get(val, str(val))


def _compute_source(field_name: str):
    """
    计算字段当前来源：
    - 如果 PANEL_VALUES[field_name] == 原始 classification[field_name] → 用原始来源
    - 否则 → "user"
    """
    if not _CURRENT_ANNOTATED or not _CURRENT_CLASSIFICATION:
        return "user"
    orig_val = _CURRENT_CLASSIFICATION.get(field_name)
    panel_val = PANEL_VALUES.get(field_name)
    if isinstance(orig_val, list) and isinstance(panel_val, list):
        if set(orig_val) == set(panel_val):
            return _CURRENT_ANNOTATED.get("field_sources", {}).get(field_name, "default")
    elif panel_val == orig_val:
        return _CURRENT_ANNOTATED.get("field_sources", {}).get(field_name, "default")
    return "user"


def _refresh_panels():
    """编辑字段后刷新两个面板（用全局缓存的 annotated/classification 重新渲染）。"""
    if _CURRENT_ANNOTATED and _CURRENT_CLASSIFICATION:
        if _RESULT_CONTAINER:
            build_result_panel(_CURRENT_ANNOTATED, _CURRENT_CLASSIFICATION, _RESULT_CONTAINER)
        if _ADVANCED_CONTAINER:
            build_advanced_panel(_CURRENT_ANNOTATED, _CURRENT_CLASSIFICATION, _ADVANCED_CONTAINER)


def _render_field_card(field_name: str, container):
    """渲染单个字段的卡片行（点击 → 弹出编辑对话框）。"""
    cfg = FIELD_DISPLAY_CFG.get(field_name, {})
    if not cfg:
        return

    # 当前值：优先 PANEL_VALUES，兜底 classification
    val = PANEL_VALUES.get(field_name)
    if val is None and _CURRENT_CLASSIFICATION:
        val = _CURRENT_CLASSIFICATION.get(field_name)

    # 来源图标
    src = _compute_source(field_name)
    icon = SOURCE_ICON.get(src, "⚙️")

    # 置信度
    conf = 0.0
    if _CURRENT_ANNOTATED:
        fd = _CURRENT_ANNOTATED.get(field_name)
        if fd and isinstance(fd, dict):
            conf = fd.get("confidence", 0.0)

    with container:
        with ui.card().classes("w-full p-2 mb-1 cursor-pointer hover:bg-gray-100").style("border-left: 3px solid #e5e7eb") as card:
            # 点击卡片 → 弹出编辑对话框（用 default 参数固化闭包值）
            card.on("click", lambda _, fn=field_name: edit_field_dialog(fn))

            with ui.row().classes("w-full items-center gap-2"):
                ui.label(cfg.get("zh", field_name)).classes("text-sm font-bold w-20")
                display_val = _format_field_value(field_name, val, cfg)
                ui.html(display_val).classes("flex-1 text-sm")
                ui.badge(icon, color={"file":"blue","rule":"teal","llm":"purple","user":"amber","default":"grey","system":"grey"}.get(src, "grey")).props("outline dense").classes("text-xs")
                if field_name in REQUIRED_FACET_FIELDS:
                    bar_color = "green" if conf >= 0.75 else "orange" if conf >= 0.40 else "red"
                    ui.linear_progress(value=conf, color=bar_color).classes("w-16 h-2")
                if 0 < conf < 0.40:
                    ui.label("⚠ 建议复核").classes("text-xs text-orange")


def _render_group(group_name: str, field_names: list, container):
    """渲染一个分组的字段卡片。"""
    with container:
        ui.label(group_name).classes("text-sm font-bold text-gray-500 mt-2")
        for fn in field_names:
            _render_field_card(fn, container)


def build_result_panel(annotated: dict, classification: dict, container):
    """
    渲染始终展示区的卡片式结果面板（分面分类4个 + 内容标识4个）。
    同时缓存 annotated/classification/container 供编辑后刷新用。
    """
    global _CURRENT_ANNOTATED, _CURRENT_CLASSIFICATION, _RESULT_CONTAINER
    _CURRENT_ANNOTATED = annotated
    _CURRENT_CLASSIFICATION = classification
    _RESULT_CONTAINER = container

    container.clear()
    overall = annotated.get("overall_confidence", 0.0)

    with container:
        # 整体置信度进度条（顶部）
        with ui.card().classes("w-full p-3 mb-4"):
            with ui.row().classes("w-full items-center gap-4"):
                ui.label("AI 分析完成").classes("text-lg font-bold")
                ui.element("div").classes("flex-1")
                with ui.column().classes("items-end"):
                    ui.label(f"整体置信度 {int(overall*100)}%").classes("text-sm")
                    bar_color = "green" if overall >= 0.75 else "orange" if overall >= 0.40 else "red"
                    ui.linear_progress(value=overall, color=bar_color).classes("w-32")

        # 分组1：分面分类（4个，始终展示）
        _render_group("分面分类", ["content_type", "domain", "temporal_nature", "epistemic_status"], container)
        ui.separator()
        # 分组2：内容标识（4个，始终展示）
        _render_group("内容标识", ["title", "keywords", "auto_summary", "author"], container)


def build_advanced_panel(annotated: dict, classification: dict, container):
    """
    渲染高级选项折叠区（知识属性6个 + 来源信息3个 + 时间戳2个）。
    同时缓存 container 供编辑后刷新用。
    """
    global _ADVANCED_CONTAINER
    _ADVANCED_CONTAINER = container

    container.clear()
    with container:
        with ui.expansion("高级选项", icon="⚙️").classes("w-full") as exp:
            _render_group("知识属性", [
                "lifecycle", "knowledge_type", "is_personal",
                "trust_score", "source_project", "udc_code",
            ], exp)
            ui.separator()
            _render_group("来源信息", ["source", "language", "origin.source_url"], exp)
            ui.separator()
            _render_group("时间戳", ["timeline.published", "timeline.effective"], exp)


def _build_edit_widget(cfg: dict, current):
    """
    根据字段配置构建对应的编辑控件。
    
    返回:
        edit_widget (ui.element) — 或 None（label 类型不可编辑）
    """
    widget_type = cfg.get("widget", "input")

    if widget_type == "select":
        opts = cfg.get("options", [])
        return ui.select(
            label=cfg.get("zh"),
            options=[o[0] for o in opts],
            value=current,
        ).classes("w-full")

    elif widget_type == "multiselect":
        opts = cfg.get("options", [])
        return ui.select(
            label=cfg.get("zh"),
            options=[o[0] for o in opts],
            value=current,
            multiple=True,
        ).classes("w-full").props("use-chips")

    elif widget_type == "input":
        return ui.input(
            label=cfg.get("zh"),
            value=current or "",
        ).classes("w-full")

    elif widget_type == "input_chips":
        current_str = ", ".join(current) if isinstance(current, list) else (current or "")
        return ui.input(
            label=cfg.get("zh"),
            placeholder="逗号分隔",
            value=current_str,
        ).classes("w-full")

    elif widget_type == "switch":
        return ui.switch(
            label=cfg.get("zh"),
            value=bool(current),
        )

    elif widget_type == "slider":
        return ui.slider(
            min=0, max=5,
            value=current or 3,
            step=1,
        ).classes("w-full")

    elif widget_type == "date":
        return ui.date(
            value=current or "",
        ).classes("w-full")

    elif widget_type in ("label", "label_multiline"):
        ui.label("此字段由系统自动生成，不可编辑").classes("text-sm text-gray-500")
        return None

    # fallback: input
    return ui.input(label=cfg.get("zh"), value=current or "").classes("w-full")


def edit_field_dialog(field_name: str):
    """
    弹出编辑对话框，修改指定字段的值。
    确认后更新 PANEL_VALUES → 刷新两个面板（显示新值 + 👤 来源徽章）。
    """
    cfg = FIELD_DISPLAY_CFG.get(field_name, {})
    if not cfg.get("editable", True):
        ui.notify(f"字段「{cfg.get('zh', field_name)}」不可编辑", type="warning")
        return

    widget_type = cfg.get("widget", "input")
    current = PANEL_VALUES.get(field_name)

    with ui.dialog() as dialog, ui.card().classes("p-4 w-96"):
        ui.label(f"编辑：{cfg.get('zh', field_name)}").classes("text-lg font-bold mb-4")
        edit_widget = _build_edit_widget(cfg, current)

        if edit_widget is not None:
            ui.separator()
            with ui.row().classes("w-full justify-end gap-2"):
                ui.button("取消", on_click=dialog.close).props("flat")

                def _on_confirm(fname=field_name, w=edit_widget, wt=widget_type):
                    new_val = None
                    if wt == "input_chips":
                        raw = w.value or ""
                        new_val = [k.strip() for k in raw.split(",") if k.strip()]
                    elif wt == "multiselect":
                        new_val = list(w.value) if w.value else []
                    elif wt == "switch":
                        new_val = w.value
                    else:
                        new_val = w.value

                    PANEL_VALUES[fname] = new_val
                    ui.notify(f"字段「{cfg.get('zh')}」已更新", type="positive")
                    dialog.close()
                    # 刷新面板：显示新值 + 更新来源徽章为 👤
                    _refresh_panels()

                ui.button("确认", on_click=_on_confirm, color="teal")

        else:
            ui.separator()
            ui.button("关闭", on_click=dialog.close).classes("w-full")
        dialog.open()
