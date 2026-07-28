# Athanor 知识库字段设计文档（Schema v5.1）

> ⚠️ **文档版本说明**：本文档追踪**字段设计**的版本（v1.0 → v2.0 → v4.0 → v5.0 → v5.1），
> 独立于项目版本。项目版本见 [PROJECT_PLAN.md](../PROJECT_PLAN.md)。

> 分面分类（Faceted Classification）+ 分组字段设计
> 总字段数：36 个（28 个活跃字段 + 10 个预留扩展槽位）
>
> 设计原则：
> - 语义相近的字段聚合成分组对象（relations / timeline / origin / stats）
> - 减少扁平字段数，提高可读性和可维护性
> - 预留扩展槽位覆盖未来未知需求
> - 所有活跃字段 100% 自动填充，无需人工介入（四象限来源：文件自带 / AI推断 / 程序生成 / 智能默认值）
>
> v5.1 变更（2026-06-17）：
> - 明确 36 字段 = 28 活跃 + 10 扩展槽位
> - 新增四象限字段来源分类（见文档 §七）
> - 确立 title/author 字段的填充优先级：文件自带 > AI 推断 > 程序兜底
>
> v5.0 重大变更（2026-06-16）：
> - domain: 自定义9域 → UDC 9主类（国际十进分类法）
> - 分面3: lifecycle → temporal_nature（lifecycle 降级为普通字段）
> - 分面4: project_source → epistemic_status（project_source 已废弃，溯源由 hook 写 source_project 取代；tags 已废弃，形式题材由 subject 接管）
> - 移除: objectivity（被 content_type + epistemic_status 联合覆盖）
> - 新增普通字段: udc_code（UDC 细分码）

---

## 一、存储方案

- **向量数据库**：Qdrant
- **集合名称**：`athanor_v1`（单集合方案）
- **向量维度**：2560（qwen3-embedding:4b）
- **距离度量**：Cosine（余弦相似度）
- **Payload 索引**：10 个字段

---

## 二、分面分类（4 个维度）

### 分面1：内容类型 content_type（必填）

| 值 | 说明 | 场景 |
|----|------|------|
| `knowledge` | 知识条目 | 从文档/书籍/论文提取的结构化知识点 |
| `document` | 原始文档 | 上传的 PDF/Word/TXT，未提取知识 |
| `video_script` | 视频脚本 | B站/抖音视频脚本 |
| `social_post` | 社媒文案 | 小红书/公众号/微博 |
| `article` | 文章/博客 | 博客/专栏文章 |
| `book` | 书籍 | 出版书籍的章节或全文 |
| `paper` | 学术论文 | 期刊/会议论文 |
| `standard` | 标准/规范 | 国标/ISO/行业规范 |
| `webpage` | 网页内容 | 爬虫或手动保存的网页 |
| `personal_note` | 个人笔记 | 学习笔记/心得/日记 |
| `project_note` | 项目笔记 | 工作日志/项目记录 |
| `idea` | 想法/灵感 | 未成形的创意点子 |
| `template` | 模板 | 脚本模板/文档模板 |
| `legal_doc` | 法律文件 | 合同/证书/专利 |
| `other` | 其它 | 无法归类的内容 |

### 分面2：主题域 domain（必填，UDC 9 主类，可多选）

| 值 | 说明 |
|----|------|
| `0` | 总论、信息科学（计算机、AI、知识管理、标准） |
| `1` | 哲学、心理学（认知、个人成长） |
| `2` | 宗教、神学 |
| `3` | 社会科学（法律、经济、管理、教育） |
| `5` | 数学、自然科学（数学、物理、化学、生物） |
| `6` | 应用科学、技术（机械、电气、通信、建筑、医疗） |
| `7` | 艺术、文体（设计、影视、音乐） |
| `8` | 语言、文学（写作、出版、语言学） |
| `9` | 历史、地理（传记、技术史） |

> 类 4（语言）已并入类 8，现存 9 个有效主类。
> 精筛用 `udc_code` 普通字段（如 `"621"` / `"004.8"` / `"621:004.8"`），不占分面。

### 分面3：时效属性 temporal_nature（必填）

| 值 | 说明 |
|----|------|
| `evergreen` | 常青 — 长期有效，不随时间贬值（数学定理、设计原则、标准参数） |
| `timeboxed` | 有时限 — 一段时间内有效，之后可能过期（行业最佳实践、当前国标版本） |
| `transient` | 时效敏感 — 会快速过时（行业动态、产品发布信息、趋势预测） |

