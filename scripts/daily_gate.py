# -*- coding: utf-8 -*-
"""每日闸门：北京时间当天只允许发布一次。

这是「一天一次」的**唯一权威判定**，由 GitHub Actions 运行。
admin.html 里的当日预检只是友好提示，清缓存、换浏览器、直接调 API
都能绕过前端，但绕不过这里。

写入 $GITHUB_OUTPUT：
    allowed = true / false
    today   = YYYY-MM-DD（北京时间）
    reason  = 说明

被拒绝时把 data/news.json 回滚成当前已发布的 news.json，
避免「当天第二次上传」在第二天被误当成新数据发布。
"""
import datetime
import io
import json
import os
import shutil

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data", "news.json")
PUBLISHED = os.path.join(ROOT, "news.json")
STATE = os.path.join(ROOT, "state", "last-publish.json")
REJECT_LOG = os.path.join(ROOT, "state", "last-rejected.json")


def beijing_today(override=None):
    if override:
        return override
    return (datetime.datetime.now(datetime.timezone.utc)
            + datetime.timedelta(hours=8)).date().isoformat()


def emit(key, value):
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with io.open(path, "a", encoding="utf-8") as f:
            f.write("%s=%s\n" % (key, value))
    print("%s=%s" % (key, value))


def read_json(path):
    if not os.path.exists(path):
        return {}
    try:
        return json.load(io.open(path, encoding="utf-8"))
    except Exception:
        return {}


def main():
    force = os.environ.get("FORCE", "") == "1"
    today = beijing_today(os.environ.get("TEST_TODAY") or None)
    last = (read_json(STATE).get("date") or "").strip()
    allowed = force or (last != today)

    emit("today", today)
    emit("allowed", "true" if allowed else "false")

    if allowed:
        emit("reason", "force" if force else ("首次发布" if not last else "新的一天"))
        return 0

    # 拒绝：撤销本次上传，把待发布数据恢复为线上正在用的快照
    if os.path.exists(PUBLISHED):
        shutil.copyfile(PUBLISHED, DATA)
    io.open(REJECT_LOG, "w", encoding="utf-8").write(
        json.dumps({
            "date": today,
            "last_publish": last,
            "reason": "当日已发布过一次，本次上传已撤销",
            "rolled_back_to": "news.json",
        }, ensure_ascii=False, indent=2) + "\n")
    emit("reason", "当日重复上传，已回滚 data/news.json")
    print("::warning::%s 已经发布过一次，本次上传已撤销，站点内容未变" % today)
    return 0  # 不在这里失败：workflow 需要先 commit 回滚，再显式标红


if __name__ == "__main__":
    raise SystemExit(main())
