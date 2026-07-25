"""
Citrinitas 分面分类 + 完整字段定义 — Faceted Classification Schema v5.1


设计原则：
  - 分面分类（Faceted Classification）替代传统层级分类法
  - 4个独立分面：内容类型 / 主题域(UDC) / 时效属性 / 认知验证状态
  - 分组字段：relations / timeline / origin / stats（语义聚拢，减少字段数）
  - 每个分面的值可独立扩展，无需修改数据结构
  - 总字段数：36 个（28 个活跃字段 + 10 个预留扩展槽位）
  - 所有活跃字段 100% 自动填充，字段来源分四象限（见下方）

存储方案：单集合（athanor_v1）+ Payload 过滤

═══════════════════════════════════════════
字段来源四象限（Field Source Classification）
═══════════════════════════════════════════

象限一 — 文件自带（File-originated，置信度 1.0）
  从文件元数据层提取，优先级最高。当与 AI 推断冲突时，文件自带优先。
  字段: title, origin.author, origin.source_url, origin.file_type, source,
        timeline.published, version, timeline.effective

象限二 — AI 推断（AI-inferred，置信度由 LLM 返回）
  LLM 分析文本语义推断。当文件无对应元数据时，AI 作为后备来源。
  字段: content_type, domain, temporal_nature, epistemic_status, udc_code,
        keywords, auto_summary, trust_score, knowledge_type, is_personal, lifecycle

象限三 — 程序自动生成（System-generated，置信度 1.0）
  纯代码逻辑，确定性输出。
  字段: doc_id, content_hash, text, chunk_index, images, language,
        timeline.ingested, timeline.accessed, stats.access_count, stats.starred,
        origin.ingest_method, is_canonical, access_level, is_archived, batch_id

象限四 — 智能默认值（Smart defaults，置信度 0.0）
  当前无法自动确定，填入占位值等待未来进化。
  字段: target_platform, related_product, relations,
        timeline.expiry, + 10 预留扩展槽位

填充优先级: 文件自带 > AI 推断 > 智能默认值
程序自动生成字段与其他三类无重叠，不存在优先级冲突。

═══════════════════════════════════════════

v5.1 变更（2026-06-17）:
  - 新增四象限字段来源分类（即本文档顶部章节）
  - 明确 36 = 28活跃 + 10扩展槽位
  - title/author 填充优先级：文件自带 > AI 推断

v5.0 变更（2026-06-16）:
  - domain: 自定义9域 → UDC 9主类
  - 分面3: lifecycle → temporal_nature（lifecycle 降级为普通字段）
  - 分面4: project_source → epistemic_status（project_source 已废弃，溯源改由 hook 写 source_project；tags 已废弃，形式题材由 subject 接管）
  - 移除: objectivity（被 content_type + epistemic_status 联合覆盖）
"""

# ═══════════════════════════════════════════
# 分面1：内容类型（content_type）— 必填
# 覆盖：文档/视频脚本/书籍/论文/标准/网页/笔记/其它
# ═══════════════════════════════════════════
CONTENT_TYPES = {
    "knowledge":     "知识条目（从文档/书籍/论文提取的结构化知识点）",
    "document":      "原始文档（PDF/Word/TXT，未提取知识）",
    "video_script":  "视频脚本（B站/抖音等）",
    "social_post":   "社媒文案（小红书/公众号/微博）",
    "article":       "文章/博客",
    "book":          "书籍章节或全文",
    "paper":         "学术论文/期刊",
    "standard":      "标准/规范文件（国标/ISO/行业规范）",
    "webpage":       "网页内容（爬虫或手动保存）",
    "personal_note": "个人笔记（学习/心得/日记）",
    "project_note":  "项目笔记（工作日志/项目记录）",
    "idea":          "想法/灵感（未成形的点子）",
    "template":      "模板（脚本模板/文档模板）",
    "legal_doc":     "法律文件（合同/证书/专利）",
    "other":         "其它（无法归类的内容）",
}

