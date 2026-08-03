"""
Citrinitas 配置加载器 — 唯一配置入口

加载顺序:
  1. pipe_cfg.yaml (默认配方)
  2. .env 环境变量 (覆盖同名参数)
  3. 验证 (P1-3: 负数/越界/非法值拦截)

所有模块从这里读配置，不再各自散落硬编码。
"""

import os
import sys
import yaml
from pathlib import Path
from dotenv import load_dotenv

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ── 加载 .env（先加载，后续 YAML 读取时可覆盖）──
_dotenv_path = os.path.join(PROJECT_DIR, ".env")
if os.path.isfile(_dotenv_path):
    load_dotenv(_dotenv_path)
else:
    print("[settings] WARNING: 未找到 .env 文件，使用 YAML 默认值 + 系统环境变量")
    print(f"  可以从 .env.example 复制并填写: cp .env.example .env")

# ── 加载 YAML ──
_yaml_path = os.path.join(PROJECT_DIR, "pipe_cfg.yaml")


def _load_yaml(path: str) -> dict:
    """加载 YAML 文件，文件不存在时报清晰错误。"""
    if not os.path.isfile(path):
        print(f"[settings] ERROR: 配置文件缺失: {path}")
        print(f"  请确保 pipe_cfg.yaml 存在于项目根目录。")
        print(f"  可以从 install.ps1 自动生成（尚未实现），或手动创建。")
        sys.exit(1)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except yaml.YAMLError as e:
        print(f"[settings] ERROR: YAML 语法错误: {path}")
        print(f"  {e}")
        sys.exit(1)


_cfg = _load_yaml(_yaml_path)


# ═══════════════════════════════════════════════════════════════
# 辅助函数：YAML + .env 双层取值
# ═══════════════════════════════════════════════════════════════

def _yaml_or_env(
    yaml_path: str,
    env_key: str,
    default,
    cast=str,
    validator=None,
) -> any:
    """
    取值: YAML 默认值 → .env 覆盖（如有）→ 验证。

    参数:
        yaml_path: 点号分隔的 YAML 键，如 "chunk.max_chars"
        env_key:   环境变量名，如 "KB_CHUNK_SIZE"
        default:   默认值（env 未设置且 YAML 缺失时用）
        cast:      类型转换函数（str/int/float/bool）
        validator: 验证函数 (value) → None（通过）/ str（错误信息）
    """
    # 从 YAML 取
    parts = yaml_path.split(".")
    val = _cfg
    for p in parts:
        if isinstance(val, dict):
            val = val.get(p)
        else:
            val = None
            break

    # 从 .env 覆盖（仅当明确设置时）
    env_val = os.environ.get(env_key)
    if env_val is not None and env_val != "":
        val = env_val

    # 类型转换
    if val is None:
        val = default
    else:
        try:
            if cast is bool:
                if isinstance(val, bool):
                    pass  # YAML 原生 bool
                else:
                    val = str(val).strip().lower() in ("true", "1", "yes", "on")
            else:
                val = cast(val)
        except (ValueError, TypeError):
            print(f"[settings] WARNING: {env_key}={val!r} 无法转为 {cast.__name__}，使用默认 {default!r}")
            val = default

    # 验证
    if validator:
        err = validator(val)
        if err:
            print(f"[settings] ERROR: {env_key} = {val!r} — {err}")
            sys.exit(1)

    return val


# ═══════════════════════════════════════════════════════════════
# 具体参数定义
# ═══════════════════════════════════════════════════════════════

# ── 文本切块 ──
CHUNK_MAX_CHARS = _yaml_or_env(
    "chunk.max_chars", "KB_CHUNK_MAX_CHARS", 800, cast=int,
    validator=lambda v: None if v >= 50 else "must be >= 50",
)
CHUNK_OVERLAP = _yaml_or_env(
    "chunk.overlap", "KB_CHUNK_OVERLAP", 60, cast=int,
    validator=lambda v: None if v >= 0 else "must be >= 0",
)

