# -*- coding: utf-8 -*-
"""逐题跑检索 + 生成，记录召回了什么、证据块排第几、答得对不对、错在哪。

用法：
    python eval/run_eval.py                     # 默认：混合检索，top-8，不限额
    python eval/run_eval.py --mode bm25         # 消融：只用 BM25
    python eval/run_eval.py --cap 1             # 每公司最多 1 块
    python eval/run_eval.py --fanout            # 全景题按公司逐个检索再合并
    python eval/run_eval.py --summarize         # 人工填完 verdict 后重算汇总

关于判定
--------
脚本只负责把「检索过程」客观记下来（召回块、排名、耗时、答案原文）。
`verdict`（对/部分对/错）和 `error_class`（R1–R6）**由人工读年报原文后填写**，
脚本不自动打分——自动打分会让「答对了没有」这件事失去可信度。
"""
import argparse
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from common import EVAL_DIR                                    # noqa: E402
from llm import answer as llm_answer                           # noqa: E402
from retrieval import get_retriever                            # noqa: E402

QUESTIONS = os.path.join(EVAL_DIR, "questions.jsonl")
RESULTS = os.path.join(EVAL_DIR, "results.json")

# 错因分类
ERROR_CLASSES = {
    "R1": "检索失败——证据块根本没进候选",
    "R2": "排序失败——进了候选但被融合挤出 top-k（全景题高发）",
    "R3": "表格还原失败——表格抽取串行/丢字导致读错",
    "R4": "生成失败——证据在上下文里，模型算错/编造",
    "R5": "数据不可得——年报根本没披露该指标",
    "R6": "口径误读——合并 vs 母公司、单位（元/千元/百万元）混淆",
}


