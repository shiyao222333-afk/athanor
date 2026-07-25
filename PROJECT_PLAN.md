# Citrinitas — 项目主计划

> 功能路线图 + 设计决策。版本变更记录见 `CHANGELOG.md`，Bug 跟踪用 GitHub Issues。
> 已完成版本的详细记录见 `CHANGELOG.md`，本文件只保留当前状态 + 未来规划。

最后更新: 2026-07-21

---

## 当前状态

  - 当前版本：**v1.2.1**（书库存储层 + 受控词表 + 自动化质检；v1.2.0 闪念笔记已发布）
  - 活跃 Bug：**0**
  - 下个版本：**v1.2.x** — 断点续存（书库存储层核心已随 v1.2.1 发布；剩断点续存未做）
- Git 状态：main 分支

---

## 版本路线图

> 按「地基 → 框架 → 墙体 → 装修 → 交付」逐层递进。✅=已完成，🔮=待开发。

| 版本 | 状态 | 层级 | 核心交付 |
|------|:----:|:--:|---------|
| v0.1.0~v0.5.1 | ✅ | 地基+框架 | CLI搜索 + Web UI + 分面分类 v5.0 + 智能摄入 + 内存优化 |
| v0.6.0 | ✅ | 框架 | 卡片式结果面板 + 三层并行管道 + 来源徽章 |
| v0.7.0 | ✅ | 框架 | 摄入执行重构 + 批量摄入 + Nigredo 钩子接口 |
| v0.8.0 | ✅ | 墙体 | 混合检索 + 重排序 + 置信度路由 UI |
| v0.9.0 | ✅ | 装修 | 知识库综合管理（侧边栏5→4 + 仪表盘 + 浏览 + 批量摄入） |
| v1.0.0 | ✅ | 交付 | 无 UI 管线 + YAML 配置化 + 桌面一键打包 |
| v1.0.1 | ✅ | 交付 | 死代码清理 + 大文件拆分 + run.bat 修复 |
| **v1.1.0** | ✅ | 交付 | **架构重构 + 错误日志规范** — Service 层解耦 UI/核心 + 统一日志 + 错误码体系 |
| **v1.2.0** | ✅ | 交付 | **闪念笔记** — idea 关键词规则识别 + lifecycle 联动 + 💡标记 + 相关灵感自动浮现面板 |
| **v1.2.x** | 🔮 | 交付 | **书库存储层 + 断点续存** — library/ 单一根目录（books 源文件 + images 所有图统一 + inbox 待处理 + file_state 状态）；切块记章节/段落位置指针；确定性 doc_id；书类不删源文件（按格式触发）；文字小说优先断点续存（源持久化 + 增量写 + 记最后完成块，关机可续，复用位置指针） |
| v1.3.0 | 🔮 | 交付 | 对外接口 — MCP（AI 专用工具接口，让 AI 在对话里调用熔知搜索/入库）+ REST API（给其他软件 / 手机 App 对接）；与 OpusMagnum 对接 |
| v1.4.0 | 🔮 | 交付 | 知识关系网 — NetworkX 图谱可视化 + QA 自动生成 + LLM 关系发现 |
| v1.5.0 | 🔮 | 交付 | 录入预处理 — 抓取残留清洗 + 去除无关内容 + 网页 URL 直接摄入（自动纠错 / 统一语言翻译 / 去广告已上移 Albedo 认知精炼，由上游精炼阶段完成） |
| v1.6.0 | 🔮 | 交付 | LLM 智能选择 — 用户可选云LLM / 本地小模型 / 机械程序 |
| v1.7.0 | 🔮 | 交付 | 性能优化 — 后台服务模式 + 内存优化 + 嵌入批处理 + 启动并行化 |
| v1.8.0 | 🔮 | 交付 | 知识保鲜 — 定期检查过期内容 + 提醒更新 + 批量重摄入 |
| v1.9.0 | 🔮 | 交付 | UI 美化 — 视觉升级 + 卡片式界面 + 暗色主题 + 响应式布局 |
| v1.10.0 | 🔮 | 交付 | Git 说明页面 — 版本历史 + 变更记录 + 开发者入口 |
| v1.11.0 | 🔮 | 交付 | **元关键词聚合（Meta-Keyword）** — 高度相似关键词自动归并为同一概念节点，免维护受控词表（详见「元关键词系统」规划） |
| v1.12.0 | 🔮 | 重构 | **UDC 细分码（udc_code）重构** — 当前 udc_code 由 LLM 从受控词表选填，仍有偶发漂移（非确定性兜底）；重构为「由 domain 主类确定性派生 + 受控细分码校验」的纯规则路径，彻底消除漂移，与分面重构统一治理 |
| v1.20.0 | 🔮 | 交付 | **热度/互动数据可检索字段** — 单一 payload 字段 `engagement`（JSON/dict）承载多指标，按 `content_type` 区分指标集（B站视频=播放/点赞/投币/收藏/分享/评论/弹幕计数+完播率等；小红书带货笔记=转化率/下单量/GMV 等）；需 Nigredo 已采集 + Albedo 经 handoff 契约透传 `engagement` 键 |

