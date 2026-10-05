# -*- coding: utf-8 -*-
"""问答页面：检索 + 出处，可选 LLM 生成答案。

两种模式：
  离线检索  永远可用，不需要任何凭证。页面默认走这条。
  生成答案  走 DeepSeek，凭证只从环境变量读。取不到凭证时页面照常工作，
            只是「生成答案」按钮返回一条说明，检索结果不受影响。

关于服务端预渲染
----------------
带 `?q=...&ask=1` 访问时，检索和生成都在**服务端**做完，结果以 JSON 内联进 HTML，
页面加载后同步渲染。这么做是为了截图：Chrome 无头 `--screenshot` 在页面加载完
立刻拍照，纯前端 fetch 方案拍到的会是空页面。预渲染让截图结果确定可复现。
"""
import json
import os
import time

from flask import Flask, jsonify, render_template_string, request

from common import EVAL_DIR, INDEX_DIR, load_companies
from llm import answer as llm_answer
from retrieval import get_retriever

app = Flask(__name__)

MODES = {"hybrid": "混合(BM25+向量)", "bm25": "仅 BM25", "dense": "仅向量"}

CSS = """
:root{--bg:#f5f6f8;--card:#fff;--ink:#15181c;--mut:#6b7280;--line:#e3e6ea;--acc:#1f6feb}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.65 "Microsoft YaHei","Segoe UI",sans-serif}
header{background:linear-gradient(100deg,#0d2440,#1f6feb);color:#fff;padding:20px 28px}
header h1{margin:0 0 4px;font-size:19px;font-weight:600}
header .sub{opacity:.86;font-size:12.5px}
.wrap{max-width:1180px;margin:0 auto;padding:18px 28px 70px}
.panel{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:15px 16px;margin-bottom:14px}
.row{display:flex;gap:10px;flex-wrap:wrap;align-items:center}
input[type=text]{flex:1;min-width:260px;padding:10px 12px;border:1px solid var(--line);border-radius:7px;font-size:14px}
select{padding:8px 10px;border:1px solid var(--line);border-radius:7px;background:#fff;font-size:13px}
button{padding:10px 18px;border:0;border-radius:7px;background:var(--acc);color:#fff;font-size:14px;cursor:pointer;font-weight:600}
button.ghost{background:#fff;color:var(--acc);border:1px solid var(--acc);font-weight:500}
.card{border:1px solid var(--line);border-radius:9px;padding:13px 15px;margin-bottom:11px;background:#fff}
.card .top{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:7px}
.badge{font-size:11.5px;padding:2px 8px;border-radius:20px;background:#eef2f7;color:#33475b;white-space:nowrap}
.badge.co{background:#e7f0ff;color:#12509b;font-weight:600}
.badge.tab{background:#f3ebff;color:#6321c4;font-weight:600}
.badge.sec{background:#eaf6ee;color:#0a7d43}
.score{font-size:11.5px;color:var(--mut);font-family:ui-monospace,Consolas,monospace;margin-left:auto}
.body{white-space:pre-wrap;word-break:break-word;font-size:13px;max-height:340px;overflow:auto}
.body.tab{font-family:ui-monospace,Consolas,"Microsoft YaHei",monospace;font-size:12px;background:#fbfbfd;padding:8px;border-radius:6px}
#ans{background:#fbfdff;border:1px solid #cfe1fb;border-radius:9px;padding:14px 16px;white-space:pre-wrap;font-size:13.5px}
#ans a{color:var(--acc);text-decoration:none;font-weight:600}
.mut{color:var(--mut);font-size:12.5px}
.err{color:#b42318;background:#fef3f2;border:1px solid #fecdca;padding:10px 12px;border-radius:8px;font-size:13px}
table{border-collapse:collapse;width:100%;font-size:12.5px;background:#fff}
th,td{border:1px solid var(--line);padding:6px 9px;text-align:left;vertical-align:top}
th{background:#f2f5f9;font-weight:600}
tr.ok td{background:#f4fbf7} tr.part td{background:#fffbf0} tr.bad td{background:#fff5f4}
.kpi{display:flex;gap:12px;flex-wrap:wrap;margin:14px 0}
.kpi div{background:#fff;border:1px solid var(--line);border-radius:9px;padding:10px 16px}
.kpi b{display:block;font-size:21px;color:var(--acc)}
"""

