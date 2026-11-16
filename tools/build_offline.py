# -*- coding: utf-8 -*-
"""把线上 index.html 打包成一个自包含、可双击打开的离线单文件。

做法：保留 <style> 与内嵌 JSON 数据，把 app.js 内联进页面，剥离所有
外链（icon.png / manifest / Service Worker 注册），并把 favicon 换成
内嵌 data URI。新闻配图仍是源站外链，离线时图片不显示但正文完整可读。

每次 update_news.py 更新数据后重跑本脚本即可让离线版同步最新快照：
    python build_offline.py
"""
import os
import re
import io

import paths

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = paths.INDEX_HTML
JS = paths.APP_JS
DST = paths.OFFLINE_HTML


def build():
    html = io.open(SRC, encoding='utf-8').read()
    js = io.open(JS, encoding='utf-8').read()

    if '</script' in js.lower():
        raise SystemExit('app.js 含 </script，内联会截断，请先转义')

    # 1) 把 app.js 外链替换成内联脚本
    html, n = re.subn(
        r'<script src="app\.js[^"]*"></script>',
        lambda m: '<script>\n' + js + '\n</script>',
        html, count=1)
    if n != 1:
        raise SystemExit('没找到 app.js 外链，index.html 结构变了')

    # 2) 删掉 Service Worker 注册（离线文件用 file:// 打开，不需要也注册不了）
    html = re.sub(
        r'<script>\s*/\* 桌面版：注册 Service Worker.*?</script>',
        '', html, count=1, flags=re.S)

    # 3) 删掉 manifest / apple-touch-icon 外链，favicon 保持 data URI 不动
    html = re.sub(r'<link rel="apple-touch-icon"[^>]*>\s*', '', html)
    html = re.sub(r'<link rel="manifest"[^>]*>\s*', '', html)

    # 4) 离线版不该再提示「装到桌面」，按注释标记整段剥离弹窗、脚本与样式
    html = re.sub(r'<!--INSTALL_POPUP_START-->.*?<!--INSTALL_POPUP_END-->', '',
                  html, count=1, flags=re.S)
    html = re.sub(r'/\*INSTALL_POPUP_CSS_START\*/.*?/\*INSTALL_POPUP_CSS_END\*/', '',
                  html, count=1, flags=re.S)

    # 5) 标注这是离线快照，避免用户误以为会自动更新
    html = html.replace('<html lang="zh-CN"', '<html lang="zh-CN" data-offline="1"', 1)
    html = html.replace('<title>今日球报', '<title>今日球报 · 离线版', 1)

    io.open(DST, 'w', encoding='utf-8').write(html)
    print('已生成 %s (%d 字节)' % (DST, len(html.encode('utf-8'))))


if __name__ == '__main__':
    build()
