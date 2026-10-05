# -*- coding: utf-8 -*-
"""把「每页一条」的解析结果切成检索块，并挂上公司/章节/页码元数据。

关于文本字段的分工（这决定了检索行为，值得写清楚）：
  header      展示用的定位串「长江电力 FY2025 第12页 第三节 管理层讨论与分析」
  text        原始内容，用于页面展示和人工核对
  bm25_text   header + text。公司名在每块里只出现一次，相当于一个温和的加权，
              而不是像把公司名重复十遍那样把词频彻底带偏
  embed_text  bge 的中文检索指令前缀 + header + text

表格块的正文里会显式写入「（单位：千元）」这类声明——这是数值题答错的
高发原因（评测里归为 R6 口径误读），宁可让模型看到，也不要让它自己猜。
"""
import json
import os
import sys

from common import EXTRACT_DIR, INDEX_DIR, YEAR, load_companies

TARGET = 500      # 目标块长（字符）
OVERLAP = 80      # 相邻块重叠
MAX_TABLE = 2400  # 超长表格按行组切分


def split_text(text, target=TARGET, overlap=OVERLAP):
    """按段落累积切块；超长段落硬切。返回 [str]。"""
    paras = [p.strip() for p in (text or "").split("\n") if p.strip()]
    chunks, cur = [], ""
    for p in paras:
        while len(p) > target:                      # 单段超长 → 硬切
            if cur:
                chunks.append(cur)
                cur = ""
            chunks.append(p[:target])
            p = p[target - overlap:]
        if cur and len(cur) + len(p) + 1 > target:
            chunks.append(cur)
            tail = cur[-overlap:] if overlap else ""
            cur = (tail + "\n" + p).strip() if tail else p
        else:
            cur = (cur + "\n" + p) if cur else p
    if cur.strip():
        chunks.append(cur)
    return chunks


def split_table(md, target=MAX_TABLE):
    """超长表格按行组切分，每组重复表头，避免丢列语义。"""
    lines = md.split("\n")
    if len(md) <= target or len(lines) < 4:
        return [md]
    head = lines[:2]
    out, cur = [], []
    for ln in lines[2:]:
        cur.append(ln)
        if sum(len(x) + 1 for x in cur) >= target - len("\n".join(head)):
            out.append("\n".join(head + cur))
            cur = []
    if cur:
        out.append("\n".join(head + cur))
    return out


def build(companies):
    all_chunks = []
    for c in companies:
        src = os.path.join(EXTRACT_DIR, f"{c['code']}.jsonl")
        if not os.path.exists(src):
            print(f"  !! 缺解析结果: {src}")
            continue
        n_text = n_tab = 0
        for line in open(src, encoding="utf-8"):
            rec = json.loads(line)
            page = rec.get("page")
            sec = rec.get("section") or ""
            sub = rec.get("subsection") or ""
            header = f"{c['cn']} FY{YEAR} 第{page}页 {sec}" + (f" · {sub}" if sub else "")
            base = {"company": c["cn"], "code": c["code"], "sector": c["sector"],
                    "year": YEAR, "page": page, "section": sec, "subsection": sub}

            for i, t in enumerate(split_text(rec.get("text", ""))):
                if len(t) < 40:                     # 丢弃页眉页脚级别的碎片
                    continue
                all_chunks.append({**base, "chunk_id": f"{c['code']}-p{page}-t{i}",
                                   "type": "text", "unit": None,
                                   "header": header, "text": t,
                                   "bm25_text": header + "\n" + t,
                                   "embed_text": header + "\n" + t})
                n_text += 1

            for ti, tab in enumerate(rec.get("tables", [])):
                unit = tab.get("unit")
                unit_line = f"（单位：{unit}）" if unit else ""
                for gi, md in enumerate(split_table(tab.get("md", ""))):
                    if len(md) < 30:
                        continue
                    body = (f"{unit_line}\n{md}" if unit_line else md)
                    suffix = f" 表格{ti+1}" + (f"-{gi+1}" if gi else "")
                    all_chunks.append({**base, "chunk_id": f"{c['code']}-p{page}-b{ti}-{gi}",
                                       "type": "table", "unit": unit,
                                       "header": header + suffix, "text": body,
                                       "bm25_text": header + "\n" + body,
                                       "embed_text": header + "\n" + body})
                    n_tab += 1
        print(f"  {c['cn']:<6}({c['code']})  正文块 {n_text:>5}  表格块 {n_tab:>5}")

    dst = os.path.join(INDEX_DIR, "chunks.jsonl")
    with open(dst, "w", encoding="utf-8") as f:
        for ch in all_chunks:
            f.write(json.dumps(ch, ensure_ascii=False) + "\n")
    n_t = sum(1 for c in all_chunks if c["type"] == "text")
    n_b = len(all_chunks) - n_t
    print(f"\n合计 {len(all_chunks)} 块（正文 {n_t} / 表格 {n_b}）-> {dst}")
    return all_chunks


if __name__ == "__main__":
    print(f"切块参数：目标 {TARGET} 字 / 重叠 {OVERLAP} / 表格上限 {MAX_TABLE}\n")
    build(load_companies())