CONTENT_TYPE_OPTIONS = [
    ("knowledge",     "📖 知识条目"),
    ("document",      "📄 原始文档"),
    ("video_script",  "🎬 视频脚本"),
    ("social_post",   "📱 社媒文案"),
    ("article",       "📰 文章/博客"),
    ("book",          "📚 书籍"),
    ("paper",         "📑 学术论文"),
    ("standard",      "📜 标准/规范"),
    ("webpage",       "🌐 网页内容"),
    ("personal_note", "📝 个人笔记"),
    ("project_note",  "📋 项目笔记"),
    ("idea",          "💡 想法/灵感"),
    ("template",      "📐 模板"),
    ("legal_doc",     "⚖️ 法律文件"),
    ("other",         "📦 其它"),
]


# ═══════════════════════════════════════════
# 分面2：主题域（domain）— 必填，UDC 9 主类
# 基于国际十进分类法（UDC），9 个主类，支持多选
# 细分 UDC 码存为普通字段 udc_code，不入分面
# ═══════════════════════════════════════════
DOMAINS = {
    "0": "总论、信息科学（计算机、AI、知识管理、标准）",
    "1": "哲学、心理学（认知、个人成长）",
    "2": "宗教、神学",
    "3": "社会科学（法律、经济、管理、教育）",
    "5": "数学、自然科学（数学、物理、化学、生物）",
    "6": "应用科学、技术（机械、电气、通信、建筑、医疗）",
    "7": "艺术、文体（设计、影视、音乐）",
    "8": "语言、文学（写作、出版、语言学）",
    "9": "历史、地理（传记、技术史）",
}

DOMAIN_OPTIONS = [
    ("0", "📚 总论·信息科学"),
    ("1", "🧠 哲学·心理学"),
    ("2", "⛪ 宗教·神学"),
    ("3", "🏛️ 社会科学"),
    ("5", "🔬 数学·自然科学"),
    ("6", "⚙️ 应用科学·技术"),
    ("7", "🎨 艺术·文体"),
    ("8", "📝 语言·文学"),
    ("9", "📅 历史·地理"),
]


# ═══════════════════════════════════════════
# 生命周期（lifecycle）— 普通字段（非分面），可选
# v5.0: 从分面降级为普通字段，仍可 filter
# ═══════════════════════════════════════════
LIFECYCLE_STAGES = {
    "idea":        "想法阶段",
    "draft":       "草稿阶段",
    "in_progress": "进行中",
    "review":      "审核中",
    "published":   "已发布",
    "archived":    "已归档",
}

LIFECYCLE_OPTIONS = [
    ("idea",        "💡 想法"),
    ("draft",       "📝 草稿"),
    ("in_progress", "🔨 进行中"),
    ("review",      "👀 审核中"),
    ("published",   "✅ 已发布"),
    ("archived",    "📦 已归档"),
]


# ═══════════════════════════════════════════
# 分面3：时效属性（temporal_nature）— 必填
# 借鉴 RMS-Ltd doc-lifecycle-metadata-spec
# ═══════════════════════════════════════════
TEMPORAL_NATURE = {
    "evergreen": "常青 — 长期有效，不随时间贬值（数学定理、设计原则、标准参数）",
    "timeboxed": "有时限 — 一段时间内有效，之后可能过期（行业最佳实践、当前国标版本）",
    "transient": "时效敏感 — 会快速过时（行业动态、产品发布信息、趋势预测）",
}

TEMPORAL_NATURE_OPTIONS = [
    ("evergreen", "🌲 常青"),
    ("timeboxed", "⏳ 有时限"),
    ("transient", "⚡ 时效敏感"),
]