---

## 热度/互动数据字段（v1.20.0，设计要点）

> 用户拍板（2026-07-21）：热度数据**需要**进熔知（此前按"分析用不入库"暂未存）。设计约束：① **只占一个 payload 字段**，内部用 dict 装多个指标；② **指标集随 content_type 变化**，不同类型文件装的子数据不同。

- **字段**：`engagement`（payload 单字段，JSON/dict）。
- **类型化指标集（registry，按 content_type 选填，不强求统一键）**：
  - B站视频（`video_tutorial` / `video_script`）：`play_count` `like_count` `coin_count` `favorite_count` `share_count` `comment_count` `danmaku_count` + `completion_rate` `like_rate` 等。
  - 小红书带货笔记（`xiaohongshu_promote`）：`conversion_rate` `order_count` `gmv` `click_rate` 等（关注**转化**，非播放）。
  - 其它类型：dict 预留扩展键，按需添加。
- **数据流**：Nigredo 已采集互动/播放数据 → Albedo 经 handoff 契约新增 `engagement` 键透传（`report.py` `build_ingestion_frontmatter` 写进 refined frontmatter）→ Citrinitas `ingest_pipeline.py` payload 加 `engagement` 单字段 + 按需要对子键建 Payload Index（支持"按播放量/转化率排序筛选"）。
- **不做**：不为每种类型各开一个 payload 字段（违反"单字段"约束）；不把原始字幕/评论正文塞进 `engagement`（那是分析依据，非热度指标）。

---

**对外接口形态（待决策）** — 对应 v1.3.0：
- **现状**：熔知当前无对外接口（无网页 API、无 MCP），搜索/入库逻辑是可被直接调用的程序。
- **推荐方向**：① AI（含本助手）在对话里调用熔知 → 优先做 **MCP**（AI 专用工具接口，输入/输出约定清晰，换不同 AI 客户端也能用）；② 给其他软件 / 手机 App 用 → 做 **REST API**。
- **决策待定**：v1.3.0 落地时再确认具体接入方式、MCP 服务器形态，以及是否与 OpusMagnum 共用同一接口。

## 下一版本：v1.2.x 书库存储层

**状态**：书库存储层核心已实现并已于 2026-07-12 提交（commit `e5078d0`，#18–#41 + #48–#54 全批）。本批次交付：

- `library/` 单一根目录 + 图片统一 `library/images/`（取消"每本书各建图目录"）
- 章节 / 段落位置指针（`chapter_index` / `chapter_title` / `chunk_in_chapter`）
- 确定性 `doc_id`（路径哈希优先、正文内容哈希兜底，覆盖更新零孤儿）
- 书类不删源（按格式触发挪 `library/books/`）
- 受控词表（`udc_code` / 题材 / 关键词同义词归一，未受控进待审核队列）
- 存储原子性加固（先写后删孤儿 · `doc_id` 统一砍 `doc_uid` · `set_payload` 保留 BM25 向量 · 删图护栏）
- 自动化回归防护（契约测试 `tests/` + 存储医生 `scripts/storage_doctor.py` + 导入冒烟 `tests/test_imports.py`）
- 调试开关（配置页强制全量进待审核）+ 活动日志 `local_data/activity_log.jsonl`

