# -*- coding: utf-8 -*-
"""混合检索：BM25 + 向量 → RRF 融合，可选按公司配额。

两个刻意的设计：
  1) mode 参数保留 "bm25" / "dense" / "hybrid" 三个取值，评测里做消融，
     用来回答「融合到底有没有用、哪类题靠哪一路」。
  2) per_company_max 配额：跨公司全景题的天敌是 naive top-k——15 家里
     某一家的一次年报陈述可能一口气占满前 8 个位置，其余 14 家一个都进不来。
     配额模式强制每家公司最多贡献若干块。这是评测里全景题的主要变量。
"""
import json
import os
import pickle

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

import numpy as np

from common import BGE_INSTRUCTION, INDEX_DIR, tokenize

MODEL_NAME = "BAAI/bge-small-zh-v1.5"
RRF_K0 = 60          # RRF 平滑常数，经验值
CANDIDATE = 50       # 每路先取多少候选再融合


class Retriever:
    def __init__(self, index_dir=INDEX_DIR):
        with open(os.path.join(index_dir, "chunks.jsonl"), encoding="utf-8") as f:
            self.chunks = [json.loads(l) for l in f if l.strip()]
        with open(os.path.join(index_dir, "bm25.pkl"), "rb") as f:
            self.bm25 = pickle.load(f)["bm25"]
        self.emb = np.load(os.path.join(index_dir, "emb.npy"))
        self._model = None

    @property
    def model(self):
        if self._model is None:
            from fastembed import TextEmbedding
            self._model = TextEmbedding(model_name=MODEL_NAME)
        return self._model

    def _dense(self, q):
        v = np.array(list(self.model.embed([BGE_INSTRUCTION + q])), dtype=np.float32)[0]
        v /= (np.linalg.norm(v) + 1e-9)
        return self.emb @ v

    def search(self, q, k=8, per_company_max=None, companies=None, types=None,
               mode="hybrid", candidate=CANDIDATE):
        """返回 [{...chunk 字段, bm25_rank, dense_rank, rrf}...]。"""
        n = len(self.chunks)
        allow = np.ones(n, dtype=bool)
        if companies:
            s = set(companies)
            allow &= np.array([c["company"] in s for c in self.chunks])
        if types:
            s = set(types)
            allow &= np.array([c["type"] in s for c in self.chunks])
        allowed = np.where(allow)[0]
        if allowed.size == 0:
            return []

        bm_rank, dn_rank = {}, {}
        if mode in ("hybrid", "bm25"):
            scores = self.bm25.get_scores(tokenize(q))
            order = allowed[np.argsort(-scores[allowed])][:candidate]
            bm_rank = {int(i): r for r, i in enumerate(order)}
        if mode in ("hybrid", "dense"):
            ds = self._dense(q)
            order = allowed[np.argsort(-ds[allowed])][:candidate]
            dn_rank = {int(i): r for r, i in enumerate(order)}

        fused = {}
        for i, r in bm_rank.items():
            fused[i] = fused.get(i, 0.0) + 1.0 / (RRF_K0 + r + 1)
        for i, r in dn_rank.items():
            fused[i] = fused.get(i, 0.0) + 1.0 / (RRF_K0 + r + 1)

        ranked = sorted(fused.items(), key=lambda x: -x[1])
        out, per_co = [], {}
        for i, sc in ranked:
            c = self.chunks[i]
            if per_company_max is not None:
                if per_co.get(c["company"], 0) >= per_company_max:
                    continue
                per_co[c["company"]] = per_co.get(c["company"], 0) + 1
            out.append({**c,
                        "bm25_rank": bm_rank.get(i),
                        "dense_rank": dn_rank.get(i),
                        "rrf": round(sc, 6)})
            if len(out) >= k:
                break
        return out


_rt = None


def get_retriever():
    """进程内单例，避免 Flask 每个请求都重载模型。"""
    global _rt
    if _rt is None:
        _rt = Retriever()
    return _rt


if __name__ == "__main__":
    import sys
    rt = get_retriever()
    q = sys.argv[1] if len(sys.argv) > 1 else "长江电力2025年营业总收入"
    print(f"查询：{q}\n")
    for mode in ("bm25", "dense", "hybrid"):
        print(f"--- {mode} ---")
        for r in rt.search(q, k=5, mode=mode):
            print(f"  {r['rrf']:.5f} bm25={r['bm25_rank']} dense={r['dense_rank']} "
                  f"{r['company']} p{r['page']} [{r['type']}] {r['text'][:50]!r}")
        print()