# ── 向量嵌入 ──
EMBED_MODEL = _yaml_or_env(
    "embed.model", "KB_EMBED_MODEL", "qwen3-embedding:4b",
    validator=lambda v: None if v.strip() else "model name cannot be empty",
)
EMBED_DIM = _yaml_or_env(
    "embed.dim", "KB_EMBED_DIM", 2560, cast=int,
    validator=lambda v: None if v > 0 else "must be > 0",
)
OLLAMA_URL = _yaml_or_env(
    "embed.ollama_url", "KB_OLLAMA_URL", "http://localhost:11434",
)

# ── 搜索 ──
SEARCH_TOP_K = _yaml_or_env(
    "search.top_k", "KB_SEARCH_TOP_K", 10, cast=int,
    validator=lambda v: None if 1 <= v <= 100 else "must be 1-100",
)
SEARCH_SCORE_THRESHOLD = _yaml_or_env(
    "search.score_threshold", "KB_SEARCH_SCORE_THRESHOLD", 0.3, cast=float,
    validator=lambda v: None if 0 <= v <= 1 else "must be 0-1",
)
SEARCH_CHUNKS_PER_DOC = _yaml_or_env(
    "search.chunks_per_doc", "KB_SEARCH_CHUNKS_PER_DOC", 20, cast=int,
    validator=lambda v: None if 1 <= v <= 50 else "must be 1-50",
)
FACET_CACHE_TTL = _yaml_or_env(
    "search.facet_cache_ttl", "KB_FACET_CACHE_TTL", 30, cast=int,
    validator=lambda v: None if 0 <= v <= 300 else "must be 0-300",
)

# ── 重排序 ──
RERANK_ENABLED = _yaml_or_env(
    "search.rerank.enabled", "KB_RERANK_ENABLED", True, cast=bool,
)
RERANK_MODEL = _yaml_or_env(
    "search.rerank.model", "KB_RERANK_MODEL", "qwen3-embedding:4b",
)
RERANK_TOP_N = _yaml_or_env(
    "search.rerank.top_n", "KB_RERANK_TOP_N", 20, cast=int,
    validator=lambda v: None if v >= 1 else "must be >= 1",
)

# ── 摄入 ──
INGEST_SKIP_DUPLICATES = _yaml_or_env(
    "ingest.skip_duplicates", "KB_INGEST_SKIP_DUPLICATES", True, cast=bool,
)

# ── 置信度阈值 ──
CONFIDENCE_LOW = _yaml_or_env(
    "confidence.low", "KB_CONFIDENCE_LOW", 0.40, cast=float,
    validator=lambda v: None if 0 <= v <= 1 else "must be 0-1",
)
CONFIDENCE_HIGH = _yaml_or_env(
    "confidence.high", "KB_CONFIDENCE_HIGH", 0.75, cast=float,
    validator=lambda v: None if 0 <= v <= 1 else "must be 0-1",
)

# ── 表格处理 ──
TABLE_SPLIT_THRESHOLD = _yaml_or_env(
    "table_split_threshold", "KB_TABLE_SPLIT_THRESHOLD", 4, cast=int,
    validator=lambda v: None if v >= 1 else "must be >= 1",
)

