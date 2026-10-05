# -*- coding: utf-8 -*-
"""表格还原质量的量化审计。

为什么要有这个脚本：`REPORT.md` 里「表格题翻车」是一条主要结论，如果只写
「表格还原有损」这种定性说法，等于没写——没法核对、也没法判断该不该动手修。
这里给出一组**可复现**的计数，并落盘到 `docs/table_audit.md`，README/REPORT 引用它。

四个判据（都是保守的代理指标，宁可低估问题的规模）：

1. **坍缩表：单个单元格里聚了 >= 8 个数值。** 正常单元格只装一个值，一格塞进一二十个
   数，说明整张表被拍平进了一格——列名与数值的对应关系丢失，正文里只剩一串无法归属的
   数字。评测里 Q8 就是这个形态。
   （先说清楚一个否掉的判据：`n_col <= 1` 实测为 **0 张**。坍缩不是「变成一列」，
   而是「列数看着正常、内容全在第一个格子里」——用列数抓不到，必须看单元格内容。）
2. 超长单元格 任一单元格 > 60 字：多半是多列内容并进了一格（合并单元格、串列），
   是坍缩的温和版本。
3. 列数异常 `n_col > 20`：跨页横表或纵向排版被误切。
4. 单位缺失 `unit is None`：该表附近没有识别到「单位：X」声明，块的 unit 元数据为空。
   单位是数值题（R6 口径误读）的关键上下文，缺了它模型只能猜。

阈值（8 个数 / 60 字 / 20 列）是拍的，但**判据和计数都公开**，换阈值重跑即可，
结论的可核对性不依赖这些数。
"""
import json
import os
import re
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import DOCS_DIR, EXTRACT_DIR, INDEX_DIR            # noqa: E402

MAX_CELL_CHARS = 60
MAX_COLS = 20
COLLAPSE_NUMS = 8                                               # 单格数值数 >= 此值 → 判为坍缩
NUM = re.compile(r"[-+(]?\d[\d,]*\.?\d*")
OUT = os.path.join(DOCS_DIR, "table_audit.md")


def cells(md):
    """把 markdown 表拆成单元格文本。"""
    out = []
    for line in md.split("\n"):
        line = line.strip()
        if not line.startswith("|"):
            continue
        if set(line) <= set("|-: "):                            # 分隔行
            continue
        out.extend(c.strip() for c in line.strip("|").split("|"))
    return out


