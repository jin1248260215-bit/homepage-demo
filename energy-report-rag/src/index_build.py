# -*- coding: utf-8 -*-
"""建 BM25 与向量索引。

向量走 fastembed + BAAI/bge-small-zh-v1.5（ONNX，512 维，约 115 MB），
**不依赖 torch**——Windows 上 torch 默认包约 2.5 GB，这里省掉了。

HF_ENDPOINT 默认指向国内镜像：huggingface.co 在本机实测被墙（15 s 超时），
而 hf-mirror.com 通。用 setdefault 是为了不覆盖你自己设的环境变量。
"""
import json
import os
import pickle
import sys
import time

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

import numpy as np

from common import INDEX_DIR, tokenize

MODEL_NAME = "BAAI/bge-small-zh-v1.5"
CHUNKS = os.path.join(INDEX_DIR, "chunks.jsonl")
BM25_PKL = os.path.join(INDEX_DIR, "bm25.pkl")
EMB_NPY = os.path.join(INDEX_DIR, "emb.npy")
STATS = os.path.join(INDEX_DIR, "build_stats.json")


def load_chunks():
    with open(CHUNKS, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def main():
    if not os.path.exists(CHUNKS):
        print(f"!! 缺少 {CHUNKS}，请先运行 src/chunk.py")
        return 1
    chunks = load_chunks()
    stats = {"n_chunks": len(chunks),
             "n_text": sum(1 for c in chunks if c["type"] == "text"),
             "n_table": sum(1 for c in chunks if c["type"] == "table"),
             "model": MODEL_NAME}
    print(f"块数 {len(chunks)}（正文 {stats['n_text']} / 表格 {stats['n_table']}）")

    # ---------------- BM25
    t0 = time.time()
    corpus = [tokenize(c["bm25_text"]) for c in chunks]
    avg_len = sum(len(x) for x in corpus) / max(len(corpus), 1)
    vocab = len({w for doc in corpus for w in doc})
    from rank_bm25 import BM25Okapi
    bm25 = BM25Okapi(corpus)
    with open(BM25_PKL, "wb") as f:
        pickle.dump({"bm25": bm25, "n": len(corpus)}, f)
    stats.update(bm25_avg_tokens=round(avg_len, 1), bm25_vocab=vocab,
                 bm25_seconds=round(time.time() - t0, 1))
    print(f"BM25 就绪：{vocab:,} 词表 / 平均 {avg_len:.1f} 词每块 / {time.time()-t0:.1f}s")

    # ---------------- 向量
    t0 = time.time()
    from fastembed import TextEmbedding
    model = TextEmbedding(model_name=MODEL_NAME)
    texts = [c["embed_text"] for c in chunks]
    emb = np.array(list(model.embed(texts, batch_size=64)), dtype=np.float32)
    emb /= (np.linalg.norm(emb, axis=1, keepdims=True) + 1e-9)
    np.save(EMB_NPY, emb)
    stats.update(emb_dim=int(emb.shape[1]), emb_seconds=round(time.time() - t0, 1),
                 emb_bytes=int(emb.nbytes))
    print(f"向量就绪：{emb.shape} / {emb.nbytes/1024/1024:.1f} MB / {time.time()-t0:.1f}s")

    with open(STATS, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=1)
    print(f"统计写入 {STATS}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
