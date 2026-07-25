"""
受控词表加载层 + 自由文本字段归一化（#28 核心）

【小白导读 · 这个文件干嘛的？】
  它管一份"标准词清单"（受控词表，文件在 library/controlled_vocabulary.json）。
  你（或 AI）给文档打的标签，常常同一个意思写出不同词——"齿轮设计""传动设计"
  其实是一回事。不统一，搜索时搜得到这个、搜不到那个，知识库就"漏检"。

  它做两件事：
  ① 把清单读进内存（load_vocabulary，带单例缓存，读一次就留着复用，不每次读盘）；
  ② 把 AI 给文档打的标签对照清单"归一"——
     命中的 → 收拢成标准词；没命中的 → 保留原文，并打上"待审核"标记（绝不静默丢弃）。

  一条文档是怎么流过这里的（抽象流程，对应 FLOWCHART 的"归一化/受控校验"节点）：
    1. 一份文件在"入库组装线"（ingest_pipeline.build_payloads）里先被切块、算好向量；
    2. 组装线在"生成最终点位之前"，调本文件的 normalize_free_text_fields(metadata, doc_id)；
       （为什么挂在 build_payloads？因为它是守望夹 和 网页上传 两条摄入路线的唯一汇合点，
        一处挂载，两条路都覆盖，不用改两遍——这就是"单一挂载点"的意义。）
    3. 对三个自由文本字段分别处理：
       - udc_code：受控细分码。命中→标准码；未命中→清空
         （错码比空更糟，会污染检索/展示，所以宁可清空）；
       - subject（形式题材，取代已废弃的 tags）/ keywords（关键词）：subject 单值归一，keywords 逐条归一。命中→标准词；未命中→保留原文；
    4. 只要有一个字段"没受控"，就把这份文档打上 needs_review=True——
       文档照常入库，但先进「待审核」队列，等你在审核页人工确认/修正后才正式放行。
       这个标记叠加在"置信度路由"之上：置信度低的本来也会进待审核，两者不冲突。

  为什么这样设计（诚实的存疑点）：
  - "未受控的词不删、只打标记"是为了不丢 AI 的有用发现，词表可以边用边补。
    但代价是：未受控词会一直堆在审核队列里，需要你定期去补词表或审核。
  - udc_code 与 subject/keywords 待遇不同（一个清空、一个保留），是因为细分码是
    结构化检索键，乱填比空更有害；题材/关键词是描述性标签，保留原文无害且可后期归并。
    这条分界线是我拍板的，未必最优——也许将来 udc 也改成"保留+待审核"会更一致。
  - 形状校验（_validate_vocab_shape）是后来补的：词表文件被人手改坏（比如把 themes
    写成了列表而非对象）时，旧代码会静默当空表，结果全库字段都"不受控"→全进待审核。
    现在改为"形状错就报错并保留上一份好词表"；但如果你从没成功加载过词表、又遇到坏文件，
    它也只能退化成空表（不约束）——这是"不崩摄入"和"严格约束"之间的取舍，接受了前者优先。
  术语不懂看 docs/GLOSSARY.md。

职责：
  1. 加载 library/controlled_vocabulary.json（用户可手动编辑的词表）
  2. 对 AI 自由文本字段（udc_code / subject / keywords）做受控校验
     —— 命中标准词/同义词 → 归一为标准词；未收录 → 保留原文 + 记日志（绝不静默丢弃）
  3. 不碰 4 分面骨架（content_type / domain / temporal_nature / epistemic_status）
     —— 那四个由 config/normalize.py 的枚举守卫管，这里是它们的补充

设计原则（对齐历史坑）：
  - 单例缓存 + 文件变更检测：避免每次摄入都读盘
  - 文件缺失 → 空词表 + warning（向后兼容：用户还没填词时等于不约束）
  - 文件损坏/形状错 → ERROR + 保留上次成功缓存，绝不静默清空（见 _validate_vocab_shape）
  - 空词表 = 不约束（向后兼容）；未收录的词不会被删，只记日志 → 不丢 AI 的有用发现

调用点（#37）：ingest_pipeline.build_payloads() 内、_prepare_metadata() 返回后、
  构建 points 之前调用 normalize_free_text_fields(metadata, doc_id)。
  build_payloads 是守望夹与 UI 上传两条摄入路线的唯一汇合点，故一处挂载同时覆盖两者。
  （注：normalize_facet_values() 只接收 4 个分面字段，不含 udc_code/subject/keywords，
   故词表校验不能挂在那；正确挂载点是 build_payloads。）
"""

