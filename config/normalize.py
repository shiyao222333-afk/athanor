"""
Enum Guard — 模糊映射表 + 分面值规范化。

【小白导读 · 这个文件干嘛的？】
  "枚举守卫"= 给文档分类的"固定选项表"。AI 给文档打的类别（内容类型/领域/时效/可信度等）
  必须落在固定几种里，不能乱写。这个文件就是把 AI 写偏的词纠正回标准词。
  例：AI 写"社媒文案"→ 纠正成标准词 "social_post"。术语不懂看 docs/GLOSSARY.md。

Extracted from config/classifications.py (v0.7.0 B1 refactor).

管道位置:
  LLM 返回 → normalize_facet_values() → 严格枚举值 → 写入 Qdrant

职责:
  FUZZY_FACET_MAPPING  — LLM 常见跑偏 → 标准 key 的映射表
  normalize_facet_values() — 枚举守卫主函数
"""


# ════════════════════════════════════════════
# G1: 模糊映射表（LLM 常见跑偏 → 标准 key）
# 中文/英文各种写法都映射到同一个标准词，AI 写偏也能纠正回来
# ════════════════════════════════════════════
FUZZY_FACET_MAPPING = {
    "content_type": {
        # 中文 → 标准 key
        "视频脚本": "video_script",
        "社媒文案": "social_post",
        "社媒":     "social_post",
        "文章":     "article",
        "博客":     "article",
        "书籍":     "book",
        "书":       "book",
        "论文":     "paper",
        "学术论文": "paper",
        "期刊":     "paper",
        "标准":     "standard",
        "规范":     "standard",
        "国标":     "standard",
        "网页":     "webpage",
        "网页内容": "webpage",
        "网站":     "webpage",
        "笔记":     "personal_note",
        "个人笔记": "personal_note",
        "项目笔记": "project_note",
        "想法":     "idea",
        "灵感":     "idea",
        "点子":     "idea",
        "模板":     "template",
        "法律文件": "legal_doc",
        "法律":     "legal_doc",
        "合同":     "legal_doc",
        "专利":     "legal_doc",
        "知识条目": "knowledge",
        "知识":     "knowledge",
        "原始文档": "document",
        "文档":     "document",
        "其它":     "other",
        "其他":     "other",
        # 英文变体 → 标准 key
        "video script":      "video_script",
        "video_scripts":    "video_script",
        "social media":     "social_post",
        "social post":      "social_post",
        "webpage":          "webpage",
        "web page":         "webpage",
        "personal note":    "personal_note",
        "project note":     "project_note",
        "idea":             "idea",
        "thought":          "idea",
        "template":         "template",
        "legal":            "legal_doc",
        "knowledge":        "knowledge",
        "document":         "document",
        "other":            "other",
    },
    "domain": {
        # 中文描述 → UDC 代码
        "总论":         "0",
        "信息科学":       "0",
        "计算机":         "0",
        "ai":            "0",
        "人工智能":       "0",
        "知识管理":       "0",
        "标准":          "0",
        "哲学":          "1",
        "心理学":        "1",
        "认知":          "1",
        "个人成长":       "1",
        "宗教":          "2",
        "神学":          "2",
        "社会科学":       "3",
        "法律":          "3",
        "经济":          "3",
        "管理":          "3",
        "教育":          "3",
        "数学":          "5",
        "自然科学":       "5",
        "物理":          "5",
        "化学":          "5",
        "生物":          "5",
        "应用科学":       "6",
        "技术":          "6",
        "机械":          "6",
        "电气":          "6",
        "通信":          "6",
        "建筑":          "6",
        "医疗":          "6",
        "艺术":          "7",
        "文体":          "7",
        "设计":          "7",
        "影视":          "7",
        "音乐":          "7",
        "语言":          "8",
        "文学":          "8",
        "写作":          "8",
        "出版":          "8",
        "语言学":        "8",
        "历史":          "9",
        "地理":          "9",
        "传记":          "9",
        "技术史":        "9",
        # 英文描述 → UDC 代码
        "general":          "0",
        "computer science": "0",
        "ai":               "0",
        "philosophy":       "1",
        "psychology":       "1",
        "religion":         "2",
        "theology":         "2",
        "social science":   "3",
        "law":              "3",
        "economics":        "3",
        "management":       "3",
        "education":        "3",
        "mathematics":      "5",
        "physics":          "5",
        "chemistry":        "5",
        "biology":          "5",
        "engineering":      "6",
        "technology":       "6",
        "mechanical":       "6",
        "electrical":       "6",
        "medical":          "6",
        "art":              "7",
        "music":            "7",
        "language":         "8",
        "literature":       "8",
        "writing":          "8",
        "history":          "9",
        "geography":        "9",
    },
    "temporal_nature": {
        "常青":     "evergreen",
        "永久有效":   "evergreen",
        "长期有效":   "evergreen",
        "不过时":    "evergreen",
        "有时限":    "timeboxed",
        "限时":     "timeboxed",
        "会过期":    "timeboxed",
        "时效敏感":   "transient",
        "快速过时":   "transient",
        "短期有效":   "transient",
        "动态":     "transient",
        "evergreen": "evergreen",
        "timeboxed": "timeboxed",
        "transient": "transient",
    },
    "epistemic_status": {
        "L0":          "unverified",
        "L1":          "substantiated",
        "L2":          "corroborated",
        "l0":          "unverified",
        "l1":          "substantiated",
        "l2":          "corroborated",
        "未验证":      "unverified",
        "猜想":       "unverified",
        "假设":       "unverified",
        "个人意见":     "unverified",
        "原始笔记":     "unverified",
        "逻辑验证":     "substantiated",
        "逻辑自洽":     "substantiated",
        "缺实证":      "substantiated",
        "实证验证":     "corroborated",
        "已验证":      "corroborated",
        "有引用":      "corroborated",
        "标准":       "corroborated",
        "论文":       "corroborated",
        "实验数据":     "corroborated",
        "法规":       "corroborated",
        "unverified":    "unverified",
        "substantiated": "substantiated",
        "corroborated":  "corroborated",
        "rejected":      "rejected",
        "证伪":          "rejected",
        "已证伪":        "rejected",
        "虚假":          "rejected",
        "确认虚假":      "rejected",
    },
    "knowledge_type": {
        # 中文 → 标准 key
        "原理":       "principle",
        "公式":       "formula",
        "案例":       "case",
        "标准":       "standard",
        "规范":       "standard",
        "概念":       "concept",
        "定义":       "concept",
        "方法":       "method",
        "流程":       "method",
        "数据":       "data",
        "参数":       "data",
        "参考文献":   "reference",
        "参考":       "reference",
        "工序":       "procedure",
        "工艺":       "procedure",
        "需求":       "requirement",
        "规格":       "requirement",
        "测试数据":   "test_data",
        "测试":       "test_data",
        "实验数据":   "test_data",
        # 英文变体 → 标准 key
        "principle":       "principle",
        "formula":         "formula",
        "formulae":        "formula",
        "case":            "case",
        "case study":      "case",
        "案例研究":         "case",
        "规范标准":         "standard",
        "concept":         "concept",
        "definition":      "concept",
        "method":          "method",
        "methodology":     "method",
        "process":         "method",
        "workflow":        "method",
        "data":            "data",
        "parameter":       "data",
        "dataset":         "data",
        "reference":       "reference",
        "citation":        "reference",
        "procedure":       "procedure",
        "operation":       "procedure",
        "requirement":     "requirement",
        "specification":   "requirement",
        "spec":            "requirement",
        "test data":       "test_data",
        "test_data":       "test_data",
        "testing":         "test_data",
    },
    "lifecycle": {
        # 中文 → 标准 key
        "想法": "idea",
        "点子": "idea",
        "构思": "idea",
        "草稿": "draft",
        "拟稿": "draft",
        "初稿": "draft",
        "进行中": "in_progress",
        "开发中": "in_progress",
        "编写中": "in_progress",
        "制作中": "in_progress",
        "审核中": "review",
        "评审中": "review",
        "待审": "review",
        "审阅": "review",
        "已发布": "published",
        "发布": "published",
        "上线": "published",
        "正式": "published",
        "已归档": "archived",
        "归档": "archived",
        "存档": "archived",
        # 英文变体 → 标准 key
        "idea": "idea",
        "draft": "draft",
        "in progress": "in_progress",
        "in_progress": "in_progress",
        "review": "review",
        "reviewing": "review",
        "published": "published",
        "archived": "archived",
    },
}


