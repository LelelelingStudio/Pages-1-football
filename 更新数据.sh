#!/bin/sh
# ===========================================================
#  今日球报 - 一键每日更新（macOS / Linux）
#  抓取最新足球资讯 -> 重建离线版 -> 检查发布闸门 -> 提交 -> 推送到 GitHub
#
#  规则：每天可推送任意次，没有次数限制。
#  如需恢复「一天一次」，把 tools/daily_gate.py 顶部 ENABLE_DAILY_LIMIT 改为 True。
# ===========================================================
set -e
cd "$(dirname "$0")"

echo ""
echo " [1/3] 查找 Python ..."
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
echo " [2/3] 检查钩子配置 ..."
# core.hooksPath 是本地配置，换机器后需要重设，这里自动补上
HOOKS=$(git config --get core.hooksPath 2>/dev/null || echo "")
if [ "$HOOKS" != ".githooks" ]; then
  echo "     未配置，正在设置 core.hooksPath = .githooks ..."
  git config core.hooksPath .githooks
  echo "     已设置。钩子已就位（当前每天可推送任意次）。"
else
  echo "     已配置 ✓"
fi

echo ""
echo " [3/3] 开始每日更新（抓取 - 构建 - 检查 - 提交 - 推送）..."
echo ""
if "$PY" tools/daily_update.py --push; then
  echo ""
  echo " [OK] 今日球报已更新并推送。等 1-3 分钟，GitHub Pages 会自动重建。"
else
  echo ""
  echo " [!] 没有推送成功。常见原因："
  echo "     1) 网络问题 —— 直接重新运行本脚本即可；"
  echo "     2) 首次推送需要登录授权 —— 请在弹出的浏览器里登录 GitHub 账号；"
  echo "     3) 若你恢复了「一天一次」限制且今天已推过，明天再跑即可。"
fi
echo ""
