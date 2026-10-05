# -*- coding: utf-8 -*-
"""公共工具：路径、股票池、单位识别、中文分词。

单位识别单独拿出来，是因为年报里「元 / 千元 / 万元 / 百万元」混用，
是数值题答错的高发原因（评测里归类为 R6 口径误读）。
"""
import os
import re
import json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
PDF_DIR = os.path.join(DATA_DIR, "pdf")
META_DIR = os.path.join(DATA_DIR, "meta")
EXTRACT_DIR = os.path.join(DATA_DIR, "extracted")
INDEX_DIR = os.path.join(ROOT, "index")
EVAL_DIR = os.path.join(ROOT, "eval")
DOCS_DIR = os.path.join(ROOT, "docs")
SHOT_DIR = os.path.join(DOCS_DIR, "screenshots")

YEAR = 2025

for _d in (PDF_DIR, META_DIR, EXTRACT_DIR, INDEX_DIR, EVAL_DIR, DOCS_DIR, SHOT_DIR):
    os.makedirs(_d, exist_ok=True)


def load_companies():
    """读取 15 家公司的股票池元数据。"""
    with open(os.path.join(META_DIR, "companies.json"), encoding="utf-8") as f:
        return json.load(f)


def pdf_path(code, cn):
    return os.path.join(PDF_DIR, f"{code}_{cn}_FY{YEAR}.pdf")


# ---------------------------------------------------------------- 单位识别
# 年报里常见的写法：单位：元 / 单位：人民币千元 / 单位：万元（人民币）
UNIT_RX = re.compile(r"单位\s*[:：]\s*(?:人民币)?\s*(百万元|千元|万元|元)")
UNIT_SCALE = {"元": 1.0, "千元": 1e3, "万元": 1e4, "百万元": 1e6}


def find_unit(text, window=400):
    """在文本（通常取表格上方一小段）中找单位声明，返回 '元'/'千元'/'万元'/'百万元' 或 None。"""
    if not text:
        return None
    m = UNIT_RX.search(text[:window])
    return m.group(1) if m else None


def to_yuan(value, unit):
    """把带单位的金额统一换算成元；单位未知时返回 None，调用方需据此拒绝作答。"""
    if unit is None or value is None:
        return None
    return float(value) * UNIT_SCALE.get(unit, 1.0)


# ---------------------------------------------------------------- 中文分词
# 财报高频词，避免 jieba 把「资产负债率」切成「资产/负债/率」这类碎片
FIN_TERMS = [
    "归属于母公司股东的净利润", "归属于上市公司股东的净利润", "扣除非经常性损益",
    "营业总收入", "营业总成本", "营业收入", "营业成本", "销售费用", "管理费用",
    "研发费用", "财务费用", "资产减值损失", "信用减值损失", "经营活动产生的现金流量净额",
    "基本每股收益", "加权平均净资产收益率", "资产负债率", "毛利率", "净利率",
    "合同负债", "其他流动负债", "少数股东权益", "未分配利润", "货币资金",
    "在建工程", "固定资产", "无形资产", "商誉", "递延所得税",
    "煤炭产量", "煤炭销量", "装机容量", "发电量", "上网电价", "利用小时数",
    "桶油主要成本", "油气产量", "原油产量", "天然气产量", "探明储量",
    "光伏组件", "电池片", "硅片", "动力电池", "储能系统", "逆变器",
]

_jieba = None


# BGE 中文模型（bge-small-zh-v1.5）的官方用法：**只给 query 加指令前缀，passage 不加**。
# 一开始我把这个前缀写进了块的嵌入文本里，那是错的——检索时才对 query 加。
BGE_INSTRUCTION = "为这个句子生成表示以用于检索相关文章："


def tokenize(text):
    """中文分词（jieba 懒加载，首次调用时注入财务词表与公司名）。"""
    global _jieba
    if _jieba is None:
        import jieba
        for t in FIN_TERMS:
            jieba.add_word(t, freq=10_000)
        try:
            for c in load_companies():
                jieba.add_word(c["cn"], freq=50_000)
        except Exception:
            pass
        _jieba = jieba
    return [w for w in _jieba.lcut(text or "") if w.strip()]


# ---------------------------------------------------------------- 章节识别
# 证监会年报标准结构：第一节 释义 … 第十节 财务报告
SECTION_RX = re.compile(r"^\s*第\s*([一二三四五六七八九十百]+)\s*节\s*([^\n]{0,30})")
# 财务报告节内 的附注编号： 「57、销售费用」
NOTE_RX = re.compile(r"^\s*(\d{1,3})\s*、\s*([^\n]{1,24})\s*$")


def parse_section(line):
    """若该行是章节标题，返回 '第X节 名称'，否则 None。"""
    m = SECTION_RX.match(line or "")
    if not m:
        return None
    name = (m.group(2) or "").strip().rstrip("：:")
    return f"第{m.group(1)}节 {name}".strip()


def parse_note(line):
    """若该行是附注小标题（如「57、销售费用」），返回科目名，否则 None。"""
    m = NOTE_RX.match(line or "")
    return m.group(2).strip() if m else None