import json
import os
import logging

from qconst import LIBRARY_DIR

logger = logging.getLogger("vocabulary")

VOCAB_PATH = os.path.join(LIBRARY_DIR, "controlled_vocabulary.json")

# ── 模块级缓存（单例）──
_VOCAB_CACHE = None
_THEME_LOOKUP = {}     # 同义词(小写) → 标准题材词
_KEYWORD_LOOKUP = {}   # 同义词(小写) → 标准关键词
_UDC_CODES = set()     # 受控细分码集合


def _validate_vocab_shape(data) -> str | None:
    """形状校验：返回 None 表示形状正常；否则返回错误描述（供 load 时拦截）。

    受控词表必须是 dict，且三个受控字段（udc_subdivisions / themes / keywords）
    若存在，必须是 dict（不能是 list / str / 数字）。
    形状错 = 文件被手改坏或导出格式变了。这种情况绝不能静默当空表——
    否则全库字段都"不受控" → 全进待审核队列（正是 #39 那类坑）。
    必须在 _build_lookup（里面会对 themes/keywords 调 .items()）之前拦下来，
    否则会抛 'list' object has no attribute 'items' 被 except 吞掉、又静默清空。
    """
    if not isinstance(data, dict):
        return f"根节点应为对象(dict)，实际为 {type(data).__name__}"
    for key in ("udc_subdivisions", "themes", "keywords"):
        val = data.get(key)
        if val is not None and not isinstance(val, dict):
            return f"字段 '{key}' 应为对象(dict)，实际为 {type(val).__name__}"
    return None


def load_vocabulary(force: bool = False) -> dict:
    """
    加载词表。单例缓存 + 文件变更检测。

    设计原则（对齐历史坑，尤其 #39）：
      - 文件缺失       → 空词表 + warning（向后兼容：用户还没填词时等于不约束）
      - 文件损坏/形状错 → ERROR + 保留上次成功缓存（绝不静默清空）；
                          无历史缓存可保留时，才退化空词表并明确告警（仍不崩摄入）。
    """
    global _VOCAB_CACHE, _THEME_LOOKUP, _KEYWORD_LOOKUP, _UDC_CODES
    try:
        # 单例缓存：词表读一次就留内存，之后复用，不每次读盘
        if _VOCAB_CACHE is not None and not force:
            return _VOCAB_CACHE

        if not os.path.exists(VOCAB_PATH):
            logger.warning(
                f"[vocab] 词表文件不存在: {VOCAB_PATH}，使用空词表（不约束任何字段）"
            )
            _VOCAB_CACHE = _empty_vocab()
            return _VOCAB_CACHE

        with open(VOCAB_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)

        # 形状校验：损坏的手改词表（如 themes 写成 list）必须拦在 _build_lookup 之前，
        # 否则会在 .items() 上抛 'list' object has no attribute 'items' → 被 except 吞掉 → 静默清空。
        shape_err = _validate_vocab_shape(data)
        if shape_err:
            logger.error(f"[vocab] 词表形状错误，拒绝加载: {shape_err}")
            if _VOCAB_CACHE is not None:
                logger.error("[vocab] 保留上次成功加载的词表（不覆盖，摄入继续用旧词表）")
                return _VOCAB_CACHE
            logger.error("[vocab] 无历史缓存可用，退化空词表（不约束）；请修复词表文件后保存/重启！")
            _VOCAB_CACHE = _empty_vocab()
            return _VOCAB_CACHE

        _VOCAB_CACHE = {
            "udc_subdivisions": data.get("udc_subdivisions", {}) or {},
            "themes": data.get("themes", {}) or {},
            "keywords": data.get("keywords", {}) or {},
        }
        _build_lookup(_VOCAB_CACHE)
        logger.info(
            f"[vocab] 词表已加载：细分码 {len(_UDC_CODES)} 个，"
            f"题材 {len(_THEME_LOOKUP)} 条映射，关键词 {len(_KEYWORD_LOOKUP)} 条映射"
        )
        return _VOCAB_CACHE

    except Exception as e:
        # 仅捕获"磁盘/JSON 解析"层面的异常（文件打不开、JSON 语法错等）。
        # 形状错误已在上面提前拦截，不会落到这里被静默清空。
        logger.error(f"[vocab] 词表读取失败: {e}")
        if _VOCAB_CACHE is not None:
            logger.error("[vocab] 保留上次成功加载的词表（不覆盖，摄入继续用旧词表）")
            return _VOCAB_CACHE
        logger.warning("[vocab] 无历史缓存，退化空词表（不约束，不阻断摄入）")
        _VOCAB_CACHE = _empty_vocab()
        return _VOCAB_CACHE


