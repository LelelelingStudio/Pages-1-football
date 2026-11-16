# -*- coding: utf-8 -*-
"""每日一次发布闸门（客户端侧）。

背景
----
本仓库**不使用 GitHub Actions**（用户明确要求：免费额度撑不住，
Pages 的 source 设为分支而非 Actions）。因此「一天只能发布一次」没有
服务端强制力，只能靠本地 git 钩子实现。

核心设计：让**每一次提交都自动盖上「北京日期」戳**，而不是依赖某个
脚本记得去写。这样不管用 GitHub Desktop 点「Push origin」、命令行
`git push`、还是 IDE 里提交，戳都在，规则都成立。

判定依据（按优先级）
--------------------
1. **远端提交历史**（最强，换机器也有效）
   读 origin/main 最近若干次提交里的 state/last-publish.json 日期戳。
   只要远端已经有任何一次提交盖的是今天的戳 → 拒绝今天的再次推送。
   这是跨机器、跨工具都成立的判据：David 今天推过一次，
   你今天在自己机器上再推，远端历史里已经有今天的戳，直接拦下。
2. **本机推送记录**（.git/wb-publish-state.json）
   每次成功推送后由 post-push 钩子写入。用于远端历史还没同步到本地
   （刚 clone 完还没 fetch）的场景。

戳是怎么盖上的
--------------
`.githooks/pre-commit` 钩子在每次提交前调用本脚本的 `--stamp-commit`，
把今天的北京日期写进 state/last-publish.json 并 git add，
于是这个戳会随提交一起进入 git 历史 —— 谁推的、什么时候推的，
历史里都有据可查。

强制力说明（如实告知，不夸大）
------------------------------
1. 钩子是**本地**行为：换台电脑 clone、不装钩子、或用
   `git push --no-verify`，都能绕过。这是客户端闸门的固有上限。
2. GitHub Desktop **会执行 git 钩子**（官方文档明确支持，且失败时会
   阻止推送并给出绕过选项），所以按日常流程走是拦得住的。
3. 钩子要生效必须设置 `core.hooksPath = .githooks`。这是**本地配置**，
   不会随仓库同步，所以换机器 clone 后要跑一次 `首次配置.bat`
   （README 第一节有说明）。
4. 真正想要服务端强制，唯一办法是加回 workflow；本仓库按用户要求不做。

用法
----
    python tools/daily_gate.py                # 只检查，打印当前是否允许发布
    python tools/daily_gate.py --stamp        # 检查并把今天写进仓库状态戳
    python tools/daily_gate.py --force        # 忽略闸门强制写日期戳（应急）
    python tools/daily_gate.py --stamp-commit # 供 pre-commit 钩子调用（盖戳）
    python tools/daily_gate.py --check-push   # 供 pre-push 钩子调用
    python tools/daily_gate.py --mark-published # 供 post-push 钩子调用
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


# ---------------------------------------------------------------- 基础工具

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
    io.open(STATE, "w", encoding="utf-8", newline="\n").write(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def write_log(payload):
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    io.open(LOG, "w", encoding="utf-8", newline="\n").write(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def _git(*args):
    """跑一条 git 命令，返回 (returncode, stdout.strip())。"""
    try:
        p = subprocess.run(["git"] + list(args), cwd=ROOT, capture_output=True,
                           text=True, encoding="utf-8", errors="replace")
    except Exception:
        return 1, ""
    return p.returncode, (p.stdout or "").strip()


def git_dir():
    """仓库的 .git 目录（兼容 worktree：那里 .git 是文件）。"""
    rc, out = _git("rev-parse", "--absolute-git-dir")
    if rc == 0 and out:
        return out
    return os.path.join(ROOT, ".git")


# -------------------------------------------- 本机推送记录（.git 内，不入库）

def local_state_file():
    """本机推送记录放在 .git 目录里：不进版本库、不弄脏工作区。"""
    return os.path.join(git_dir(), "wb-publish-state.json")


def local_published_date():
    p = local_state_file()
    if not os.path.exists(p):
        return ""
    try:
        return (json.load(io.open(p, encoding="utf-8")).get("date") or "").strip()
    except Exception:
        return ""


def mark_published(today=None, extra=None):
    """记下「本机今天已推送」。由 post-push 钩子调用。"""
    today = today or beijing_today()
    payload = {
        "date": today,
        "updated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "note": "本机最后一次成功推送到 main 的北京日期（UTC+8）。"
                "由 .githooks/post-push 自动维护，不进版本库。",
    }
    if extra:
        payload.update(extra)
    p = local_state_file()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    io.open(p, "w", encoding="utf-8", newline="\n").write(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    return payload


# ---------------------------------------------------------------- 仓库内戳

def check(today=None, force=False):
    """返回 (allowed, reason, last_date)。只看仓库里的公开日期戳。"""
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


def stamp_commit(today=None):
    """给本次提交盖上今天的北京日期戳。

    由 .githooks/pre-commit 调用。盖完立刻 git add，
    于是这个戳随提交进入 git 历史 —— 远端能看到「这次发布是哪天的」。

    注意：同一天内的后续提交会**刷新**戳而不是跳过。
    因为「今天已发布」这个事实，是靠远端历史里出现今天的戳来表达的；
    如果第二个提交保留前一个的旧日期，远端就永远看不到今天的戳，
    跨机器的拦截会失效。所以每天都盖当天的日期。
    """
    today = today or beijing_today()
    state = read_state()
    state["date"] = today
    state["updated_at"] = datetime.datetime.now().isoformat(timespec="seconds")
    state["note"] = ("每次提交由 .githooks/pre-commit 自动盖上北京日期（UTC+8）。"
                     "pre-push 钩子据此判断当天是否已发布过。")
    write_state(state)
    rc, _ = _git("add", "--", STATE_REL)
    if rc != 0:
        return False, "git add 失败，戳没能进入提交"
    return True, "已盖戳：%s" % today


# ---------------------------------------------------------------- push 判定

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


def remote_head_sha(remote="origin"):
    """直接问远端 main 的当前 sha。

    为什么不用 origin/main 这个远程跟踪引用：
    - 刚 clone 完还没 fetch 时它可能不存在
    - 手工 `git remote add` 的仓库不会自动建 fetch 规则，也就没有这个引用
    - 上一次 push 失败后它可能还指向旧值
    `git ls-remote` 直接问服务器，是唯一可靠的真值来源。
    代价是要联网；拿不到就退回到本地引用（见 remote_stamp_dates）。
    """
    for ref in ("refs/heads/main", "refs/heads/master"):
        rc, out = _git("ls-remote", remote, ref)
        if rc == 0 and out:
            parts = out.split()
            if parts and parts[0] and set(parts[0]) != {"0"}:
                return parts[0]
    return ""


def _commit_stamps(sha_list, limit=30):
    """对给定的 sha 列表，抽出每个提交里的日期戳。"""
    result = []
    for sha in sha_list:
        if not sha:
            continue
        d = stamp_at(sha)
        if d:
            rc, subj = _git("log", "-1", "--format=%s", sha)
            result.append((d, sha[:7], (subj or "").strip()[:40]))
    return result


def remote_stamp_dates(limit=20):
    """列出远端 main 最近若干次提交里的日期戳。

    返回 [(日期戳, 提交短 sha, 提交说明)]，新到旧。

    优先用本地已有的远程跟踪引用（快，不联网）；
    本地没有这个引用时，改用 git ls-remote 拿远端真实 sha，
    再从本地对象库里找该提交（本地有对象就能读，没对象就跳过）。
    """
    # 快路径：本地有远程跟踪引用
    remote_ref = ""
    for ref in ("origin/main", "origin/master"):
        rc, _ = _git("rev-parse", "--verify", "-q", ref)
        if rc == 0:
            remote_ref = ref
            break

    if remote_ref:
        rc, out = _git("log", "-%d" % limit, "--format=%H", remote_ref)
        if rc == 0 and out:
            result = _commit_stamps(out.split()[:limit])
            if result:
                return result

    # 慢路径：直接问远端要 sha，再在本地对象库里找
    sha = remote_head_sha()
    if not sha:
        return []

    # 该提交在本地吗？在的话可以一路往上翻
    rc, _ = _git("cat-file", "-e", "%s^{commit}" % sha)
    if rc == 0:
        rc, out = _git("log", "-%d" % limit, "--format=%H", sha)
        if rc == 0 and out:
            return _commit_stamps(out.split()[:limit])

    # 本地没这个提交对象：只能读远端那一刻的戳。退而求其次，
    # 用 git show 试试（部分场景下 fetch --depth 过的仓库仍能读到）
    d = stamp_at(sha)
    if d:
        return [(d, sha[:7], "(远端最新提交)")]
    return []


def check_push(today=None, force=False):
    """pre-push 用的判定：今天是否已经推送过。返回 (allowed, reason)。"""
    today = today or beijing_today()

    if force:
        return True, "force：已忽略每日闸门"

    # 1) 远端提交历史里有没有今天的戳 —— 换机器、换工具都成立
    for d, sha, subject in remote_stamp_dates():
        if d == today:
            return False, ("远端 origin/main 已有一次 %s 的发布（提交 %s：%s）"
                           % (today, sha, subject))

    # 2) 本机推送记录 —— 兜底（远端历史还没同步到本地时）
    local = local_published_date()
    if local == today:
        return False, "本机今天（%s）已经成功推送过一次" % today

    return True, "今天（%s）还没有发布过" % today


def main():
    args = set(sys.argv[1:])
    today = os.environ.get("TEST_TODAY") or None
    force = "--force" in args or os.environ.get("FORCE") == "1"

    if "--check-push" in args:
        allowed, reason = check_push(today, force)
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

    if "--stamp-commit" in args:
        ok, reason = stamp_commit(today)
        print("每日闸门：%s" % reason)
        return 0

    if "--mark-published" in args:
        payload = mark_published(today)
        print("每日闸门：已记录本机发布日期 %s" % payload["date"])
        return 0

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
