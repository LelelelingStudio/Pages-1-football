# -*- coding: utf-8 -*-
"""统一路径解析：区分「站点根」与「脚本目录」。

这个仓库是 GitHub Pages 的**分支部署**仓库，仓库根目录就是网站根目录，
index.html / news.json / offline.html 都必须落在仓库根，Pages 才能直接发布。

抓取管线的脚本放在 tools/ 下（不干扰站点根的干净度），但它们的缓存文件
（migu_clips.json / euro_clips.json / upcoming.json / estimate_cache.json）
也留在 tools/ 里，不混进网站根。

所以约定：
    SITE_ROOT  = 仓库根（网站根，产物落这里）
    TOOLS_DIR  = tools/（脚本与缓存）
"""
import os

TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
SITE_ROOT = os.path.dirname(TOOLS_DIR)


def site(*parts):
    """仓库根下的路径（网站产物）。"""
    return os.path.join(SITE_ROOT, *parts)


def tool(*parts):
    """tools/ 下的路径（脚本与缓存）。"""
    return os.path.join(TOOLS_DIR, *parts)


# 站点产物
INDEX_HTML = site("index.html")
NEWS_JSON = site("news.json")
OFFLINE_HTML = site("offline.html")
APP_JS = site("app.js")

# 缓存与状态
MIGU_JSON = tool("migu_clips.json")
EURO_JSON = tool("euro_clips.json")
UPCOMING_JSON = tool("upcoming.json")
ESTIMATE_CACHE = tool("estimate_cache.json")
FRAGMENT_CLIPS = tool("fragment_clips.json")
ARCHIVE_CLIPS = tool("archive_clips.json")
BILI_SEED = tool("bili_seed.json")