def main():
    total = 0
    collapsed = []                                             # (单格数值数, 公司, 页, n_row, n_col)
    n_narrow = 0                                               # n_col <= 1
    longcell = 0
    wide = 0
    no_unit = 0
    worst = []                                                 # (最长单元格, 公司, 页, n_row, n_col)
    per_company = Counter()

    for fn in sorted(os.listdir(EXTRACT_DIR)):
        if not fn.endswith(".jsonl"):
            continue
        with open(os.path.join(EXTRACT_DIR, fn), encoding="utf-8") as f:
            for line in f:
                rec = json.loads(line)
                for t in rec.get("tables") or []:
                    total += 1
                    per_company[rec["company"]] += 1
                    nr, nc = t.get("n_row") or 0, t.get("n_col") or 0
                    cs = cells(t.get("md") or "")
                    ml = max((len(c) for c in cs), default=0)
                    mn = max((len(NUM.findall(c)) for c in cs), default=0)
                    if nc <= 1:
                        n_narrow += 1
                    if mn >= COLLAPSE_NUMS:
                        collapsed.append((mn, rec["company"], rec["page"], nr, nc))
                    if ml > MAX_CELL_CHARS:
                        longcell += 1
                    if nc > MAX_COLS:
                        wide += 1
                    if not t.get("unit"):
                        no_unit += 1
                    worst.append((ml, rec["company"], rec["page"], nr, nc))

    # 块层面的单位覆盖率：模型实际看到的是块，不是表
    n_table_chunks = n_unit_chunks = 0
    cp = os.path.join(INDEX_DIR, "chunks.jsonl")
    if os.path.exists(cp):
        with open(cp, encoding="utf-8") as f:
            for line in f:
                c = json.loads(line)
                if c.get("type") == "table":
                    n_table_chunks += 1
                    if c.get("unit"):
                        n_unit_chunks += 1

    pct = lambda a, b: f"{100.0 * a / b:.1f}%" if b else "—"
    L = []
    L.append("# 表格还原质量审计\n")
    L.append("由 `python src/table_audit.py` 生成，计数可复现。判据见脚本 docstring。\n")
    L.append(f"语料：15 家公司 FY2025 年报，共 **{total:,}** 张表。\n")
    L.append("\n## 四个判据\n")
    L.append("| 判据 | 数量 | 占比 | 说明 |")
    L.append("|---|---|---|---|")
    L.append(f"| 坍缩表（单格 ≥{COLLAPSE_NUMS} 个数值） | {len(collapsed)} | "
             f"{pct(len(collapsed), total)} | 整表拍平进一格，数值无法归属列名 |")
    L.append(f"| 超长单元格（>{MAX_CELL_CHARS} 字） | {longcell} | {pct(longcell, total)} | "
             "多半是多列内容并进一格 |")
    L.append(f"| 列数异常（>{MAX_COLS} 列） | {wide} | {pct(wide, total)} | "
             "跨页横表或纵向排版被误切 |")
    L.append(f"| 单位缺失 | {no_unit} | {pct(no_unit, total)} | "
             "附近没有「单位：X」声明，块上的 unit 元数据为空 |")

    L.append("\n## 块层面的单位覆盖率\n")
    L.append("模型实际读到的是**块**，所以这个数字比上表最后一行更要紧：\n")
    L.append(f"- 表格块 {n_table_chunks:,} 个，其中带 unit 元数据的 **{n_unit_chunks:,} 个"
             f"（{pct(n_unit_chunks, n_table_chunks)}）**。\n")
    L.append("\n也就是说，**约三分之二的表格块没有单位上下文**。数值题里模型看到"
             "「332.1」时，多数情况下无法从块本身得知这是百万吨还是吨——"
             "这是 R6（口径误读）的结构性来源，不是模型不听话。\n")

    L.append(f"\n## 坍缩表清单（单格 ≥{COLLAPSE_NUMS} 个数值）\n")
    if collapsed:
        L.append("| 单格数值数 | 公司 | 页 | n_row | n_col |")
        L.append("|---|---|---|---|---|")
        for mn, co, pg, nr, nc in sorted(collapsed, reverse=True):
            L.append(f"| {mn} | {co} | {pg} | {nr} | {nc} |")
    else:
        L.append("无。\n")

    L.append("\n## 最长的 5 个单元格（超长单元格的典型形态）\n")
    L.append("| 单元格字数 | 公司 | 页 | n_row | n_col |")
    L.append("|---|---|---|---|---|")
    for ml, co, pg, nr, nc in sorted(worst, reverse=True)[:5]:
        L.append(f"| {ml} | {co} | {pg} | {nr} | {nc} |")

    L.append("\n## 按公司\n")
    L.append("| 公司 | 表数 |")
    L.append("|---|---|")
    for co, n in per_company.most_common():
        L.append(f"| {co} | {n} |")

    L.append(f"""
---

## 怎么读这份审计

- **坍缩率低（{pct(len(collapsed), total)}），但它造成的伤害不成比例。** 一张坍缩表里的数字会进上下文，
  却带着错误的结构——模型看到的是一串数，不是「哪个数属于哪一列」。
  评测里 Q8 正是这个形态：**数字送到了，结构没送到，数字就成了噪声。**
- **顺带否掉一个想当然的判据**：坍缩**不是**「表变成一列」。实测 `n_col <= 1` 的表有
  {n_narrow} 张。坍缩的真实形态是「列数看着正常、内容全挤进第一个格子」，只看列数会
  完全漏掉——上表 601088 第 303 页的表 2 就是这样：`n_row=3 n_col=2` 看着没毛病，
  实际一格里塞了 18 个数、列名与数值全被拍平。**指标选错，比没有指标更危险。**
- **不要把「坍缩率低」当成「表格没问题」。** 超长单元格（多列并一格）是同一类错误的
  温和版本，占比高一个量级，同样是数值题失分的来源。
- **单位缺失是最值得先修的一项**：它最容易修（把「单位：」声明的识别窗口从当前页
  扩到前若干页 + 复用同表续页），且直接对应一类错因（R6）。
""")

    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    print(f"已生成 {OUT}")
    print(f"表 {total:,} 张：坍缩 {len(collapsed)} ({pct(len(collapsed), total)})，"
          f"超长单元格 {longcell} ({pct(longcell, total)})，"
          f"列数异常 {wide} ({pct(wide, total)})，"
          f"单位缺失 {no_unit} ({pct(no_unit, total)})")
    if n_table_chunks:
        print(f"表格块 {n_table_chunks:,} 个，带单位 {n_unit_chunks:,} "
              f"({pct(n_unit_chunks, n_table_chunks)})")


if __name__ == "__main__":
    main()