⚠️ **断点续存未做**（源持久化 + 增量写 + 记最后完成块，关机可续），留待后续版本。

**核心决策（用户拍板）**：
- **单一知识库根目录 `library/`**：知识库真正保存的内容集中于此，不再散落。结构：
  - `library/books/` — 书籍源文件长期保留（.epub/.pdf/.docx/.txt/.md 等）
  - `library/images/` — **所有图片统一一处**（书本插图 + OCR 抽取图）。取消原"每本书各建图目录"方案，书本图也进这同一个目录。
  - `library/inbox/` — 待摄入文件（知识库前厅）
  - `library/file_state.jsonl` — 已保存内容的状态索引
- **`local_data/` 只放程序运维杂物**：logs/、reports/、dead_letter/、activity_log.jsonl、ingest_log.jsonl 等，不进 `library/`。
- **图片统一一处的具体落地**：`qconst.IMAGES_DIR` 由 `local_data/images` 改为 `library/images`；书本插图与 OCR 抽取图都写入这同一个目录，无需为书另开目录、也无需 base_dir 分流参数（原"图片目录写死"问题因此自然消解）。

**存储机制**：
- **位置指针**：切块时记录「第几章 / 第几段」指针；Qdrant payload 的 `source_path` 指向 `library/books/` 下持久化的源文件（相对路径），搜索命中可直接回溯翻开对应章节。
- **确定性 doc_id**：`ingest_pipeline.py` 现 `doc_id=uuid4()` 随机 → 改为由文件内容/路径派生，便于重录入去重与"同一本书不重复入库"，并支撑断点续存。
- **书籍细分主题（复用 `udc_code`，不新增分类）**：主题细分不走新标签体系，复用已有的 UDC 细分码字段 `udc_code`（即 `domain` 主类小数点后的细分层，如主类 `0` → 细分 `004.8` 人工智能应用）。书级主题 = `domain`（主类）+ `udc_code`（细分码）；章级主题 = 每章切块各自的 `udc_code` 细分值（由 AI 从章节标题/内容自动推断）。**9 个主类保持不变，细分是字段值而非新分类维度**，符合"大类即可、分类不无限增加"的原则；搜索时 `udc_code` 可作为筛选维度。
- **按格式触发书库分支**：是否走"归一化 + 保留源"逻辑由文件格式（EPUB/PDF/Word）决定，而非分类结果（分类可能误判）。
- **书类必留源**：`watcher/processor.py` 现 `keep_file=False` 时删原文件 → 书类文件改挪到 `library/books/` 长期保留。
- **章节保留 + 抽图**：`extract.py` 在 EPUB/PDF 提取时保留章节结构、抽取插图存到 `library/images/`；归一化为 Markdown 时保留图片引用，不丢图。

**不做（边界）**：不做书架页 UI（知识库只做保存与搜索回溯）；不做阅读进度/批注（由未来浏览界面承担）；不强制书本 OCR（纯图直存，OCR 分流列为未来通用模块）。

**未来规划（已列入路线图）**：
- **v1.3.0 对外接口**：MCP（AI 专用工具接口，让 AI 在对话里调用熔知搜索/入库）+ REST API（给其他软件 / 手机 App 对接），与 OpusMagnum 对接。
- **v1.5.0 录入预处理**：抓取残留清洗 + 去除无关内容 + 网页 URL 直接摄入（自动纠错 / 统一语言翻译 / 去广告已上移 Albedo 认知精炼，由上游在精炼阶段完成）；**其中「OCR 分流通用模块」（纯图直存 / 含大量文字的图走 OCR）不止用于书籍，作为录入预处理通用能力，值得深入研究**。
- **重复录入同一本书**：因确定性 doc_id + 内容哈希去重，重录入会被判重、不重复建块；如确需强制重录，提供明确入口。
- **v1.11.0 元关键词系统（Meta-Keyword）**：用户设想——高度相似的关键词可视为同一个关键词，从而**免去人工维护受控词表**。可行方向：① 用嵌入向量近邻（embeddings + 余弦）把语义相近关键词聚成"概念簇"，簇心即代表词；② 入库/搜索时关键词先过聚类映射再存/查，用户写"副业""搞钱""赚外快"都归到同一节点；③ 与现有 `udc_code` 受控体系不冲突——`udc_code` 管"学科分类"，元关键词管"自由词归一"，二者互补。实现前提：已有 embedding 能力（qwen3-embedding:4b 已用于 Qdrant），复用即可，无需新模型。落地待 v1.11.0 评估。