def _build_lookup(vocab: dict) -> None:
    """构建内部查找表：标准词与同义词都映射到标准词；细分码入集合。"""
    # 建索引：标准词和同义词都指向同一个标准词，查的时候忽略大小写
    global _THEME_LOOKUP, _KEYWORD_LOOKUP, _UDC_CODES
    _THEME_LOOKUP = {}
    _KEYWORD_LOOKUP = {}
    _UDC_CODES = set()

    for code in (vocab.get("udc_subdivisions") or {}).keys():
        _UDC_CODES.add(str(code).strip())

    for std, synonyms in (vocab.get("themes") or {}).items():
        std_key = std.strip().lower()
        _THEME_LOOKUP[std_key] = std
        if isinstance(synonyms, list):
            for s in synonyms:
                _THEME_LOOKUP[str(s).strip().lower()] = std

    for std, synonyms in (vocab.get("keywords") or {}).items():
        std_key = std.strip().lower()
        _KEYWORD_LOOKUP[std_key] = std
        if isinstance(synonyms, list):
            for s in synonyms:
                _KEYWORD_LOOKUP[str(s).strip().lower()] = std


def _empty_vocab() -> dict:
    """返回空词表（不约束任何字段），并刷新查找表。"""
    empty = {"udc_subdivisions": {}, "themes": {}, "keywords": {}}
    _build_lookup(empty)
    return empty


def normalize_udc(code) -> str | None:
    """
    归一化 UDC 细分码。命中受控码 → 返回标准码；未命中 → None。
    调用方对 None 的处理：清空（码错比空更糟，乱填会破坏检索/展示）。
    """
    if not code:
        return None
    load_vocabulary()  # 兜底：确保查找表已构建（有单例缓存，重复调用开销可忽略）
    return str(code).strip() if str(code).strip() in _UDC_CODES else None


def normalize_theme(tag) -> str | None:
    """归一化题材标签。命中标准词或同义词 → 标准词；否则 None（调用方保留原文）。"""
    if not tag:
        return None
    load_vocabulary()  # 兜底：确保查找表已构建
    return _THEME_LOOKUP.get(str(tag).strip().lower())


def normalize_keyword(kw) -> str | None:
    """归一化关键词。命中标准词或同义词 → 标准词；否则 None（调用方保留原文）。"""
    if not kw:
        return None
    load_vocabulary()  # 兜底：确保查找表已构建
    return _KEYWORD_LOOKUP.get(str(kw).strip().lower())