# ═══════════════════════════════════════════════════════════════
# 守望文件夹 v2（统一收件箱 + 状态追踪）
# ═══════════════════════════════════════════════════════════════
# ⚠️ 此目录（inbox）摄入即入库即删源；AI 模型禁止直接写入，唯一入口 = 巨作摄入路由。
WATCH_V2_INBOX_DIR = _yaml_or_env(
    "watch_v2.inbox_dir", "KB_WATCH_V2_INBOX_DIR", "library/inbox",
)
WATCH_V2_STATE_FILE = _yaml_or_env(
    "watch_v2.state_file", "KB_WATCH_V2_STATE_FILE", "library/file_state.jsonl",
)
WATCH_V2_WRITE_COMPLETE_CHECKS = _yaml_or_env(
    "watch_v2.write_complete_checks", "KB_WATCH_V2_WRITE_COMPLETE_CHECKS", 2, cast=int,
    validator=lambda v: None if v >= 1 else "must be >= 1",
)
WATCH_V2_WRITE_CHECK_INTERVAL = _yaml_or_env(
    "watch_v2.write_check_interval", "KB_WATCH_V2_WRITE_CHECK_INTERVAL", 0.5, cast=float,
    validator=lambda v: None if v > 0 else "must be > 0",
)
WATCH_V2_MAX_FILE_SIZE_MB = _yaml_or_env(
    "watch_v2.max_file_size_mb", "KB_WATCH_V2_MAX_FILE_SIZE_MB", 2048, cast=int,
    validator=lambda v: None if v >= 0 else "must be >= 0",
)
WATCH_V2_PROGRESS_STALL_TIMEOUT = _yaml_or_env(
    "watch_v2.progress_stall_timeout", "KB_WATCH_V2_PROGRESS_STALL_TIMEOUT", 300, cast=int,
    validator=lambda v: None if (v == 0 or v >= 30) else "must be 0 (禁用) 或 >= 30",
)
WATCH_V2_PROCESSING_TIMEOUT = _yaml_or_env(
    "watch_v2.processing_timeout", "KB_WATCH_V2_PROCESSING_TIMEOUT", 3600, cast=int,
    validator=lambda v: None if (v == 0 or v >= 30) else "must be 0 (禁用) 或 >= 30",
)
WATCH_V2_QUEUE_MAX_SIZE = _yaml_or_env(
    "watch_v2.queue_max_size", "KB_WATCH_V2_QUEUE_MAX_SIZE", 100, cast=int,
    validator=lambda v: None if v >= 1 else "must be >= 1",
)
WATCH_V2_QUEUE_PUT_TIMEOUT = _yaml_or_env(
    "watch_v2.queue_put_timeout", "KB_WATCH_V2_QUEUE_PUT_TIMEOUT", 0.5, cast=float,
    validator=lambda v: None if 0 < v <= 10 else "must be > 0 and <= 10",
)
WATCH_V2_CLEANUP_INTERVAL = _yaml_or_env(
    "watch_v2.cleanup_interval", "KB_WATCH_V2_CLEANUP_INTERVAL", 300, cast=int,
    validator=lambda v: None if v >= 60 else "must be >= 60",
)
WATCH_V2_INFRA_RETRY_INTERVAL = _yaml_or_env(
    "watch_v2.infra_retry_interval", "KB_WATCH_V2_INFRA_RETRY_INTERVAL", 15, cast=int,
    validator=lambda v: None if v > 0 else "must be > 0",
)
# 保留策略（内容驱动，逐页 WLNK 决策）
WATCH_V2_TEXT_DENSITY_THRESHOLD = _yaml_or_env(
    "watch_v2.retention.text_density_threshold", "KB_WATCH_V2_TEXT_DENSITY_THRESHOLD", 0.3, cast=float,
    validator=lambda v: None if 0 <= v <= 1 else "must be 0-1",
)
WATCH_V2_OCR_CONF_THRESHOLD = _yaml_or_env(
    "watch_v2.retention.ocr_conf_threshold", "KB_WATCH_V2_OCR_CONF_THRESHOLD", 0.7, cast=float,
    validator=lambda v: None if 0 <= v <= 1 else "must be 0-1",
)
# 故障处理
WATCH_V2_MAX_AUTO_RETRIES = _yaml_or_env(
    "watch_v2.failure_strategies.max_auto_retries", "KB_WATCH_V2_MAX_AUTO_RETRIES", 3, cast=int,
    validator=lambda v: None if v >= 0 else "must be >= 0",
)
WATCH_V2_AUTO_RETRY_DELAY = _yaml_or_env(
    "watch_v2.failure_strategies.auto_retry_delay", "KB_WATCH_V2_AUTO_RETRY_DELAY", 5, cast=int,
    validator=lambda v: None if v >= 1 else "must be >= 1",
)
WATCH_V2_DLQ_TTL_DAYS = _yaml_or_env(
    "watch_v2.failure_strategies.dlq_ttl_days", "KB_WATCH_V2_DLQ_TTL_DAYS", 30, cast=int,
    validator=lambda v: None if v >= 0 else "must be >= 0",
)
WATCH_V2_NOTIFY_ON_FATAL = _yaml_or_env(
    "watch_v2.failure_strategies.notify_on_fatal", "KB_WATCH_V2_NOTIFY_ON_FATAL", True, cast=bool,
)
# 关闭超时
WATCH_V2_PROCESS_TIMEOUT = _yaml_or_env(
    "watch_v2.process_timeout", "KB_WATCH_V2_PROCESS_TIMEOUT", 30, cast=int,
    validator=lambda v: None if v >= 1 else "must be >= 1",
)