---

## 架构原则（不可变）

1. **非必要不用大模型** — 尽可能由固定程序完成
2. **核心逻辑与 UI 完全解耦** — 面向未来多端交互
3. **输出统一 JSON 结构化数据** — search/ingest/answer 返回值均为 dict
4. **配置用环境变量** — KB_LLM_BASE_URL/KEY/MODEL, KB_EMBED_MODEL 等
5. **本地优先** — 向量库本地、嵌入模型本地，仅 LLM 合成需联网

---

## 竞品学习要点

> 详细分析见 `docs/competitor-research-2026-06-16.md` 和 `docs/knowledge-graph-research-2026-06-16.md`

| 启发 | 学自 | 落地版本 |
|------|------|:--:|
| 知识关系网（NetworkX 内存图，零 LLM 建图） | RAGFlow | v1.4.0 |
| QA 自动生成（文档→问答对→向量化） | FastGPT | v1.4.0 |
| 管线 YAML 配置化 | Dify | ✅ v1.0.0 |

**不做**：GraphRAG 社区发现（成本高） / Neo4j（NetworkX 够用） / 从零实体提取 / 可视化工作流编辑器

---

## 远期待办

> 不在当前版本计划中，作为未来参考。

- **搜索词→分面自动推断** — LLM 解析搜索词自动生成分面过滤（如 "齿轮国标" → domain:["6"] + content_type:"standard"）
- **个人内容分类深化** — content_type 扩展子类（medical_record / financial_doc / diary）+ 隐私权限机制
- **认知精炼职责已移交 Albedo（原部分归 Citrinitas）** — 质量评估（真/假/可疑）/ 优点分析 / 内容净化（去广告·纠错·翻译）及 FPF 信任聚合（WLNK）均归 Albedo 核心功能，由上游精炼阶段完成；熔知 v1.5.0 录入预处理仅保留「抓取残留清洗 + 去除无关内容 + 网页 URL 直接摄入」等存储侧清洗，不再做认知层加工
- ~~**project_source 升级**~~ — 已废弃：权威契约（handoff-spec §2.3）改为由 hook 写 `source_project` 取代，不再作为分面
- **关键词→UDC 映射增强** — 当前仅 52 条，待积累后增强为规则引擎
- **normalize_facet_values() 独立化** — 当前内联校验，未来独立为统一入口函数
- **旧域数据迁移** — 执行 DOMAIN_MIGRATION_MAP，补充 temporal_nature/epistemic_status 默认值

---

## 代码质量待办

> 已完成的重构见 CHANGELOG.md。以下为尚未完成的项。

| # | 问题 | 位置 | 严重度 | 状态 |
|---|------|------|--------|------|
| 11 | `watcher.py` 单文件 1834 行，职责过多 | `watcher.py` → `watcher/` 包 | 🔴 P0 | ✅ 已拆分（v1.1.x 期间，`watcher/` 含 listener/state/processor/failures/utils/migration） |
| 12 | `pages/hub.py` 单文件 1418 行，多 Tab 混在一起 | `pages/hub.py` → `pages/hub/` 包 | 🔴 P0 | ✅ 已拆分（v1.1.x 期间，`pages/hub/` 含 overview/browse/review/dlq/detail/inbox/logs/helpers） |

**拆分方案**（✅ 已于 v1.1.x 期间完成）：

```
watcher.py (1834行) → watcher/ 包
├── __init__.py        re-export start/stop/retry
├── listener.py        文件系统监听（watchdog）
├── dedup.py          内容去重（content_hash 比较）
├── dispatcher.py      事件分发（触发摄入管道）
└── state.py           监听状态管理

pages/hub.py (1418行) → pages/hub/ 包
├── __init__.py        re-export page_hub + page_doc_detail
├── overview.py        概览标签
├── browse.py         浏览标签
├── review.py         待审核标签
├── dlq.py            死信队列标签
└── detail.py         /doc/{id} 详情页
```