def _fuzzy(value: str, mapping: dict) -> str | None:
    """查 FUZZY_FACET_MAPPING，返回标准 key 或 None。"""
    if not value or not mapping:
        return None
    v = value.strip()
    # 1. 精确匹配（区分大小写）
    if v in mapping:
        return mapping[v]
    # 2. 大小写不敏感匹配
    v_lower = v.lower()
    for k, v2 in mapping.items():
        if k.lower() == v_lower:
            return v2
    # 3. 部分匹配（如 "视频脚本" in mapping keys）
    for k, v2 in mapping.items():
        if v in k or k in v:
            return v2
    return None


def normalize_facet_values(metadata: dict) -> dict:
    """
    枚举守卫：验证并规范化分面字段值。
    
    在 LLM 返回结果后、写入 Qdrant 前执行：
        LLM 返回 → normalize_facet_values() → 严格枚举值 → 写入 Qdrant
    
    核心逻辑：
        1. 查 FUZZY_FACET_MAPPING（LLM 常见跑偏 → 标准 key）
        2. 单选枚举 → 标准化 → 精确匹配 → fallback 默认值
        3. 多选列表 → 逐项标准化 → 去重
        4. 数值字段 → 确保在合法范围内
    
    返回：规范化后的 metadata（原地修改 + 返回）
    """
    # 惰性导入避免循环依赖（config/classifications.py 在底部导入本模块）
    from config.classifications import (
        CONTENT_TYPES, DOMAINS, TEMPORAL_NATURE,
        EPISTEMIC_STATUS, KNOWLEDGE_TYPES,
    )
    # ── content_type：单选，15 种 ──
    ct = metadata.get("content_type")
    if ct and isinstance(ct, str):
        ct_norm = ct.strip().lower().replace(" ", "_")
        # 1. 查模糊映射表
        mapped = _fuzzy(ct, FUZZY_FACET_MAPPING.get("content_type", {}))
        if mapped and mapped in CONTENT_TYPES:
            metadata["content_type"] = mapped
        # 2. 精确匹配
        elif ct_norm in CONTENT_TYPES:
            metadata["content_type"] = ct_norm
        # 3. 子串匹配
        else:
            for valid_key in CONTENT_TYPES.keys():
                if valid_key in ct_norm or ct_norm in valid_key:
                    metadata["content_type"] = valid_key
                    break
            else:
                metadata["content_type"] = "other"  # fallback
    
    # ── domain：多选列表，9 种 UDC 主类 ──
    dom = metadata.get("domain")
    if dom:
        if isinstance(dom, str):
            dom = [d.strip() for d in dom.split(",")]
        elif not isinstance(dom, list):
            dom = [str(dom)]
        normalized = []
        for d in dom:
            d_norm = d.strip()
            # 1. 查模糊映射表
            mapped = _fuzzy(d, FUZZY_FACET_MAPPING.get("domain", {}))
            if mapped and mapped in DOMAINS:
                normalized.append(mapped)
            # 2. 精确匹配
            elif d_norm in DOMAINS:
                normalized.append(d_norm)
            # 3. 子串匹配（中文描述）
            else:
                for valid_key in DOMAINS.keys():
                    if valid_key in d_norm or d_norm in valid_key:
                        normalized.append(valid_key)
                        break
        metadata["domain"] = list(dict.fromkeys(normalized))  # 去重保持顺序
    
    # ── temporal_nature：单选，3 种 ──
    tn = metadata.get("temporal_nature")
    if tn and isinstance(tn, str):
        tn_norm = tn.strip().lower()
        # 1. 查模糊映射表
        mapped = _fuzzy(tn, FUZZY_FACET_MAPPING.get("temporal_nature", {}))
        if mapped and mapped in TEMPORAL_NATURE:
            metadata["temporal_nature"] = mapped
        # 2. 精确匹配
        elif tn_norm in TEMPORAL_NATURE:
            metadata["temporal_nature"] = tn_norm
        # 3. 子串匹配
        else:
            for valid_key in TEMPORAL_NATURE.keys():
                if valid_key in tn_norm or tn_norm in valid_key:
                    metadata["temporal_nature"] = valid_key
                    break
            else:
                metadata["temporal_nature"] = "timeboxed"  # fallback
    
    # ── epistemic_status：单选，3 种 ──
    es = metadata.get("epistemic_status")
    if es and isinstance(es, str):
        es_norm = es.strip().lower()
        # 1. 查模糊映射表
        mapped = _fuzzy(es, FUZZY_FACET_MAPPING.get("epistemic_status", {}))
        if mapped and mapped in EPISTEMIC_STATUS:
            metadata["epistemic_status"] = mapped
        # 2. 精确匹配
        elif es_norm in EPISTEMIC_STATUS:
            metadata["epistemic_status"] = es_norm
        # 3. 子串匹配
        else:
            for valid_key in EPISTEMIC_STATUS.keys():
                if valid_key in es_norm or es_norm in valid_key:
                    metadata["epistemic_status"] = valid_key
                    break
            else:
                metadata["epistemic_status"] = "unverified"  # fallback
    
    # ── trust_score：数值，0-5 ──
    ts = metadata.get("trust_score")
    if ts is not None:
        try:
            ts_int = int(ts)
            metadata["trust_score"] = max(0, min(5, ts_int))
        except (ValueError, TypeError):
            metadata["trust_score"] = 3  # fallback 中等可信
    
    # ── knowledge_type：单选，11 种（仅 content_type="knowledge" 时有效）──
    kt = metadata.get("knowledge_type")
    if kt and isinstance(kt, str):
        kt_norm = kt.strip().lower().replace(" ", "_")
        # 1. 查模糊映射表
        mapped = _fuzzy(kt, FUZZY_FACET_MAPPING.get("knowledge_type", {}))
        if mapped and mapped in KNOWLEDGE_TYPES:
            metadata["knowledge_type"] = mapped
        # 2. 精确匹配
        elif kt_norm in KNOWLEDGE_TYPES:
            metadata["knowledge_type"] = kt_norm
        # 3. 子串匹配
        else:
            for valid_key in KNOWLEDGE_TYPES.keys():
                if valid_key in kt_norm or kt_norm in valid_key:
                    metadata["knowledge_type"] = valid_key
                    break
            else:
                metadata["knowledge_type"] = "concept"  # fallback
    
    return metadata


