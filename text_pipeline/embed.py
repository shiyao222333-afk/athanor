"""
Text Pipeline — 嵌入向量

调用 Ollama 批量获取文本嵌入向量。
"""

import logging
import os
import requests

from qconst import OLLAMA_URL, EMBED_MODEL

logger = logging.getLogger(__name__)


def _embed(texts: list[str], model: str = EMBED_MODEL, progress_callback=None) -> list[list[float]]:
    """调用 Ollama 批量获取嵌入向量（优先批量，失败回退逐条）。"""
    # 允许通过环境变量 KB_EMBED_MODEL 即时切换模型（配置页保存后无需重启）
    model = model or os.environ.get("KB_EMBED_MODEL", EMBED_MODEL)
    if not texts:
        return []
    # 尝试批量 API（Ollama /api/embed 支持 input 数组）
    try:
        resp = requests.post(
            f"{OLLAMA_URL}/api/embed",
            json={"model": model, "input": texts},
            timeout=120
        )
        resp.raise_for_status()
        embeddings = resp.json().get("embeddings", [])
        if embeddings and len(embeddings) == len(texts):
            return embeddings
    except Exception as e:
        logger.warning(f"[Embed] 批量嵌入失败，回退到逐条: {e}")
    # 逐条回退
    vectors = []
    _dim = 0  # 从首个成功结果推导维度
    for i, text in enumerate(texts):
        try:
            resp = requests.post(
                f"{OLLAMA_URL}/api/embeddings",
                json={"model": model, "prompt": text},
                timeout=60
            )
            resp.raise_for_status()
            vec = resp.json()["embedding"]
            if _dim == 0:
                _dim = len(vec)
            vectors.append(vec)
        except Exception:
            if len(texts) == 1:
                raise
            if _dim == 0:
                logger.warning(f"[Embed] 首个块 #{i} 嵌入失败（{len(text)} 字符），无法推导维度，已跳过")
                continue
            logger.warning(f"[Embed] 块 #{i} 嵌入失败（{len(text)} 字符），用零向量占位（{_dim} 维）")
            vectors.append([0.0] * _dim)
        if progress_callback:
            progress_callback(i, len(texts))
    return vectors