PAGE = r"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>能源行业财报问答知识库</title>
<style>__CSS__</style></head><body>
<header>
  <h1>能源行业财报问答知识库</h1>
  <div class="sub">__SUB__</div>
</header>
<div class="wrap">
  <div class="panel">
    <div class="row">
      <input type="text" id="q" placeholder="例：中国神华2025年商品煤产量和煤炭销售量分别是多少？" value="__Q0__">
      <select id="mode">__MODE_OPTS__</select>
      <select id="types">__TYPE_OPTS__</select>
      <select id="cap">__CAP_OPTS__</select>
      <button onclick="run()">检索</button>
      <button class="ghost" onclick="ask()">生成答案</button>
    </div>
    <div class="row" style="margin-top:9px">
      <span class="mut">按公司过滤（不选=全部 15 家）：</span>
      <select id="co"><option value="">全部 15 家</option>__CO_OPTS__</select>
      <span class="mut" id="stat"></span>
    </div>
  </div>
  <div id="ansbox" style="display:none;margin-bottom:14px"><div id="ans"></div></div>
  <div id="res"></div>
</div>
<script>
const esc=s=>String(s??"").replace(/[&<>]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]));
function params(){
  const p=new URLSearchParams();
  p.set("q",document.getElementById("q").value.trim());
  p.set("mode",document.getElementById("mode").value);
  const t=document.getElementById("types").value; if(t)p.set("types",t);
  const c=document.getElementById("cap").value; if(c)p.set("per_company_max",c);
  const co=document.getElementById("co").value; if(co)p.set("companies",co);
  p.set("k",8); return p;
}
function renderSearch(js){
  document.getElementById("stat").textContent =
    `召回 ${js.results.length} 块 · 检索方式 ${js.mode_cn} · 耗时 ${js.ms} ms`;
  document.getElementById("res").innerHTML = js.results.map((c,i)=>`
    <div class="card" id="c${i+1}">
      <div class="top">
        <span class="badge co">${esc(c.company)}</span>
        <span class="badge">${esc(c.sector)}</span>
        <span class="badge sec">${esc(c.section||"未识别章节")}</span>
        <span class="badge">第 ${c.page} 页</span>
        <span class="badge ${c.type==="table"?"tab":""}">${c.type==="table"?"表格":"正文"}</span>
        ${c.unit?`<span class="badge">单位 ${esc(c.unit)}</span>`:""}
        <span class="score">bm25#${c.bm25_rank??"-"} · vec#${c.dense_rank??"-"} · rrf ${c.rrf}</span>
      </div>
      <div class="body ${c.type==="table"?"tab":""}">${esc(c.text)}</div>
    </div>`).join("") || '<div class="panel mut">没有召回任何块。</div>';
}
function renderAnswer(js){
  const box=document.getElementById("ansbox"), a=document.getElementById("ans");
  box.style.display="block";
  a.innerHTML = js.ok
    ? esc(js.answer).replace(/\[(\d+)\]/g,(m,n)=>`<a href="#c${n}">[${n}]</a>`)
      + `<div class="mut" style="margin-top:9px">依据 ${js.n_chunks} 个召回片段 · 模型 ${esc(js.model)}</div>`
    : `<div class="err">生成失败：${esc(js.error)}</div>`;
}
async function run(){
  const q=document.getElementById("q").value.trim(); if(!q)return alert("请输入问题");
  document.getElementById("ansbox").style.display="none";
  renderSearch(await (await fetch("/api/search?"+params())).json());
}
async function ask(){
  const q=document.getElementById("q").value.trim(); if(!q)return alert("请输入问题");
  const a=document.getElementById("ans");
  document.getElementById("ansbox").style.display="block";
  a.innerHTML="<span class='mut'>检索并生成中…</span>";
  renderAnswer(await (await fetch("/api/ask",{method:"POST",
    headers:{"Content-Type":"application/json"},body:JSON.stringify(Object.fromEntries(params()))})).json());
  run();
}
__AUTORUN__
</script></body></html>"""


def _stats():
    p = os.path.join(INDEX_DIR, "build_stats.json")
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {}


def _subtitle():
    s = _stats()
    n = s.get("n_chunks")
    txt = f"15 家公司 · FY2025 年度报告全文 · 共 {n:,} 个检索块" if n else "15 家公司 · FY2025 年度报告全文"
    return txt + " · 出处可追溯至「公司 / 章节 / 页码」"


def _search_params():
    mode = request.args.get("mode", "hybrid") or "hybrid"
    if mode not in MODES:
        mode = "hybrid"
    types = request.args.get("types") or None
    companies = request.args.get("companies") or None
    cap = request.args.get("per_company_max")
    return dict(mode=mode, types=[types] if types else None,
                companies=[companies] if companies else None,
                per_company_max=int(cap) if cap else None)


@app.route("/")
def index():
    q0 = request.args.get("q", "")
    want_ask = request.args.get("ask") == "1"
    pre = None
    if q0:
        rt = get_retriever()
        p = _search_params()
        p.pop("mode", None)
        t0 = time.time()
        chunks = rt.search(q0, k=int(request.args.get("k", 8)),
                           mode=request.args.get("mode", "hybrid"), **p)
        entry = {"q": q0, "results": chunks, "ms": int((time.time() - t0) * 1000),
                 "mode_cn": MODES.get(request.args.get("mode", "hybrid"), MODES["hybrid"])}
        if want_ask:
            entry["answer"] = llm_answer(q0, chunks)
        pre = entry

    autorun = ""
    if pre:
        autorun = ("window.__PRE__=" + json.dumps(pre, ensure_ascii=False) + ";"
                   + "window.addEventListener('load',()=>{"
                   + "if(window.__PRE__.answer){renderSearch(window.__PRE__);renderAnswer(window.__PRE__.answer);}"
                   + "else{renderSearch(window.__PRE__);}});") if want_ask else \
                  ("window.__PRE__=" + json.dumps(pre, ensure_ascii=False) + ";"
                   "window.addEventListener('load',()=>renderSearch(window.__PRE__));")

    def opts(pairs, cur):
        """把下拉项渲染成 option 串，并让当前取值呈选中态。

        不这么做的话，带 URL 参数（如 ?per_company_max=1）访问时，服务端确实按该
        参数检索了，但控件仍显示默认值「不限制每公司」——截图与页面都会误导读者，
        让人以为配额没生效。
        """
        out = []
        for val, label in pairs:
            sel = " selected" if str(val) == str(cur or "") else ""
            out.append(f'<option value="{val}"{sel}>{label}</option>')
        return "".join(out)

    cur_mode = request.args.get("mode", "hybrid")
    cur_type = request.args.get("types", "")
    cur_cap = request.args.get("per_company_max", "")
    cur_co = request.args.get("companies", "")

    modes = opts(list(MODES.items()), cur_mode)
    types = opts([("", "正文+表格"), ("table", "仅表格"), ("text", "仅正文")], cur_type)
    caps = opts([("", "不限制每公司"), ("1", "每公司≤1块"),
                 ("2", "每公司≤2块"), ("3", "每公司≤3块")], cur_cap)
    cos = opts([("", "全部 15 家")] + [(c["cn"], f'{c["cn"]}（{c["sector"]}）')
                                      for c in load_companies()], cur_co)
    return (PAGE.replace("__CSS__", CSS).replace("__SUB__", _subtitle())
                .replace("__CO_OPTS__", cos).replace("__MODE_OPTS__", modes)
                .replace("__TYPE_OPTS__", types).replace("__CAP_OPTS__", caps)
                .replace("__Q0__", q0.replace('"', "&quot;"))
                .replace("__AUTORUN__", autorun))


@app.route("/api/search")
def api_search():
    rt = get_retriever()
    q = request.args.get("q", "").strip()
    t0 = time.time()
    res = rt.search(q, k=int(request.args.get("k", 8)), **_search_params())
    return jsonify({"q": q, "mode": request.args.get("mode", "hybrid"),
                    "mode_cn": MODES.get(request.args.get("mode", "hybrid"), ""),
                    "ms": int((time.time() - t0) * 1000), "results": res})


@app.route("/api/ask", methods=["POST"])
def api_ask():
    d = request.get_json(force=True) or {}
    q = (d.get("q") or "").strip()
    rt = get_retriever()
    cap = d.get("per_company_max")
    res = rt.search(q, k=int(d.get("k", 8)), mode=d.get("mode", "hybrid"),
                    types=[d["types"]] if d.get("types") else None,
                    companies=[d["companies"]] if d.get("companies") else None,
                    per_company_max=int(cap) if cap else None)
    out = llm_answer(q, res)
    out["q"] = q
    return jsonify(out)


@app.route("/eval")
def eval_page():
    p = os.path.join(EVAL_DIR, "results.json")
    if not os.path.exists(p):
        return ("<body style='font:14px \"Microsoft YaHei\",sans-serif;padding:30px'>"
                "<h2>尚未运行评测</h2><p>请先执行 <code>python eval/run_eval.py</code></p></body>")
    js = json.load(open(p, encoding="utf-8"))
    cls = {"对": "ok", "部分对": "part", "错": "bad"}
    rows = ""
    for it in js["items"]:
        rows += (f"<tr class='{cls.get(it.get('verdict'),'')}'>"
                 f"<td>{it['qid']}</td><td>{it['question']}</td><td>{it['type']}</td>"
                 f"<td>{it.get('verdict') or '待判定'}</td>"
                 f"<td>{it.get('error_class') or '—'}</td>"
                 f"<td>{it.get('first_hit_rank') or '未召回'}</td>"
                 f"<td>{', '.join(it.get('retrieved_companies', [])[:6])}</td></tr>")
    s = js["summary"]
    return render_template_string("""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>评测结果</title><style>{{ CSS|safe }}</style></head><body>