来源：借鉴 RMS-Ltd `doc-lifecycle-metadata-spec.md`、arxiv 2601.21116 证据衰减追踪。

### 分面4：认知验证状态 epistemic_status（必填）

| 值 | 说明 |
|----|------|
| `unverified` | L0 猜想 — 未验证的假设、个人意见、原始笔记 |
| `substantiated` | L1 逻辑验证通过 — 逻辑自洽，但缺外部实证 |
| `corroborated` | L2 实证验证 — 引用标准/论文/实验数据/法规 |

来源：arxiv 2601.21116（Gilda & Lamb, 2026）FPF 第一性原理框架。

---

## 二-B、降级/普通字段

### 生命周期 lifecycle（普通字段，可选）

`idea` → `draft` → `in_progress` → `review` → `published` → `archived`

不再作为 Payload Index 分面，降级为普通字段。仍支持 Qdrant filter。

### 来源项目（已废弃）

`project_source` 已由 hook 写入的 `source_project`（如 `"albedo-refined"`）取代，不再作为 payload 字段；形式题材标签 `tags` 也已废弃，由 `subject` 接管。详见 `albedo-citrinitas-handoff-spec.md` §2.3。

### UDC 细分码 udc_code（普通字段，可选）

LLM 自由输出任意精度的 UDC 类号，如 `"621"` / `"621.39"` / `"621:004.8"`（复合类号）。不入 Payload Index。

---

## 三、完整字段表（28 活跃 + 10 扩展槽位）

### 内容字段（5）

| 字段名 | 类型 | 说明 |
|--------|------|------|
| `text` | string | 正文内容 |
| `title` | string | 标题 |
| `source` | string | 来源显示名 |
| `chunk_index` | int | 分块序号 |
| `images` | array[string] | 图片路径列表 |

### 分面字段（4）

| 字段名 | 类型 | 必填 |
|--------|------|------|
| `content_type` | string | **必填** |
| `domain` | array[string] | **必填** |
| `temporal_nature` | string | **必填** |
| `epistemic_status` | string | **必填** |

### 知识管理字段（8）

| 字段名 | 类型 | 说明 |
|--------|------|------|
| `knowledge_type` | string | 知识子类型（11种） |
| `is_personal` | boolean | 是否个人化 |
| `trust_score` | int | 可信度 0-5（0=未评级，3=默认，5=最高） |
| `tags` | array[string] | 自定义标签 |
| `is_canonical` | boolean | 是否为主知识点 |
| `relations` | array[object] | 通用关系数组 `{type, doc_id}` |
| `keywords` | array[string] | 提取的关键词 |
| `auto_summary` | string | 自动生成摘要 |

**知识子类型 knowledge_type（仅 content_type=knowledge 时填）**：
`principle` / `formula` / `case` / `standard` / `concept` / `method` / `data` / `reference` / `procedure` / `requirement` / `test_data`

**关系类型 relations[].type**：
`similar` / `references` / `contradicts` / `derived_from` / `merged_into` / `supersedes` / `depends_on`

### timeline 时间戳（1 个分组对象）

| 子字段 | 类型 | 说明 |
|--------|------|------|
| `published` | datetime | 原文发布时间 |
| `effective` | datetime | 知识生效时间 |
| `expiry` | datetime | 知识过期时间 |
| `ingested` | datetime | 入库时间 |
| `accessed` | datetime | 最后访问时间 |

### origin 来源追踪（1 个分组对象）

| 子字段 | 类型 | 说明 |
|--------|------|------|
| `author` | string | 原作者 |
| `source_url` | string | 来源链接 |
| `file_type` | string | 原始文件类型 |
| `ingest_method` | string | 摄入方式 |
| `source_path` | string | 原始文件路径（用于追溯） |

`ingest_method` 可选值：`upload` / `email` / `api` / `crawler` / `manual` / `ocr`

### stats 使用统计（1 个分组对象）

| 子字段 | 类型 | 说明 |
|--------|------|------|
| `access_count` | int | 访问次数 |
| `starred` | boolean | 是否收藏 |

### 内容创作字段（2）

| 字段名 | 类型 | 说明 |
|--------|------|------|
| `target_platform` | string | 目标发布平台 |
| `related_product` | string | 关联产品 |

### 系统字段（5 个活跃 + 1 审核标记）

