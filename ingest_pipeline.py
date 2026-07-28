"""
Ingest Pipeline — Qdrant payload builder（入库组装线）.

【小白导读 · 这个文件干嘛的？】
  一份文件要进知识库，得先被切小块、每块变成数字向量。这个文件负责把
  "小块文字 + 它的向量 + 标签"拼成一格格知识库能存的数据（叫 point / 点位）。
  关键概念：分块(chunk)=长文件切的小段；点位(point)=知识库最小一格；
  doc_id=每份文件的身份证号（同一文件永远同一个号 → 重放=更新，不堆重复）。
  术语不懂看 docs/GLOSSARY.md。

  build_payloads 的"组装线"一步一步（对应 FLOWCHART 的"入库"主流程节点）：
    1. _derive_doc_id：算出这份文件的身份证号。有文件路径就用路径算（同名文件=更新）；
       没有（纯文本/粘贴/死信重传/OCR）就用正文内容哈希算（相同内容永远同号）。
    2. _prepare_metadata：把上游（AI 分析 / 用户填写）给的一堆字段，整理成统一的字典。
       —— 这里会先过一遍"枚举守卫"(normalize_facet_values) 和生命周期归一
          (normalize_lifecycle)，把 AI 写偏的类别纠正回标准词。
    3. normalize_free_text_fields（受控词表校验，#28/#37 挂载点）：
       把 subject/keywords/udc_code 对照词表归一，未受控的打 needs_review 标记。
       这是"两条摄入路线唯一汇合点"上的关键一步——守望夹和网页上传都从这儿过。
    4. 调试开关（#44）：若系统配置页打开了"强制所有摄入进待审核"，这里直接把
       needs_review 置 True。因为挂在 build_payloads，开关对所有来源一次性生效。
    5. _build_point：把"文字块 + 向量 + 元数据"拼成 Qdrant 的一个点位。
       —— 点位号(_derive_point_id)由 (doc_id, 第几块) 算出，重录入时 upsert 覆盖旧点位。
       —— 元数据里哪些字段写进 payload、扩展槽只写有值的，都在这儿定。
    6. 返回 {ok, points, doc_id, ...}，交给 kb_query.ingest() 去写 Qdrant。

  诚实的存疑点：
  - 第 1 步"路径即身份"对书类文件成立（书处理后稳定落在 library/books/，文件名唯一），
    但理论上若用户移动/重命名源文件，doc_id 会变 → 被视为"新文件"而非"更新"。
    目前没遇到，但这是个潜在 edge case，也许将来该用内容哈希做更稳的身份。
  - _prepare_metadata 里把 base_meta 几乎原样透传成几十个字段，函数偏长。
    当时这样写是为了"一处看全字段"，但确实不够优雅；若要重构，可能按分组拆成几个小函数。
  - 扩展槽(ext_text/num/bool/date 1~3)的透传用了一串近乎重复的循环——能抽成一个 helper，
    只是当时为了"看得清每个槽"故意展开了，未必是最优写法。

Extracted from kb_query.py (v0.7.0 B1 refactor).

职责:
  build_payloads() — 将文本/块/向量/元数据组装为 Qdrant points 列表
  不负责: 文本提取、分块、嵌入计算、Qdrant 写入（由 kb_query.ingest() 协调）
"""
import hashlib
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

from text_pipeline import _text_hash, _detect_language
from config.normalize import normalize_facet_values, normalize_lifecycle
from vocabulary import normalize_free_text_fields  # #28 受控词表校验（#37 挂载点）
from config.settings import is_force_review_all  # 调试开关：强制所有摄入进待审核
from search_engine import _call_llm_api, LLM_API_KEY, LLM_BASE_URL, LLM_MODEL
from utils.llm_helpers import extract_json_block as _extract_json_block

logger = logging.getLogger(__name__)


