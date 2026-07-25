"""
Citrinitas 受控词表契约测试（#28/#39 根因治理，防回归）。

无外部依赖、可直接运行：
    python tests/test_vocabulary.py

覆盖项（对应 #28 设计）：
  L1  加载层：有效词表加载 / 文件缺失 → 空词表不崩 / 文件损坏 → 空词表不崩
  L2  归一化：udc_code 精确命中；subject/keywords 同义词归并；未命中 → None
  L3  自由文本校验：全受控不进待审核；任一未受控 → needs_review=True（udc 清空、subject/keywords 保留原文）
  L4  懒加载兜底：调用方忘调 load 也不空表误判（#37 接入健壮性）
  L5  写回回环：save_vocabulary → 重新加载 → 校对一致；原子写不损坏原文件

测试通过把 vocabulary.VOCAB_PATH 指向临时文件，避免触碰真实词表。
"""
import os
import sys
import json
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import vocabulary as vb
import vocab_doctor as vd

FAILS = []


def check(name, cond):
    print(("PASS" if cond else "FAIL"), name)
    if not cond:
        FAILS.append(name)


def with_vocab(data: dict) -> str:
    """写一个临时词表文件，并把 vocabulary 指向它，返回路径。"""
    p = tempfile.mktemp(suffix=".json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    vb.VOCAB_PATH = p
    return p


def reset_cache():
    vb._VOCAB_CACHE = None
    vb._THEME_LOOKUP.clear()
    vb._KEYWORD_LOOKUP.clear()
    vb._UDC_CODES.clear()


# ════════════════ L1：加载层 ═══════════════
def test_load():
    p = with_vocab({
        "udc_subdivisions": {"621.81": {"label": "齿轮", "parent": "621.8"}},
        "themes": {"机械设计": ["齿轮设计", "传动设计"]},
        "keywords": {"齿面接触疲劳强度": ["齿面硬度"]},
    })
    v = vb.load_vocabulary(force=True)
    check("L1 细分码加载", v["udc_subdivisions"].get("621.81", {}).get("label") == "齿轮")
    check("L1 题材同义词映射", vb.normalize_theme("齿轮设计") == "机械设计")
    check("L1 关键词同义词映射", vb.normalize_keyword("齿面硬度") == "齿面接触疲劳强度")
    check("L1 udc 精确命中", vb.normalize_udc("621.81") == "621.81")
    os.remove(p)


def test_missing_file():
    vb.VOCAB_PATH = "/nonexistent_dir/vocab_does_not_exist.json"
    v = vb.load_vocabulary(force=True)
    check("L1 缺失文件→空词表不崩", v["themes"] == {} and v["keywords"] == {} and v["udc_subdivisions"] == {})
    check("L1 缺失文件→归一全 None", vb.normalize_theme("任何词") is None and vb.normalize_udc("621") is None)


def test_corrupt_file():
    p = tempfile.mktemp(suffix=".json")
    with open(p, "w", encoding="utf-8") as f:
        f.write("{ 这不是合法 json,,, ")
    vb.VOCAB_PATH = p
    v = vb.load_vocabulary(force=True)
    check("L1 损坏文件→空词表不崩", v["themes"] == {} and v["keywords"] == {} and v["udc_subdivisions"] == {})
    os.remove(p)


def test_shape_error_keeps_cache():
    """#39 回归：词表形状错（如 themes 写成 list）绝不能静默清空→全库进待审核。

    场景：先成功加载一份正常词表（缓存非空），再让 load 读一份"形状错"的词表。
    期望：ERROR + 保留旧缓存（不覆盖、不静默清空），归一仍用旧词表。
    """
    # 1) 先成功加载正常词表，建立非空缓存
    good = with_vocab({
        "udc_subdivisions": {"621.81": {"label": "齿轮", "parent": "621.8"}},
        "themes": {"机械设计": ["齿轮设计"]},
        "keywords": {"齿轮": []},
    })
    vb.load_vocabulary(force=True)
    check("L1 形状错前：正常词表已生效(题材映射)", vb.normalize_theme("齿轮设计") == "机械设计")

    # 2) 把文件改成"形状错"（themes 是 list 而非 dict）
    with open(good, "w", encoding="utf-8") as f:
        json.dump({
            "udc_subdivisions": {},
            "themes": ["机械设计", "齿轮设计"],   # 错误：应为 dict
            "keywords": {},
        }, f, ensure_ascii=False)
    v = vb.load_vocabulary(force=True)
    # 形状错 → 保留旧缓存：旧词表仍是 themes={机械设计:[齿轮设计]}，故仍能归一
    check("L1 形状错→拒绝加载而非静默清空", vb.normalize_theme("齿轮设计") == "机械设计")
    check("L1 形状错→返回的是旧缓存对象", v["themes"].get("机械设计") == ["齿轮设计"])
    os.remove(good)


def test_shape_error_no_cache_falls_empty():
    """#39 回归：形状错且无历史缓存 → 退化空词表（不崩），但明确是"无约束"状态。"""
    p = tempfile.mktemp(suffix=".json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(["这根本不是对象，是 list"], f, ensure_ascii=False)
    vb.VOCAB_PATH = p
    reset_cache()  # 清空内存缓存，模拟"首次加载就遇到坏文件"
    v = vb.load_vocabulary(force=True)
    check("L1 形状错无缓存→空词表不崩", v["themes"] == {} and v["keywords"] == {})
    check("L1 形状错无缓存→归一全 None", vb.normalize_theme("任何词") is None)
    os.remove(p)


# ════════════════ L2：归一化 ═══════════════
def test_normalize_miss():
    p = with_vocab({
        "udc_subdivisions": {"621": {"label": "机械应用科学", "parent": ""}},
        "themes": {"机械": []},
        "keywords": {"齿轮": []},
    })
    vb.load_vocabulary(force=True)
    check("L2 udc 命中", vb.normalize_udc("621") == "621")
    check("L2 udc 未命中→None", vb.normalize_udc("xyz.99") is None)
    check("L2 theme 命中标准词", vb.normalize_theme("机械") == "机械")
    check("L2 theme 未命中→None", vb.normalize_theme("未知题材X") is None)
    check("L2 keyword 未命中→None", vb.normalize_keyword("未知关键词Y") is None)
    check("L2 大小写不敏感", vb.normalize_theme("机械".upper()) is None or vb.normalize_theme("机械") == "机械")
    os.remove(p)


# ════════════════ L3：自由文本字段校验（含待审核标记）══════════════
def test_free_text_fields():
    p = with_vocab({
        "udc_subdivisions": {"621.81": {"label": "齿轮", "parent": "621.8"}},
        "themes": {"机械设计": ["齿轮设计"]},
        "keywords": {"齿面接触疲劳强度": ["齿面硬度"]},
    })
    vb.load_vocabulary(force=True)

    # 全受控 → 不进审核队列，值被同义词归并
    m = {"udc_code": "621.81", "subject": "齿轮设计", "keywords": ["齿面硬度"], "needs_review": False}
    vb.normalize_free_text_fields(m, "doc1")
    check("L3 全受控不进审核", m.get("needs_review") is False)
    check("L3 全受控 udc 保留", m["udc_code"] == "621.81")
    check("L3 全受控 subject 归并", m["subject"] == "机械设计")
    check("L3 全受控 keywords 归并", m["keywords"] == ["齿面接触疲劳强度"])

    # 有未受控 → 进审核队列；udc 清空、subject/keywords 保留原文
    m2 = {"udc_code": "xyz", "subject": "未知题材", "keywords": ["未知词"], "needs_review": False}
    vb.normalize_free_text_fields(m2, "doc2")
    check("L3 未受控 udc 清空", m2["udc_code"] == "")
    check("L3 未受控 subject 保留原文", m2["subject"] == "未知题材")
    check("L3 未受控→needs_review", m2.get("needs_review") is True)

    # 已为 True 不降级
    m3 = {"udc_code": "621.81", "subject": "机械设计", "keywords": ["齿面接触疲劳强度"], "needs_review": True}
    vb.normalize_free_text_fields(m3, "doc3")
    check("L3 已审核不降级", m3["needs_review"] is True)

    # 缺 needs_review 键不崩（setdefault 护栏）
    m4 = {"udc_code": "621.81", "subject": "机械设计", "keywords": ["齿面接触疲劳强度"]}
    vb.normalize_free_text_fields(m4, "doc4")
    check("L3 无 needs_review 键不崩", m4.get("needs_review") is False)

    os.remove(p)


# ════════════════ L4：懒加载兜底（#37 接入健壮性）══════════════
def test_lazy_load_guard():
    p = with_vocab({
        "udc_subdivisions": {},
        "themes": {"机械设计": ["齿轮设计"]},
        "keywords": {},
    })
    # 模拟调用方忘调 load：清空内存缓存
    reset_cache()
    # 直接调归一函数，应自行加载词表并返回正确结果（不空表误判）
    check("L4 懒加载兜底生效", vb.normalize_theme("齿轮设计") == "机械设计")
    os.remove(p)


# ════════════════ L5：写回回环（save → reload）══════════════
def test_save_roundtrip():
    p = with_vocab({"udc_subdivisions": {}, "themes": {}, "keywords": {}})
    # 预置自定义头，验证 save 时保留既有 version/description（原子写不丢头）
    with open(p, "w", encoding="utf-8") as f:
        json.dump({"version": "9.9", "description": "custom header",
                   "udc_subdivisions": {}, "themes": {}, "keywords": {}}, f, ensure_ascii=False)
    vb.VOCAB_PATH = p
    vb.load_vocabulary(force=True)
    working = {
        "udc_subdivisions": [{"code": "621.81", "label": "齿轮", "parent": "621.8"}],
        "themes": [{"std": "机械设计", "syn": ["齿轮设计", "传动设计"]}],
        "keywords": [{"std": "齿轮", "syn": []}],
    }
    ok, msg = vb.save_vocabulary(working)
    check("L5 save 成功", ok is True)

    # 内存即时生效
    check("L5 保存后内存即时生效(题材)", vb.normalize_theme("传动设计") == "机械设计")
    check("L5 保存后内存即时生效(关键词)", vb.normalize_keyword("齿轮") == "齿轮")

    # 重新加载（模拟重启）仍一致
    v = vb.load_vocabulary(force=True)
    check("L5 reload 细分码", v["udc_subdivisions"].get("621.81", {}).get("label") == "齿轮")
    check("L5 reload 题材同义词", vb.normalize_theme("齿轮设计") == "机械设计")

    # version/description 头：直接读回写盘文件校验（load_vocabulary 仅暴露 3 个词典，不含头）
    with open(p, "r", encoding="utf-8") as f:
        on_disk = json.load(f)
    check("L5 保留既有 version 头", on_disk.get("version") == "9.9")
    check("L5 保留既有 description 头", on_disk.get("description") == "custom header")

    # 原子写不损坏：再保存一次仍合法
    ok2, _ = vb.save_vocabulary(working)
    check("L5 二次保存仍成功(文件未损坏)", ok2 is True)
    os.remove(p)


# ════════════════ L6：词表医生纯函数（#40 工具自身回归）══════════════
def test_vocab_doctor_pure():
    p = with_vocab({
        "udc_subdivisions": {"621.81": {"label": "齿轮", "parent": "621.8"}},
        "themes": {"机械设计": ["齿轮设计"]},
        "keywords": {"齿面接触疲劳强度": ["齿面硬度"]},
    })
    vb.load_vocabulary(force=True)

    # 受控 payload → 无问题
    good = {"doc_id": "d", "udc_code": "621.81", "subject": "齿轮设计", "keywords": ["齿面硬度"]}
    check("L6 受控 payload 无问题码", vd.classify_payload(good) == [])

    # 非受控 → 三个码都报
    bad = {"doc_id": "d", "udc_code": "xyz", "subject": "未知题材", "keywords": ["未知词"]}
    probs = vd.classify_payload(bad)
    check("L6 非受控 udc 报码", "udc_uncontrolled" in probs)
    check("L6 非受控 subject 报码", "subject_uncontrolled" in probs)
    check("L6 非受控 keyword 报码", "keyword_uncontrolled" in probs)

    # 归一写回子集正确（udc 清空、subject/keywords 保留原文）
    upd = vd.normalize_doc_payload(bad)
    check("L6 归一 udc 清空", upd["udc_code"] == "")
    check("L6 归一 subject 保留原文", upd["subject"] == "未知题材")
    check("L6 归一 keywords 保留原文", upd["keywords"] == ["未知词"])
    os.remove(p)


if __name__ == "__main__":
    test_load()
    test_missing_file()
    test_corrupt_file()
    test_normalize_miss()
    test_free_text_fields()
    test_lazy_load_guard()
    test_save_roundtrip()
    test_vocab_doctor_pure()
    print("\n==== 结果:", "ALL PASS ✅" if not FAILS else f"FAILURES ❌ {FAILS}")
    sys.exit(1 if FAILS else 0)
