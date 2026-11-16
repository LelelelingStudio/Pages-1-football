@echo off
rem ===========================================================
rem  今日球报 - 首次配置（换机器 / 第一次 clone 后跑一次）
rem
rem  做的事：
rem    1. 设置 core.hooksPath = .githooks
rem       （让 Git 知道钩子目录在哪；当前每天可推任意次，钩子只负责盖日期戳）
rem    2. 确认仓库地址指向正确的远端
rem    3. 跑一次闸门自检
rem
rem  注意：core.hooksPath 是**本地**配置，不会随仓库同步。
rem        每次换电脑、重新 clone，都要重新跑一次本脚本。
rem ===========================================================
setlocal
cd /d "%~dp0"

echo.
echo ============================================
echo  今日球报 · 首次配置
echo ============================================
echo.

rem --- 1. 钩子目录 ---
echo [1/4] 设置钩子目录 core.hooksPath = .githooks ...
git config core.hooksPath .githooks
if errorlevel 1 (
  echo  [!] 设置失败。请确认这个目录是一个 git 仓库。
  pause
  exit /b 1
)
echo      已设置。

rem --- 2. 远端地址 ---
echo.
echo [2/4] 检查远端地址 ...
set "REPO=https://github.com/LelelelingStudio/Pages-1-football.git"
for /f "tokens=*" %%u in ('git remote get-url origin 2^>nul') do set "CUR=%%u"
if not defined CUR (
  echo      没有 origin，正在添加 ...
  git remote add origin %REPO%
) else (
  echo      当前 origin = %CUR%
)

rem --- 3. 拉取远端 ---
echo.
echo [3/4] 获取远端最新内容 ...
git fetch origin 2>&1 | findstr /v "^$"
echo      完成。

rem --- 4. 自检 ---
echo.
echo [4/4] 发布闸门自检 ...
python tools\daily_gate.py --check-push 2>&1 | findstr /v "^$"
echo.

echo ============================================
echo  配置完成。
echo.
echo  接下来：
echo    - 用 GitHub Desktop 打开这个仓库，日常更新照旧
echo    - 每天可推送任意次，没有次数限制
echo    - 想恢复「一天一次」：把 tools/daily_gate.py 顶部
echo      ENABLE_DAILY_LIMIT 改成 True 即可
echo ============================================
echo.
pause
endlocal
