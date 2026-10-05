# -*- coding: utf-8 -*-
"""把交付物集中复制到一个独立文件夹，方便直接翻看。

为什么不手工复制：手工复制的副本会**各自过期**——改了 `REPORT.md`，桌面那份还是旧的，
而且没有任何东西会提醒你。做成脚本后，改完再跑一次即可，副本永远跟着仓库走。

注意分工：**仓库仍是唯一的真源（source of truth）**，交付文件夹里的全部是副本。
要改内容请改仓库里的原文件，然后重跑本脚本；不要在交付文件夹里直接改，
下次刷新会把改动覆盖掉。

用法：python src/make_delivery.py
输出：桌面/财报问答_交付物/
"""
import os
import re
import shutil
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import EVAL_DIR, ROOT, SHOT_DIR                  # noqa: E402

DEST = os.path.join(os.path.dirname(ROOT), "财报问答_交付物")
SHOTS_DEST = os.path.join(DEST, "截图")

# (仓库内相对路径, 交付文件夹里的名字)
FILES = [
    ("REPORT.md", "一页结论.md"),
    ("README.md", "README.md"),
    (os.path.join("eval", "评测报告.md"), "逐题评测报告.md"),
    (os.path.join("docs", "table_audit.md"), "表格审计.md"),
    (os.path.join("docs", "table_fidelity.md"), "表格保真度对照.md"),
    (os.path.join("eval", "gold_answers.json"), "标准答案与页码出处.json"),
]

# 文内引用改写：原文里写的是**仓库内**路径，照抄进交付夹就会指向不存在的地方
# （「页面截图见 docs/screenshots/」——交付夹里根本没有 docs/ 这一层）。
# 所以复制文本类文件时把指向交付物本身的路径改成交付夹里的相对路径。
REWRITE = [
    ("eval/评测报告.md", "逐题评测报告.md"),
    ("docs/screenshots/", "截图/"),
    ("docs/table_audit.md", "表格审计.md"),
    ("docs/table_fidelity.md", "表格保真度对照.md"),
    ("eval/gold_answers.json", "标准答案与页码出处.json"),
]

TEXT_EXT = (".md", ".json", ".txt")


HTML_TPL = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>{title}</title>
<style>
body{{margin:0;background:#f5f6f8;color:#15181c;
 font:15px/1.75 "Microsoft YaHei","Segoe UI",sans-serif}}
