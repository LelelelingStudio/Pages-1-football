# -*- coding: utf-8 -*-
"""把 app（每日新闻目录）的最新数据同步到本仓库并推送到 GitHub Pages。

背景
----
项目有两个线上出口，数据源都在 C:\\Users\\xinyue\\Desktop\\每日新闻：

  1. WorkBuddy 静态托管（app）：由「今日球报：每日更新并自动同步线上」
     定时任务每小时检查，数据变了就发布到 app.workbuddy.host
  2. GitHub Pages（本仓库）：靠 git push 触发自动重建

本脚本负责第 2 条。检测 app 的 news.json 是否比本仓库新，若新则：
复制数据 → 注入 index.html → 重建 offline.html → commit → push。

健壮性（定时任务长期无人值守，必须自愈）
------------------------------------
* 代理自愈：git push 走本机 Clash 内核（7897）。内核可能没在跑，
  ensure_proxy() 会先探测，不通就尝试拉起内核；都不行才如实报错。
* 失败重试：即使数据已是最新，只要本地还有未推送的提交（上次 push
  失败攒下的），本脚本仍会尝试推送，不会因「数据没变」而永远跳过。
* 推送次数：当前每天可 push 任意次（闸门总开关
  tools/daily_gate.py 的 ENABLE_DAILY_LIMIT = False）。
  若以后把开关改回 True 恢复「一天一次」，当天已推过时 push 会被
  pre-push 拦下，脚本记为 deferred 并正常退出，不算失败；
  第二天闸门放行后自动把攒下的更新推上去。

用法
----
    python tools/sync_and_publish.py            # 检测 + 同步 + commit + push
    python tools/sync_and_publish.py --dry-run  # 只检测，不改动、不推送
    python tools/sync_and_publish.py --force    # 应急：绕过闸门强推
"""
import argparse
import io
import json
import os
import shutil
import socket
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import paths  # noqa: E402

# app 的数据源目录（WorkBuddy 定时任务抓取、发布的地方）
APP_DIR = r"C:\Users\xinyue\Desktop\每日新闻"
APP_NEWS = os.path.join(APP_DIR, "news.json")

# 本机 Clash 内核（git push 的代理，端口 7897）
CLASH_EXE = r"C:\Program Files\Clash Verge\verge-mihomo.exe"
CLASH_CFG = r"C:\Users\xinyue\AppData\Local\Temp\clashwork\clash.yaml"
PROXY_PORT = 7897


def log(msg):
    print(msg, flush=True)


def port_alive(port, host="127.0.0.1", timeout=1):
    try:
        s = socket.create_connection((host, port), timeout=timeout)
        s.close()
        return True
    except Exception:
        return False


