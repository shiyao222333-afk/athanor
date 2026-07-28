"""
编码检测 + 文本文件读取（带编码兜底）
"""

import os
import logging

logger = logging.getLogger(__name__)


def detect_encoding(file_path: str, sample_bytes: int = 4096) -> str:
    """
    自动检测文件编码。UTF-8 优先，再 GBK/GB2312，最后 latin-1 兜底链。

    UTF-8 优先原则（根因修复）：合法 UTF-8 直接采用 utf-8，避免把「ASCII 为主 +
    少量中文」的 UTF-8 文件误判成其他编码导致中文乱码（mojibake）。

    内存安全（整本书也不整本读入）：只采样前 CAP 字节（默认 1MB，最多 4MB）。
    但中文 UTF-8 多字节字符若被截断在采样边界，strict 解码会报「尾部不完整」而误判
    为非 UTF-8 —— 此时扩读到 4MB 上限确认：若扩读后合法 UTF-8（或仍仅尾部截断）即采用
    utf-8；若扩读后出现真实非法字节则走 GBK/latin-1 兜底。
    """
    CAP = min(max(sample_bytes, 4096), 4 << 20)  # 采样上限 4MB，避免整本书读入内存

    try:
        with open(file_path, "rb") as f:
            raw = f.read(CAP)
    except Exception:
        return "utf-8"  # 兜底

    if not raw:
        return "utf-8"

    # 1) UTF-8 优先：合法 UTF-8 直接采用（严格解码器，误判概率极低）
    try:
        raw.decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError as e:
        # 采样砍在多字节字符尾部（"unexpected end of data"）→ 扩读确认是否真 UTF-8
        if "unexpected end of data" in str(e):
            try:
                with open(file_path, "rb") as f:
                    more = f.read(4 << 20)
                try:
                    more.decode("utf-8")
                    return "utf-8"
                except UnicodeDecodeError as e2:
                    if "unexpected end of data" in str(e2):
                        return "utf-8"  # 4MB 仍仅尾部截断 → 基本确定 UTF-8
                    # 扩读后出现真实非法字节 → 不是 UTF-8，走兜底
            except Exception:
                pass

    # 2) GBK 链（中文文档非 UTF-8 的主流编码）优先于 charset_normalizer，
    #    避免其把 GBK 字节误判成 big5hkscs 等导致错读（实测踩过此坑）。
    for enc in ["gbk", "gb2312"]:
        try:
            raw.decode(enc)
            return enc
        except (UnicodeDecodeError, LookupError):
            continue

    # 3) 最终兜底：latin-1 永不失败（可能乱码，但保证不崩）
    #    注：不再依赖 charset_normalizer —— 实测它对 UTF-8 误判 latin-1、对 GBK
    #    误判 big5hkscs、对非法字节误判 windows-1251，三种都会产生乱码；
    #    中文知识库文档的编码域就是 UTF-8 / GBK，确定性链更可靠。
    return "latin-1"


def _read_text_with_fallback(file_path: str) -> str:
    """使用编码检测链读取整个文本文件。"""
    enc = detect_encoding(file_path)
    with open(file_path, "r", encoding=enc, errors="replace") as f:
        return f.read()
