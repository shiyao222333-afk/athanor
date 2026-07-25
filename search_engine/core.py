# flake8: noqa: E501
"""Search Engine 搜索核心 — 过滤条件构建 / Qdrant RRF 混合查询

从 search_engine.py 拆分（v1.0.2 代码质量清理）。
"""

import requests

from qconst import (
    QDRANT_URL, DEFAULT_COLLECTION,
    SEARCH_TOP_K, SEARCH_SCORE_THRESHOLD, SEARCH_CHUNKS_PER_DOC,
    RERANK_ENABLED, RERANK_MODEL, RERANK_TOP_N,
)
from text_pipeline import _embed
from reranker import rerank_results, rerank_results_simple
from sparse_encoder import encode_sparse_query


# 有效过滤键（facet_filter 参数校验用）
_VALID_FILTER_KEYS = {"content_type","domain","knowledge_type","subject","temporal_nature","epistemic_status","lifecycle","is_personal","trust_score_min"}


def _build_qdrant_filter(facet_filter: dict) -> tuple:
    """从 facet_filter 构建 Qdrant 过滤条件（must 数组）。
    返回 (filter_dict, warnings_list)。"""
    if not facet_filter:
        return None, []
    _invalid_keys = set(facet_filter.keys()) - _VALID_FILTER_KEYS
    warnings = []
    if _invalid_keys:
        warnings.append(f"facet_filter 无效键（已忽略）: {_invalid_keys}")
    must_conditions = []

    def _add_match(key, vals):
        must_conditions.append({
            "key": key,
            "match": {"value": vals[0]} if len(vals) == 1 else {"any": vals}
        })

    for key in ("content_type", "domain", "knowledge_type", "subject"):
        if facet_filter.get(key):
            _add_match(key, facet_filter[key])

    for key in ("temporal_nature", "epistemic_status", "lifecycle"):
        if facet_filter.get(key):
            must_conditions.append({
                "key": key,
                "match": {"value": facet_filter[key]}
            })

    if "is_personal" in facet_filter:
        must_conditions.append({
            "key": "is_personal",
            "match": {"value": facet_filter["is_personal"]}
        })

    if facet_filter.get("trust_score_min") is not None:
        must_conditions.append({
            "key": "trust_score",
            "range": {"gte": facet_filter["trust_score_min"]}
        })

    return {"must": must_conditions} if must_conditions else None, warnings


def _query_qdrant_rrf(
    query: str,
    query_vec: list,
    top_k: int,
    qdrant_filter: dict,
    score_threshold: float,
    collection: str = DEFAULT_COLLECTION,
) -> list:
    """执行 Qdrant RRF 混合查询 + 重排序，返回结果列表。"""
    # ── 生成稀疏查询向量 ──
    sparse_query = None
    try:
        sparse_query = encode_sparse_query(query)
    except Exception as e:
        print(f"[Search] 稀疏查询向量生成失败（降级为纯稠密搜索）: {e}")

    # ── 搜索 Qdrant（原生混合查询：稠密 + 稀疏 → RRF 融合）──
    prefetch = []
    if sparse_query:
        prefetch.append({
            "query": {"indices": sparse_query[0], "values": sparse_query[1]},
            "using": "bm25",
            "limit": top_k * 2,
        })
    prefetch.append({
        "query": query_vec,
        "using": "dense",
        "limit": top_k * 2,
    })

    query_body = {
        "prefetch": prefetch,
        "query": {"fusion": "rrf"},
        "limit": top_k,
        "with_payload": True,
        "with_vector": True,  # 一并取回已存稠密向量，供重排序复用（免 Ollama 重嵌入）
    }
    if qdrant_filter:
        query_body["filter"] = qdrant_filter
        query_body["params"] = {"acorn": {"enable": True, "max_selectivity": 0.4}}

    resp = requests.post(
        f"{QDRANT_URL}/collections/{collection}/points/query",
        json=query_body,
        timeout=30,
    )
    resp.raise_for_status()
    results = resp.json()["result"]["points"]

    # 后过滤（0 是有效阈值，所以用 is not None）
    if score_threshold is not None:
        results = [r for r in results if r.get("score", 0) >= score_threshold]

    # 构建 point_id → 稠密向量 映射，供重排序复用（避免对候选文档重复调用 Ollama 嵌入）
    doc_vectors = {}
    for r in results:
        v = r.get("vector")
        if isinstance(v, dict):
            dv = v.get("dense") if "dense" in v else (next(iter(v.values())) if v else None)
        else:
            dv = v
        doc_vectors[r["id"]] = dv

    # 重排序
    try:
        if RERANK_ENABLED:
            results = rerank_results(query=query, results=results,
                                   model=RERANK_MODEL, top_n=RERANK_TOP_N,
                                   query_vec=query_vec, doc_vectors=doc_vectors)
    except Exception as e:
        print(f"[Search] 重排序失败: {e}，尝试简单重排序")
        try:
            results = rerank_results_simple(query, results, top_n=RERANK_TOP_N)
        except Exception as e2:
            print(f"[Search] 简单重排序也失败: {e2}，使用原始排序")
    return results