def _derive_doc_id(file_path: str = None, text: str = None) -> str:
    """确定性文档编号：同一源 → 同一 doc_id，支撑重录入去重与覆盖更新。

    - 有文件路径：基于归一化完整路径（书类处理后稳定落在 library/books/，
      文件名唯一）→ 路径即身份，替换同名文件即「更新」而非新增。
    - 无文件路径（纯文本/粘贴/死信重传/OCR）：基于正文内容哈希 →
      相同内容永远同一编号，使「强制重录」与「重传覆盖」在所有入口生效。
    - 两者皆无：退回随机（兜底，正常流程不会走到）。
    """
    # 有文件路径 → 用路径算号（同一文件永远同一个号）
    if file_path:
        norm = os.path.normpath(file_path).replace("\\", "/")
        return "doc_" + hashlib.sha256(norm.encode("utf-8")).hexdigest()[:16]
    if text is not None and text.strip():
        return "doc_" + hashlib.sha256(text.strip().encode("utf-8")).hexdigest()[:16]
    return "doc_" + uuid.uuid4().hex[:16]


def _derive_point_id(doc_id: str, chunk_index: int) -> int:
    """确定性点编号：由 (doc_id, 块序号) 派生，使重录入时 upsert 覆盖旧点而非重复堆积。

    落在 [0, 2^64) 区间，与 Qdrant 数值型 point id 兼容；碰撞概率约 1/2^64，可忽略。
    """
    # 由(文档号,第几块)算出点位号 → 重录入时覆盖旧点位，不堆重复
    seed = f"{doc_id}#{chunk_index}".encode("utf-8")
    return int(hashlib.sha256(seed).hexdigest(), 16) & ((1 << 64) - 1)


def _prepare_metadata(base_meta: dict, text: str, source: str, file_path: str) -> dict:
    """从 base_meta 提取并规范化所有元数据字段，返回单一字典。"""
    base_meta = base_meta or {}

    # 分面字段（枚举守卫）
    facet_raw = {
        "content_type":     base_meta.get("content_type", "knowledge"),
        "domain":           base_meta.get("domain", []),
        "temporal_nature":  base_meta.get("temporal_nature", "timeboxed"),
        "epistemic_status": base_meta.get("epistemic_status", "unverified"),
    }
    facet_norm = normalize_facet_values(facet_raw)

    # 时间线字段
    publish_date   = base_meta.get("publish_date", None)
    effective_date = base_meta.get("effective_date", None)
    expiry_date    = base_meta.get("expiry_date", None)

    # 来源字段
    author        = base_meta.get("author", "")
    source_url    = base_meta.get("source_url", "")
    file_type     = base_meta.get("file_type", "txt")
    ingest_method = base_meta.get("ingest_method", "manual")

    return {
        # 分面
        "content_type":    facet_norm["content_type"],
        "domain":          facet_norm["domain"] if isinstance(facet_norm["domain"], list) else [facet_norm["domain"]],
        "temporal_nature": facet_norm["temporal_nature"],
        "epistemic_status": facet_norm["epistemic_status"],
        # 生命周期（#41：经枚举守卫归一，避免 AI 写出"草稿中"等花样）
        "lifecycle":      normalize_lifecycle(base_meta.get("lifecycle", "published")),
        "source_project": base_meta.get("source_project"),
        "udc_code":        base_meta.get("udc_code", ""),
        # 知识管理
        "knowledge_type":  base_meta.get("knowledge_type", ""),
        "is_personal":    base_meta.get("is_personal", False),
        "trust_score":    base_meta.get("trust_score", 3),
        "is_canonical":   base_meta.get("is_canonical", True),
        "relations":      base_meta.get("relations", []),
        "keywords":       base_meta.get("keywords", []),
        "auto_summary":   base_meta.get("auto_summary", ""),
        # 炼真契约字段（B-only）：形式题材(subject) + 处理状态，由 hook 强制覆盖注入
        "subject":        base_meta.get("subject", ""),
        "refined_status": base_meta.get("refined_status", ""),
        # 时效 + 版本
        "title":          base_meta.get("title") or source,
        "publish_date":   publish_date,
        "effective_date": effective_date,
        "expiry_date":   expiry_date,
        "version":        base_meta.get("version") or "无",
        # 来源
        "author":         author,
        "source_url":     source_url,
        "file_type":      file_type,
        "ingest_method":  ingest_method,
        "source_path":    file_path or "",
        # 内容创作
        "target_platform": base_meta.get("target_platform", "none"),
        "related_product": base_meta.get("related_product") or "无",
        # 系统
        "language":       base_meta.get("language") or _detect_language(text),
        "access_level":   base_meta.get("access_level", "private"),
        "batch_id":       base_meta.get("batch_id") or "无",
        "needs_review":   base_meta.get("needs_review", False),
        # 字段来源 + 置信度
        "field_sources":  base_meta.get("field_sources", {}),
        "ingest_conf":    base_meta.get("confidence_overall", None),
        # 图片
        "valid_images":   base_meta.get("_valid_images", []),
        # 扩展槽透传
        "ext_text1": base_meta.get("ext_text1"),
        "ext_text2": base_meta.get("ext_text2"),
        "ext_text3": base_meta.get("ext_text3"),
        "ext_text4": base_meta.get("ext_text4"),
        "ext_text5": base_meta.get("ext_text5"),
        "ext_num2":  base_meta.get("ext_num2"),
        "ext_num3":  base_meta.get("ext_num3"),
        "ext_bool1": base_meta.get("ext_bool1"),
        "ext_bool2": base_meta.get("ext_bool2"),
        "ext_bool3": base_meta.get("ext_bool3"),
        "ext_date1": base_meta.get("ext_date1"),
        "ext_date2": base_meta.get("ext_date2"),
        "ext_date3": base_meta.get("ext_date3"),
    }