# ═══════════════════════════════════════════
# 分面4：认知验证状态（epistemic_status）— 必填
# 基于 FPF（First Principles Framework），arxiv 2601.21116
# L0 猜想 → L1 逻辑验证 → L2 实证验证
# ═══════════════════════════════════════════
EPISTEMIC_STATUS = {
    "unverified":     "L0 猜想 — 未验证的假设、个人意见、原始笔记",
    "substantiated":  "L1 逻辑验证通过 — 逻辑自洽，但缺外部实证",
    "corroborated":   "L2 实证验证 — 引用标准/论文/实验数据/法规",
    "rejected":       "已证伪 — 自相矛盾/经核验确为虚假（卖课谎言等，源自炼真 Albedo）",
}

EPISTEMIC_STATUS_OPTIONS = [
    ("unverified",    "❓ L0 猜想"),
    ("substantiated", "🔍 L1 逻辑验证"),
    ("corroborated",  "✅ L2 实证验证"),
    ("rejected",      "🚫 已证伪"),
]


# ═══════════════════════════════════════════
# 知识子类型（knowledge_type）
# 由 classify_pipeline._derive_knowledge_type 确定性推导（source="rule"）：
#   - 仅对「知识承载型」content_type 推导（standard/paper/book/legal_doc/knowledge/
#     video_script/social_post/article/personal_note/project_note/idea）
#   - 容器型（document/webpage/other/template）结构不适用 → 留空
#   - 硬类型扫结构/全文本，软类型（易偏差）仅扫标题锚定，多命中按 method>case>principle>concept
# 不再交给 LLM 兜底，彻底消除同文档多次摄入漂移。
# ═══════════════════════════════════════════
KNOWLEDGE_TYPES = {
    "principle":   "原理",
    "formula":     "公式",
    "case":        "案例",
    "standard":    "标准/规范",
    "concept":     "概念/定义",
    "method":      "方法/流程",
    "data":        "数据/参数",
    "reference":   "参考文献",
    "procedure":   "工序/工艺",
    "requirement": "需求/规格",
    "test_data":   "测试数据",
}

KNOWLEDGE_TYPE_OPTIONS = [
    ("principle",   "📐 原理"),
    ("formula",     "🔢 公式"),
    ("case",        "📋 案例"),
    ("standard",    "📜 标准/规范"),
    ("concept",     "💡 概念/定义"),
    ("method",      "🔧 方法/流程"),
    ("data",        "📊 数据/参数"),
    ("reference",   "📚 参考文献"),
    ("procedure",   "⚙️ 工序/工艺"),
    ("requirement", "📋 需求/规格"),
    ("test_data",   "🧪 测试数据"),
]


# ═══════════════════════════════════════════
# 关系类型（relations 分组字段内的 type）
# ═══════════════════════════════════════════
RELATION_TYPES = {
    "similar":      "相似内容",
    "references":   "引用",
    "contradicts":  "矛盾/冲突",
    "derived_from": "衍生自",
    "merged_into":  "已合并到",
    "supersedes":   "替代/取代",
    "depends_on":   "依赖",
}


# ═══════════════════════════════════════════
# 摄入方式（origin.ingest_method）
# ═══════════════════════════════════════════
INGEST_METHODS = {
    "upload":  "UI上传",
    "email":   "邮件摄入",
    "api":     "API调用",
    "crawler": "爬虫",
    "manual":  "手动输入",
}


# ═══════════════════════════════════════════
# 可信度（trust_score）选项
# ═══════════════════════════════════════════
TRUST_SCORE_LABELS = {
    0: "未评级（默认值，表示尚未评估）",
    5: "⭐⭐⭐⭐⭐ 权威来源（国家标准/教科书/官方手册）",
    4: "⭐⭐⭐⭐ 可信来源（同行评审论文/官方文档）",
    3: "⭐⭐⭐ 一般来源（技术博客/个人经验）",
    2: "⭐⭐ 待验证（网络信息/未经核实）",
    1: "⭐ 存疑（矛盾/待 Crucible 验证）",
}


# ═══════════════════════════════════════════
# 语言（language）
# ═══════════════════════════════════════════
LANGUAGES = {
    "zh":    "中文",
    "en":    "English",
    "mixed": "中英混合",
}
LANGUAGE_OPTIONS = [(k, v) for k, v in LANGUAGES.items()]