**拆分原则**：每步拆一个模块，拆完立即验证功能不变；`__init__.py` re-export，调用方零改动；单文件 ≤ 400行。

---

## 已知风险（架构审查 2026-07-08）

> v1.2.x 书库存储层整批改动 + 摄入去重逻辑审查发现的隐患。非当前阻断，但影响数据完整性与未来维护。

| # | 风险 | 位置 | 严重度 | 状态 |
|---|------|------|--------|------|
| R1 | 两条录入路线（手动上传页 vs 守望夹自动）行为会悄悄分裂。根因：两条路没共用"把文件路径/确定性 doc_id 传进去"这个动作——守望夹已修（#21/#24 让 doc_id 确定性 + source_path 可见），但手动上传页仍退化为随机 doc_id（见 R7），且强制重录开关对两条路行为不一致（见 R8） | `pages/ingest.py` + `watcher/processor.py` → `ingest_service.ingest` | 🟡 P1 | ✅ **#30 已根因修复**（统一确定性 doc_id + 写入清旧点，全路线行为一致） |
| R2 | "重复就删源文件"是危险操作——自动删除源文件。#19 已对书类保护，但普通文档重复仍自动 `os.remove` 收件箱副本 | `watcher/processor.py` 重复跳过分支 | 🟡 P1 | 部分缓解（书已保护）；普通文档自动删源仍待决策（见 R10） |
| R3 | 去重仅靠全文哈希，**无"版本/更新"概念**：新版/更完整的书因哈希不同被当全新内容并行入库，搜索返回两版混合 | `_step_dedup`（`content_hash` 整本文哈希） | 🟡 P1 | ✅ **#30 已缓解**：写入前按 doc_id 清旧点 → 同名文件"更新"=覆盖而非复制（R4 同步解决） |
| R4 | 同名文件改版/精简（块数减少）重录入 → 旧高索引块成孤儿（仅 `force_reingest` 能清）；"更完整"(块数增多) 因 `point_id=(doc_id,chunk_index)` 碰撞反而被覆盖干净 | `point_id` 派生 + 普通路径不清旧块 | 🟡 P1 | ✅ **#30 已修复**：`_step_write_qdrant` 写入前按 doc_id 清空旧点，全路线零孤儿 |
| R5 | 去重键的是"抽取后文本"，抽取方式一变（OCR 改进/归一化调整）同书即变"新内容" → 重复入库 | `_text_hash(state["text"])` | 💭 P2 | 未来 |
| R6 | 去重查询异常被 `except Exception: pass` 静默吞掉 → Qdrant 抖动时去重悄悄失效、重复 creeping 无告警 | `_step_dedup` L148 | 💭 P2 | ✅ **#30 已修复**：`except` 改为 `logger.warning` |
| R7 | **手动上传页 `doc_id` 非确定性 + 强制重录开关失效**：`pages/ingest.py` 调 `ingest()` 未传 `file_path` → `doc_id` 退化为随机 uuid。后果：① 手动上传的同名/同内容文件无法关联（确定性编号仅守望夹生效）；② 用户勾选的"♻️ 强制重录"开关**实际无效**——`delete_points_by_doc_id` 用新随机 id 删不到旧点，旧碎片照样残留（#26 开关的隐藏缺陷） | `pages/ingest.py` L465-470 | 🔴 P0 | ✅ **#30 已修复**：`_derive_doc_id` 增加内容哈希兜底 → 文本/粘贴/死信/OCR 路线 doc_id 确定性，强制重录开关在所有入口生效 |
| R8 | **守望夹路径无强制重录触发**：`watcher/processor.py` `_do_ingest` 未传 `force_reingest`（永远 False）。非书类同名文件改版重录入必然残留孤儿碎片（R4），且**无任何 UI 入口可清理**——手动上传页强制重录因 R7 删不到守望夹旧 doc_id。即"自动录入的文件一旦改版，孤儿碎片永久滞留" | `watcher/processor.py` L309-316 | 🟡 P1 | ✅ **#30 已修复**：清旧点逻辑移入 `_step_write_qdrant`，对所有路线（含守望夹）自动生效，不再依赖 `force_reingest` 透传 |
| R9 | **守望夹重复抽取（性能浪费）**：`watcher/processor.py` 先自行 `extract_text` 供 AI 分类，又把 `file_path` 传给 `ingest()` 导致管线内再抽一遍 → 大书/大文件双倍耗时，且两遍规则微调可能不一致 | `watcher/processor.py` + `ingest_service._step_read_content` | 💭 P2 | 未做（性能优化，非数据完整性）；#30 未触碰 |
| R10 | 图片路径关联依赖"当前工作目录" → 程序从别处启动图显示不出（曾怀疑，审查后证伪） | — | — | ✅ **审查证伪**：图片以 `os.path.relpath(dest, PROJECT_DIR)` 存储，而 `PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))` 为绝对路径、与启动 CWD 无关，关联稳健 |
| R11 | **覆盖更新非原子（先删后写）**：`_step_write_qdrant` 先 `delete_points_by_doc_id` 删光旧块再 PUT 写新块。若 PUT 失败（网络/Qdrant 抖动/超时），旧块已删新块未写 → 整本文档凭空消失 | `services/ingest_service.py:277-304` | 🔴 P0 | ✅ **#31 已修复**：改为「先 PUT 新块（确定性 id 覆盖 0..N-1）→ 再 `delete_orphan_points` 清旧高索引孤儿」，删除不再前置；写入失败直接报错且不碰旧数据 |
| R12 | **删除失败被静默吞 → #30 孤儿修复没堵死**：`delete_points_by_doc_id` 删除 HTTP 非 200 仍返回 `ok=True, deleted=0`；调用方只在 `ok 且 deleted` 时记日志，否则跳过继续写 → 旧高索引块留成孤儿（R4 同款碎片，触发条件从"改版重录"换成"删除偶发失败"） | `doc_manager.py:600-610` + `ingest_service.py:288-294` | 🔴 P0 | ✅ **#31 已修复**：`delete_points_by_doc_id` 删除 HTTP 非 200 改返回 `ok=False`；`_step_write_qdrant` 改为写后清孤儿，孤儿清理失败仅告警不阻断 |
| R13 | **doc_id / doc_uid 双身份字段**：每点同时存两字段且需恒等（`ingest_pipeline.py:151-152`）；CRUD 函数各用各的（doc_id: `search_by_doc_id`/`delete_points_by_doc_id`/`get_doc_ids`；doc_uid: `list_documents`/`get_document`/`delete_document`/`set_doc_relations`）。靠"写入时两值相等"才不崩，任一处只填一个即静默查不到一半功能 | `ingest_pipeline.py` + `doc_manager.py` | 🟡 P1 | ✅ **#32 已修复**：摄入停写冗余 `doc_uid`（每点只留权威 `doc_id`）；`list_documents`/`get_document`/`delete_document`/`update_document` 统一以 `doc_id` 过滤（新增 `_query_doc_points` 先 doc_id 再回退 doc_uid 兼容迁移前旧数据）；搜索结果 + 全部 UI 改读 `doc_id` |
| R14 | **`update_document` 全量 PUT 会丢 BM25 稀疏向量**：读取带 `with_vector=True`，回写只取稠密 `vector` 未带 `bm25` → 更新元数据后混合检索退化为纯稠密。当前无人调用（死代码定时炸弹），`update_metadata` 用 `set_payload` 安全 | `doc_manager.py` | 🟡 P1 | ✅ **#33 已修复**：`update_document` 改用 `set_payload`（key-level merge，不动向量），混合检索不再退化 |
| R15 | **图片文件只增不删**：文档从 Qdrant 删除时其引用图片不从 `library/images/` 清理；同一书重录入生成新图文件、旧图变孤儿 → 长期堆积 | `text_pipeline/ocr.py` + `doc_manager.delete_document`/`delete_orphan_points` | 💭 P2 | ✅ **#34 已修复**：`delete_document` 与 `delete_orphan_points`（重录清孤儿）删除时联动清理引用图片，删除限制在 `IMAGES_DIR` 内（防任意路径误删） |
| R16 | **文本路线内容哈希碰撞**：`doc_id` 内容哈希兜底使两份不同文档但正文相同 → 同 doc_id → 互相覆盖（极罕见） | `ingest_pipeline.py:_derive_doc_id` | ⚪ P3 | 记录，暂不修 |