# ── 调试开关：强制所有摄入文件进待审核 ──
# 通过环境变量 KB_FORCE_REVIEW_ALL 控制（.env 由系统配置页写入）。
# 运行时读取，切换即时生效、无需重启；详见 pages/config.py 与 ingest_pipeline.build_payloads。
def is_force_review_all() -> bool:
    """调试开关：开启后强制所有摄入文件进「待审核」队列（无论词表是否受控）。

    读取环境变量 KB_FORCE_REVIEW_ALL（"true" 开启，其余为关）。
    系统配置页写入 .env 并同步 os.environ[...]，故切换即时生效、无需重启。
    用途：全量抽检摄入质量——开启后每条新摄入都先人工过一遍审核页再放行。
    """
    return str(os.environ.get("KB_FORCE_REVIEW_ALL", "false")).strip().lower() == "true"


def _get_v2_temp_patterns():
    patterns = _cfg.get("watch_v2", {}).get("temp_patterns", [])
    if not patterns or not isinstance(patterns, list):
        return ["~$*", "*.tmp", "*.part", "*.crdownload", "thumbs.db", "desktop.ini"]
    return [str(p) for p in patterns]

WATCH_V2_TEMP_PATTERNS = _get_v2_temp_patterns()


def _print_summary():
    """打印关键配置值（不包含密钥）。"""
    print("[settings] Pipeline configuration loaded:")
    print(f"  chunk.max_chars         = {CHUNK_MAX_CHARS}")
    print(f"  chunk.overlap           = {CHUNK_OVERLAP}")
    print(f"  embed.model             = {EMBED_MODEL}")
    print(f"  embed.dim               = {EMBED_DIM}")
    print(f"  search.top_k            = {SEARCH_TOP_K}")
    print(f"  search.score_threshold  = {SEARCH_SCORE_THRESHOLD}")
    print(f"  search.chunks_per_doc   = {SEARCH_CHUNKS_PER_DOC}")
    print(f"  search.facet_cache_ttl  = {FACET_CACHE_TTL}s")
    print(f"  rerank.enabled          = {RERANK_ENABLED}")
    print(f"  rerank.top_n            = {RERANK_TOP_N}")
    print(f"  ingest.skip_duplicates  = {INGEST_SKIP_DUPLICATES}")
    print(f"  confidence.low          = {CONFIDENCE_LOW}")
    print(f"  confidence.high         = {CONFIDENCE_HIGH}")
    print(f"  table_split_threshold   = {TABLE_SPLIT_THRESHOLD}")
    print(f"  watch_v2.inbox_dir         = {WATCH_V2_INBOX_DIR}")
    print(f"  watch_v2.state_file        = {WATCH_V2_STATE_FILE}")
    print(f"  watch_v2.max_file_size_mb  = {WATCH_V2_MAX_FILE_SIZE_MB}")
    print(f"  watch_v2.queue_max_size    = {WATCH_V2_QUEUE_MAX_SIZE}")
    print(f"  watch_v2.queue_put_timeout = {WATCH_V2_QUEUE_PUT_TIMEOUT}s")
    print(f"  watch_v2.cleanup_interval   = {WATCH_V2_CLEANUP_INTERVAL}s")
    print(f"  watch_v2.max_retries       = {WATCH_V2_MAX_AUTO_RETRIES}")
    print(f"  watch_v2.retry_delay       = {WATCH_V2_AUTO_RETRY_DELAY}s")
    print(f"  watch_v2.infra_retry       = {WATCH_V2_INFRA_RETRY_INTERVAL}s")
    print(f"  watch_v2.dlq_ttl_days      = {WATCH_V2_DLQ_TTL_DAYS}")
    print(f"  watch_v2.processing_timeout= {WATCH_V2_PROCESSING_TIMEOUT}s")
    print(f"  watch_v2.progress_stall_timeout= {WATCH_V2_PROGRESS_STALL_TIMEOUT}s")
    print(f"  watch_v2.text_density_thr  = {WATCH_V2_TEXT_DENSITY_THRESHOLD}")
    print(f"  watch_v2.ocr_conf_thr      = {WATCH_V2_OCR_CONF_THRESHOLD}")