def ensure_proxy():
    """确保 git push 的代理端口可用；返回 (ok, 说明)。不改动任何持久配置。"""
    if port_alive(PROXY_PORT):
        return True, "代理已在运行"
    if not (os.path.exists(CLASH_EXE) and os.path.exists(CLASH_CFG)):
        return False, "代理未运行且找不到 Clash 内核（%s / %s）" % (CLASH_EXE, CLASH_CFG)
    try:
        # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP：脚本结束后内核继续活到本次推送完成
        flags = 0x00000008 | 0x00000200
        subprocess.Popen(
            [CLASH_EXE, "-d", os.path.dirname(CLASH_CFG), "-f", CLASH_CFG],
            cwd=os.path.dirname(CLASH_CFG),
            creationflags=flags,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except Exception as e:
        return False, "拉起 Clash 内核失败：%s" % str(e)[:120]
    for _ in range(15):
        time.sleep(1)
        if port_alive(PROXY_PORT):
            return True, "已自动拉起 Clash 内核"
    return False, "Clash 内核启动了但 %d 端口仍未就绪" % PROXY_PORT


def read_updated_at(path):
    try:
        with io.open(path, encoding="utf-8") as f:
            return (json.load(f).get("updated_at") or "").strip()
    except Exception:
        return ""


def git(*args, check=True):
    p = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if check and p.returncode != 0:
        raise SystemExit("git %s 失败：%s" % (" ".join(args),
                                             (p.stderr or p.stdout or "").strip()[:300]))
    return p


def pending_commits():
    """本地领先 origin/main 的提交数（上次 push 失败攒下的）。"""
    git("fetch", "origin", check=False)
    p = git("rev-list", "--count", "origin/main..HEAD", check=False)
    try:
        return int((p.stdout or "0").strip())
    except Exception:
        return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只检测，不改动不推送")
    ap.add_argument("--force", action="store_true", help="应急绕过每日闸门")
    args = ap.parse_args()

    if not os.path.exists(APP_NEWS):
        log(json.dumps({"action": "skip", "reason": "app 数据源不存在",
                        "app_news": APP_NEWS}, ensure_ascii=False))
        return

    app_stamp = read_updated_at(APP_NEWS)
    local_stamp = read_updated_at(paths.NEWS_JSON)
    if not app_stamp:
        log(json.dumps({"action": "skip", "reason": "app 数据无 updated_at"},
                       ensure_ascii=False))
        return

    data_changed = (app_stamp != local_stamp)
    pending = pending_commits()

    if args.dry_run:
        log(json.dumps({"app_updated_at": app_stamp, "pages_updated_at": local_stamp,
                        "need_sync": data_changed, "pending_commits": pending},
                       ensure_ascii=False))
        return

    # 数据没变、也没有攒下的提交 → 真的无需动作
    if not data_changed and pending == 0:
        log(json.dumps({"action": "skip", "reason": "已是最新，无需同步",
                        "updated_at": local_stamp}, ensure_ascii=False))
        return

    # 1) 数据变了才复制 + 注入 + 重建
    sha = ""
    if data_changed:
        log("[1/4] 复制 app 最新数据（%s → %s）" % (app_stamp, local_stamp or "空"))
        shutil.copyfile(APP_NEWS, paths.NEWS_JSON)
        import update_news
        import build_offline
        with io.open(paths.NEWS_JSON, encoding="utf-8") as f:
            payload = json.load(f)
        injected = update_news.inject_html(payload)
        log("[2/4] 注入 index.html：%s" % ("成功" if injected else "失败（标记缺失）"))
        if injected:
            build_offline.build()
            log("      离线版 offline.html 已重建")

        git("add", "-A")
        st = git("status", "--porcelain", check=False)
        if st.stdout.strip():
            git("commit", "-m", "同步 app 数据：%s" % app_stamp)
            sha = git("rev-parse", "--short", "HEAD").stdout.strip()
            log("[3/4] 已提交 %s" % sha)
        else:
            log("[3/4] 文件无实际变化，跳过提交")
    else:
        log("[1-3/4] 数据未变，但有 %d 个上次未推送的提交，直接重试推送" % pending)

    # 2) 推送前有未推送提交才推
    if pending_commits() == 0:
        log(json.dumps({"action": "skip", "reason": "无待推送提交"}, ensure_ascii=False))
        return

    ok, note = ensure_proxy()
    log("[4/4] 代理检查：%s" % note)
    if not ok:
        log(json.dumps({"action": "error", "reason": "代理不可用，推送跳过（提交已留在本地，下次自动重试）",
                        "local_sha": sha, "app_updated_at": app_stamp}, ensure_ascii=False))
        return

    push_args = ["push"]
    if args.force:
        push_args.append("--no-verify")
    push_args += ["origin", "main"]
    p = git(*push_args, check=False)
    if p.returncode != 0:
        msg = (p.stderr or p.stdout or "").strip()
        if "每日闸门" in msg or "已经发布过" in msg or "pre-push" in msg:
            log(json.dumps({"action": "deferred", "reason": "当天已推送过，提交留在本地，明天自动推",
                            "local_sha": sha, "app_updated_at": app_stamp},
                           ensure_ascii=False))
            return
        log(json.dumps({"action": "error", "reason": "推送失败：%s" % msg[:200],
                        "local_sha": sha}, ensure_ascii=False))
        return

    log(json.dumps({"action": "published", "sha": sha or "（补推已有提交）",
                    "app_updated_at": app_stamp,
                    "reason": "已推送，等 1-3 分钟 Pages 自动重建"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
