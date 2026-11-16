# 今日球报 · 五大联赛与欧冠

每日 50 条足球要闻 + 赛果集锦 + 正赛赛果 + 即将开赛胜率。
纯静态站点，**GitHub Pages 分支部署**，没有 workflow，不需要 token。

- 仓库：`https://github.com/LelelelingStudio/Pages-1-football`
- 线上地址：`https://football-pages.leleleling.site`
- 默认分支：`main`，站点入口 = 仓库根目录的 `index.html`

---

## 一、给 David 的操作指南（第一次配置）

### 1. 确认 GitHub 账号

| 项 | 值 |
| --- | --- |
| GitHub 账号 | **`LelelelingStudio`** |
| 账号显示名 | David Zhao |
| 账号类型 | 个人账号（非组织） |
| 主页 | https://leleleling.site |

> **三种账号情况，对应三条路：**
>
> **情况 A —— 你是 `LelelelingStudio` 本人**（仓库就建在这个账号下）：
> 直接用这个账号登录即可，推送、Pages 设置、自定义域名全都能做，无需任何人授权。
>
> **情况 B —— 你有 `LelelelingStudio` 的账号密码，但不是同一个人**：
> 让账号主人把仓库权限给你，或直接把账号密码给你代登录。
>
> **情况 C —— 你还没有 GitHub 账号**：
> 1. 到 https://github.com/signup 注册一个（需要邮箱验证）；
> 2. 让 `LelelelingStudio` 账号（仓库所有者）把你加为 collaborator：
>    仓库页面 → **Settings → Collaborators → Add people** → 填你的 GitHub 用户名，
>    角色选 **Write** 就够了（能推分支、能开 Pages 设置）；
> 3. 用新账号登录 GitHub Desktop 即可。
>
> 三种情况都不需要 Personal Access Token —— GitHub Desktop 和
> Git Credential Manager 都是浏览器授权登录。

### 2. 安装 GitHub Desktop

下载：https://desktop.github.com/

安装后用 `LelelelingStudio` 登录。**不需要 Personal Access Token**，
GitHub Desktop 自带登录态，第一次推送时会弹浏览器授权。

### 3. 克隆仓库

GitHub Desktop → **File → Clone repository** → 选 `LelelelingStudio / Pages-1-football`
→ Clone 到本地。

### 4. 装上「一天只推一次」的钩子（重要，只做一次）

在 **GitHub Desktop 的菜单 → Repository → Settings → Repository settings** 里没有这项，
用命令行做一次即可（Windows 上用 GitHub Desktop 自带的 Git Bash，
或任意装了 Git 的终端）：

```bash
cd <仓库本地目录>
git config core.hooksPath .githooks
```

这行命令的意思是：把仓库里的 `.githooks/` 目录设为 Git 钩子目录。
`pre-push` 钩子就会在每次推送前自动检查「今天是不是已经发过了」。

验证装好了：

```bash
python tools/daily_gate.py --check-push
```

### 5. 开启 GitHub Pages（仓库所有者 / 有 Write 权限的人做）

仓库页面 → **Settings → Pages**（左侧栏最下面）→ **Build and deployment**：

| 选项 | 选什么 |
| --- | --- |
| Source | **Deploy from a branch**（⚠️ 不要选 GitHub Actions） |
| Branch | **main** |
| Folder | **/ (root)** |

保存后等 1-3 分钟，站点会在 `https://lelelelingstudio.github.io/Pages-1-football/` 可访问。

### 6. 设置自定义域名

同一个 **Settings → Pages** 页面，往下找到 **Custom domain**，
填入：

```
football-pages.leleleling.site
```

保存。GitHub 会校验并自动配置证书，通常一两分钟生效。

**DNS 不需要动任何东西。** `*.leleleling.site` 的通配符解析早就指向
`lelelelingstudio.github.io` 了，任选多级子域名都能解析，这套规则已经覆盖
`football-pages.leleleling.site`。

> 顺手记一下，域名固定用 `【一堆字】-pages.leleleling.site` 这个格式，
> 中间不能带点。这样每个站点一条通配符就够了，永远不会和后端用的
> 其它子域名撞车。

---

## 二、每天怎么更新（日常操作）

### 方式 A：跑一键脚本（推荐）

Windows 双击仓库根目录的 **`更新数据.bat`**；
macOS / Linux 执行 `./更新数据.sh`。

脚本会依次完成：

```
抓取资讯/集锦/赛果/即将开赛
  → 重建自包含离线单文件 offline.html
  → 检查每日闸门（今天发过了就停下）
  → git add + commit
  → git push origin main
```

首次推送时 Git Credential Manager 会弹出浏览器，登录一次即可，
以后自动。

### 方式 B：GitHub Desktop 手动

1. 先跑抓取：`python tools/daily_update.py`（只构建提交，不推送）
2. 在 GitHub Desktop 里看到改动 → 左下角 **Commit to main** → 填个说明 → Commit
3. 点顶部工具条的 **Push origin**

