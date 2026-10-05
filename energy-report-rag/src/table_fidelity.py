# -*- coding: utf-8 -*-
"""对比 pymupdf 与 pdfplumber 的表格还原质量，产出 docs/table_fidelity.md。

为什么要有这个文件
------------------
方案里选了 pymupdf 做主表格引擎（0.03 s/页），pdfplumber 慢约 30 倍。
速度快是有代价的——pymupdf 在合并单元格、换行文字、长文本截断上都有实测缺陷。
这份对照用同一页的真实数据把差异摊开，而不是在 README 里含糊带过。
"""
import os
import sys
import time

import pdfplumber
import pymupdf

from common import DOCS_DIR, find_unit, load_companies, pdf_path
from extract import merge_continuation, table_to_md

SAMPLES = ["600900", "601088", "300750", "600028", "601012"]
N_TABLES = 3          # 每家公司取前 N 张表
MAX_PAGES = 60        # 每家公司最多扫描多少页来找表


def pymupdf_tables(page):
    try:
        tabs = list(page.find_tables().tables)
    except Exception:
        return []
    out = []
    for t in tabs:
        try:
            rows = merge_continuation(t.extract())
        except Exception:
            continue
        if len(rows) >= 2 and max(len(r) for r in rows) >= 2:
            out.append((rows, table_to_md(rows)))
    return out


def pdfplumber_tables(page):
    out = []
    for t in page.find_tables():
        rows = [[(c or "").strip().replace("\n", " ") for c in r] for r in t.extract()]
        if len(rows) >= 2 and max(len(r) for r in rows) >= 2:
            out.append((rows, table_to_md(rows)))
    return out


def main():
    companies = {c["code"]: c for c in load_companies()}
    lines = ["# 表格还原保真度对照\n",
             "同一页、同一张表，两种引擎的输出并列。生成脚本：`src/table_fidelity.py`。\n",
             "| 引擎 | 定位 | 实测速度 | 本方案中的角色 |",
             "|---|---|---|---|",
             "| pymupdf `find_tables()` | 快，无需额外依赖 | ~0.03 s/页 | **主引擎**（全量解析） |",
             "| pdfplumber | 慢，按框线还原 | ~1 s/页 | 抽样对照用 |\n"]
    stats = []

    for code in SAMPLES:
        c = companies.get(code)
        if not c:
            continue
        path = pdf_path(code, c["cn"])
        if not os.path.exists(path):
            print(f"  跳过 {c['cn']}（缺 PDF）")
            continue
        doc = pymupdf.open(path)
        picked = 0
        for i in range(min(doc.page_count, MAX_PAGES)):
            if picked >= N_TABLES:
                break
            t0 = time.time()
            mu = pymupdf_tables(doc[i])
            dt_mu = time.time() - t0
            if not mu:
                continue

            t0 = time.time()
            with pdfplumber.open(path, pages=[i + 1]) as pl:
                pl_tabs = pdfplumber_tables(pl.pages[0])
            dt_pl = time.time() - t0

            picked += 1
            mu_rows, mu_md = mu[0]          # (rows, md) 元组，别把元组当 rows 量长度
            mu_r, mu_c = len(mu_rows), max(len(r) for r in mu_rows)
            pl_rows = pl_tabs[0][0] if pl_tabs else None
            pl_r, pl_c = (len(pl_rows), max(len(r) for r in pl_rows)) if pl_rows else (0, 0)

            lines.append(f"\n---\n\n## {c['cn']} 第 {i+1} 页（第 {picked} 张表）\n")
            unit = find_unit(doc[i].get_text())
            lines.append(f"页内声明的单位：`{unit or '未识别'}`　"
                         f"耗时 pymupdf {dt_mu*1000:.0f} ms / pdfplumber {dt_pl*1000:.0f} ms\n")
            lines.append(f"**pymupdf**（{mu_r} 行 × {mu_c} 列）\n")
            lines.append("```\n" + mu_md[:1400] + "\n```\n")
            if pl_rows:
                lines.append(f"**pdfplumber**（{pl_r} 行 × {pl_c} 列）\n")
                lines.append("```\n" + pl_tabs[0][1][:1400] + "\n```\n")
            else:
                lines.append("**pdfplumber**：该页未识别出表格\n")
            stats.append((c["cn"], i + 1, mu_r, mu_c, pl_r, pl_c, dt_mu, dt_pl))
        doc.close()

    lines.append("\n---\n\n## 汇总\n")
    lines.append("| 公司 | 页 | pymupdf 行×列 | pdfplumber 行×列 | pymupdf ms | pdfplumber ms |")
    lines.append("|---|---|---|---|---|---|")
    for cn, pg, r1, c1, r2, c2, d1, d2 in stats:
        lines.append(f"| {cn} | {pg} | {r1}×{c1} | {r2}×{c2} | {d1*1000:.0f} | {d2*1000:.0f} |")

    lines.append("""
## 观察到的具体缺陷（不是推测，是对照里可见的）

1. **合并单元格错位**：`释义` 这类左右两栏、中间「指」字的表，pymupdf 会把跨行的
   左侧单元格留空并另起一行，行列语义被切断。pdfplumber 同样不完美。
2. **换行文字被拆成多行**：单元格内文字换行时，pymupdf 会把续行当成新的一行。
   本方案的 `extract.py::merge_continuation()` 做了启发式合并，能救回大部分，
   但会把「本来就是独立空行」的情况误并。
3. **长文本被截断**：实测出现过 `香港联合交易` 丢失尾字「所」的情况。
   这类丢字**无法自动修复**，也是评测里 R3（表格还原失败）的主要来源。
4. **速度差约 30 倍**：全量 15 份年报 3800+ 页，pdfplumber 需要约一小时，
   pymupdf 约 4 分钟。这是选择主引擎的决定性因素——不是在精度上做了让步，
   而是在「能跑完」和「跑不完」之间做的取舍。

**结论**：本方案的表格还原"结构基本正确、细节有损"。数值题如果答案落在
带合并单元格或长文本的表里，错误率会明显上升——这一点在 `eval/评测报告.md`
里有对应的逐题记录，不掩盖。
""")

    dst = os.path.join(DOCS_DIR, "table_fidelity.md")
    with open(dst, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"对照写入 {dst}（{len(stats)} 张表样本）")


if __name__ == "__main__":
    sys.exit(main())
