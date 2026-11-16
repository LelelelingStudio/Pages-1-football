# -*- coding: utf-8 -*-
"""每日更新：抓取 → 注入 → 重建离线版 → 检查闸门 → 提交 → 推送。

用法（在仓库根目录）：
    python tools/daily_update.py            # 抓取 + 构建 + 提交（不推送）
    python tools/daily_update.py --push     # 再推送到 origin/main
    python tools/daily_update.py --force    # 忽略每日闸门（应急重发）
    python tools/daily_update.py --skip-fetch   # 不重新抓取，只重建 + 提交

流程说明
--------
1. 调抓取管线，生成 news.json 并注入 index.html
2. 重建自包含离线单文件 offline.html
3. 跑每日闸门（只读）：今天已发布过就拒绝，除非 --force
4. 把日期戳写进 state/last-publish.json
5. git add + commit（推送由 --push 决定）
6. git push origin main（pre-push 钩子会再核一次闸门）

关于顺序的两个细节
------------------
* 闸门在推送之前：先确认「今天还没发过」，再允许把新数据推上去。
* 推送失败时回滚日期戳：否则「写了戳但没推上去」会让当天无法重试。
  回滚后重跑本脚本即可：提交内容一致，git push 会把已有提交推上去。
"""
import argparse
import io
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import daily_gate  # noqa: E402
import paths  # noqa: E402


def sh(args, cwd=ROOT, check=True):
    p = subprocess.run(args, cwd=cwd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if check and p.returncode != 0:
        print((p.stdout or "") + (p.stderr or ""))
        raise SystemExit("命令失败：%s" % " ".join(args))
    return p


def fetch():
    print("[1/6] 抓取资讯、集锦、赛果与即将开赛 ...")
    import update_news
    update_news.main()
    print("      抓取完成")


def rebuild_offline():
    print("[2/6] 重建自包含离线单文件 ...")
    import build_offline
    build_offline.build()


def gate(force):
    """只读检查今天的发布资格。不写日期戳。"""
    print("[3/6] 检查每日闸门 ...")
    allowed, reason, last = daily_gate.check(force=force)
    print("      %s（%s）" % ("允许发布" if allowed else "拒绝发布", reason))
    print("      上次发布日期：%s" % (last or "（无）"))
    if not allowed:
        raise SystemExit(
            "今天已经发布过一次了。强制重发请加 --force "
            "（或直接 git push --no-verify）。")
    return reason


def write_stamp(force):
    """写入今天的日期戳。返回写之前的旧状态（用于失败回滚）。"""
    backup = daily_gate.read_state()
    daily_gate.stamp(force=force, extra={
        "note": "每次发布成功后写入北京日期（UTC+8）。pre-push 钩子据此拦截当天第二次推送。",
    })
    return backup


def rollback_stamp(backup):
    daily_gate.write_state(backup)
    print("      日期戳已回滚，今天仍可重试。")


def commit(message):
    print("[4/6] 提交改动 ...")
    sh(["git", "add", "-A"])
    # 没有改动就别硬造一个空提交
    st = sh(["git", "status", "--porcelain"], check=False)
    if not st.stdout.strip():
        print("      没有需要提交的改动（内容与上次一致）")
        return False
    sh(["git", "commit", "-m", message])
    sha = sh(["git", "rev-parse", "--short", "HEAD"]).stdout.strip()
    print("      已提交 %s：%s" % (sha, message))
    return True


def push():
    print("[5/6] 推送到 origin/main ...")
    p = sh(["git", "push", "origin", "main"], check=False)
    if p.returncode != 0:
        print((p.stdout or "") + (p.stderr or ""))
        return False
    print("      推送成功")
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--push", action="store_true", help="构建后推送到远端")
    ap.add_argument("--force", action="store_true", help="忽略每日闸门")
    ap.add_argument("--skip-fetch", action="store_true",
                    help="跳过抓取，只用现有 news.json 重新构建")
    args = ap.parse_args()

    if not args.skip_fetch:
        fetch()
    rebuild_offline()
    gate(args.force)
    backup = write_stamp(args.force)

    stamp = ""
    try:
        d = json.load(io.open(paths.NEWS_JSON, encoding="utf-8"))
        stamp = d.get("updated_at", "")
    except Exception:
        pass
    commit("更新：%s" % (stamp or daily_gate.beijing_today()))

    if args.push:
        if not push():
            rollback_stamp(backup)
            raise SystemExit(
                "推送失败。可能是网络问题，或被每日闸门的 pre-push 钩子拦住了。"
                "修好之后重新运行本脚本即可（日期戳已回滚，不算今天的发布）。")
    else:
        print("[5/6] 未指定 --push，跳过推送（需要发布请加 --push）")
    print("[6/6] 完成。")


if __name__ == "__main__":
    main()
