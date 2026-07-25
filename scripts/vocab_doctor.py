"""
Citrinitas 词表医生（#28/#40 根因治理）— 已入库文档标签规范化体检 + 可选修复。

【小白导读】"词表医生"是个清理脚本：把已入库的老文档里"不在词表"的标签，
按现在的词表归并一遍（同义词→标准词）。默认只读、不动数据；加 --fix 才真改。
详见 docs/GLOSSARY.md 的"词表医生"词条。

  它是怎么干活的（抽象流程）：
    1. 连上 Qdrant，把集合里的点(point)一页页翻出来（collect_points，翻页不一次拉爆内存）；
    2. 对每个 point 的 payload 跑 classify_payload——逐字段问"在词表里吗？"，
       汇总出非受控问题码（udc_uncontrolled / tag_uncontrolled / keyword_uncontrolled）；
    3. 只读模式下把问题汇总打印成"体检报告"；--fix 模式下调 normalize_doc_payload
       归并写回（set_payload 做 key 级合并，不动稠密/稀疏向量）。

  诚实的存疑点 / 历史坑：
  - 早期版本有个 bug（#39）：normalize_doc_payload 只管归并字段、不动 needs_review。
    结果老文档被医生"治好了"（标签都受控了），却仍卡在审核队列里出不去——
    因为没人把 needs_review 清掉。现已在 fix_normalize 里补上：
    "归并后若已无受控问题，就顺手把 needs_review 置 False"。
    这个修复点就是这类"修好了数据、却忘了清状态"的典型坑，值得记住。
  - 它直接打 Qdrant REST 接口（requests.post），没走项目的 qdrant_client 封装。
    当时是为了"脚本自包含、不依赖内部封装"，但代价是和封装层两份连接逻辑，
    将来若连接层改造，这里容易漏改。

默认只读扫描，打印非受控标签汇总；显式加 --fix 才动手归并
（set_payload 写回，不动稠密/稀疏向量，复用 #33 安全写法）。

为什么要它：
  #28 受控词表只约束「新摄入」文档。已入库的旧文档若当时 AI 写出了
  不在词表里的 udc_code / 题材 / 关键词，不会自动归并 —— 这些词就成了
  「游离词」，搜索时与其它同义写法对不上。本脚本把存量数据按现行词表
  归并一遍（同义词→标准词；udc 未受控清空）。

  ⚠️ 默认只读，绝不修改任何数据；只有显式 --fix 才写回。

扫描项：
  udc_uncontrolled      udc_code 不在受控词表（会被清空）
  tag_uncontrolled     题材标签中有不在受控词表的值（同义词归并）
  keyword_uncontrolled 关键词中有不在受控词表的值（同义词归并）

用法：
  python scripts/vocab_doctor.py                  # 只读报告
  python scripts/vocab_doctor.py --fix           # 归并已入库旧文档
  python scripts/vocab_doctor.py --collection athanor_v1 --limit 50000
"""
import os
import sys
import json
import argparse
import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

try:
    from qconst import QDRANT_URL, DEFAULT_COLLECTION
except Exception as e:
    print(f"❌ 无法导入 qconst（请在项目根目录运行）: {e}")
    sys.exit(1)

import vocabulary as vb


# ═══════════════════════════════════════════
# 纯函数：单点诊断 / 归一（便于单测，不触网）
# ═════════════════════════════════════════
def classify_payload(payload: dict) -> list:
    """返回该 payload 的非受控问题码列表。"""
    problems = []
    udc = payload.get("udc_code", "")
    if udc and vb.normalize_udc(udc) is None:
        problems.append("udc_uncontrolled")
    subj = payload.get("subject")
    if subj and vb.normalize_theme(str(subj)) is None:
        problems.append("subject_uncontrolled")
    for k in (payload.get("keywords") or []):
        if k and vb.normalize_keyword(str(k)) is None:
            problems.append("keyword_uncontrolled")
            break
    return problems


def normalize_doc_payload(payload: dict) -> dict:
    """
    对 payload 的受控字段做同义词归并（不动 needs_review，不动向量）。
    仅返回要写回的字段子集（set_payload 做 key-level merge）。
    """
    out = {}
    udc = payload.get("udc_code", "")
    if udc:
        out["udc_code"] = vb.normalize_udc(udc) or ""   # 未受控清空
    subj = payload.get("subject")
    if subj:
        out["subject"] = vb.normalize_theme(str(subj)) or str(subj).strip()
    kws = payload.get("keywords") or []
    out["keywords"] = [vb.normalize_keyword(str(k)) or str(k).strip() for k in kws if k]
    return out