| 字段名 | 类型 | 说明 |
|--------|------|------|
| `doc_id` | string | 文档 ID（UUID） |
| `doc_uid` | string | 文档稳定标识（= doc_id，用于去重） |
| `content_hash` | string | 内容哈希（SHA256 前 32 位） |
| `language` | string | 语言 |
| `access_level` | string | 访问权限 |
| `is_archived` | boolean | 是否归档 |
| `batch_id` | string | 批次 ID |
| `version` | string | 版本标识 |
| `needs_review` | boolean | 置信度路由标记，低置信度入库时需要审核（默认 false） |

### 预留扩展槽位（10，不计入活跃字段数）

> 这些是 Qdrant schema 的扩展槽位，当前全部为 `null`。
> 新增字段时优先用它们，无需修改 Qdrant collection schema。

| 字段名 | 类型 | 用途 |
|--------|------|------|
| `ext_text1` ~ `ext_text5` | string | 预留文本 |
| `ext_num1` ~ `ext_num3` | float | 预留数字 |
| `ext_bool1` ~ `ext_bool3` | boolean | 预留布尔 |
| `ext_date1` ~ `ext_date3` | datetime | 预留日期 |

---

## 四、完整条目示例

```json
{
  "text": "齿轮模数 m=2.0 是优选值", "title": "齿轮模数标准",
  "source": "gb1357.txt", "chunk_index": 0, "images": [],

  "content_type": "standard", "domain": ["0", "6"],
  "temporal_nature": "evergreen", "epistemic_status": "corroborated",
  "lifecycle": "", "source_project": "albedo-refined", "udc_code": "621",

  "knowledge_type": "standard", "is_personal": false,
  "trust_score": 5, "tags": ["齿轮", "模数"],
  "is_canonical": true, "relations": [],
  "keywords": ["齿轮", "模数", "国标"],
  "auto_summary": "GB 齿轮模数标准值 m=2.0",

  "timeline": {
    "published": "2008-05-01", "effective": "2008-05-01",
    "expiry": null, "ingested": "2026-06-15", "accessed": null
  },

  "origin": {
    "author": "国家标准化管理委员会",
    "source_url": "https://std.gov.cn/gb1357",
    "file_type": "txt", "ingest_method": "manual",
    "source_path": "D:/Documents/KnowledgeBase/机械设计/原始文件/gb1357.txt"
  },

  "stats": { "access_count": 0, "starred": false },

  "target_platform": "none", "related_product": "",
  "version": "GB/T 1357-2008",

  "doc_id": "a1b2c3d4-e5f6-...", "doc_uid": "a1b2c3d4-e5f6-...",
  "content_hash": "a1b2c3d4...",
  "language": "zh", "access_level": "private",
  "is_archived": false, "batch_id": "",

  "ext_text1": null, "ext_text2": null, "ext_text3": null,
  "ext_text4": null, "ext_text5": null,
  "ext_num1": null, "ext_num2": null, "ext_num3": null,
  "ext_bool1": null, "ext_bool2": null, "ext_bool3": null,
  "ext_date1": null, "ext_date2": null, "ext_date3": null
}
```

---

## 五、Payload Index 配置

| 字段名 | 索引类型 | 说明 |
|--------|----------|------|
| `content_type` | keyword | 高频过滤 |
| `domain` | keyword | 高频过滤（UDC 9主类） |
| `temporal_nature` | keyword | 高频过滤 |
| `epistemic_status` | keyword | 高频过滤 |
| `is_personal` | bool | 布尔过滤 |
| `trust_score` | integer | 范围过滤 |
| `knowledge_type` | keyword | 知识子类型过滤 |
| `target_platform` | keyword | 平台过滤 |
| `language` | keyword | 语言过滤 |
| `access_level` | keyword | 权限过滤 |
| `source_project` | keyword | 溯源标记（hook 写入，如 albedo-refined；取代已废弃的 project_source） |
| `needs_review` | bool | 审核标记（知识中枢页面筛选待审核条目） |

---

## 六、变更日志

| 版本 | 日期 | 变更内容 |
|------|------|----------|
| v5.2 | 2026-06-20 | 添加 `origin.source_path` 字段（原始文件路径追溯）；添加 `doc_uid` 字段（文档稳定标识）；更新示例 JSON |
| v5.1 | 2026-06-17 | 明确 36 = 28活跃+10扩展槽位；四象限来源分类；title/author 填充优先级（文件>AI>程序） |
| v5.0 | 2026-06-16 | domain → UDC 9主类；分面3 temporal_nature(3级)；分面4 epistemic_status(3级/L0-L2)；lifecycle/project_source 降级普通字段；移除 objectivity；新增 udc_code 普通字段 |
| v4.0 | 2026-06-15 | 36字段分组方案：content_type 15种、domain 9种、knowledge_type 11种；新增 relations/timeline/origin/stats 分组字段；新增 keywords/auto_summary/batch_id/is_archived/version；删除 content_stage/task_id/updated_at/quality_score/category |
| v2.0 | 2026-06-15 | 重写字段设计，采用分面分类方案 |
| v1.0 | 2026-05-xx | 初始版本（层级分类法，已废弃） |