def normalize_lifecycle(value, default: str = "") -> str:
    """
    归一化 lifecycle（生命周期）字段（#41 补丁：枚举守卫原先漏掉了它）。
    lifecycle = 文档处于哪个阶段：想法/草稿/进行中/审核中/已发布/已归档。

    逻辑：
        1. 已是标准 key（idea/draft/in_progress/review/published/archived）→ 原样返回
        2. 查 FUZZY_FACET_MAPPING["lifecycle"]（中文/英文变体 → 标准 key）
        3. 子串兜底：标准 key 的中文标签（如 "已发布" in "已发布的状态"）
        4. 都不中 → fallback 默认空字符串（交由人工在第6类手动管理）

    返回标准 key，绝不抛异常、绝不写入非法值。
    """
    from config.classifications import LIFECYCLE_STAGES
    if not value:
        return default
    v = str(value).strip()
    # 1. 已是标准 key
    if v in LIFECYCLE_STAGES:
        return v
    # 2. 模糊映射（中文/英文变体）
    mapped = _fuzzy(v, FUZZY_FACET_MAPPING.get("lifecycle", {}))
    if mapped and mapped in LIFECYCLE_STAGES:
        return mapped
    # 3. 子串兜底（标准 key 的中文标签）
    for k, label in LIFECYCLE_STAGES.items():
        if k in v or v in label or label in v:
            return k
    return default