def _backfill_subject_keywords(text: str, metadata: dict) -> None:
    """炼真↔熔知 handoff 缺口兜底（v1.2 修正：炼真现产出 subject/keywords）。

    炼真产出的契约强制键（content_type[载体类型] / subject[形式题材] / keywords[视频标签+主题] /
    epistemic_status / trust_score / refined_status / auto_summary / ext_*）由钩子强制覆盖进 metadata。
    subject（形式题材）与 keywords（视频标签+主题）炼真已产，熔知此处仅当上游**未提供（空）**时才用
    LLM 兜底（兼容非 Albedo 文件 / 旧文件）。LLM 失败则静默留空（优雅降级），绝不覆盖已填值。
    """
    need_subject = not str(metadata.get("subject") or "").strip()
    need_keywords = not (metadata.get("keywords") or [])

    if not need_subject and not need_keywords:
        return

    api_key = os.environ.get("KB_LLM_API_KEY") or LLM_API_KEY
    if not api_key:
        return

    sample = text[:5000].strip()
    if not sample:
        return

    want = []
    example = {}
    if need_subject:
        want.append(
            "### subject — 这条内容的「题材/主题领域」（如：编程教程、商业思维、"
            "游戏实况、美食探店、职场经验），用 2-8 个字概括，不要写成长句"
        )
        example["subject"] = "题材示例"
    if need_keywords:
        want.append(
            "### keywords — 3-8 个核心关键词/术语（JSON 数组），覆盖主要内容话题，"
            "不要写整句"
        )
        example["keywords"] = ["关键词1", "关键词2"]

    prompt = (
        "你是一个内容理解助手。请分析以下文本，只填写要求的字段。\n\n"
        f"## 文本内容\n{sample}\n\n"
        "## 需要填写的字段\n" + "\n".join(want) + "\n\n"
        "## 输出格式\n严格输出以下 JSON，不要包含任何额外文字、不要用 ```json 包裹：\n"
        + json.dumps(example, ensure_ascii=False)
    )

    try:
        raw = _call_llm_api(
            [{"role": "user", "content": prompt}],
            base_url=os.environ.get("KB_LLM_BASE_URL") or LLM_BASE_URL,
            api_key=api_key,
            model=os.environ.get("KB_LLM_MODEL") or LLM_MODEL,
        )
    except Exception as e:
        logger.warning(f"_backfill_subject_keywords LLM failed: {e}")
        return

    result = _extract_json_block(raw)
    if not result:
        return

    fs = metadata.get("field_sources") or {}
    if need_subject:
        subj = str(result.get("subject") or "").strip()
        if subj:
            metadata["subject"] = subj[:60]
            fs["subject"] = "llm"
    if need_keywords and isinstance(result.get("keywords"), list):
        kws = [str(x).strip() for x in result["keywords"] if str(x).strip()][:8]
        if kws:
            metadata["keywords"] = kws
            fs["keywords"] = "llm"
    metadata["field_sources"] = fs


