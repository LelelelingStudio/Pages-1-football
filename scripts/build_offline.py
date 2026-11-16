# -*- coding: utf-8 -*-
"""把仓库根的 index.html 打包成自包含、可双击打开的 offline.html。

保留 <style> 与内嵌 JSON，把 app.js 内联，剥离 manifest / SW 注册 /
进站安装弹窗。新闻配图仍是源站外链，离线时图片不显示但正文完整可读。

由 build_site.py 在 workflow 内调用，也可单独运行：
    python scripts/build_offline.py
"""
import io
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(ROOT, "index.html")
JS = os.path.join(ROOT, "app.js")
DST = os.path.join(ROOT, "offline.html")


def build():
    html = io.open(SRC, encoding="utf-8").read()
    js = io.open(JS, encoding="utf-8").read()

    if "</script" in js.lower():
        raise SystemExit("app.js 含 </script，内联会截断，请先转义")

    html, n = re.subn(
        r'<script src="app\.js[^"]*"></script>',
        lambda m: "<script>\n" + js + "\n</script>",
        html, count=1)
    if n != 1:
        raise SystemExit("没找到 app.js 外链，index.html 结构变了")

    html = re.sub(
        r"<script>\s*/\* 桌面版：注册 Service Worker.*?</script>",
        "", html, count=1, flags=re.S)
    html = re.sub(r'<link rel="apple-touch-icon"[^>]*>\s*', "", html)
    html = re.sub(r'<link rel="manifest"[^>]*>\s*', "", html)
    html = re.sub(r"<!--INSTALL_POPUP_START-->.*?<!--INSTALL_POPUP_END-->",
                  "", html, count=1, flags=re.S)
    html = re.sub(r"/\*INSTALL_POPUP_CSS_START\*/.*?/\*INSTALL_POPUP_CSS_END\*/",
                  "", html, count=1, flags=re.S)

    html = html.replace('<html lang="zh-CN"', '<html lang="zh-CN" data-offline="1"', 1)
    html = html.replace("<title>今日球报", "<title>今日球报 · 离线版", 1)

    io.open(DST, "w", encoding="utf-8").write(html)
    print("已生成 offline.html (%d 字节)" % len(html.encode("utf-8")))


if __name__ == "__main__":
    build()