# ═══════════════════════════════════════════
# 访问权限（access_level）
# ═══════════════════════════════════════════
ACCESS_LEVELS = {
    "private": "仅自己",
    "team":    "团队可见（未来）",
    "public":  "公开（未来）",
}
ACCESS_LEVEL_OPTIONS = [(k, v) for k, v in ACCESS_LEVELS.items()]


# ═══════════════════════════════════════════
# 目标平台（target_platform）— 内容分发的目标平台
# ═══════════════════════════════════════════
TARGET_PLATFORMS = {
    "none":     "无特定平台",
    "bilibili": "B站",
    "douyin":   "抖音",
    "xiaohongshu": "小红书",
    "wechat":   "微信公众号",
    "weibo":    "微博",
    "zhihu":    "知乎",
    "blog":     "个人博客",
    "internal": "内部使用",
}
TARGET_PLATFORM_OPTIONS = [(k, v) for k, v in TARGET_PLATFORMS.items()]


# ═══════════════════════════════════════════
# 许可证（license）— 未来用，暂存 ext_text1
# ═══════════════════════════════════════════
LICENSE_TYPES = {
    "private":   "私有",
    "cc0":       "CC0 公共领域",
    "cc_by":     "CC BY 署名",
    "cc_by_sa":  "CC BY-SA 署名相同方式共享",
    "fair_use":  "合理引用",
}


# ═══════════════════════════════════════════
# T2: 规则引擎 — CLASSIFY_RULES
# 覆盖 4 个分面字段，关键词 + 正则双路径匹配
# 命中即定值，100% 可复现，不依赖 LLM
# ═══════════════════════════════════════════
CLASSIFY_RULES = {
    # ── content_type ──
    "content_type": [
        {"value": "standard", "keywords": ["国家标准", "行业标准", "企业标准", "标准化", "规范文件", "技术规范", "国标"],
         "patterns": [r"GB/T\s*\d+", r"GB\s*\d+", r"ISO\s*\d+", r"IEC\s*\d+", r"标准(?!的)", r"规范(?!的)"]},
        {"value": "paper", "keywords": ["摘要", "参考文献", "arXiv", "引言", "结论", "abstract", "references"],
         "patterns": [r"doi:\s*10\.", r"arXiv:\s*\d+"]},
        {"value": "book", "keywords": ["前言", "序言", "后记", "目录", "第版"],
         "patterns": [r"第[一二三四五六七八九十\d]+章"]},
        # idea 规则放在 video_script/personal_note 之前，避免"收藏""笔记"等词误抢灵感
        {"value": "idea", "keywords": ["灵感", "点子", "突发奇想", "突然想到", "也许可以",
                                        "要不试试", "TODO", "待办", "备忘", "一闪念",
                                        "想法是", "有个想法"]},
        {"value": "video_script", "keywords": ["视频", "B站", "弹幕", "UP主", "点赞", "投币", "收藏", "剪辑"]},
        {"value": "social_post", "keywords": ["小红书", "公众号", "微博", "抖音", "种草", "安利"]},
        {"value": "personal_note", "keywords": ["日记", "心得", "笔记", "感想", "今天", "复盘"]},
        {"value": "legal_doc", "keywords": ["合同", "协议", "甲方", "乙方", "条款", "专利号"]},
        {"value": "template", "keywords": ["模板", "模板格式", "填空"]},
    ],
    # ── domain (UDC 9 主类) ──
    "domain": [
        {"value": "0", "keywords": ["llm", "算法", "编程", "python", "数据", "知识管理", "标准", "计算机", "人工智能", "深度学习", "神经网络", "数据库", "软件"]},
        {"value": "1", "keywords": ["哲学", "认知", "心理", "冥想", "成长", "自我", "意识", "思维"]},
        {"value": "2", "keywords": ["宗教", "神学", "信仰", "佛", "道", "圣经"]},
        {"value": "3", "keywords": ["法律", "经济", "管理", "教育", "合同", "财务", "投资", "营销", "团队"]},
        {"value": "5", "keywords": ["数学", "物理", "化学", "生物", "定理", "公式", "量子", "分子", "实验"]},
        {"value": "6", "keywords": ["齿轮", "模数", "机械", "电机", "轴承", "建筑", "医疗", "通信", "电气", "传动", "强度", "公差", "材料", "制造", "工程", "电路", "传感器"]},
        {"value": "7", "keywords": ["设计", "影视", "音乐", "排版", "配色", "构图", "摄影", "动画", "美术"]},
        {"value": "8", "keywords": ["写作", "语法", "翻译", "出版", "修辞", "小说", "散文", "诗词"]},
        {"value": "9", "keywords": ["历史", "传记", "地理", "考古", "年表", "年代", "战争史"]},
    ],
    # ── temporal_nature ──
    "temporal_nature": [
        {"value": "evergreen", "keywords": ["公式", "定理", "定律", "公理", "原理", "基础理论"],
         "patterns": [r"[A-Za-z]\s*=\s*[\d]", r"σ\s*=", r"F\s*=\s*m"]},
        {"value": "transient", "keywords": ["新闻", "趋势", "2024", "2025", "2026"],
         "patterns": [r"\d{4}年\d{1,2}月"]},
        {"value": "timeboxed", "keywords": ["版本", "规范", "指南", "best practice", "最佳实践"]},
    ],
    # ── epistemic_status ──
    "epistemic_status": [
        {"value": "corroborated", "keywords": ["国标", "标准", "ISO", "论文", "实验", "数据", "研究", "GB/T", "doi"],
         "patterns": [r"GB/T\s*\d+", r"ISO\s*\d+", r"doi:\s*10\."]},
        {"value": "unverified", "keywords": ["我认为", "我觉得", "猜测", "可能", "也许", "大概", "猜测", "个人认为"]},
        {"value": "substantiated", "keywords": ["推导", "证明", "逻辑", "因此", "综上所述", "由此可得"]},
    ],
}


