# -*- coding: utf-8 -*-
"""起服务 + 用本机 Chrome 无头截图。

为什么要服务端预渲染：Chrome 的 --headless --screenshot 在页面加载完立刻拍照，
而「生成答案」要等 API 返回。app.py 里 `?q=...&ask=1` 会在服务端把检索和生成都做完、
把结果内联进 HTML，所以截图是确定可复现的，不依赖 JS 的时序。

不需要 playwright——本机已装 Chrome，直接用它的 --screenshot。
"""
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))) + "/src")
from common import ROOT, SHOT_DIR                       # noqa: E402

BASE = None                                             # main() 里按空闲端口设定

CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
]


def free_port():
    """向系统要一个空闲端口。

    不要写死 5000：Windows 下 Flask 开发服务器带 SO_REUSEADDR，多个进程可以同时
    绑上同一端口，**新进程绑得上却不接管流量**，请求照样被路由到先绑的那个旧进程。
    于是「改了代码、截图没变」，而且进程不报任何错——排查起来非常费时。
    实测本机 5000 端口上曾同时挂着 5 个上一轮遗留的服务进程。
    """
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def find_chrome():
    for p in CHROME_CANDIDATES:
        if os.path.exists(p):
            return p
    raise SystemExit("找不到 Chrome/Edge")


def wait_up(base, timeout=90):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            urllib.request.urlopen(base + "/eval", timeout=3)
            return True
        except Exception:
            time.sleep(1.5)
    return False


def assert_own_server(base):
    """确认应答的就是本次启动的代码，而不是端口上残留的旧进程。

    判据：带 `?per_company_max=1` 请求首页，控件里必须出现 `value="1" selected`。
    这是 app.py 的服务端渲染逻辑，旧版本（硬编码下拉项、不反映 URL 参数）不会满足。
    不校验的话，截出来的图可能整组来自旧代码，而过程没有任何报错。
    """
    html = urllib.request.urlopen(base + "/?per_company_max=1", timeout=60) \
                       .read().decode("utf-8", "replace")
    if 'value="1" selected' not in html:
        raise SystemExit(
            "端口上的服务不是本次启动的进程（控件未反映 URL 参数）。\n"
            "多半是上一轮遗留的 app.py 仍占着端口，请先结束它再重试。")
    return True


def shot(chrome, name, path, height=1500, width=1600):
    """截一张图。

    `--user-data-dir` **必须每张图一个**：同一个 profile 连续访问同源页面时，
    Chrome 会把上一页的表单状态（下拉框选中的项）恢复到下一页，**盖掉 HTML 里的
    `selected` 属性**。实测后果：`?per_company_max=1` 的页面服务端确实按配额检索了
    （「召回 6 块」），但下拉框仍显示「不限制每公司」——截图自相矛盾、读者会以为配额
    没生效。独立 profile 后，控件状态与 URL 参数一致。
    """
    url = BASE + path
    out = os.path.join(SHOT_DIR, name + ".png")
    prof = os.path.join(os.environ.get("TEMP", "."), "cshot_" + name)
    cmd = [chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars",
           "--force-device-scale-factor=1", f"--window-size={width},{height}",
           f"--user-data-dir={prof}", f"--screenshot={out}", url]
    try:
        subprocess.run(cmd, capture_output=True, timeout=180)
        ok = os.path.exists(out) and os.path.getsize(out) > 5000
        kb = os.path.getsize(out) / 1024 if ok else 0
        print(f"  {'OK ' if ok else 'FAIL'} {name}.png  "
              + (f"{kb:.0f} KB" if ok else "(无输出或过小)"))
        return ok
    finally:
        shutil.rmtree(prof, ignore_errors=True)


def q(s):
    return urllib.parse.quote(s)


def main():
    global BASE
    chrome = find_chrome()
    print(f"浏览器: {chrome}")

    base = f"http://127.0.0.1:{free_port()}"
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PORT"] = base.rsplit(":", 1)[1]      # 让 app.py 绑到我们挑的端口
    server = subprocess.Popen([sys.executable, os.path.join(ROOT, "src", "app.py")],
                              env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    BASE = base
    try:
        if not wait_up(base):
            raise SystemExit("服务未在超时内启动")
        assert_own_server(base)
        print(f"服务已就绪（{base}，已校验为本次启动的进程），开始截图\n")

        # 题目直接从评测集读，不手抄：手抄会让截图和评测报告悄悄漂移
        # （曾经这里写的是 Q10 的简写版，少了「分别下滑多少？」，检索结果和
        #  `/eval` 里的 Q10 对不上，图和表互相印证不了）。
        qs = {}
        with open(os.path.join(ROOT, "eval", "questions.jsonl"), encoding="utf-8") as f:
            for line in f:
                r = json.loads(line)
                qs[r["qid"]] = r["question"]
        q1, q2, q9, q10 = qs[1], qs[2], qs[9], qs[10]

        shots = [
            ("01_首页", "/", 1250),
            ("02_检索结果", "/?q=" + q(q2), 1750),
            ("03_生成答案带出处", "/?q=" + q(q2) + "&ask=1", 2150),
            ("04_全景题_不限额", "/?q=" + q(q9), 1750),
            ("05_全景题_每公司配额1块", "/?q=" + q(q9) + "&per_company_max=1", 1750),
            ("06_评测总表", "/eval", 1500),
            ("07_失败案例_全景题15家", "/?q=" + q(q10) + "&ask=1", 2150),
            ("08_单公司题_正确带出处", "/?q=" + q(q1) + "&ask=1", 2150),
        ]
        ok = sum(shot(chrome, n, p, h) for n, p, h in shots)
        print(f"\n完成 {ok}/{len(shots)} 张 -> {SHOT_DIR}")
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except Exception:
            server.kill()


if __name__ == "__main__":
    main()
