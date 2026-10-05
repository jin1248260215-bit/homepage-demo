# -*- coding: utf-8 -*-
"""从巨潮资讯网（cninfo）下载 15 家能源公司 FY2025 年度报告全文。

标题匹配必须放宽——实测四家写法各不相同：
    中国神华  <em>中国神华</em>2025年度报告        （年度报告，无「年」）
    中国石油  中国石油天然气股份有限公司2025年年报  （年报）
    中国石化  中国石化2024年年度报告               （年年度报告）
    华能国际  华能国际2024年年度报告全文           （全文 后缀）
只认「20XX年年度报告$」会静默漏掉中国神华和中国石油。
"""
import os
import re
import sys
import time

import requests

from common import PDF_DIR, YEAR, load_companies

HEAD = {
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Referer": "http://www.cninfo.com.cn/new/commonUrl?url=disclosure/list/notice",
}
QUERY = "http://www.cninfo.com.cn/new/hisAnnouncement/query"
STATIC = "http://static.cninfo.com.cn/"

# 排除：摘要、英文版、修订/更正/补充/更新、H 股报告、单纯的「公告」
BAD = re.compile(r"摘要|英文|English|修订|取消|更正|补充|更新|业绩公告|H股|公告$")
# 接受四种写法，结尾可带「全文」
OK = re.compile(r"(年度报告|年报)\s*(全文)?$")


def _clean(title):
    """去掉巨潮返回的高亮标记，兼容两种转义形式。"""
    return re.sub(r"&lt;/?em&gt;|</?em>", "", title or "").strip()


def query(name, column, page):
    data = {
        "pageNum": page, "pageSize": 30, "column": column, "tabName": "fulltext",
        "category": "category_ndbg_szsh", "searchkey": name,
        "sortName": "", "sortType": "", "isHLtitle": "true",
    }
    r = requests.post(QUERY, headers=HEAD, data=data, timeout=30)
    r.raise_for_status()
    return r.json()


def pick(company):
    """在巨潮返回里挑出该公司 FY2025 年报全文。返回 (title, size_kb, url) 或 None。"""
    code, name, column = company["code"], company["searchkey"], company["column"]
    cands = []
    for page in (1, 2, 3, 4):
        try:
            js = query(name, column, page)
        except Exception as e:
            print(f"      ! 第{page}页请求失败 {type(e).__name__}", file=sys.stderr)
            break
        anns = js.get("announcements") or []
        for a in anns:
            if a.get("secCode") != code:
                continue
            t = _clean(a.get("announcementTitle"))
            if BAD.search(t):
                continue
            m = re.search(r"(20\d{2})", t)
            if not m or int(m.group(1)) != YEAR:
                continue
            if not OK.search(t):
                continue
            cands.append((a.get("announcementTime", 0), a.get("adjunctSize") or 0, t, a["adjunctUrl"]))
        time.sleep(0.3)
        if len(anns) < 30:      # 已经翻到最后一页
            break

    if not cands:
        return None
    # 最新披露优先；同一次披露若有多个候选，取体积最大的（= 全文，不是摘要）
    cands.sort(key=lambda x: (x[0], x[1]), reverse=True)
    _, size, title, url = cands[0]
    return title, size, url


def main():
    companies = load_companies()
    print(f"目标：{len(companies)} 家，FY{YEAR} 年度报告全文\n")
    ok = fail = 0
    for i, c in enumerate(companies, 1):
        dst = os.path.join(PDF_DIR, f"{c['code']}_{c['cn']}_FY{YEAR}.pdf")
        tag = f"[{i:>2}/{len(companies)}] {c['cn']:<6}({c['code']}) {c['sector']:<5}"

        if os.path.exists(dst) and os.path.getsize(dst) > 200_000:
            print(f"{tag} 已存在 {os.path.getsize(dst)/1024/1024:6.2f} MB")
            ok += 1
            continue

        hit = pick(c)
        if not hit:
            print(f"{tag} ❌ 未搜到 FY{YEAR} 年报")
            fail += 1
            continue

        title, size_kb, url = hit
        try:
            r = requests.get(STATIC + url, headers={"User-Agent": HEAD["User-Agent"]}, timeout=180)
            r.raise_for_status()
        except Exception as e:
            print(f"{tag} ❌ 下载失败 {type(e).__name__}: {e}")
            fail += 1
            continue

        with open(dst, "wb") as f:
            f.write(r.content)
        mb = len(r.content) / 1024 / 1024
        warn = "  ⚠ 体积异常，需查是否扫描件" if mb > 30 else ""
        print(f"{tag} ✅ {mb:6.2f} MB  「{title}」{warn}")
        ok += 1
        time.sleep(0.6)

    print(f"\n完成：成功 {ok} / 失败 {fail}")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