<header><h1>评测结果 · {{ n }} 题</h1>
<div class="sub">配置 mode={{ c.mode }} k={{ c.k }} cap={{ c.cap }} fanout={{ c.fanout }}</div></header>
<div class="wrap">
<div class="kpi">
 <div><b>{{ s.n_correct }}/{{ n }}</b>完全答对</div>
 <div><b>{{ s.n_partial }}</b>部分正确</div>
 <div><b>{{ s.n_wrong }}</b>答错</div>
 <div><b>{{ '%.0f%%' % s.recall_rate }}</b>证据召回率</div>
 <div><b>{{ '%.0f' % s.avg_ms }} ms</b>平均检索耗时</div>
</div>
<table><tr><th>#</th><th>问题</th><th>类型</th><th>判定</th><th>错因</th><th>证据块排名</th><th>召回公司</th></tr>
{{ rows|safe }}</table></div></body></html>""",
                               n=len(js["items"]), s=s, rows=rows, c=js["config"], CSS=CSS)


if __name__ == "__main__":
    st = _stats()
    print(f"索引统计: {st}")
    # 端口可覆盖：shoot.py 会挑一个空闲端口塞进来，避免撞上遗留的旧服务
    # （Windows 下 Flask 的 SO_REUSEADDR 允许多个进程同时绑同一端口，新进程
    #  绑得上但不接管流量，请求仍被路由到旧进程——表现是「改了代码截图没变」）。
    port = int(os.environ.get("PORT", 5000))
    app.run(host="127.0.0.1", port=port, debug=False)