def _build_point(chunk: str, vec: list, i: int, total_chunks: int,
                doc_id: str, full_text_hash: str, metadata: dict,
                sparse_vec: Optional[tuple] = None,
                position: Optional[dict] = None) -> dict:
    """构建单个 Qdrant point。"""
    point_id = _derive_point_id(doc_id, i)
    m = metadata  # 简写
    pos = position or {}

    payload = {
        "text": chunk,
        "title": m["title"],
        "source": m.get("source", "unknown"),
        "chunk_index": i,
        "total_chunks": total_chunks,
        # 书库位置指针（无章节文本时为默认值）
        "chapter_index": pos.get("chapter_index", 0),
        "chapter_title": pos.get("chapter_title", ""),
        "chunk_in_chapter": pos.get("chunk_in_chapter", i + 1),
        "doc_id": doc_id,
        "content_hash": full_text_hash,
        "images": m["valid_images"],
        # 分面
        "content_type":    m["content_type"],
        "domain":          m["domain"],
        "temporal_nature": m["temporal_nature"],
        "epistemic_status": m["epistemic_status"],
        # 生命周期
        "lifecycle":      m["lifecycle"],
        "source_project": m["source_project"],
        "udc_code":        m["udc_code"],
        # 知识管理
        "knowledge_type":  m["knowledge_type"],
        "is_personal":    m["is_personal"],
        "trust_score":    m["trust_score"],
        "is_canonical":   m["is_canonical"],
        "relations":      m["relations"] if isinstance(m["relations"], list) else [],
        "keywords":       m["keywords"] if isinstance(m["keywords"], list) else [],
        "auto_summary":   m["auto_summary"],
        # 炼真契约字段（B-only）
        "subject":        m["subject"],
        "refined_status": m["refined_status"],
        # timeline
        "timeline": {
            "published": m["publish_date"],
            "effective": m["effective_date"],
            "expiry":    m["expiry_date"],
            "ingested":  m["ingested_at"],
            "accessed":  None,
        },
        # origin
        "origin": {
            "author":         m["author"],
            "source_url":     m["source_url"],
            "file_type":      m["file_type"],
            "ingest_method":  m["ingest_method"],
            "source_path":    m["source_path"],
        },
        # stats
        "stats": {"access_count": 0, "starred": False},
        # 内容创作
        "target_platform": m["target_platform"],
        "related_product": m["related_product"],
        "version":        m["version"],
        # 系统
        "language":       m["language"],
        "access_level":   m["access_level"],
        "batch_id":       m["batch_id"],
        "is_archived":   False,
        "needs_review":   m["needs_review"],
        # 字段来源 + 置信度
        "field_sources":  m["field_sources"],
        "ingest_conf":    m["ingest_conf"],
    }
    # 扩展槽（只写入有值的字段，不写 None）
    for i, val in enumerate([m.get("ext_text1"), m.get("ext_text2"), m.get("ext_text3"),
                              m.get("ext_text4"), m.get("ext_text5")], 1):
        if val is not None:
            payload[f"ext_text{i}"] = val
    for i, val in enumerate([m.get("ext_num2"), m.get("ext_num3")], 1):
        if val is not None:
            payload[f"ext_num{i}"] = val
    for i, val in enumerate([m.get("ext_bool1"), m.get("ext_bool2"), m.get("ext_bool3")], 1):
        if val is not None:
            payload[f"ext_bool{i}"] = val
    for i, val in enumerate([m.get("ext_date1"), m.get("ext_date2"), m.get("ext_date3")], 1):
        if val is not None:
            payload[f"ext_date{i}"] = val

    point = {
        "id": point_id,
        "vector": {"dense": vec},
        "payload": payload,
    }
    if sparse_vec:
        point["vector"]["bm25"] = {"indices": sparse_vec[0], "values": sparse_vec[1]}
    return point