# ═══════════════════════════════════════════
# 兼容层：保留旧接口
# ═══════════════════════════════════════════
CLASSIFICATION_SCHEMES = {
    "faceted": {
        "label":  "faceted 分面分类（推荐）",
        "desc":   "多维度标签式分类，适合混合内容类型",
        "detail": (
            "4 个分面：内容类型(15) / 主题域-UDC(9) / 时效属性(3) / 认知验证状态(3)\n"
            "28 个活跃字段 + 10 个预留扩展槽位：分组设计（relations/timeline/origin/stats）"
        ),
        "collections": {"athanor_v1": "全部分面分类内容"},
    }
}
DEFAULT_SCHEME = "faceted"
DEFAULT_COLLECTION = "athanor_v1"


# ═══════════════════════════════════════════
# 域迁移映射（旧 9 域 → UDC 9 主类）
# 用于数据迁移脚本
# ═══════════════════════════════════════════
DOMAIN_MIGRATION_MAP = {
    "机械设计":   ["6"],    # 应用科学·技术 → 机械
    "智能家居":   ["6"],    # 应用科学·技术 → 电气/通信
    "AI编程":     ["0"],    # 总论·信息科学 → 计算机/AI
    "内容创作":   ["7"],    # 艺术·文体
    "企业管理":   ["3"],    # 社会科学 → 管理
    "个人成长":   ["1"],    # 哲学·心理学
    "出版写作":   ["8"],    # 语言·文学
    "法律专利":   ["3"],    # 社会科学 → 法律
    "标准规范":   ["0", "6"],  # 总论(标准) + 应用科学
}


# ═══════════════════════════════════════════
# 重新导出（实现位于 config/normalize.py，此处保持向后兼容）
# ═══════════════════════════════════════════
from config.normalize import normalize_facet_values, FUZZY_FACET_MAPPING  # noqa: E402, F401