def load_questions():
    with open(QUESTIONS, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


_WS = re.compile(r"\s+")


def _norm(s):
    """删掉全部空白再比对。

    PDF 抽取会在词中间插硬换行——中国海油原文「桶油主要成本为27.9美元/桶油当量」
    被抽成「桶油主要成\\n本为27.9」，用原始子串匹配会判成「没召回」。
    实测这会让证据召回率被系统性低估。判分前先归一化空白。
    """
    return _WS.sub("", s or "")


def is_evidence(chunk, q):
    """该块是否算「证据块」：公司对得上，且含任一关键指标词。"""
    if chunk["company"] not in q["gold_companies"]:
        return False
    body = _norm(chunk["text"])
    return any(_norm(k) in body for k in q["evidence_keywords"])


def retrieve(rt, q, k, mode, cap, fanout, per_co):
    """返回 (chunks, 用了什么策略描述)。fanout 时逐公司各取 per_co 块再合并。"""
    if fanout and len(q["gold_companies"]) > 1:
        seen, out = set(), []
        for co in q["gold_companies"]:
            for c in rt.search(q["question"], k=per_co, mode=mode, companies=[co]):
                if c["chunk_id"] in seen:
                    continue
                seen.add(c["chunk_id"])
                out.append(c)
        return out, f"fanout(每公司≤{per_co})"
    return rt.search(q["question"], k=k, mode=mode, per_company_max=cap), \
        f"single-shot(top-{k}" + (f", 每公司≤{cap})" if cap else ")")


def run(args):
    rt = get_retriever()
    questions = load_questions()
    items = []
    print(f"配置：mode={args.mode} k={args.k} cap={args.cap} fanout={args.fanout}\n")
    for q in questions:
        t0 = time.time()
        chunks, strategy = retrieve(rt, q, args.k, args.mode, args.cap, args.fanout, args.per_co)
        ms = int((time.time() - t0) * 1000)

        first_hit, hits = None, 0
        for rank, c in enumerate(chunks, 1):
            if is_evidence(c, q):
                hits += 1
                if first_hit is None:
                    first_hit = rank
        recall = min(hits, len(chunks)) / max(len(q["gold_companies"]), 1)

        gen = llm_answer(q["question"], chunks)
        items.append({
            "qid": q["qid"], "type": q["type"], "question": q["question"],
            "gold_companies": q["gold_companies"], "evidence_keywords": q["evidence_keywords"],
            "strategy": strategy, "mode": args.mode, "k": args.k, "cap": args.cap,
            "fanout": args.fanout,
            "ms": ms, "n_retrieved": len(chunks),
            "recall_at_k": round(recall, 3),
            "first_hit_rank": first_hit,
            "retrieved_companies": sorted({c["company"] for c in chunks}),
            "retrieved": [{"chunk_id": c["chunk_id"], "company": c["company"],
                           "page": c["page"], "section": c["section"], "type": c["type"],
                           "bm25_rank": c["bm25_rank"], "dense_rank": c["dense_rank"],
                           "rrf": c["rrf"], "head": c["text"][:120]} for c in chunks],
            "answer": gen.get("answer"), "llm_ok": gen.get("ok"),
            "llm_error": gen.get("error"), "model": gen.get("model"),
            # ↓ 由人工读年报原文后填写
            "gold_answer": None, "verdict": None, "error_class": None, "note": "",
        })
        hit_cn = f"证据排名#{first_hit}" if first_hit else "未召回证据"
        print(f"  Q{q['qid']:>2} [{q['type']:<6}] {hit_cn:<12} 召回{len(chunks):>2}块 "
              f"公司{len(set(c['company'] for c in chunks)):>2}家 {ms:>4}ms  "
              f"{'生成OK' if gen.get('ok') else '生成失败'}")

    out = {
        "config": {"mode": args.mode, "k": args.k, "cap": args.cap,
                   "fanout": args.fanout, "per_co": args.per_co},
        "error_classes": ERROR_CLASSES,
        "summary": summarize(items),
        "items": items,
    }
    with open(RESULTS, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"\n{summarize(items)}")
    print(f"结果写入 {RESULTS}")
    print("提示：verdict / error_class / gold_answer 需人工读年报原文后填写，"
          "再运行 --summarize 重算汇总。")


def summarize(items):
    n = len(items)
    s = {"n": n,
         "n_correct": sum(1 for i in items if i.get("verdict") == "对"),
         "n_partial": sum(1 for i in items if i.get("verdict") == "部分对"),
         "n_wrong": sum(1 for i in items if i.get("verdict") == "错"),
         "n_ungraded": sum(1 for i in items if not i.get("verdict")),
         "recall_rate": round(100 * sum(1 for i in items if i.get("first_hit_rank")) / n, 1),
         "avg_ms": round(sum(i["ms"] for i in items) / n, 1),
         "by_type": {}}
    for t in {i["type"] for i in items}:
        sub = [i for i in items if i["type"] == t]
        s["by_type"][t] = {
            "n": len(sub),
            "correct": sum(1 for i in sub if i.get("verdict") == "对"),
            "partial": sum(1 for i in sub if i.get("verdict") == "部分对"),
            "wrong": sum(1 for i in sub if i.get("verdict") == "错"),
            "recall_rate": round(100 * sum(1 for i in sub if i.get("first_hit_rank")) / len(sub), 1),
        }
    ec = {}
    for i in items:
        if i.get("error_class"):
            ec[i["error_class"]] = ec.get(i["error_class"], 0) + 1
    s["error_class_counts"] = ec
    return s


def do_summarize():
    js = json.load(open(RESULTS, encoding="utf-8"))
    js["summary"] = summarize(js["items"])
    with open(RESULTS, "w", encoding="utf-8") as f:
        json.dump(js, f, ensure_ascii=False, indent=1)
    print(json.dumps(js["summary"], ensure_ascii=False, indent=1))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="hybrid", choices=["hybrid", "bm25", "dense"])
    ap.add_argument("--k", type=int, default=8)
    ap.add_argument("--cap", type=int, default=None)
    ap.add_argument("--fanout", action="store_true")
    ap.add_argument("--per-co", type=int, default=2)
    ap.add_argument("--summarize", action="store_true")
    a = ap.parse_args()
    if a.summarize:
        do_summarize()
    else:
        run(a)