def search(
    query: str,
    top_k: int = None,
    collection: str = DEFAULT_COLLECTION,
    score_threshold: float = None,
    model: str = None,
    facet_filter: dict = None,
) -> dict:
    """
    向量搜索知识库（支持分面过滤）。

    参数:
        query: 搜索问题
        top_k: 返回结果数
        collection: 搜索的集合
        score_threshold: 最低相似度
        model: 嵌入模型
        facet_filter: 分面过滤条件，格式：
            {
                "content_type": ["knowledge"],           # 内容类型（任一匹配）
                "domain": ["0", "6"],                    # 主题域-UDC（任一匹配）
                "temporal_nature": "evergreen",          # 时效属性（单个值）
                "epistemic_status": "corroborated",      # 认知验证状态（单个值）
                "lifecycle": "published",               # 生命周期（单个值，普通字段）
                "is_personal": false,                  # 是否个人化
                "trust_score_min": 3,                  # 最低可信度
                "knowledge_type": ["formula"],          # 知识子类型
                "subject": "齿轮",                     # 标签（任一匹配）
            }

    返回结构:
    {
        "ok": true/false,
        "query": "原始查询",
        "total": 匹配数,
        "chunks": [...],
        "warnings": [...]
    }
    """
    from qdrant_client import _ensure_collection

    if not _ensure_collection(collection):
        return {"ok": False, "error": "Qdrant 未运行。请先启动 Qdrant（双击 run.bat）。"}

    # 参数验证
    if not query or not query.strip():
        return {"ok": False, "error": "查询不能为空"}

    # 默认值从 pipe_cfg.yaml 读取（参数显式传入时优先）
    if top_k is None:
        top_k = SEARCH_TOP_K
    if top_k < 1:
        top_k = 1
    if top_k > 100:
        top_k = 100
    if score_threshold is None:
        score_threshold = SEARCH_SCORE_THRESHOLD
    if model is None:
        # 交给 _embed 统一解析（含 KB_EMBED_MODEL 环境变量），与索引时模型一致
        model = None

    # 嵌入查询
    try:
        query_vec = _embed([query], model=model)[0]
    except Exception as e:
        return {"ok": False, "error": f"嵌入查询失败: {e}"}

    # 构建过滤条件（分面过滤）
    qdrant_filter, filter_warnings = _build_qdrant_filter(facet_filter)

    # ── 搜索 Qdrant（原生混合查询：稠密 + 稀疏 → RRF 融合）──
    try:
        results = _query_qdrant_rrf(query, query_vec, top_k, qdrant_filter, score_threshold, collection)
    except Exception as e:
        return {"ok": False, "error": f"搜索失败: {e}"}

    # ── 整理结果（v4.0 分组字段）──
    chunks = []
    for r in results:
        payload = r.get("payload", {})
        _title = payload.get("title") or payload.get("source") or ""
        _source = payload.get("source") or ""
        chunks.append({
            "text":            payload.get("text", ""),
            "title":           _title,
            "source":          _source,
            "score":           round(r.get("score", 0), 4),
            "chunk_index":     payload.get("chunk_index", 0),
            "total_chunks":    payload.get("total_chunks", 0),
            "doc_id":          payload.get("doc_id", ""),
            "content_hash":    payload.get("content_hash", ""),
            "images":          payload.get("images", []),
            "content_type":    payload.get("content_type", "knowledge"),
            "domain":          payload.get("domain", []),
            "temporal_nature": payload.get("temporal_nature", "timeboxed"),
            "epistemic_status":payload.get("epistemic_status", "unverified"),
            "lifecycle":       payload.get("lifecycle", ""),
            "source_project":  payload.get("source_project", ""),
            "udc_code":        payload.get("udc_code", ""),
            "is_personal":     payload.get("is_personal", False),
            "trust_score":     payload.get("trust_score", 3),
            "knowledge_type":  payload.get("knowledge_type", ""),
            "subject":         payload.get("subject", ""),
            "is_canonical":    payload.get("is_canonical", True),
            "relations":       payload.get("relations", []),
            "keywords":        payload.get("keywords", []),
            "auto_summary":    payload.get("auto_summary", ""),
            "needs_review":   payload.get("needs_review", False),
            "timeline":        payload.get("timeline", {}),
            "origin":          payload.get("origin", {}),
            "stats":           payload.get("stats", {}),
            "target_platform": payload.get("target_platform", "none"),
            "related_product": payload.get("related_product", ""),
            "version":         payload.get("version", ""),
            "language":        payload.get("language", "zh"),
            "access_level":    payload.get("access_level", "private"),
            "batch_id":        payload.get("batch_id", ""),
            "is_archived":     payload.get("is_archived", False),
            "ingest_conf":     payload.get("ingest_conf", None),
            "field_sources":   payload.get("field_sources", {}),
            "rerank_score":   r.get("rerank_score", None),
            # 书库位置指针（章节 / 段落）——供搜索卡片显示「第X章·标题·第N段」
            "chapter_index":   payload.get("chapter_index", 0),
            "chapter_title":   payload.get("chapter_title", ""),
            "chunk_in_chapter":payload.get("chunk_in_chapter", 0),
        })

    # ── v0.8.0 / Q1 fix: 按 doc_id 分组，每文档保留 Top-N chunks ──
    if chunks:
        doc_groups = {}
        for c in chunks:
            did = c["doc_id"]
            if did not in doc_groups:
                doc_groups[did] = {"best_score": c["score"], "chunks": [], "total_in_results": 0}
            doc_groups[did]["total_in_results"] += 1
            if c["score"] > doc_groups[did]["best_score"]:
                doc_groups[did]["best_score"] = c["score"]
            doc_groups[did]["chunks"].append(c)
        result = []
        for did, g in doc_groups.items():
            sorted_chunks = sorted(g["chunks"], key=lambda x: x["score"], reverse=True)
            for ch in sorted_chunks[:SEARCH_CHUNKS_PER_DOC]:
                ch["group_chunks_count"] = g["total_in_results"]
                result.append((g["best_score"], ch))
        result.sort(key=lambda x: x[0], reverse=True)
        chunks = [ch for _, ch in result]

    return {
        "ok": True,
        "query": query,
        "total": len(chunks),
        "chunks": chunks,
        "warnings": filter_warnings if filter_warnings else [],
    }