**存储层加固（防未来同类问题，候选 #31）**：

> 本轮审查（2026-07-08）发现：#30 虽统一了录入路线与覆盖更新，但存储写入本身是"先删后写"且失败静默，孤儿碎片与文档消失风险未真正归零；且项目**至今无自动化测试目录**，这是同类问题反复出现的根因。

- **P0 修复（R11/R12）**：覆盖写改为「先 PUT 新块（确定性 point_id 覆盖 0..N-1）→ 再 scroll 查 doc_id 现存 point_id，删掉不在新集合里的孤儿」。即"先写后删孤儿"，删除失败也最多留旧碎片、绝不丢整本文档；删除步骤失败必须显式报错/重试，不再假装 ok。
- **P1 修复（R13/R14）**：① 全项目砍掉 `doc_uid`，统一用 `doc_id`（CRUD 5 函数 + `search_engine/core.py` + UI 一并改）；② `update_document` 改用 `set_payload` API（保留向量）或直接删除死代码。 → ✅ **已实现（#32/#33）**
- **P2 修复（R15）**：文档删除时联动清理 `library/images/` 中其引用图片；重录入前先清旧图。 → ✅ **已实现（#34）**
- **根因治理（最关键）**：补契约测试目录 `tests/`，至少覆盖 4 条：① 重录后块数变化 → 断言最终块数正确且无孤儿；② 写入中途失败 → 断言文档不丢；③ 全库扫描 → 断言每点 `doc_id` 存在且（若保留）`doc_id==doc_uid`、无缺失；④ 更新元数据 → 断言稀疏向量仍在。再加「存储医生」脚本（启动/定期扫描孤儿 point_id、`doc_id` 缺失/≠`doc_uid`、`source_path` 指向已删文件）提前报警。 → ✅ **已实现（#35）**：`tests/test_storage_contract.py`（32 项契约测试，可直接 `python tests/test_storage_contract.py` 运行）+ `scripts/storage_doctor.py`（只读体检 + `--fix` 可选修复）
- **架构约束**：所有路线与 CRUD 写入统一走 `ingest_service.ingest` 这一唯一带契约的入口，禁止旁路直写 Qdrant。

