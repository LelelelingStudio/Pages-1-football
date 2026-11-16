# -*- coding: utf-8 -*-
"""每日更新：抓取 → 注入 → 重建离线版 → 检查闸门 → 提交 → 推送。

用法（在仓库根目录）：
    python tools/daily_update.py            # 抓取 + 构建 + 提交（不推送）
    python tools/daily_update.py --push     # 再推送到 origin/main
    python tools/daily_update.py --force    # 跳过闸门 --no-verify（恢复限制后才用得上）
    python tools/daily_update.py --skip-fetch   # 不重新抓取，只重建 + 提交

流程说明
--------
1. 调抓取管线，生成 news.json 并注入 index.html
2. 重建自包含离线单文件 offline.html
3. 跑发布闸门（只读）：当前每天可推任意次，一律放行；恢复限制后才按天拦截
4. git add + commit（日期戳由 .githooks/pre-commit 自动盖，历史可查）
5. git push origin main（pre-push 钩子会再核一次闸门，当前直接放行）

关于顺序的两个细节
------------------
* 闸门在推送之前（恢复限制后才会真的拦）：先确认「今天还没发过」，
  再允许把新数据推上去。当前开关关闭，这一步只是留痕。
* 推送失败不用回滚日期戳：日期戳是**提交**时盖的，不是推送时写的。
  恢复限制后，pre-push 判据看的是**远端历史**，所以推送失败后当天仍可重试。
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
    print("[1/5] 抓取资讯、集锦、赛果与即将开赛 ...")
    import update_news
    update_news.main()
    print("      抓取完成")


def rebuild_offline():
    print("[2/5] 重建自包含离线单文件 ...")
    import build_offline
    build_offline.build()


def gate(force):
    """只读检查发布资格。判定与 pre-push 钩子完全一致。

    当前闸门总开关 ENABLE_DAILY_LIMIT=False，每次都放行；
    若以后改回 True 恢复「一天一次」，这里才会拒绝当天二次发布。
    """
    print("[3/5] 检查发布闸门 ...")
    allowed, reason = daily_gate.check_push(force=force)
    print("      %s（%s）" % ("允许发布" if allowed else "拒绝发布", reason))
    if not allowed:
        raise SystemExit(
            "闸门恢复了「一天一次」限制，今天已经发布过。强制重发请加 --force "
            "（或直接 git push --no-verify）。")
    return reason


def commit(message):
    print("[4/5] 提交改动 ...")
    sh(["git", "add", "-A"])
    # 没有改动就别硬造一个空提交
    st = sh(["git", "status", "--porcelain"], check=False)
    if not st.stdout.strip():
        print("      没有需要提交的改动（内容与上次一致）")
        return False
    sh(["git", "commit", "-m", message])
    sha = sh(["git", "rev-parse", "--short", "HEAD"]).stdout.strip()
    print("      已提交 %s：%s" % (sha, message))
    print("      （日期戳已由 pre-commit 钩子自动盖上）")
    return True


def push(force=False):
    """推送到 origin/main。

    --force 时必须真的加 --no-verify：只让脚本内的 gate() 放行没用，
    pre-push 钩子是 git 在 push 阶段独立调用的，仍会按远端历史拦下来。
    """
    print("[5/5] 推送到 origin/main ...")
    cmd = ["git", "push"]
    if force:
        cmd.append("--no-verify")
        print("      （--force：本次跳过 pre-push 闸门）")
    cmd += ["origin", "main"]
    p = sh(cmd, check=False)
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

    stamp = ""
    try:
        d = json.load(io.open(paths.NEWS_JSON, encoding="utf-8"))
        stamp = d.get("updated_at", "")
    except Exception:
        pass
    commit("更新：%s" % (stamp or daily_gate.beijing_today()))

    if args.push:
        if not push(force=args.force):
            raise SystemExit(
                "推送失败。可能是网络问题，或被每日闸门的 pre-push 钩子拦住了。"
                "修好之后重新运行本脚本即可 —— 提交还在本地，"
                "远端历史里没有今天的戳，所以今天仍然可以重试。")
    else:
        print("[5/5] 未指定 --push，跳过推送（需要发布请加 --push）")
    print("完成。")


if __name__ == "__main__":
    main()
