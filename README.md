# 今日球报 · 五大联赛与欧冠

每日 50 条足球要闻 + 赛果集锦 + 正赛赛果 + 即将开赛胜率。
纯静态站点，**GitHub Pages 分支部署**，没有 workflow，不需要 token。

- 仓库：`https://github.com/LelelelingStudio/Pages-1-football`
- **线上地址：`https://football-pages.leleleling.site`（已上线，可直接访问）**
- 默认分支：`main`，站点入口 = 仓库根目录的 `index.html`
- GitHub Pages：source = **Deploy from a branch** / `main` / **/ (root)**；
  自定义域名 = `football-pages.leleleling.site`（都已配置好，状态 built）

---

## ⚡ 最快上手：怎么更新到这个网址

网站已经在 `https://football-pages.leleleling.site` 上线了。
**更新 = 把新数据 push 到 `main`，Pages 会自动重建，1-3 分钟后线上就是新内容。**
不用手动上传、不用进 Pages 后台、不用碰 DNS。

日常只有两步：

1. **抓取并生成新数据**：双击仓库根目录的 `更新数据.bat`（macOS/Linux 跑 `./更新数据.sh`）
2. **等 1-3 分钟**，刷新 `https://football-pages.leleleling.site` 即可

脚本会自动完成：抓取 → 重建离线版 → 检查闸门 → commit → push。
如果今天已经推过一次，闸门会拦下，属正常（一天一次规则，见下文）。
详细步骤与 GitHub Desktop 手动方式见 [第二节](#二每天怎么更新日常操作)。

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

**换机器、重新 clone 之后，都要重新跑这一步。**

Windows 双击仓库根目录的 **`首次配置.bat`**；
macOS / Linux 执行 `./首次配置.sh`。

它做了三件事：

1. 设置 `core.hooksPath = .githooks` —— 让 Git 知道钩子目录在哪
2. 检查远端地址并 `fetch` 一次
3. 跑一次闸门自检

> `core.hooksPath` 是**本地配置**，不会随仓库同步到别的电脑。
> 这就是为什么每个新环境都要跑一次。

手动做也行（Windows 上用 GitHub Desktop 自带的 Git Bash）：

```bash
cd <仓库本地目录>
git config core.hooksPath .githooks
git fetch origin
```

验证装好了：

```bash
python tools/daily_gate.py --check-push
```

输出「今天还没有发布过」就说明闸门在正常工作。

### 5. 开启 GitHub Pages（仓库所有者 / 有 Write 权限的人做）

仓库页面 → **Settings → Pages**（左侧栏最下面）→ **Build and deployment**：

| 选项 | 选什么 |
| --- | --- |
| Source | **Deploy from a branch**（⚠️ 不要选 GitHub Actions） |
| Branch | **main** |
| Folder | **/ (root)** |

保存后等 1-3 分钟，站点会在 `https://lelelelingstudio.github.io/Pages-1-football/` 可访问。

> **为什么不用 Actions？** 免费额度有限，而且 Actions 部署会消耗运行分钟数。
> 分支部署每次推送触发一次构建，官方软限制是每小时 10 次 ——
> 本项目每天只推一次，完全够用。

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

#### 闸门是怎么工作的

三个钩子配合，**不依赖任何特定脚本，也不依赖特定推送工具**：

| 钩子 | 时机 | 做什么 |
| --- | --- | --- |
| `pre-commit` | 每次提交前 | 自动给 `state/last-publish.json` 盖上**今天（北京）的日期戳**，并 `git add`，让戳随提交进入 git 历史 |
| `pre-push` | 每次推送前 | 查远端 `origin/main` 的提交历史，只要里面有今天的戳 → 拒绝这次推送 |
| `post-push` | 推送成功后 | 在 `.git/` 里记一笔「本机今天推过」，用于远端历史还没同步到本地时的兜底 |

关键点是：**戳是提交时自动盖的**。所以不管用 GitHub Desktop 点「Commit」、
命令行 `git commit`、还是 IDE 里提交，戳都会在。
判定读的是**远端提交历史**，所以跨机器、跨工具都成立 ——
David 今天推过了，你今天在自己电脑上再推，会被拦下。

当天第二次推送会被拦下，提示长这样：

```
==========================================
 今天的新闻已经发布过一次了
 远端 origin/main 已有一次 2026-11-16 的发布（提交 5ba2231：D 首次发布）
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
- 即使钩子被绕过，**远端提交历史里仍然会留下当天的日期戳**，
  下次正常推送时会被拦下 —— 所以绕过只对当次有效，不是彻底失效。

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
│   └── last-publish.json       ← 发布日期戳（每次提交由 pre-commit 自动盖）
├── .githooks/
│   ├── pre-commit              ← 提交前自动盖上今天的北京日期戳
│   ├── pre-push                ← 推送前检查：远端历史里有没有今天的戳
│   └── post-push               ← 推送成功后记录本机发布日期
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
├── 首次配置.bat / 首次配置.sh   ← 换机器后跑一次（装钩子）
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
