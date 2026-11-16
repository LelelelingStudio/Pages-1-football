# -*- coding: utf-8 -*-
"""把 data/news.json 注入站点，生成部署产物 dist/，更新每日状态。

由 workflow 在每日闸门放行后调用：
    python scripts/build_site.py

产物：
    index.html        内嵌 JSON 换成新数据（同时提交回仓库）
    news.json         站点「刷新」按钮读取的最新快照
    offline.html      自包含离线单文件
    state/last-publish.json  写入北京日期，锁住当天
    dist/             仅含站点文件的 Pages 部署目录（.gitignore 忽略）
"""
import datetime
import io
import json
import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

DATA = os.path.join(ROOT, "data", "news.json")
INDEX = os.path.join(ROOT, "index.html")
NEWS = os.path.join(ROOT, "news.json")
STATE = os.path.join(ROOT, "state", "last-publish.json")
DIST = os.path.join(ROOT, "dist")

EMBED_RE = re.compile(
    r'(<script id="embedded-news" type="application/json">)(.*?)(</script>)',
    re.S)

SITE_FILES = [
    "index.html", "app.js", "news.json", "offline.html", "sw.js",
    "manifest.webmanifest", "icon.png", "icon-192.png", "icon.svg",
    "admin.html", "config.json", "CNAME",
]


def beijing_today():
    return (datetime.datetime.now(datetime.timezone.utc)
            + datetime.timedelta(hours=8)).date().isoformat()


def load_data():
    with io.open(DATA, encoding="utf-8") as f:
        d = json.load(f)
    if not isinstance(d, dict):
        raise SystemExit("数据必须是 JSON 对象")
    items = d.get("items")
    if not isinstance(items, list) or not items:
        raise SystemExit("数据校验失败：items 必须是非空数组")
    for key in ("highlights", "upcoming", "alt_highlights"):
        if key in d and not isinstance(d[key], list):
            raise SystemExit("数据校验失败：%s 必须是数组" % key)
    return d


def embed_payload(d):
    # </script> 会提前闭合脚本标签，JSON 里的 </ 必须转义
    return json.dumps(d, ensure_ascii=False).replace("</", "<\\/")


def inject(html, payload):
    m = EMBED_RE.search(html)
    if not m:
        raise SystemExit("index.html 里找不到 embedded-news 数据块")
    return html[:m.start(2)] + payload + html[m.end(2):]


def make_dist():
    if os.path.isdir(DIST):
        shutil.rmtree(DIST)
    os.makedirs(DIST)
    for name in SITE_FILES:
        src = os.path.join(ROOT, name)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(DIST, name))
    return len(os.listdir(DIST))


def main():
    d = load_data()
    payload = embed_payload(d)

    html = io.open(INDEX, encoding="utf-8").read()
    io.open(INDEX, "w", encoding="utf-8").write(inject(html, payload))
    io.open(NEWS, "w", encoding="utf-8").write(json.dumps(d, ensure_ascii=False))

    import build_offline
    build_offline.build()

    state = {
        "date": beijing_today(),
        "updated_at": d.get("updated_at", ""),
        "item_count": len(d["items"]),
        "highlight_count": len(d.get("highlights") or []),
        "upcoming_count": len(d.get("upcoming") or []),
        "source": "admin.html → GitHub Contents API → publish.yml",
        "note": "北京时间当天只允许发布一次；强制重发可在 Actions 里勾选 force",
    }
    io.open(STATE, "w", encoding="utf-8").write(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n")

    n = make_dist()
    print("已注入 %d 条资讯、%d 条集锦/赛果，dist/ 共 %d 个文件"
          % (state["item_count"], state["highlight_count"], n))
    print("每日闸门日期戳 =", state["date"])


if __name__ == "__main__":
    main()