# ═════════════════════════════════════════
# 扫描
# ═══════════════════════════════════════
def collect_points(collection: str, limit: int = 50000):
    points = []
    offset = 0
    batch = 1000
    while len(points) < limit:
        resp = requests.post(
            f"{QDRANT_URL}/collections/{collection}/points/scroll",
            json={"limit": batch, "offset": offset,
                  "with_payload": True, "with_vector": False},
            timeout=60,
        )
        if resp.status_code != 200:
            print(f"❌ scroll 失败 HTTP {resp.status_code}")
            break
        page = resp.json()["result"]["points"]
        if not page:
            break
        points.extend(page)
        offset += len(page)
        if len(page) < batch:
            break
    return points


def scan(collection: str, limit: int = 50000):
    print(f"🔍 扫描集合 {collection}（对照受控词表）...")
    points = collect_points(collection, limit)
    total = len(points)
    print(f"   共 {total} 个 point")

    # 按 doc_id 归并问题（任一 chunk 有问题即计入该文档）
    doc_problems = {}
    doc_samples = {}
    for p in points:
        pl = p.get("payload", {})
        did = pl.get("doc_id") or pl.get("doc_uid", "")
        for code in classify_payload(pl):
            doc_problems.setdefault(did, set()).add(code)
            if did not in doc_samples:
                doc_samples[did] = pl.get("title") or pl.get("source") or did

    counts = {c: 0 for c in ("udc_uncontrolled", "tag_uncontrolled", "keyword_uncontrolled")}
    for did, codes in doc_problems.items():
        for c in codes:
            counts[c] += 1

    print("\n==== 词表体检报告 ====")
    print(f"涉及文档数（任一字段非受控）: {len(doc_problems)}")
    for code in ("udc_uncontrolled", "tag_uncontrolled", "keyword_uncontrolled"):
        n = counts.get(code, 0)
        flag = "⚠️" if n else "✅"
        print(f"{flag} {code:<22}: {n}")
    if doc_problems:
        print("   样本文档:")
        for did in list(doc_problems)[:5]:
            print(f"      · {did}  {doc_samples.get(did, '')}")
    print("======================")
    return counts, doc_problems


# ═════════════════════════════════════════
# 修复（仅 --fix 时）
# ═══════════════════════════════════════
def fix_normalize(collection: str, limit: int = 50000):
    points = collect_points(collection, limit)
    fixed = 0
    for p in points:
        pl = p.get("payload", {})
        if not classify_payload(pl):
            continue
        updates = normalize_doc_payload(pl)
        # #39 修复：归并后若已无受控问题，顺手清掉"待审核"标记。
        # 否则老文档被医生修正后，仍卡在审核队列里出不去（normalize_doc_payload 不动 needs_review）。
        merged = dict(pl)
        merged.update(updates)
        if not classify_payload(merged):
            updates["needs_review"] = False
        resp = requests.post(
            f"{QDRANT_URL}/collections/{collection}/points/payload",
            json={"payload": updates, "points": [p["id"]]},
            timeout=10,
        )
        if resp.status_code == 200:
            fixed += 1
    print(f"🔧 已归并 {fixed} 个 point 的受控字段（udc 未受控清空、subject/keywords 同义词归并；"
          f"修正后无受控问题的同时清掉待审核标记）")


def main():
    ap = argparse.ArgumentParser(description="Citrinitas 词表医生")
    ap.add_argument("--collection", default=DEFAULT_COLLECTION)
    ap.add_argument("--limit", type=int, default=50000)
    ap.add_argument("--fix", action="store_true",
                    help="显式写回归并结果（默认只读，不修改任何数据）")
    args = ap.parse_args()

    # 连通性
    try:
        r = requests.get(f"{QDRANT_URL}/collections/{args.collection}", timeout=5)
        if r.status_code != 200:
            print(f"❌ 集合 {args.collection} 不可达 (HTTP {r.status_code})")
            sys.exit(1)
    except Exception as e:
        print(f"❌ 无法连接 Qdrant ({QDRANT_URL}): {e}")
        sys.exit(1)

    # 确保词表已加载（用真实 controlled_vocabulary.json）
    vb.load_vocabulary()

    counts, _ = scan(args.collection, args.limit)

    if not args.fix:
        print("\n（只读模式。需要归并已入库旧文档请加 --fix）")
        return

    if sum(counts.values()) == 0:
        print("✅ 没有非受控字段，无需修复。")
        return
    print(f"\n⚠️ 即将归并非受控字段（set_payload 写回，不动向量，不可逆归并但非删除）")
    fix_normalize(args.collection, args.limit)
    print("\n✅ 修复完成。建议再跑一次不带 --fix 复核。")


if __name__ == "__main__":
    main()