def build_payloads(
    text: str,
    chunks: list,
    vectors: list,
    sparse_vectors: Optional[list] = None,
    base_meta: Optional[dict] = None,
    file_path: str = "",
    source: str = "unknown",
    model: str = "",
    chunk_positions: Optional[list] = None,
) -> dict:
    """
    构建 Qdrant points 列表（含完整 payload）。

    参数:
        text:       原始全文（用于 content_hash 和语言检测）
        chunks:     已切块的文本列表
        vectors:    嵌入向量列表（与 chunks 一一对应）
        base_meta:  用户提供的元数据字典
        file_path:  原始文件路径
        source:     来源标识
        model:      嵌入模型名

    返回:
        {"ok": True, "points": [...], "doc_id": "...",
         "content_hash": "...", "valid_images": [...], "ingested_at": "..."}
    """
    base_meta = base_meta or {}
    doc_id = base_meta.get("doc_id") or _derive_doc_id(file_path, text)
    ingested_at = datetime.now(timezone.utc).isoformat()
    full_text_hash = _text_hash(text)

    # 准备元数据（注入 ingested_at）
    metadata = _prepare_metadata(base_meta, text, source, file_path)
    # #28 受控词表校验（#37 挂载点）：udc_code/subject/keywords 归一化，
    # 任一字段存在未受控值 → metadata["needs_review"]=True → 进「待审核」队列。
    # 此挂载点在 build_payloads 内、两条摄入路线（守望夹 + UI 上传）唯一汇合处，
    # 故一处接入同时覆盖两者；doc_id 用于日志定位。
    # 关键一步：把 AI 标签对照词表归一（不在表里的进待审核队列）
    normalize_free_text_fields(metadata, doc_id)
    # 炼真↔熔知 handoff 缺口兜底（v1.2）：subject(形式题材)/keywords(视频标签+主题) 炼真已产出并由钩子强制覆盖；
    # 此处仅在熔知自己摄入（非 Albedo 文件）且上游为空时用 LLM 兜底。放在 normalize 之后，避免 LLM
    # 派生的语义关键词被受控词表校验误判进「待审核」；仅当上游未提供时才调 LLM。
    _backfill_subject_keywords(text, metadata)
    # 调试开关：开启后强制所有摄入文件进待审核队列（build_payloads 是两条摄入路线唯一汇合点，一处接入全覆盖）
    if is_force_review_all():
        metadata["needs_review"] = True
    # 观察1 修复（needs_review 泄漏）：上游精炼稿 refined_status="ok" 即代表已审核通过，
    # 熔知词表校验 / 调试开关不得再翻转为 needs_review=True，避免与「已精炼 = 已审核」矛盾。
    # 仅当上游精炼稿自身就要求复核（base_meta.needs_review=True）时才保留待审核。
    if metadata.get("refined_status") == "ok" and not base_meta.get("needs_review"):
        if metadata.get("needs_review"):
            logger.info(
                f"[review] doc_id={doc_id} refined_status=ok → 清除词表/开关误标的 needs_review"
                f"（与已精炼状态保持一致）"
            )
        metadata["needs_review"] = False
    metadata["ingested_at"] = ingested_at
    metadata["source"] = source

    # 构建 points
    points = []
    for i, (chunk, vec) in enumerate(zip(chunks, vectors)):
        sparse_vec = None
        if sparse_vectors and i < len(sparse_vectors):
            sparse_vec = sparse_vectors[i]
        pos = None
        if chunk_positions and i < len(chunk_positions):
            pos = chunk_positions[i]
        point = _build_point(
            chunk, vec, i, len(chunks), doc_id, full_text_hash, metadata, sparse_vec, pos
        )
        points.append(point)

    return {
        "ok": True,
        "points": points,
        "doc_id": doc_id,
        "content_hash": full_text_hash,
        "valid_images": metadata["valid_images"],
        "ingested_at": ingested_at,
    }