---

## 七、字段来源四象限（Field Source Classification）

所有 28 个活跃字段**100% 自动填充**，按来源分为四类：

### 象限一：文件自带（File-originated）— 置信度 1.0

从文件的元数据层提取，确定性数据。**优先级最高**，当与 AI 推断冲突时，文件自带优先。

| 字段 | 提取来源 |
|------|----------|
| `title` | EPUB/PDF 元数据 / HTML `<title>` / DOCX core_properties |
| `origin.author` | EPUB creator / PDF author / DOCX author |
| `origin.source_url` | HTML `<link rel="canonical">` |
| `origin.file_type` | 文件扩展名推断 |
| `source` | 文件 basename |
| `timeline.published` | EPUB date / PDF CreationDate / EXIF DateTimeOriginal |
| `version` | 文件名模式匹配（如 `GB/T 1357-2008`） |
| `timeline.effective` | 同 `published`（法律/合同类文档可能不同） |

### 象限二：AI 推断（AI-inferred）— 置信度由 LLM 返回

LLM 分析文本语义推断的字段。**后备来源**：文件无 `title`/`author` 时，AI 尝试从正文推断。

| 字段 | 推断方式 |
|------|----------|
| `content_type` | 文本语义 → 15 选 1 |
| `domain` | 文本主题 → UDC 9 选 N |
| `temporal_nature` | 文本时效特征 → 3 选 1 |
| `epistemic_status` | 文本引用/证据 → 3 选 1 |
| `udc_code` | 文本精确主题 → UDC 细分码 |
| `keywords` | 提取 3-8 个关键词 |
| `auto_summary` | 生成 ≤100 字摘要 |
| `trust_score` | 评估来源权威度 0-5（0=未评级） |
| `knowledge_type` | 仅 content_type=knowledge 时推断子类型 |
| `is_personal` | 判断是否个人经验 |
| `lifecycle` | 第6类（使用期手动填）；入库默认空，不推断 |

### 象限三：程序自动生成（System-generated）— 置信度 1.0

纯代码逻辑，确定性输出，无需任何推断。

| 字段 | 生成方式 |
|------|----------|
| `doc_id` | UUID 前 8 位 |
| `content_hash` | SHA256 |
| `text` | 文件解析（txt/md 直接读、EPUB/PDF/DOCX 解包） |
| `chunk_index` | 分块序号 0, 1, 2... |
| `images` | 正则提取 `![](path)` 引用并验证 |
| `language` | `langdetect` 库检测 |
| `timeline.ingested` | `datetime.now(timezone.utc)` |
| `timeline.accessed` | 初始 `null`，查询时更新 |
| `stats.access_count` | 初始 `0` |
| `stats.starred` | 初始 `false` |
| `origin.ingest_method` | `"upload"` / `"manual"` / `"api"` |
| `is_canonical` | 默认 `true`（第一个 chunk） |
| `access_level` | 默认 `"private"` |
| `is_archived` | 默认 `false` |
| `batch_id` | 批次 ID（批量摄入时生成） |

### 象限四：智能默认值（Smart defaults）— 置信度 0.0

当前无法自动确定，填入占位值等待未来进化。

| 字段 | 默认值 | 未来可能来源 |
|------|--------|--------------|
| `source_project` | `""` | 溯源标记（hook 写入，取代已废弃的 project_source） |
| `target_platform` | `"none"` | 内容发布（Elixir 模块） |
| `related_product` | `""` | 产品关联（Crucible 模块） |
| `tags` | `[]` | 用户自定义（远期） |
| `relations` | `[]` | 知识图谱（Crucible 模块） |
| `timeline.expiry` | `null` | `temporal_nature=timeboxed` 时 AI 推断 |
| 预留扩展槽位 ×10 | `null` | 按需启用 |

### 填充优先级

对同一字段有多个来源时（如 `title` 可能来自文件元数据也可能来自 AI 推断）：

```
文件自带（最高） → AI 推断（后备） → 智能默认值（兜底）
```

程序自动生成的字段与其他三类无重叠，不存在优先级冲突。
