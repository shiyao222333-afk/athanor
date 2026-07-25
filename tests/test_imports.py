"""
Citrinitas 启动导入冒烟测试（#39 根因治理，防"启动即崩"类回归）。

无外部依赖（不连 Qdrant / Ollama），只验证：
  L1  关键摄入链路模块能正常 import（无 ImportError / 缺符号 / 启动即崩）
  L2  build_payloads 能跑通一条最小链路（词表挂载点 + 调试开关生效）
  L3  调试开关 is_force_review_all() 受 KB_FORCE_REVIEW_ALL 控制

第三轮架构审查发现：缺这类测试，导致 ingest_pipeline 的导入 bug（错 import 源）
能混过绿灯测试、直到用户本地一启动才崩。本测试把"启动前能否 import 通"
变成可自动验证的关卡。

直接运行：
    python tests/test_imports.py
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

FAILS = []


def check(name, cond):
    print(("PASS" if cond else "FAIL"), name)
    if not cond:
        FAILS.append(name)


def test_imports():
    """L1：关键模块必须能无错 import（任何 ImportError 都直接炸 = 启动即崩）。"""
    mods = [
        "config.settings",
        "config.normalize",
        "vocabulary",
        "ingest_pipeline",
        "text_pipeline",
        "kb_query",
        "doc_manager",
        "scripts.vocab_doctor",
        "utils.activity",
        # 页面模块：main.py 启动时会 import，它们若崩同样 = 启动即崩
        "pages.ingest",
        "pages.vocabulary",
        "pages.hub.review",
    ]
    for mod in mods:
        try:
            __import__(mod)
            check(f"L1 import {mod}", True)
        except Exception as e:
            check(f"L1 import {mod}", False)
            print(f"     ↳ {type(e).__name__}: {e}")


def test_build_payloads_minimal():
    """L2/L3：最小链路跑通——调试开关关闭时正常产出，开启时强制 needs_review。"""
    import ingest_pipeline as ip
    import config.settings as st

    base = {
        "title": "冒烟测试文档",
        "content_type": "knowledge",
        "domain": ["test"],
        "udc_code": "621.81",
        "subject": "机械设计",
        "keywords": ["齿轮"],
    }
    try:
        res = ip.build_payloads(
            text="这是一段用于冒烟测试的最小文本。",
            chunks=["这是一段用于冒烟测试的最小文本。"],
            vectors=[[0.0] * 8],
            base_meta=base,
            source="smoke_test",
        )
        check("L2 build_payloads 返回 ok", res.get("ok") is True)
        check("L2 产出至少 1 个 point", len(res.get("points", [])) >= 1)
        check("L2 默认 needs_review 为 False", res["points"][0]["payload"]["needs_review"] is False)

        # 打开调试开关
        os.environ["KB_FORCE_REVIEW_ALL"] = "true"
        res2 = ip.build_payloads(
            text="这是一段用于冒烟测试的最小文本。",
            chunks=["这是一段用于冒烟测试的最小文本。"],
            vectors=[[0.0] * 8],
            base_meta=base,
            source="smoke_test",
        )
        check("L2 调试开关开启→强制 needs_review", res2["points"][0]["payload"]["needs_review"] is True)
        check("L3 is_force_review_all() 读 env 生效", st.is_force_review_all() is True)

        # 还原
        os.environ["KB_FORCE_REVIEW_ALL"] = "false"
        check("L3 is_force_review_all() 还原", st.is_force_review_all() is False)
    except Exception as e:
        check("L2 build_payloads 跑通", False)
        print(f"     ↳ {type(e).__name__}: {e}")


if __name__ == "__main__":
    test_imports()
    test_build_payloads_minimal()
    print("\n==== 结果:", "ALL PASS ✅" if not FAILS else f"FAILURES ❌ {FAILS}")
    sys.exit(1 if FAILS else 0)