.wrap{{max-width:900px;margin:0 auto;background:#fff;padding:34px 44px 70px;
 border-left:1px solid #e3e6ea;border-right:1px solid #e3e6ea}}
h1{{font-size:25px;border-bottom:2px solid #1f6feb;padding-bottom:10px}}
h2{{font-size:20px;margin-top:34px;border-bottom:1px solid #e3e6ea;padding-bottom:6px}}
h3{{font-size:16.5px;margin-top:26px}}
table{{border-collapse:collapse;width:100%;font-size:13.5px;margin:14px 0}}
th,td{{border:1px solid #d7dbe0;padding:7px 10px;text-align:left;vertical-align:top}}
th{{background:#f2f5f9;font-weight:600}}
tr:nth-child(even) td{{background:#fafbfc}}
code{{background:#f2f4f7;padding:1px 5px;border-radius:4px;
 font-family:Consolas,"Microsoft YaHei",monospace;font-size:13px}}
pre{{background:#f7f8fa;border:1px solid #e3e6ea;border-radius:7px;padding:12px;overflow:auto}}
pre code{{background:none;padding:0}}
blockquote{{margin:12px 0;padding:8px 16px;border-left:3px solid #1f6feb;
 background:#f6f9ff;color:#33475b}}
a{{color:#1f6feb}}
hr{{border:0;border-top:1px solid #e3e6ea;margin:30px 0}}
img{{max-width:100%}}
.tip{{background:#fffbe8;border:1px solid #f0d98c;padding:10px 14px;border-radius:7px;
 font-size:13px;color:#5c4a10}}
</style></head><body><div class="wrap">
<div class="tip">这是 <b>{title}</b> 的网页版，由 Markdown 自动生成，双击即可用浏览器阅读。
要改内容请改仓库里的原文件，然后重跑 <code>python src/make_delivery.py</code>。</div>
{body}
</div></body></html>"""


def to_html(md_text, title):
    """Markdown → 自带样式的单文件 HTML。

    为什么值得做这一步：.md 是纯文本，用记事本打开会看到满屏 `##` 和 `|`，
    而这些文档里表格极多，纯文本下基本没法读。转成 html 后双击用浏览器打开
    即可正常排版，**不需要装 VS Code / Typora / pandoc 任何东西**。
    """
    import mistune
    md = mistune.create_markdown(plugins=["table", "strikethrough", "url", "task_lists"])
    body = md(md_text)
    # 文档之间的链接原本指向 .md；在网页版里点 .md 会变成下载，
    # 所以改指同名的 .html，点开才是排版好的页面。
    body = re.sub(r'href="([^"]+)\.md"', r'href="\1.html"', body)
    return HTML_TPL.format(title=title, body=body)


def build_index(copied, shots):
    """生成 00_先读我.md：先看哪份、每份是什么、以及怎么刷新。"""
    L = []
    L.append("# 能源行业财报问答知识库 · 交付物\n")
    L.append("这个文件夹里的东西**全部是副本**，真源是 `桌面/energy-report-rag/`（代码在那里）。\n")
    L.append(f"生成时间：{time.strftime('%Y-%m-%d %H:%M')}　"
             "由 `python src/make_delivery.py` 生成。\n")

    L.append("\n## 怎么打开这些文件（重要）\n")
    L.append("`.md` 是 **Markdown**，本质是**纯文本**——用记事本也能开，但会看到满屏 `##` 和 `|`，"
             "而这几份文档里表格极多，纯文本下基本没法读。\n")
    L.append("**所以：请双击同名的 `.html` 文件**（用浏览器打开），排版、表格都是正常的，"
             "**不需要安装任何软件**。`.md` 是给程序和版本管理用的原件，可以不看。\n")
    L.append("| 想看什么 | 双击这个 | 是什么 |")
    L.append("|---|---|---|")
    L.append("| ① **只看一份** | **一页结论.html** | 哪类题答得好、哪类翻车、为什么 |")
    L.append("| ② | 逐题评测报告.html | 10 道题逐题明细：召回了哪些块、答对没有、错在哪里、模型答案原文 |")
    L.append("| ③ | 截图/ | 8 张页面截图（问答页面 + 评测总表） |")
    L.append("| ④ | 表格审计.html | 表格还原缺陷的实测计数（可复现） |")
    L.append("| ⑤ | 标准答案与页码出处.json | 人工核出的标准答案，判分基准 |")
    L.append("| ⑥ | README.html | 代码怎么跑、技术选型、踩过的坑 |")
    L.append("| ⑦ | 表格保真度对照.html | pymupdf vs pdfplumber 的表格抽取对照 |")

    L.append("\n## 三样交付物分别在哪\n")
    L.append("| 交付物 | 位置 |")
    L.append("|---|---|")
    L.append("| **代码仓库**（可提交 GitHub） | `桌面/energy-report-rag/`（本文件夹里没有代码，代码在原处） |")
    L.append("| **页面截图** | 本文件夹 `截图/`（8 张） |")
    L.append("| **一页结论** | 本文件夹 `一页结论.md` |")

    L.append("\n## 关于文内的路径\n")
    L.append("指向**交付物**的引用已经改写成本文件夹内的相对路径（例如 `截图/`、`逐题评测报告.md`），"
             "直接点开就能跳到。\n")
    L.append("但指向**代码**的路径（`src/xxx.py`、`eval/apply_grades.py`）保持原样——"
             "代码不在本文件夹里，它们都在 `桌面/energy-report-rag/` 下。\n")

    L.append("\n## 截图清单\n")
    for s in shots:
        L.append(f"- `截图/{s}`")

    L.append("\n---\n\n## 怎么刷新这个文件夹\n")
    L.append("改完仓库里的原文件后，跑一次就能同步：\n")
    L.append("```bash")
    L.append("cd 桌面/energy-report-rag")
    L.append("python src/make_delivery.py")
    L.append("```\n")
    L.append("**不要在交付文件夹里直接改文件**——下次刷新会覆盖掉。\n")

    if len(copied) != len(FILES):
        L.append("\n> ⚠ 有文件没复制成功，见脚本输出。\n")
    return "\n".join(L)


def main():
    # 只清空内容，**不删目录本身**：Windows 上如果这个目录正被别的进程占着
    # （比如资源管理器开着、或它就是当前 shell 的工作目录），
    # `rmtree` 会把里面的文件删干净、最后卡在删目录那一步报 WinError 32，
    # 留下一个半清空的文件夹。留目录、清内容就没这个问题。
    os.makedirs(DEST, exist_ok=True)
    for entry in os.listdir(DEST):
        p = os.path.join(DEST, entry)
        shutil.rmtree(p, ignore_errors=True) if os.path.isdir(p) else os.remove(p)
    os.makedirs(SHOTS_DEST, exist_ok=True)

    copied, missing, fixed = [], [], 0
    for rel, name in FILES:
        src = os.path.join(ROOT, rel)
        if not os.path.exists(src):
            missing.append(rel)
            print(f"  !! 缺文件 {rel}（先跑生成它的脚本）")
            continue
        if rel.endswith(TEXT_EXT):
            with open(src, encoding="utf-8") as f:
                txt = f.read()
            for a, b in REWRITE:
                if a in txt:
                    fixed += txt.count(a)
                    txt = txt.replace(a, b)
            with open(os.path.join(DEST, name), "w", encoding="utf-8") as f:
                f.write(txt)
            if name.endswith(".md"):                        # 附一份网页版
                with open(os.path.join(DEST, name[:-3] + ".html"), "w",
                          encoding="utf-8") as f:
                    f.write(to_html(txt, name[:-3]))
        else:
            shutil.copy2(src, os.path.join(DEST, name))
        copied.append(name)
        print(f"  OK  {name}")

    shots = sorted(f for f in os.listdir(SHOT_DIR) if f.lower().endswith(".png"))
    for s in shots:
        shutil.copy2(os.path.join(SHOT_DIR, s), os.path.join(SHOTS_DEST, s))
    print(f"  OK  截图/  {len(shots)} 张")

    idx = build_index(copied, shots)
    with open(os.path.join(DEST, "00_先读我.md"), "w", encoding="utf-8") as f:
        f.write(idx)
    with open(os.path.join(DEST, "00_先读我.html"), "w", encoding="utf-8") as f:
        f.write(to_html(idx, "00_先读我"))

    print(f"  OK  文内引用改写 {fixed} 处（把仓库内路径换成交付夹内的相对路径）")
    print(f"  OK  网页版 {len([c for c in copied if c.endswith('.md')]) + 1} 份"
          "（双击 .html 看排版，不用装任何软件）")
    print(f"\n完成 -> {DEST}")
    if missing:
        print(f"有 {len(missing)} 个文件缺失：{missing}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
