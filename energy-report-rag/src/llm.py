# -*- coding: utf-8 -*-
"""基于召回片段调用 DeepSeek（OpenAI 兼容端点）生成带出处的答案。

凭证处理原则
------------
只从环境变量读，**不打印、不写文件、不进仓库**（.gitignore 已挡住 .env）。
本机 Claude Code 的 ANTHROPIC_BASE_URL 指向 api.deepseek.com/anthropic，
这里把它换成同一家的 OpenAI 兼容端点 /chat/completions。

Prompt 里的五条约束是针对实测会犯的错设计的：
  编数字、忽略单位、混淆合并/母公司报表、该说不确定时硬答。
"""
import os

import requests

SYSTEM = """你是严谨的财报分析助手。你只能依据用户提供的【片段】作答。

规则：
1. 每个事实性陈述后标注来源编号，如 [1]、[2]。
2. 片段中没有的信息，直接回答「片段中没有披露该信息」，禁止用常识补数字。
3. 留意单位：片段里写了（单位：千元/万元/百万元）的，换算时必须说明口径，不要默认是元。
4. 区分合并报表与母公司报表；若两者都出现，明确说明引用的是哪一个。
5. 涉及计算时写出算式，便于核对。
6. 如果多个片段对同一指标给出不同数值，指出差异并说明各自出处，不要挑一个了事。
"""


def endpoint():
    base = os.environ.get("ANTHROPIC_BASE_URL") or "https://api.deepseek.com/anthropic"
    host = base.split("//", 1)[-1].split("/", 1)[0]
    return f"https://{host}/chat/completions"


def api_key():
    """优先专用变量，其次复用 Claude Code 的 token。绝不外传、绝不落盘。"""
    return os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")


def build_context(chunks):
    parts = []
    for i, c in enumerate(chunks, 1):
        kind = "表格" if c["type"] == "table" else "正文"
        parts.append(f"[{i}] {c['header']}（{kind}）\n{c['text']}")
    return "\n\n".join(parts)


def answer(question, chunks, model="deepseek-chat", timeout=150):
    """返回 dict：ok / answer / model / error / n_chunks。"""
    key = api_key()
    if not key:
        return {"ok": False, "answer": None, "n_chunks": len(chunks),
                "error": "未检测到 API 凭证：请设置 DEEPSEEK_API_KEY（或复用 ANTHROPIC_AUTH_TOKEN）。"
                         "检索功能不受影响，仍可正常使用。"}
    if not chunks:
        return {"ok": False, "answer": None, "n_chunks": 0, "error": "没有召回任何片段，拒绝生成。"}

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content":
                f"【片段】\n{build_context(chunks)}\n\n【问题】\n{question}\n\n"
                f"请依据上述 {len(chunks)} 个片段作答，逐句标注 [编号]。"},
        ],
        "temperature": 0.1,
        "stream": False,
    }
    try:
        r = requests.post(endpoint(),
                          headers={"Authorization": f"Bearer {key}",
                                   "Content-Type": "application/json"},
                          json=payload, timeout=timeout)
        if r.status_code != 200:
            return {"ok": False, "answer": None, "n_chunks": len(chunks),
                    "error": f"HTTP {r.status_code}: {r.text[:300]}"}
        js = r.json()
        return {"ok": True, "answer": js["choices"][0]["message"]["content"],
                "model": js.get("model", model), "n_chunks": len(chunks),
                "usage": js.get("usage"), "error": None}
    except Exception as e:
        return {"ok": False, "answer": None, "n_chunks": len(chunks),
                "error": f"{type(e).__name__}: {e}"}
