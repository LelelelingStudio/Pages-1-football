#!/bin/sh
# ===========================================================
#  今日球报 - 首次配置（换机器 / 第一次 clone 后跑一次）
#
#  做的事：
#    1. 设置 core.hooksPath = .githooks
#       （让 Git 知道钩子目录在哪，「一天只推一次」的闸门才会生效）
#    2. 确认仓库地址指向正确的远端
#    3. 跑一次闸门自检
#
#  注意：core.hooksPath 是**本地**配置，不会随仓库同步。
#        每次换电脑、重新 clone，都要重新跑一次本脚本。
# ===========================================================
set -e
cd "$(dirname "$0")"

echo
echo "============================================"
echo " 今日球报 · 首次配置"
echo "============================================"
echo

echo "[1/4] 设置钩子目录 core.hooksPath = .githooks ..."
git config core.hooksPath .githooks
echo "      已设置。"

echo
echo "[2/4] 检查远端地址 ..."
REPO="https://github.com/LelelelingStudio/Pages-1-football.git"
CUR=$(git remote get-url origin 2>/dev/null || echo "")
if [ -z "$CUR" ]; then
  echo "      没有 origin，正在添加 ..."
  git remote add origin "$REPO"
else
  echo "      当前 origin = $CUR"
fi

echo
echo "[3/4] 获取远端最新内容 ..."
git fetch origin || echo "      (fetch 失败，可能是网络问题，不影响继续)"

echo
echo "[4/4] 闸门自检 ..."
echo "      正在检查「今天是否已经发布过」..."
python3 tools/daily_gate.py --check-push 2>/dev/null || python tools/daily_gate.py --check-push || true
echo

echo "============================================"
echo " 配置完成。"
echo
echo " 接下来："
echo "   - 用 GitHub Desktop 打开这个仓库，日常更新照旧"
echo "   - 每天只会被允许推送一次，第二次会被拦下（这是设计如此）"
echo "   - 真需要强制重发时：git push --no-verify"
echo "============================================"
echo
