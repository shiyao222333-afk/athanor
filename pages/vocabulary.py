"""
Citrinitas · 熔知 — 受控词表维护页面（/vocab）

【小白导读】这是"标准词清单"的可视化编辑器。你在网页上增删词，
点保存就写回 library/controlled_vocabulary.json，下次摄入文档时立即生效。
想搞懂"受控词表/归一化"是什么，见 docs/GLOSSARY.md。

允许用户在网页上直接查看 / 增删受控词，保存即写回
library/controlled_vocabulary.json 并刷新内存缓存，下次摄入即时生效。
"""

import logging
from nicegui import ui

from vocabulary import load_vocabulary, save_vocabulary
from utils.ui_shared import build_left_drawer

logger = logging.getLogger(__name__)


def _vocab_to_working(src: dict) -> dict:
    """把加载到的词表转成页面可编辑的工作副本（列表结构，规避 dict 键重命名难题）。"""
    working = {"udc_subdivisions": [], "themes": [], "keywords": []}
    for code, meta in (src.get("udc_subdivisions") or {}).items():
        if not isinstance(meta, dict):
            meta = {"label": str(meta), "parent": ""}
        working["udc_subdivisions"].append({
            "code": str(code),
            "label": meta.get("label", ""),
            "parent": meta.get("parent", ""),
        })
    for section in ("themes", "keywords"):
        for std, syns in (src.get(section) or {}).items():
            if not isinstance(syns, list):
                syns = [syns]
            working[section].append({"std": str(std), "syn": [str(s) for s in syns]})
    return working


@ui.page("/vocab")
def page_vocab():
    """受控词表维护页面（/vocab）—— 查看 / 增删受控词，保存即生效。"""
    build_left_drawer(active_page="vocab")

    src = load_vocabulary()
    working = _vocab_to_working(src)

    container = ui.column().classes("w-full p-6")

    def _save(_e=None):
        ok, msg = save_vocabulary(working)
        if ok:
            ui.notify("✅ 词表已保存，下次摄入即时生效", type="positive")
        else:
            ui.notify(f"⚠️ 保存失败: {msg}", type="negative")

    def _section_code():
        with ui.card().classes("w-full mb-4"):
            ui.markdown("### 🔢 学科细分码（udc_code）")
            ui.label(
                "标准 UDC 细分码 → 中文名 + 父级码（用于层级）。"
                "错填的码会让文档进「待审核」队列。"
            ).classes("text-xs text-gray-500")
            for item in working["udc_subdivisions"]:
                with ui.row().classes("items-center gap-2 w-full"):
                    ui.input("细分码", value=item["code"]).classes("w-1/5").props("dense outlined").on_change(
                        lambda e, it=item: it.update(code=e.value.strip()))
                    ui.input("中文名", value=item["label"]).classes("w-2/5").props("dense outlined").on_change(
                        lambda e, it=item: it.update(label=e.value.strip()))
                    ui.input("父级码", value=item["parent"]).classes("w-1/5").props("dense outlined").on_change(
                        lambda e, it=item: it.update(parent=e.value.strip()))
                    ui.button("🗑️", on_click=lambda e, it=item: (
                        working["udc_subdivisions"].remove(it), _render_all()))\
                        .props("flat dense color=red")
            with ui.row().classes("items-center gap-2 w-full mt-2"):
                new_code = ui.input("新细分码").classes("w-1/5").props("dense outlined")
                new_label = ui.input("中文名").classes("w-2/5").props("dense outlined")
                new_parent = ui.input("父级码").classes("w-1/5").props("dense outlined")
                def _add(_e=None):
                    c = new_code.value.strip()
                    if not c:
                        ui.notify("细分码不能为空", type="warning")
                        return
                    working["udc_subdivisions"].append({
                        "code": c, "label": new_label.value.strip(), "parent": new_parent.value.strip()})
                    _render_all()
                ui.button("➕ 添加", on_click=_add).props("flat dense")

    def _section_syn(section_key: str, title: str, icon: str):
        with ui.card().classes("w-full mb-4"):
            ui.markdown(f"### {icon} {title}")
            ui.label(
                "标准词 → 同义词（逗号分隔）。AI 写出的同义词会被归一成标准词；"
                "完全不在表里的词会让文档进「待审核」队列。"
            ).classes("text-xs text-gray-500")
            for item in working[section_key]:
                with ui.row().classes("items-center gap-2 w-full"):
                    ui.input("标准词", value=item["std"]).classes("w-1/3").props("dense outlined").on_change(
                        lambda e, it=item: it.update(std=e.value.strip()))
                    ui.input("同义词(逗号分隔)", value=", ".join(item["syn"])).classes("w-1/2").props(
                        "dense outlined").on_change(
                        lambda e, it=item: it.update(syn=[s.strip() for s in e.value.split(",") if s.strip()]))
                    ui.button("🗑️", on_click=lambda e, it=item: (
                        working[section_key].remove(it), _render_all()))\
                        .props("flat dense color=red")
            with ui.row().classes("items-center gap-2 w-full mt-2"):
                new_std = ui.input("新标准词").classes("w-1/3").props("dense outlined")
                new_syn = ui.input("同义词(逗号分隔)").classes("w-1/2").props("dense outlined")
                def _add(_e=None):
                    s = new_std.value.strip()
                    if not s:
                        ui.notify("标准词不能为空", type="warning")
                        return
                    syns = [x.strip() for x in new_syn.value.split(",") if x.strip()]
                    working[section_key].append({"std": s, "syn": syns})
                    _render_all()
                ui.button("➕ 添加", on_click=_add).props("flat dense")

    def _render_all():
        container.clear()
        with container:
            ui.markdown("# 📖 受控词表")
            ui.markdown(
                "*这里收录的「标准词」决定 AI 打的标签能不能直接入库。"
                "不在表里的词会让文档进「待审核」队列。修改后点底部「保存词表」生效。*"
            )
            _section_code()
            _section_syn("themes", "形式题材（subject）", "🏷️")
            _section_syn("keywords", "关键词（keywords）", "🔑")
            ui.button("💾 保存词表", on_click=_save).props("color=primary").classes("mt-4")

    _render_all()