两种方式效果一样，闸门都会拦。

### 每天一次的规则

**本仓库每天只允许推送一次新数据。** 这是用户明确要求的硬规则，
目的是让 Pages 的构建额度用得省一点（分支部署每小时 10 次构建的软限制）。

当天第二次推送会被 pre-push 钩子拦下，提示长这样：

```
==========================================
 今天的新闻已经发布过一次了
 远端 origin/main 已经发布过 2026-11-16 的数据
 本仓库每天只允许推送一次新数据。
 如需强制重发：git push --no-verify
==========================================
```

**确实是今天没发过、只是误判了**，可以应急绕过：

```bash
git push --no-verify
```

### 关于这个规则的强度（如实说明）

这是**客户端**闸门，不是服务端强制：

- 钩子装在那台推代码的电脑上。换个电脑 clone、不装钩子、或者加
  `--no-verify`，都能绕过去。
- 真想要服务端强制（谁都绕不过），唯一的办法是加回 GitHub Actions
  在 workflow 里做判断 —— 但那样会消耗免费额度，本项目按要求不这么做。
- 按正常流程走（同一台机器 + 装了钩子 + 不加 `--no-verify`），拦得住。

---

## 三、目录结构

```
football-daily-public/          ← 仓库根 = 网站根（Pages 直接发布这个目录）
├── index.html                  ← 站点入口，新闻数据内嵌在这里
├── news.json                   ← 同一份数据的独立文件（刷新按钮读它）
├── offline.html                ← 自包含离线单文件（app.js 已内联）
├── app.js  sw.js  manifest.webmanifest
├── icon.svg  icon.png  icon-192.png
├── CNAME                       ← 自定义域名声明：football-pages.leleleling.site
├── .nojekyll                   ← 让 Pages 不要走 Jekyll 处理
├── config.json                 ← 公开配置（owner/repo/域名），无密钥
├── state/
│   └── last-publish.json       ← 上次发布的北京日期戳，闸门靠它判断
├── .githooks/
│   └── pre-push                ← 每日一次的闸门
├── tools/                      ← 抓取与构建脚本（不入网站产物）
│   ├── paths.py                ← 路径分层：SITE_ROOT / TOOLS_DIR
│   ├── update_news.py          ← 主抓取管线
│   ├── migu_clips.py           ← 咪咕集锦
│   ├── euro_clips.py           ← 欧国联集锦
│   ├── upcoming.py             ← 即将开赛
│   ├── model_winrate.py        ← 胜率估算
│   ├── build_offline.py        ← 重建 offline.html
│   ├── daily_gate.py           ← 每日闸门（判定逻辑在这里）
│   └── daily_update.py         ← 一键流程
├── 更新数据.bat / 更新数据.sh   ← 一键更新入口
└── .github/                    ← 已删除（本项目不用 Actions）
```

### 站点产物的路径分层

`tools/paths.py` 统一定义两类路径，别写死：

| 常量 | 含义 |
| --- | --- |
| `paths.SITE_ROOT` | 仓库根 = 网站产物落点 |
| `paths.TOOLS_DIR` | `tools/` = 脚本与缓存落点 |
| `paths.site(...)` | 拼仓库根下的路径 |
| `paths.tool(...)` | 拼 tools/ 下的路径 |

缓存 JSON（`migu_clips.json`、`upcoming.json` 等）都放 `tools/`，
不会被 Pages 发布出去。

---

## 四、常见问题

**Q：改了代码，线上没变？**
A：Pages 构建需要 1-3 分钟。等一会儿，或到 Settings → Pages 看
「Deployments」有没有新记录。

**Q：推上去报 `Permission denied` / 403？**
A：多半是没被加 collaborator，或者 GitHub Desktop 没登录对账号。
仓库所有者 → Settings → Collaborators 把你加进去（Write 权限）。

**Q：推上去报 `Updates were rejected`？**
A：远端有你本地没有的提交。先在 GitHub Desktop 点 **Fetch origin**，
再 **History** 里右键那个新提交 → **Reset to this commit**，
或者直接命令行 `git pull --rebase origin main`。

**Q：站点打不开 / 证书报错？**
A：检查 Settings → Pages 的 Source 是不是选了 **Deploy from a branch**、
Branch 是 `main`、Folder 是 `/ (root)`。如果勾了 GitHub Actions，
在 Build and deployment 里切换成分支部署即可。

**Q：想改域名？**
A：改三处 —— `CNAME` 文件、`manifest.webmanifest` 里的 `id`、
`config.json` 里的 `customDomain`；然后在 Settings → Pages 的
Custom domain 里同步改一次。域名仍要符合 `xxx-pages.leleleling.site`，
且 `xxx` 里不能有点。

**Q：真的需要 token 吗？**
A：不需要。本机已经装好 Git Credential Manager（`credential.helper=manager`），
推送时走浏览器授权登录 GitHub 账号即可。GitHub Desktop 自带这套能力。
