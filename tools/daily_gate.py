# -*- coding: utf-8 -*-
"""每日一次发布闸门（客户端侧）。

背景：这个仓库**不使用 GitHub Actions**（用户明确要求：免费额度撑不住，
Pages 的 source 设为分支而非 Actions）。因此「一天只能发布一次」没有
workflow 那种服务端强制力，只能靠本地钩子 + 状态戳来实现。

判定规则
--------
state/last-publish.json 里记着上一次成功发布的北京时间日期。
推送前（pre-push 钩子）比对：
    - 今天（北京）已经发过  -> 拒绝这次推送
    - 今天还没发过        -> 放行

判定基准是 **git 对象里的日期戳**，不是工作区文件：
    - origin/main 的日期戳 = 已经发布到线上的最后一次
    - HEAD 与 HEAD~1 的日期戳 = 本次要推的提交、以及上一次提交
这样「写入日期戳 → 提交 → 推送」这条链路不会自己把自己拦下来。

强制力说明（如实告知，不夸大）
------------------------------
1. pre-push 钩子是**本地**行为：换台电脑 clone、不装钩子、或用
   `git push --no-verify`，都能绕过。这是客户端闸门的固有上限。
2. GitHub Desktop **会执行 git 钩子**（官方文档明确支持，且失败时会
   阻止推送并给出绕过选项），所以按日常流程走是拦得住的。
3. 真正想要服务端强制，唯一办法是加回 workflow；本仓库按用户要求不做。
4. 因此这里同时做了「软约束」：钩子被绕过时，站点自身仍会按
   日期戳判断当天是否已更新，避免一天内出现两次不同的数据快照。

用法
----
    python tools/daily_gate.py            # 只检查，打印当前是否允许发布
    python tools/daily_gate.py --stamp    # 检查并把今天写进状态戳
    python tools/daily_gate.py --force    # 忽略闸门强制写日期戳（应急）
    python tools/daily_gate.py --check-push   # 供 pre-push 钩子调用
"""
import datetime
import io
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
STATE = os.path.join(ROOT, "state", "last-publish.json")
LOG = os.path.join(ROOT, "state", "last-rejected.json")
STATE_REL = "state/last-publish.json"


def beijing_today(override=None):
    """北京时间今天。跨日任务里 UTC 的「今天」比北京晚 8 小时，容易错。"""
    if override:
        return override
    return (datetime.datetime.now(datetime.timezone.utc)
            + datetime.timedelta(hours=8)).date().isoformat()


def read_state():
    if not os.path.exists(STATE):
        return {}
    try:
        return json.load(io.open(STATE, encoding="utf-8"))
    except Exception:
        return {}


def write_state(payload):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    io.open(STATE, "w", encoding="utf-8").write(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def write_log(payload):
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    io.open(LOG, "w", encoding="utf-8").write(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def check(today=None, force=False):
    """返回 (allowed, reason, last_date)。"""
    today = today or beijing_today()
    last = (read_state().get("date") or "").strip()
    if force:
        return True, "force：已忽略每日闸门", last
    if not last:
        return True, "首次发布（尚无历史日期戳）", last
    if last == today:
        return False, "%s 已经发布过一次，今天不能再发" % today, last
    return True, "新的一天（上次发布 %s）" % last, last


def stamp(today=None, force=False, extra=None):
    """检查并写入日期戳。返回 (allowed, reason)。"""
    today = today or beijing_today()
    allowed, reason, last = check(today, force)
    if not allowed:
        write_log({"date": today, "last_publish": last,
                   "reason": reason, "at": datetime.datetime.now().isoformat()})
        return False, reason
    state = read_state()
    state["date"] = today
    state["updated_at"] = datetime.datetime.now().isoformat(timespec="seconds")
    if extra:
        state.update(extra)
    write_state(state)
    return True, reason


# ---------------------------------------------------------------- push 判定

def _git(*args):
    """跑一条 git 命令，返回 (returncode, stdout.strip())。"""
    try:
        p = subprocess.run(["git"] + list(args), cwd=ROOT, capture_output=True,
                           text=True, encoding="utf-8", errors="replace")
    except Exception:
        return 1, ""
    return p.returncode, (p.stdout or "").strip()


def stamp_at(rev):
    """读某个 git 对象（ref / sha）里 state/last-publish.json 的 date。"""
    if not rev:
        return ""
    rc, out = _git("show", "%s:%s" % (rev, STATE_REL))
    if rc != 0 or not out:
        return ""
    try:
        return (json.loads(out).get("date") or "").strip()
    except Exception:
        return ""


def check_push(today=None):
    """pre-push 用的判定：今天是否已经推送过。返回 (allowed, reason)。"""
    today = today or beijing_today()

    remote_ref = ""
    for ref in ("origin/main", "origin/master"):
        rc, _ = _git("rev-parse", "--verify", "-q", ref)
        if rc == 0:
            remote_ref = ref
            break
    remote = stamp_at(remote_ref) if remote_ref else ""

    head = stamp_at("HEAD")
    rc, _ = _git("rev-parse", "--verify", "-q", "HEAD~1")
    prev = stamp_at("HEAD~1") if rc == 0 else ""

    if remote and remote == today:
        return False, "远端 %s 已经发布过 %s 的数据" % (remote_ref, today)
    if head == today and prev == today:
        return False, "今天已经提交过一次发布（%s）" % today
    return True, "今天（%s）还没有发布过" % today


def main():
    args = set(sys.argv[1:])
    today = os.environ.get("TEST_TODAY") or None
    force = "--force" in args or os.environ.get("FORCE") == "1"

    if "--check-push" in args:
        allowed, reason = check_push(today)
        if allowed:
            print("每日闸门：%s" % reason)
            return 0
        print("")
        print("==========================================")
        print(" 今天的新闻已经发布过一次了")
        print(" %s" % reason)
        print(" 本仓库每天只允许推送一次新数据。")
        print(" 如需强制重发：git push --no-verify")
        print("==========================================")
        print("")
        return 1

    if "--stamp" in args:
        allowed, reason = stamp(today, force)
        print("allowed=%s" % ("true" if allowed else "false"))
        print("reason=%s" % reason)
        return 0 if allowed else 1

    allowed, reason, last = check(today, force)
    print("allowed=%s" % ("true" if allowed else "false"))
    print("today=%s" % (today or beijing_today()))
    print("last_publish=%s" % last)
    print("reason=%s" % reason)
    return 0 if allowed else 1


if __name__ == "__main__":
    raise SystemExit(main())
