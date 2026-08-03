# flake8: noqa: E501
"""Search Engine LLM 问答合成 — 提示词构建 / 引用重编号 / LLM API 调用

从 search_engine.py 拆分（v1.0.2 代码质量清理）。
"""

import os
import re
import requests

from qconst import PROJECT_DIR, SEARCH_TOP_K, SEARCH_SCORE_THRESHOLD, TABLE_SPLIT_THRESHOLD
from .core import search

# ── 报告输出目录（供 pages/search.py 等外部调用方使用）────
OUTPUT_DIR = os.path.join(PROJECT_DIR, "local_data", "reports")

# ── LLM API 配置（OpenAI 兼容接口）──
LLM_BASE_URL = os.environ.get("KB_LLM_BASE_URL", "https://api.deepseek.com/v1")
LLM_API_KEY  = os.environ.get("KB_LLM_API_KEY", "")
LLM_MODEL    = os.environ.get("KB_LLM_MODEL", "deepseek-chat")


def _call_llm_api(messages: list, base_url: str = None, api_key: str = None, model: str = None) -> str:
    """调用 OpenAI 兼容 Chat API，返回模型回复文本。"""
    base_url = (base_url or LLM_BASE_URL).rstrip("/")
    resp = requests.post(
        f"{base_url}/chat/completions",
        json={
            "model": model or LLM_MODEL,
            "messages": messages,
            "temperature": 0,
            "max_tokens": 2048
        },
        headers={"Authorization": f"Bearer {api_key or LLM_API_KEY}"},
        timeout=120
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def _renumber_citations(synthesis: str, citation_keys: list) -> tuple[str, list[int]]:
    """
    正则提取回答中实际使用的引用编号，重编号为连续 1~N。
    返回 (重编号后文本, 实际使用的原始引用索引列表(1-based))。

    E6 修复：先保护 LaTeX 公式块（$$...$$ 和 $...$），避免误替换公式内的数字。
    """
    latex_blocks = []
    def _save_latex(m):
        latex_blocks.append(m.group(0))
        return f"\x00LTX{len(latex_blocks)-1}\x00"

    # 保护 $$...$$ 块（多行公式）
    text = re.sub(r'\$\$.*?\$\$', _save_latex, synthesis, flags=re.DOTALL)
    # 保护 $...$ 行内公式
    text = re.sub(r'\$(?:\\.|[^$])+?\$', _save_latex, text)

    # 兼容多种格式：[引用5] [引用 5] 引用5 引用 5
    used_raw = re.findall(r'\[?引用\s*(\d+)\]?', text)
    if not used_raw:
        return synthesis, []

    # 去重保持首次出现顺序
    seen = set()
    used = []
    for x in used_raw:
        nx = int(x)
        if nx not in seen:
            seen.add(nx)
            used.append(nx)

    # 建立映射：原编号 → 新编号（按出现顺序从1开始）
    mapping = {old: new for new, old in enumerate(used, 1)}

    # 替换全文（兼容 [引用5] 和 引用5 两种格式）
    def _replace(match):
        old_num = int(match.group(1))
        new_num = mapping.get(old_num)
        if new_num is None:
            return match.group(0)
        orig = match.group(0)
        if orig.startswith('['):
            return f"[引用{new_num}]"
        else:
            return f"引用{new_num}"

    new_text = re.sub(r'\[?引用\s*(\d+)\]?', _replace, text)

    # ── 还原 LaTeX 块 ──
    def _restore_latex(m):
        idx = int(m.group(1))
        return latex_blocks[idx] if idx < len(latex_blocks) else m.group(0)

    new_text = re.sub(r'\x00LTX(\d+)\x00', _restore_latex, new_text)

    return new_text, used


def _expand_chunks(chunks: list, threshold: int = None) -> list:
    """
    展开 chunks：表格行数 > threshold 时，按行拆分为虚拟 chunk。
    返回展开后的 chunks 列表（长度 >= len(chunks)）。
    """
    if threshold is None:
        threshold = TABLE_SPLIT_THRESHOLD

    expanded = []
    for c in chunks:
        text = c["text"]
        pipe_lines = [l for l in text.split("\n") if l.strip().startswith("|")]
        is_table = len(pipe_lines) >= 3 and "---" in pipe_lines[1]

        if is_table and len(pipe_lines) - 2 > threshold:
            for dl in pipe_lines[2:]:
                vc = dict(c)
                vc["text"] = f"{pipe_lines[0]}\n{pipe_lines[1]}\n{dl}"
                expanded.append(vc)
        else:
            expanded.append(c)

    return expanded


def _build_synthesis_prompt(query: str, chunks: list, table_split_threshold: int = None) -> tuple[str, list[str]]:
    """
    根据搜索结果构建 LLM 合成提示词。
    输入 chunks 已去重。
    如果 table_split_threshold 非空且某个表格 chunk 的行数 > 阈值，
    则将该表格按行拆分为多个迷你表引用（每行一个 [引用N]）。

    返回 (prompt_text, citation_keys)。
    """

    if table_split_threshold is None:
        table_split_threshold = TABLE_SPLIT_THRESHOLD

    expanded = []  # list of (ref_id, src, text)

    for c in chunks:
        text = c["text"]
        src = c.get("source") or "未知"

        pipe_lines = [l for l in text.split("\n") if l.strip().startswith("|")]
        is_table = len(pipe_lines) >= 3 and "---" in pipe_lines[1]

        if is_table and len(pipe_lines) - 2 > table_split_threshold:
            header_line = pipe_lines[0]
            sep_line = pipe_lines[1]
            data_lines = pipe_lines[2:]
            for dl in data_lines:
                mini = f"{header_line}\n{sep_line}\n{dl}"
                expanded.append((None, src, mini))
        else:
            if len(text) > 1500:
                text = text[:1500] + "…(省略)"
            expanded.append((None, src, text))

    # 统一编号
    materials = []
    citation_keys = []
    for i, (_, src, text) in enumerate(expanded):
        ref_id = f"[引用{i+1}]"
        citation_keys.append(ref_id)
        materials.append(f"{ref_id} 来源:{src}\n{text}")

    materials_text = "\n\n---\n\n".join(materials)

    prompt = f"""你是知识库助手。请根据下面的参考资料，用中文直接回答用户的问题。

要求：
1. 从参考资料中提取相关信息，用自己的语言组织答案
2. 必须使用所有提供的参考资料（共{len(materials)}条），每个论断后面标注引用编号
3. 引用编号必须使用提供的 [引用1] [引用2] 等格式，不要自行编造编号
4. 如果某部分内容不是来自参考资料，而是你自己的推理或补充知识，请在句末标注 [补充]
5. 禁止编造参考资料中不存在的公式、数据、结论。[补充] 内容除外
6. 公式用 LaTeX 语法（行内 $...$，独行 $$...$$）
7. 如果参考资料不足以回答问题，请诚实说明
8. 回答字数控制在 300-800 字

用户问题：{query}

参考资料：
{materials_text}"""

    return prompt, citation_keys


def answer(
    query: str,
    top_k: int = None,
    collection: str = None,
    model: str = None,
    threshold: float = None,
    llm_model: str = None,
    llm_base_url: str = None,
    llm_api_key: str = None,
    output_dir: str = None,
    table_split_threshold: int = None,
    facet_filter: dict = None,
    exclude_archived: bool = False,
) -> dict:
    """
    端到端知识库问答：搜索 → LLM API 合成 → HTML 报告（KaTeX 公式渲染）。

    参数:
        facet_filter: 分面过滤条件（见 search() 函数说明）
        exclude_archived: 是否排除已归档内容（is_archived=true）
    """
    from report_renderer import render_report_html

    output_dir = output_dir or OUTPUT_DIR

    # 默认值从 pipe_cfg.yaml 读取（参数显式传入时优先）
    if top_k is None:
        top_k = SEARCH_TOP_K
    if model is None:
        model = os.environ.get("KB_EMBED_MODEL", "qwen3-embedding:4b")
    if threshold is None:
        threshold = SEARCH_SCORE_THRESHOLD
    if table_split_threshold is None:
        table_split_threshold = TABLE_SPLIT_THRESHOLD
    # 从 os.environ 实时读取（避免 .env 加载顺序导致的空值）
    llm_model = llm_model or os.environ.get("KB_LLM_MODEL") or LLM_MODEL
    llm_base_url = llm_base_url or os.environ.get("KB_LLM_BASE_URL") or LLM_BASE_URL
    llm_api_key = llm_api_key or os.environ.get("KB_LLM_API_KEY") or LLM_API_KEY

    if not llm_base_url or not llm_api_key:
        return {
            "ok": False,
            "error": "未配置 LLM API。请设置环境变量 KB_LLM_BASE_URL/KB_LLM_API_KEY 或传入 --llm-base-url/--llm-api-key。"
        }

    # 1. 搜索（单集合方案）
    sr = search(query, top_k=top_k, collection=collection or "athanor_v1",
                 score_threshold=threshold, model=model,
                 facet_filter=facet_filter, exclude_archived=exclude_archived)
    raw_chunks = sr.get("chunks", [])

    if not sr.get("ok"):
        return {"ok": False, "error": sr.get("error", "搜索失败")}

    if not raw_chunks:
        return {"ok": True, "query": query, "synthesis": "知识库中未找到相关内容。", "chunks": [], "html": None}

    # 1.5 去重
    from .utils import _dedup_chunks
    chunks = _dedup_chunks(raw_chunks)

    # 2. LLM 合成
    prompt_text, citation_keys = _build_synthesis_prompt(query, chunks, table_split_threshold=table_split_threshold)
    expanded_chunks = _expand_chunks(chunks, table_split_threshold)
    try:
        synthesis = _call_llm_api(
            [{"role": "user", "content": prompt_text}],
            base_url=llm_base_url, api_key=llm_api_key, model=llm_model
        )
    except Exception as e:
        synthesis = f"（LLM 调用失败：{e}。以下为原始检索结果。）"

    # 2.5 引用重编号（使编号连续不跳跃）
    from .utils import _sanitize_html
    synthesis, used = _renumber_citations(synthesis, citation_keys)

    # 2.6 HTML 过滤（防御 XSS）
    synthesis = _sanitize_html(synthesis)

    # 3. 生成 HTML 报告
    try:
        html_path = render_report_html(query, synthesis, expanded_chunks, output_dir, used=used, citation_keys=citation_keys)
    except Exception as e:
        return {"ok": False, "error": f"HTML 报告生成失败: {e}", "synthesis": synthesis, "chunks": chunks}

    return {"ok": True, "query": query, "synthesis": synthesis, "html": html_path, "chunks": expanded_chunks}
