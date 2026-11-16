# -*- coding: utf-8 -*-
"""把 app（每日新闻目录）的最新数据同步到本仓库并推送到 GitHub Pages。

背景
----
项目现在有两个线上出口，数据源都在 C:\\Users\\xinyue\\Desktop\\每日新闻：

  1. WorkBuddy 静态托管（app）：由「今日球报：每日更新并自动同步线上」
     定时任务每小时检查，数据变了就发布到 app.workbuddy.host
  2. GitHub Pages（本仓库）：靠 git push 触发自动重建

本脚本负责第 2 条。它检测 app 数据源的 news.json 是否比本仓库的新，
若新则：复制数据 → 注入 index.html → 重建 offline.html → commit → push。

「一天最多一次 push」由 .githooks/pre-push 闸门保证，本脚本不绕过它：
当天已经推过时，push 会被拦，脚本如实报告并正常退出（不算失败），
第二天闸门放行后会自动把攒下的更新推上去。

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
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import paths  # noqa: E402

# app 的数据源目录（WorkBuddy 定时任务抓取、发布的地方）
APP_DIR = r"C:\Users\xinyue\Desktop\每日新闻"
APP_NEWS = os.path.join(APP_DIR, "news.json")


def log(msg):
    print(msg, flush=True)


def read_updated_at(path):
    """读 news.json 的 updated_at；读不到返回空串。"""
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只检测，不改动不推送")
    ap.add_argument("--force", action="store_true", help="应急绕过每日闸门")
    args = ap.parse_args()

    # 1) 检测 app 数据源是否存在、是否比本仓库新
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

    if args.dry_run:
        log(json.dumps({"app_updated_at": app_stamp, "pages_updated_at": local_stamp,
                        "need_sync": app_stamp != local_stamp}, ensure_ascii=False))
        return

    if app_stamp == local_stamp:
        log(json.dumps({"action": "skip", "reason": "已是最新，无需同步",
                        "updated_at": local_stamp}, ensure_ascii=False))
        return

    # 2) 复制数据 + 注入 index.html + 重建离线版
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

    # 3) 提交（钩子会自动盖当天日期戳）
    git("add", "-A")
    st = git("status", "--porcelain", check=False)
    if not st.stdout.strip():
        log(json.dumps({"action": "skip", "reason": "文件无实际变化"},
                       ensure_ascii=False))
        return
    git("commit", "-m", "同步 app 数据：%s" % app_stamp)
    sha = git("rev-parse", "--short", "HEAD").stdout.strip()
    log("[3/4] 已提交 %s" % sha)

    # 4) 推送（闸门一天一次；--force 时才绕过）
    log("[4/4] 推送到 origin/main ...")
    push_args = ["push"]
    if args.force:
        push_args.append("--no-verify")
    push_args += ["origin", "main"]
    p = git(*push_args, check=False)
    if p.returncode != 0:
        msg = (p.stderr or p.stdout or "").strip()
        # 闸门拦截属正常：当天已发过，提交留在本地，明天自动推
        if "每日闸门" in msg or "已经发布过" in msg or "pre-push" in msg:
            log(json.dumps({"action": "deferred", "reason": "当天已推送过，提交留在本地，明天自动推",
                            "local_sha": sha, "app_updated_at": app_stamp},
                           ensure_ascii=False))
            return
        log(json.dumps({"action": "error", "reason": "推送失败：%s" % msg[:200],
                        "local_sha": sha}, ensure_ascii=False))
        return

    log(json.dumps({"action": "published", "sha": sha,
                    "app_updated_at": app_stamp,
                    "reason": "已推送，等 1-3 分钟 Pages 自动重建"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
