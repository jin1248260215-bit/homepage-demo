# -*- coding: utf-8 -*-
"""PDF → 带「公司 / 页码 / 章节」的文字与表格。

设计取舍
--------
表格引擎默认用 pymupdf.find_tables()：实测 276 页 9.5 s（约 0.03 s/页），
而 pdfplumber 约慢 30 倍——15 份年报 3000+ 页用 pdfplumber 要跑近一小时。
所以 pymupdf 做主引擎，pdfplumber 只在 docs/table_fidelity.md 的抽样对照里跑，
用来说明「保真度到底差在哪」，而不是假装它没问题。

实测 pymupdf 的三个已知缺陷，本模块用 merge_continuation() 部分修补：
  1) 合并单元格错位      → 无法完全修复，保留原样，诚实记录
  2) 换行文字被拆成多行  → merge_continuation() 修补
  3) 长文本被截断        → 无法修复（如 "香港联合交易" 丢 "所"）

单位（元/千元/万元/百万元）单独抽出来挂在表格上：这是数值题答错的高发原因。
"""
import json
import os
import re
import sys
import time

import pymupdf

from common import (EXTRACT_DIR, YEAR, find_unit, load_companies, parse_note,
                    parse_section, pdf_path)

# 结束性标点：上一行末列以这些字符结尾，说明它本来就是完整句子，不该吞并下一行
_END_PUNCT = re.compile(r"[。；：）)\]】%％]$")
MIN_COL, MIN_ROW = 2, 2


def merge_continuation(rows, max_lead=3):
    """合并续行。

    pymupdf 会把一个换行的单元格拆成多行，例如释义表：
        ['境内、国内、内地', '指', '中国大陆（仅就本报告而言，不']
        ['',                '',  '地区）']
    规则：若某行前 max_lead 列全空、末列非空，且上一行末列不以句读结尾，则并入上一行。
    """
    out = []
    for r in rows:
        cells = [(c or "").strip().replace("\n", " ") for c in r]
        if not cells:
            continue
        if out:
            lead = cells[:max_lead]
            last = cells[-1] if cells else ""
            prev = out[-1]
            prev_last = (prev[-1] or "").strip() if prev else ""
            if (last and all(not c for c in lead)
                    and prev_last and not _END_PUNCT.search(prev_last)):
                prev[-1] = prev_last + last
                continue
        out.append(list(cells))
    return out


def table_to_md(rows):
    """把二维表还原成 markdown，行列结构保留（列宽取最大列数，缺列补空）。"""
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    norm = [r + [""] * (width - len(r)) for r in rows]
    esc = lambda s: (s or "").replace("|", "\\|")
    lines = ["| " + " | ".join(esc(c) for c in norm[0]) + " |",
             "|" + "|".join(["---"] * width) + "|"]
    lines += ["| " + " | ".join(esc(c) for c in r) + " |" for r in norm[1:]]
    return "\n".join(lines)


def _nearest_unit(page, bbox):
    """找表格正上方最近的文本块，从中提取单位声明。"""
    try:
        blocks = [b for b in page.get_text("blocks") if b[6] == 0 and b[3] <= bbox[1] + 1]
    except Exception:
        return None
    blocks.sort(key=lambda b: b[3], reverse=True)   # 离表格最近的排前面
    for b in blocks[:3]:
        u = find_unit(b[4])
        if u:
            return u
    return None


def extract_page(page):
    """返回 (正文文本, [表格dict], [表格bbox])。表格区域从正文里剔除，避免重复计数。"""
    try:
        tabs = list(page.find_tables().tables)
    except Exception:
        tabs = []

    tables, boxes = [], []
    for t in tabs:
        try:
            rows = merge_continuation(t.extract())
        except Exception:
            continue
        if len(rows) < MIN_ROW:
            continue
        width = max(len(r) for r in rows)
        if width < MIN_COL:
            continue
        box = list(t.bbox)
        tables.append({
            "n_row": len(rows), "n_col": width,
            "unit": _nearest_unit(page, box),
            "md": table_to_md(rows),
        })
        boxes.append(box)

    parts = []
    try:
        blocks = page.get_text("blocks")
    except Exception:
        blocks = []
    for b in blocks:
        if b[6] != 0:
            continue
        cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
        if any(x0 - 2 <= cx <= x1 + 2 and y0 - 2 <= cy <= y1 + 2 for x0, y0, x1, y1 in boxes):
            continue
        s = b[4].strip()
        if s:
            parts.append(s)
    return "\n".join(parts), tables


def extract_pdf(path, company, limit=None):
    doc = pymupdf.open(path)
    n = min(doc.page_count, limit) if limit else doc.page_count
    sec, sub = "", ""
    records = []
    for i in range(n):
        try:
            text, tables = extract_page(doc[i])
        except Exception as e:
            records.append({"page": i + 1, "error": f"{type(e).__name__}: {e}",
                            "n_chars": 0, "text": "", "tables": []})
            continue

        for line in text.split("\n"):
            s = parse_section(line)
            if s:
                sec, sub = s, ""
                continue
            nt = parse_note(line)
            if nt and sec.startswith("第") and ("财务" in sec or "会计" in sec):
                sub = nt

        records.append({
            "company": company["cn"], "code": company["code"], "sector": company["sector"],
            "year": YEAR, "page": i + 1, "section": sec, "subsection": sub,
            "n_chars": len(text), "text": text, "tables": tables,
        })
    total = doc.page_count
    doc.close()
    return records, total


def main():
    limit = None
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])

    companies = load_companies()
    grand = {"pages": 0, "chars": 0, "tables": 0, "flagged": []}
    t0 = time.time()
    for c in companies:
        src = pdf_path(c["code"], c["cn"])
        if not os.path.exists(src):
            print(f"  !! 缺 PDF: {src}")
            continue
        dst = os.path.join(EXTRACT_DIR, f"{c['code']}.jsonl")
        recs, total_pages = extract_pdf(src, c, limit)

        with open(dst, "w", encoding="utf-8") as f:
            for r in recs:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

        pages = len(recs)
        chars = sum(r.get("n_chars", 0) for r in recs)
        tabs = sum(len(r.get("tables", [])) for r in recs)
        per_page = chars / pages if pages else 0
        grand["pages"] += pages
        grand["chars"] += chars
        grand["tables"] += tabs
        flag = ""
        if per_page < 50:
            flag = "  ⚠ 页均字符过少，疑似扫描件"
            grand["flagged"].append(c["cn"])
        print(f"  {c['cn']:<6}({c['code']}) {pages:>4}页  文本{chars:>9,}字  "
              f"页均{per_page:>6.0f}  表{tabs:>5}张{flag}")

    dt = time.time() - t0
    print(f"\n合计 {grand['pages']} 页 / {grand['chars']:,} 字 / {grand['tables']} 张表，"
          f"耗时 {dt:.1f}s（{dt/max(grand['pages'],1)*1000:.0f} ms/页）")
    if grand["flagged"]:
        print(f"⚠ 需人工复核的疑似扫描件: {', '.join(grand['flagged'])}")
    print(f"输出目录: {EXTRACT_DIR}")


if __name__ == "__main__":
    main()
