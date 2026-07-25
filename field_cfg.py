"""
文档注入 — 字段显示配置表（驱动卡片式结果面板）
由 main.py 通过 `from field_cfg import FIELD_DISPLAY_CFG, SOURCE_ICON, PANEL_VALUES` 导入。
"""

import config.classifications as classifications


# ════════════════════════════════════════
# 每个字段的配置：
#   zh:           中文显示名
#   group:        分组（决定面板里的展示区域）
#   required:      是否必填（暂未使用，预留）
#   editable:     用户在面板里能否点击修改
#   widget:       编辑对话框里用的组件类型
#   options:       下拉选项列表 [(value, label), ...]（widget=select/multiselect 时需要）
#   display_map:   英文值 → 面板里显示的中文/图标（只读字段不需要）
# ════════════════════════════════════════

FIELD_DISPLAY_CFG = {
    # ── 分组1：分面分类（4个，始终展示）──
    "content_type": {
        "zh": "内容类型",
        "group": "分面分类",
        "required": True,
        "editable": True,
        "widget": "select",
        "options": classifications.CONTENT_TYPE_OPTIONS,
        "display_map": {v: l for v, l in classifications.CONTENT_TYPE_OPTIONS},
    },
    "domain": {
        "zh": "主题域",
        "group": "分面分类",
        "required": True,
        "editable": True,
        "widget": "multiselect",
        "options": classifications.DOMAIN_OPTIONS,
        "display_map": {v: l for v, l in classifications.DOMAIN_OPTIONS},
    },
    "temporal_nature": {
        "zh": "时效属性",
        "group": "分面分类",
        "required": True,
        "editable": True,
        "widget": "select",
        "options": classifications.TEMPORAL_NATURE_OPTIONS,
        "display_map": {v: l for v, l in classifications.TEMPORAL_NATURE_OPTIONS},
    },
    "epistemic_status": {
        "zh": "认知验证",
        "group": "分面分类",
        "required": True,
        "editable": True,
        "widget": "select",
        "options": classifications.EPISTEMIC_STATUS_OPTIONS,
        "display_map": {v: l for v, l in classifications.EPISTEMIC_STATUS_OPTIONS},
    },

    # ── 分组2：内容标识（4个，始终展示）──
    "title": {
        "zh": "标题",
        "group": "内容标识",
        "required": False,
        "editable": True,
        "widget": "input",
        "display_map": {},
    },
    "keywords": {
        "zh": "关键词",
        "group": "内容标识",
        "required": False,
        "editable": True,
        "widget": "input_chips",
        "display_map": {},
    },
    "auto_summary": {
        "zh": "自动摘要",
        "group": "内容标识",
        "required": False,
        "editable": False,
        "widget": "label_multiline",
        "display_map": {},
    },
    "author": {
        "zh": "作者",
        "group": "内容标识",
        "required": False,
        "editable": True,
        "widget": "input",
        "display_map": {},
    },

    # ── 分组3：知识属性（6个，高级选项）──
    "lifecycle": {
        "zh": "工作流阶段",
        "group": "知识属性",
        "required": False,
        "editable": True,
        "widget": "select",
        "options": classifications.LIFECYCLE_OPTIONS,
        "display_map": {v: l for v, l in classifications.LIFECYCLE_OPTIONS},
    },
    "knowledge_type": {
        "zh": "知识类型",
        "group": "知识属性",
        "required": False,
        "editable": True,
        "widget": "select",
        "options": classifications.KNOWLEDGE_TYPE_OPTIONS,
        "display_map": {v: l for v, l in classifications.KNOWLEDGE_TYPE_OPTIONS},
    },
    "is_personal": {
        "zh": "是否个人",
        "group": "知识属性",
        "required": False,
        "editable": True,
        "widget": "switch",
        "display_map": {True: "👤 个人", False: "🌐 公开"},
    },
    "trust_score": {
        "zh": "可信度",
        "group": "知识属性",
        "required": False,
        "editable": True,
        "widget": "slider",
        "display_map": {
            0: "⭐ 未评级",
            1: "⭐",
            2: "⭐⭐",
            3: "⭐⭐⭐",
            4: "⭐⭐⭐⭐",
            5: "⭐⭐⭐⭐⭐",
        },
    },
    "source_project": {
        "zh": "来源项目",
        "group": "知识属性",
        "required": False,
        "editable": True,
        "widget": "input",
        "display_map": {},
    },
    "udc_code": {
        "zh": "UDC 细分码",
        "group": "知识属性",
        "required": False,
        "editable": True,
        "widget": "input",
        "display_map": {},
    },

    # ── 分组4：来源信息（3个，高级选项）──
    "source": {
        "zh": "来源名称",
        "group": "来源信息",
        "required": False,
        "editable": False,
        "widget": "label",
        "display_map": {},
    },
    "language": {
        "zh": "语言",
        "group": "来源信息",
        "required": False,
        "editable": True,
        "widget": "select",
        "options": [("zh", "🇨🇳 中文"), ("en", "🇺🇸 英文"), ("ja", "🇯🇵 日文"), ("ko", "🇰🇷 韩文")],
        "display_map": {"zh": "🇨🇳 中文", "en": "🇺🇸 英文", "ja": "🇯🇵 日文", "ko": "🇰🇷 韩文"},
    },
    "origin.source_url": {
        "zh": "来源链接",
        "group": "来源信息",
        "required": False,
        "editable": True,
        "widget": "input",
        "display_map": {},
    },

    # ── 分组5：时间戳（2个，高级选项）──
    "timeline.published": {
        "zh": "发布时间",
        "group": "时间戳",
        "required": False,
        "editable": True,
        "widget": "date",
        "display_map": {},
    },
    "timeline.effective": {
        "zh": "生效时间",
        "group": "时间戳",
        "required": False,
        "editable": True,
        "widget": "date",
        "display_map": {},
    },
}


# 来源图标映射（来源徽章用）
SOURCE_ICON = {
    "file":    "📎",
    "rule":    "📐",
    "llm":     "🤖",
    "user":    "👤",
    "default":  "⚙️",
    "system":   "⚙️",
}


# 面板当前值缓存（全局，页面刷新后需重新 AI 分析）
PANEL_VALUES = {}