def normalize_free_text_fields(metadata: dict, doc_id: str = "") -> dict:
    """
    对 metadata 的自由文本字段做受控词表校验（#37 调用入口）。

    行为（对齐用户决策：最严档）：
      - udc_code：命中 → 标准码；未命中 → 清空 + 记日志（避免乱码进库）
      - subject / keywords：subject 单值归一、keywords 逐条归一；命中 → 标准词；未命中 → 保留原文 + 记日志（不丢数据）
      - 任一字段存在未受控值 → 标记 metadata["needs_review"] = True
        文档照常入库，但进入「待审核」队列，由用户在审核页人工确认/修正后才放行。
        该标记叠加在现有置信度路由之上（不覆盖已为 True 的状态）。
    """
    has_uncontrolled = False
    # 确保 needs_review 键始终存在，避免下游直接访问时 KeyError
    metadata.setdefault("needs_review", False)

    # ── udc_code ──
    raw_udc = metadata.get("udc_code", "")
    if raw_udc:
        norm = normalize_udc(raw_udc)
        if norm:
            metadata["udc_code"] = norm
        else:
            logger.warning(
                f"[vocab] doc_id={doc_id} udc_code={raw_udc!r} 不在受控词表，已清空 + 标记待审核"
            )
            metadata["udc_code"] = ""
            has_uncontrolled = True

    # ── subject（形式题材，取代已废弃的 tags；见 handoff-spec §2.3）──
    raw_subject = metadata.get("subject")
    if isinstance(raw_subject, str) and raw_subject.strip():
        nt = normalize_theme(raw_subject)
        if nt:
            metadata["subject"] = nt
        else:
            logger.warning(f"[vocab] doc_id={doc_id} 形式题材未受控，保留原文 + 标记待审核: {raw_subject!r}")
            metadata["subject"] = raw_subject.strip()
            has_uncontrolled = True

    # ── keywords ──
    raw_kw = metadata.get("keywords", []) or []
    if isinstance(raw_kw, str):
        raw_kw = [raw_kw]
    norm_kw = []
    for k in raw_kw:
        nk = normalize_keyword(k)
        if nk:
            norm_kw.append(nk)
        else:
            logger.warning(f"[vocab] doc_id={doc_id} 关键词未受控，保留原文 + 标记待审核: {k!r}")
            norm_kw.append(str(k).strip())
            has_uncontrolled = True
    metadata["keywords"] = norm_kw

    # ── 任一未受控 → 送「待审核」队列 ──
    # 文档照常入库，但打上"待审核"标记，等人在审核页确认后才放行
    if has_uncontrolled:
        was = metadata.get("needs_review", False)
        metadata["needs_review"] = True
        logger.info(
            f"[vocab] doc_id={doc_id} 存在未受控词表字段 → 标记 needs_review"
            + ("" if was else "（新增，进审核队列）")
        )

    return metadata


def reload() -> dict:
    """强制重新加载词表（维护页保存后调用）。"""
    return load_vocabulary(force=True)


def save_vocabulary(working: dict) -> tuple:
    """
    将页面工作副本写回词表文件，并刷新内存缓存（保存后下次摄入即时生效）。

    working 结构（与 page_vocab 的编辑副本一致）：
      {"udc_subdivisions": [{"code","label","parent"}, ...],
       "themes":           [{"std","syn":[...]}, ...],
       "keywords":         [{"std","syn":[...]}, ...]}

    返回 (ok: bool, message: str)。失败时绝不损坏原文件（先写临时文件再 rename）。
    """
    global _VOCAB_CACHE, _THEME_LOOKUP, _KEYWORD_LOOKUP, _UDC_CODES
    try:
        # 保留 version / description 头（从现有文件读取，缺失则用默认）
        version = "1.0"
        description = (
            "受控词表（controlled vocabulary）— 约束 AI 自由文本字段"
            "（udc_code / subject / keywords），防止同一概念写法不一导致漏搜。"
            "用户可手动增删词条后保存即可生效。未收录的词不会被静默丢弃，"
            "仅记录日志，待后续补充。"
        )
        if os.path.exists(VOCAB_PATH):
            try:
                with open(VOCAB_PATH, "r", encoding="utf-8") as f:
                    old = json.load(f)
                version = old.get("version", version)
                description = old.get("description", description)
            except Exception:
                pass

        out = {
            "version": version,
            "description": description,
            "udc_subdivisions": {
                str(it.get("code", "")).strip(): {
                    "label": str(it.get("label", "")).strip(),
                    "parent": str(it.get("parent", "")).strip(),
                }
                for it in working.get("udc_subdivisions", [])
                if str(it.get("code", "")).strip()
            },
            "themes": {
                str(it.get("std", "")).strip(): [str(s).strip() for s in it.get("syn", []) if str(s).strip()]
                for it in working.get("themes", [])
                if str(it.get("std", "")).strip()
            },
            "keywords": {
                str(it.get("std", "")).strip(): [str(s).strip() for s in it.get("syn", []) if str(s).strip()]
                for it in working.get("keywords", [])
                if str(it.get("std", "")).strip()
            },
        }

        # 原子写：先写临时文件再 rename，避免半截文件损坏原词表
        tmp = VOCAB_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        os.replace(tmp, VOCAB_PATH)

        # 刷新内存缓存（无需再调 reload，下次摄入直接用新词表）
        _VOCAB_CACHE = out
        _build_lookup(out)
        logger.info(
            f"[vocab] 词表已保存：细分码 {len(out['udc_subdivisions'])} / "
            f"题材 {len(out['themes'])} / 关键词 {len(out['keywords'])}"
        )
        return True, "ok"
    except Exception as e:
        logger.error(f"[vocab] 词表保存失败: {e}")
        return False, str(e)
