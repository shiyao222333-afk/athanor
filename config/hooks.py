"""
预存储钩子注册表 — Pre-Store Hook Registry

外部程序（如 Nigredo / Albedo）可通过 register_hook() 注册钩子函数，
在 Citrinitas 摄入管线的「嵌入完成→写入 Qdrant」阶段介入。

钩子函数签名:
    hook(state: dict) -> state: dict

state 包含:
    file_path, text, collection, metadata, model,
    source, content_hash, chunks, vectors, valid_images,
    doc_id, ingested_at, points

钩子可以修改 state 中的任意字段后返回。管线会使用修改后的 state 继续执行。

用法:
    from config.hooks import register_hook

    def my_hook(state):
        state["metadata"]["source_project"] = "nigredo"
        return state

    register_hook(my_hook)
"""

from pathlib import Path

from text_pipeline.extract import parse_frontmatter

_hooks: list = []


def register_hook(hook):
    """注册一个预存储钩子函数"""
    if hook not in _hooks:
        _hooks.append(hook)


def get_hooks() -> list:
    """返回当前注册的所有钩子（副本，防止外部修改内部列表）"""
    return list(_hooks)


# ── Albedo 中转② frontmatter 钩子（B-only 主契约载体）──────────────────────
# v1.1（用户决策③）：删除 sidecar .meta.json，frontmatter 升为唯一主契约载体。
# 炼真 refine() 把 {name}_refined.md 写成「人读鉴定报告 + 文件头 --- YAML frontmatter」，
# frontmatter 即机器可读契约。此钩子在「嵌入完成→写 Qdrant」前读取该 .md 自身的
# frontmatter，把契约字段强制合并进 payload。
#
# 关键纪律（§3.1 原则③）：炼真是「质检关卡」，其结论不可被熔知朴素分类绕过 → 强制覆盖。
# 时序：本钩子在预存储阶段（分类已完成）运行，天然兜住 classify_pipeline 的
# _derive_* / fill_defaults 可能覆盖 frontmatter 值的漏洞（§9 🔴B3）。
#
# 仅当 frontmatter 含 albedo 签名(refined_status)才生效，对其它摄入零影响。

# §3.2 契约字段（frontmatter 键 = payload 字段，1:1；全部强制覆盖）。
#   权威定义（唯一）：albedo-citrinitas-handoff-spec.md（Claw 工作区根目录）§3.2；字段增减必须回该文档更新。
_CONTRACT_KEYS = {
    "content_type", "temporal_nature", "epistemic_status", "trust_score",
    "knowledge_type", "is_personal", "subject", "keywords", "auto_summary",
    "ext_text1", "refined_status", "publish_date",
    # 溯源与语言（2026-07-21 修复）：炼真实产，强制覆盖遏制熔知分类器 LLM 漂移
    "language", "title", "author", "source_url", "up_name",
    # v1.20.0 热度/互动数据（2026-08-03 落地）：单一 dict 字段，炼真透传强制覆盖
    "engagement",
}


def albedo_frontmatter_hook(state: dict) -> dict:
    """读取炼真中转② .md 的 frontmatter，强制覆盖 §3.2 契约字段进 state["metadata"]。

    无 frontmatter / 解析失败 / 非 Albedo 产出（frontmatter 不含 refined_status 签名）
    则原样返回，对其它摄入零影响。
    """
    fp = state.get("file_path") or ""
    if not fp:
        return state
    try:
        text = Path(fp).read_text(encoding="utf-8")
    except Exception:
        return state
    # parse_frontmatter 返回 (body, meta)；解析失败/无 frontmatter 时 meta={}
    _, fm = parse_frontmatter(text)
    if not isinstance(fm, dict) or not fm:
        return state
    # albedo 签名：炼真始终写入 refined_status；无此键即视为非炼真产出，不动
    if "refined_status" not in fm:
        return state

    md = state.setdefault("metadata", {})
    for key in _CONTRACT_KEYS:
        if key in fm and fm[key] not in (None, "", [], {}):
            md[key] = fm[key]
    md["source_project"] = "albedo-refined"
    return state


# ── 来源归属钩子（2026-08-03 用户拍板）────────────────────────────────────
# source_project 归属规则：已有归属（炼真 albedo-refined / 馏析 nigredo）不动；
# 巨作提交的闪念笔记（front-matter 带 opus-magnum-note 签名）→ opus-magnum；
# 其余无归属的摄入（熔知页面手动/上传/OCR 直入、收件箱无标记文件）→ citrinitas。
# 语义（用户拍板）：熔知只给上游管线文档标来源归属；直入熔知的文档归属熔知，
# 除非能明确识别来自巨作（闪念笔记的 source 签名）。
_SOURCE_PROJECT_NOTE_SIGNATURE = "opus-magnum-note"


def source_project_origin_hook(state: dict) -> dict:
    """为无来源归属的文档补 source_project（巨作闪念笔记 → opus-magnum，其余 → citrinitas）。

    仅当 metadata 尚无 source_project（非炼真/馏析产出）时生效；不覆盖上游归属。
    """
    md = state.setdefault("metadata", {})
    if md.get("source_project"):
        return state

    # ① 巨作闪念笔记：front-matter 带 opus-magnum-note 签名（route_note / drop_watcher 投递）
    fp = state.get("file_path") or ""
    fm_source = ""
    if fp:
        try:
            _, fm = parse_frontmatter(Path(fp).read_text(encoding="utf-8"))
            if isinstance(fm, dict):
                fm_source = fm.get("source") or ""
        except Exception:
            pass
    if fm_source == _SOURCE_PROJECT_NOTE_SIGNATURE:
        md["source_project"] = "opus-magnum"
        return state

    # ② 其余无归属（熔知页面直入 / 收件箱无标记文件）→ 归熔知
    md["source_project"] = "citrinitas"
    return state


# 模块加载即注册（ingest_service._step_pre_store_hooks 会在管线中调用 get_hooks）
register_hook(albedo_frontmatter_hook)
register_hook(source_project_origin_hook)
