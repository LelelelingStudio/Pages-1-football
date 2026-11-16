#!/bin/sh
# ===========================================================
#  今日球报 - 一键每日更新（macOS / Linux）
#  抓取最新足球资讯 -> 重建离线版 -> 检查每日闸门 -> 提交 -> 推送到 GitHub
#
#  规则：本仓库每天只允许推送一次。第二次会被 pre-push 钩子拦下。
#  应急重发：加 --force，或直接 git push --no-verify
# ===========================================================
set -e
cd "$(dirname "$0")"

echo ""
echo " [1/2] 查找 Python ..."
PY=""
for c in python3 python; do
  if command -v "$c" >/dev/null 2>&1; then PY="$c"; break; fi
done
if [ -z "$PY" ]; then
  echo ""
  echo " [!] 没找到 Python。请先安装 Python 3.9+。"
  exit 1
fi
echo "     使用：$PY"

echo ""
echo " [2/2] 开始每日更新（抓取 - 构建 - 闸门 - 提交 - 推送）..."
echo ""
if "$PY" tools/daily_update.py --push; then
  echo ""
  echo " [OK] 今日球报已更新并推送。等 1-3 分钟，GitHub Pages 会自动重建。"
else
  echo ""
  echo " [!] 没有推送成功。常见原因："
  echo "     1) 今天已经推送过一次 —— 这是每天一次的规则，属正常；"
  echo "     2) 网络问题 —— 直接重新运行本脚本即可；"
  echo "     3) 首次推送需要登录授权 —— 请在弹出的浏览器里登录 GitHub 账号。"
fi
echo ""