**去重 / 版本处理设计（#30 已实施 ✅）**：
- `doc_id` 由 `library/books/` 稳定文件名派生 = 书的身份（文件路线）；无文件时由正文内容哈希派生（文本/粘贴/死信/OCR 路线）。`ingest()` 起步即解析，所有录入路线共用同一编号规则。
- **覆盖更新**：`_step_write_qdrant` 先 upsert 新块（确定性 point_id 覆盖 0..N-1），再 `delete_orphan_points(doc_id, keep_ids)` 仅清不在新集合的旧孤儿块（#31 改"先写后删孤儿"，消除写入失败整本文档消失的 R11；删除失败仅告警不阻断）。同名文件"更新"=覆盖而非复制，从根上消除 R3/R4 的并存与孤儿，且对所有路线（含守望夹）自动生效。
- 保留 `content_hash` 精确去重作为快速拦截（完全相同文本不重复劳动）；去重发生在清旧点之前，故不会误删未重写的内容。
- 去重查询异常改为 `logger.warning`，不再静默。
- 保留 `content_hash` 精确去重作为快速拦截（完全相同文本不重复劳动）。
- 可选：每块记录 `ingested_at`，UI 可显示"本书于 X 更新过"，支撑未来 v1.8.0 知识保鲜。
- 若需保留多版本（而非覆盖），用不同文件名表达"这是另一版"，视为不同书——与用户心智一致。

---

## 管理文件体系

| 文件 | 用途 |
|------|------|
| `BLUEPRINT.md` | 项目宪法（愿景/原则/重心/边界/验收） |
| `PROJECT_PLAN.md` | 功能路线图 + 设计决策（本文件） |
| `CHANGELOG.md` | 版本变更日志（含已完成版本详细记录） |
| `FLOWCHART.md` | 流程框图 |
| `README.md` | 项目门面 |
| `docs/schema.md` | 字段设计文档 |
