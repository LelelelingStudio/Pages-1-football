# -*- coding: utf-8 -*-
"""「即将开赛」数据模块。

两块内容，全部要求有真实出处：

1. 赛程：直播吧首页直播时间表（data-time / _league / _teams / 队徽），
   只收五大联赛 / 欧冠；国际比赛日窗口内额外收欧国联。开球时间过了的不收。
2. 专家分析：直播吧近两日真实的赛前报道（前瞻 / 首发预测 / 伤停 / 备战 / 交锋），
   按「两队名」匹配到具体比赛，标题、来源、时间与摘要原样取自来源页，站内展示。

胜率分两类，**字段与页面区块都严格分开，绝不混用**：

1. winrate（官方）：只有直播吧比赛页 / 虎扑 / 懂球帝明确公布本场
   「主胜 / 平 / 客胜」百分比时才原样收录并注明出处；查不到就留空，
   前端整块不显示，也不写「暂无胜率」之类的占位数字。
2. estimate（本站模型估算）：用直播吧比赛页官方「赛前数据」接口给出的
   两队近 6 场真实比分，按公开的泊松模型估算（见 model_winrate.py）。
   前端单独成块、明确标注「本站模型估算 · 非官方数据」、可由用户一键关闭，
   并把逐场比分与公式一并列出供核对。接口失败或样本不足时不输出任何数字。

两类都不引用赔率、竞猜或彩民支持率。
"""
import html as html_mod
import json
import os
import re
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

import paths

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPCOMING_JSON = paths.UPCOMING_JSON

SCHEDULE_URL = "https://www.zhibo8.com/"
MOBILE_SCHEDULE_URL = "https://m.zhibo8.com/"   # 移动首页：国际比赛日里仍排五大联赛未来赛程
NEWS_URL = "https://news.zhibo8.com/zuqiu/"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

MAX_FIXTURES = 24          # 最多展示多少场（非国际比赛日）
DAYS_AHEAD = 7             # 只看未来 7 天
MAX_ANALYSIS_PER_MATCH = 4 # 每场最多挂几条赛前报道

# 国际比赛日：桌面首页只有欧国联，联赛要另从移动首页补。
# 总量目标 24-28 场：欧国联之外的名额留给五大联赛，各联赛轮流取，避免被单一联赛占满。
INTL_MAX_FIXTURES = 28     # 国际比赛日的总量上限
INTL_LEAGUE_SLOTS = 10     # 最多补多少场联赛（约 18 场欧国联 + 10 = 28）
CLUB_LEAGUES = ("英超", "西甲", "意甲", "德甲", "法甲")

LEAGUE_RULES = (
    ("欧冠", ("欧冠", "欧洲冠军联赛")),
    ("英超", ("英超",)),
    ("西甲", ("西甲",)),
    ("意甲", ("意甲",)),
    ("德甲", ("德甲",)),
    ("法甲", ("法甲",)),
)
NATIONS_KEYS = ("欧国联", "欧洲国家联赛")

# 赛前分析类报道的判定词；只收有信息量的赛前内容，不收转会八卦 / 赛后评述
ANALYSIS_HINTS = (
    "前瞻", "预测", "首发", "分析", "看点", "情报", "伤停", "状态",
    "交锋", "近况", "备战", "大名单", "缺阵", "对阵", "客战", "主场",
    "客场", "出战", "停赛", "复出", "阵容", "关键战", "生死战", "德比",
)
ANALYSIS_BAD = ("集锦", "全场录像", "赛后", "转会", "身价", "续约", "球衣", "慈善")


def clean(s):
    s = re.sub(r"<[^>]+>", " ", s or "")
    s = html_mod.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def _get(url, timeout=25):
    import urllib.request
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Referer": "https://www.zhibo8.com/",
        "Accept-Language": "zh-CN,zh;q=0.9",
    })
    return urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", "ignore")


def _window_active():
    """窗口判定复用 migu_clips 的单点定义，避免两边规则漂移。"""
    try:
        import migu_clips
        return bool(migu_clips.is_international_window())
    except Exception:
        return False


def league_of(round_name, window=None):
    if window is None:
        window = _window_active()
    for lg, keys in LEAGUE_RULES:
        if any(k in round_name for k in keys):
            return lg
    if window and any(k in round_name for k in NATIONS_KEYS):
        return "欧国联"
    return ""


# ---------------------------------------------------------------- 赛程
LI_RE = re.compile(
    r'<li\s+label="([^"]*)"\s+id="saishi(\d+)"\s+data-time="([^"]+)"'
    r'[^>]*data-type="football"[^>]*>(.*?)</li>', re.S)


def parse_schedule(page, now=None):
    """把首页直播时间表解成结构化赛程；只保留未来的、在收录范围内的比赛。"""
    now = now or datetime.now()
    horizon = now + timedelta(days=DAYS_AHEAD)
    window = _window_active()
    out, seen = [], set()
    for label, pid, when, body in LI_RE.findall(page):
        try:
            kick = datetime.strptime(when.strip(), "%Y-%m-%d %H:%M")
        except ValueError:
            continue
        if kick < now or kick > horizon:
            continue
        lm = re.search(r'class="_league">(.*?)</span>', body, re.S)
        tm = re.search(r'class="_teams">(.*?)</span>\s*</b>', body, re.S)
        if not lm or not tm:
            continue
        round_name = clean(lm.group(1))
        league = league_of(round_name, window)
        if not league:
            continue
        seg = tm.group(1)
        imgs = re.findall(r'<img[^>]+src="([^"]+)"', seg)
        parts = re.split(r"<img[^>]*>", seg)
        home, away = clean(parts[0]), clean(parts[-1])
        if not home or not away or home == away or len(home) > 18 or len(away) > 18:
            continue
        fid = "fx_" + pid
        if fid in seen:
            continue
        seen.add(fid)
        href = re.search(r'href="(/zhibo/zuqiu/[^"]+\.htm)"', body)
        out.append({
            "id": fid,
            "league": league,
            "round": round_name,
            "home": home,
            "away": away,
            "logos": [u for u in imgs[:2] if u.startswith("http")],
            "kickoff": kick.strftime("%Y-%m-%d %H:%M"),
            "date": kick.strftime("%m-%d"),
            "time": kick.strftime("%H:%M"),
            "weekday": "一二三四五六日"[kick.weekday()],
            "source_url": ("https://www.zhibo8.com" + href.group(1)) if href else "",
            "analysis": [],
        })
    out.sort(key=lambda x: x["kickoff"])
    return out[:MAX_FIXTURES]


# ------------------------- 国际比赛日：移动首页补五大联赛赛程
# 桌面首页在国际比赛日窗口里只排国家队赛事（欧国联），五大联赛要 11/21 才恢复，
# 桌面直播表还没挂出来。移动首页 m.zhibo8.com 则已排出未来两周的俱乐部赛程，
# 条目结构：
#   <li type="football" label="英超,曼城,富勒姆,足球,英超第11轮"
#       href="/zhibo/zuqiu/2026/match2067735v.htm" id="saishi2067735" ...>
#     <div class="time">20:30</div>
#     <div class="team left-team">...<img data-original="//..." >
#       <div class="team-name">曼城</div></div>
#     <div class="item-center"><div class="s_name">英超第11轮</div></div>
#     <div class="team right-team">...富勒姆...</div>
#     <div class="remind"><a ... &time=2026-11-21 20:30&advance=5 ...>
#   </li>
# 开赛日期从 alarm 链接的 &time= 取（和 time 字段同一场，最可靠）。
MOBILE_LI_RE = re.compile(
    r'(<li[^>]*type="football"[^>]*?id="saishi(\d+)"[^>]*>)(.*?)</li>', re.S)


def parse_mobile_schedule(page, now=None, limit=INTL_LEAGUE_SLOTS):
    """从移动首页解析未来五大联赛赛程；各联赛轮流取，均衡且真实。"""
    now = now or datetime.now()
    horizon = now + timedelta(days=DAYS_AHEAD + 7)  # 国际比赛日往后多看一周（联赛 11/21 才恢复）
    picked, seen = [], set()
    for tag, pid, body in MOBILE_LI_RE.findall(page):
        sn = re.search(r'class="s_name">([^<]+)</div>', body)
        alarm = re.search(r'&time=(\d{4}-\d{2}-\d{2} \d{2}:\d{2})', body)
        if not sn or not alarm:
            continue
        round_name = clean(sn.group(1))
        # 联赛判定只认轮次文本（label 首词可能是「足球」或球队名，不可靠）
        league = league_of(round_name, window=True)
        if league not in CLUB_LEAGUES:
            continue
        try:
            kick = datetime.strptime(alarm.group(1), "%Y-%m-%d %H:%M")
        except ValueError:
            continue
        if kick < now or kick > horizon:
            continue
        tm = re.search(r'<div class="time">([^<]+)</div>', body)
        names = re.findall(r'class="team-name">([^<]+)</div>', body)
        if not tm or len(names) < 2:
            continue
        home, away = clean(names[0]), clean(names[1])
        if not home or not away or home == away or len(home) > 18 or len(away) > 18:
            continue
        fid = "fx_" + pid
        if fid in seen:
            continue
        seen.add(fid)
        imgs = re.findall(r'data-original="([^"]+)"', body)
        href = re.search(r'href="(/zhibo/zuqiu/[^"]+\.htm)"', tag)
        picked.append({
            "id": fid,
            "league": league,
            "round": round_name,
            "home": home,
            "away": away,
            "logos": [("https:" + u if u.startswith("//") else u) for u in imgs[:2]],
            "kickoff": kick.strftime("%Y-%m-%d %H:%M"),
            "date": kick.strftime("%m-%d"),
            "time": kick.strftime("%H:%M"),
            "weekday": "一二三四五六日"[kick.weekday()],
            "source_url": ("https://www.zhibo8.com" + href.group(1)) if href else "",
            "analysis": [],
        })

    # 按开赛时间排序后，各联赛轮流取一场，取满 limit 为止（避免全是某一联赛）
    picked.sort(key=lambda x: x["kickoff"])
    queues = {lg: [x for x in picked if x["league"] == lg] for lg in CLUB_LEAGUES}
    out, round_no = [], 0
    while len(out) < limit:
        added = False
        for lg in CLUB_LEAGUES:
            if len(out) >= limit:
                break
            if round_no < len(queues[lg]):
                out.append(queues[lg][round_no])
                added = True
        if not added:
            break
        round_no += 1
    out.sort(key=lambda x: x["kickoff"])
    return out[:limit]


# ---------------------------------------------------------------- 赛前分析
def _news_links(page, today=None):
    """近两日资讯链接，去重后按日期倒序。"""
    today = today or datetime.now()
    days = {(today - timedelta(days=i)).strftime("%Y-%m-%d") for i in (0, 1, 2)}
    rows = re.findall(
        r'href="(//news\.zhibo8\.com/zuqiu/(\d{4}-\d{2}-\d{2})/[^"]+\.htm)"[^>]*>(.*?)</a>',
        page, re.S)
    seen, out = set(), []
    for href, day, raw in rows:
        if day not in days or href in seen:
            continue
        title = clean(raw)
        if len(title) < 8 or any(b in title for b in ANALYSIS_BAD):
            continue
        if not any(k in title for k in ANALYSIS_HINTS):
            continue
        seen.add(href)
        out.append({"url": "https:" + href, "title": title, "date": day})
    return out


def _name_hit(title, name):
    """中文队名匹配要排除『西班牙人 / 意大利U21 / 德国队』这类误命中。"""
    if not name or name not in title:
        return False
    bad_suffix = ("人", "U", "女", "甲", "乙", "超", "杯", "联", "籍")
    for m in re.finditer(re.escape(name), title):
        tail = title[m.end():m.end() + 1]
        if tail in bad_suffix:
            return False
    return True


def _category(title):
    if any(k in title for k in ("首发", "阵容", "大名单")):
        return "首发 / 阵容"
    if any(k in title for k in ("伤停", "缺阵", "停赛", "复出", "出战")):
        return "伤停 / 人员"
    if any(k in title for k in ("前瞻", "预测", "分析", "看点", "交锋", "关键战")):
        return "赛前前瞻"
    return "赛前动态"


def fetch_article(it):
    """抓真实摘要 / 来源 / 时间；失败只留标题，不编内容。"""
    out = dict(it)
    out["desc"] = ""
    out["source"] = "直播吧"
    out["time"] = it["date"][5:]
    try:
        page = _get(it["url"], timeout=18)
        h1 = re.search(r"<h1[^>]*>(.*?)</h1>", page, re.S)
        if h1 and len(clean(h1.group(1))) > 8:
            out["title"] = clean(h1.group(1))
        body = re.search(r'<div[^>]*id="signals"[^>]*>(.*?)</div>', page, re.S)
        if body:
            paras = [clean(p) for p in re.findall(r"<p[^>]*>(.*?)</p>", body.group(1), re.S)]
            text = re.sub(r"\s+", " ", " ".join(p for p in paras if p)).strip()
            if len(text) > 220:
                cut = text[:220]
                stop = max(cut.rfind("。"), cut.rfind("！"), cut.rfind("？"))
                text = cut[:stop + 1] if stop > 100 else cut + "…"
            out["desc"] = text
        tm = re.search(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", page)
        if tm:
            out["time"] = tm.group(1)[5:16]
        author = re.search(r'class="author-name"[^>]*>([^<]+)<', page)
        if author:
            out["source"] = "直播吧 · " + clean(author.group(1))
    except Exception as exc:
        out["error"] = type(exc).__name__
    out["category"] = _category(out["title"])
    return out


def attach_analysis(fixtures, news_page=None):
    """把真实赛前报道按队名挂到对应比赛；只抓被选中的文章，控制请求数。"""
    try:
        page = news_page if news_page is not None else _get(NEWS_URL)
    except Exception as exc:
        print("  [警告] 赛前报道列表抓取失败：%s" % exc)
        return fixtures
    pool = _news_links(page)
    chosen, picked = {}, set()
    for fx in fixtures:
        scored = []
        for a in pool:
            n = int(_name_hit(a["title"], fx["home"])) + int(_name_hit(a["title"], fx["away"]))
            if n:
                scored.append((n, a))
        # 先按匹配两队数降序，再按日期新到旧
        scored = sorted(scored, key=lambda x: (-x[0], -int(x[1]["date"].replace("-", ""))))
        take = [a for _n, a in scored[:MAX_ANALYSIS_PER_MATCH]]
        for a in take:
            picked.add(a["url"])
        chosen[fx["id"]] = take
    articles = {}
    if picked:
        with ThreadPoolExecutor(max_workers=6) as ex:
            futs = {ex.submit(fetch_article, a): a["url"] for a in pool if a["url"] in picked}
            for f in as_completed(futs):
                articles[futs[f]] = f.result()
    for fx in fixtures:
        fx["analysis"] = [articles[a["url"]] for a in chosen.get(fx["id"], [])
                          if a["url"] in articles]
    print("  赛前分析：%d 条候选报道，%d 场比赛挂上真实赛前内容"
          % (len(pool), sum(1 for fx in fixtures if fx["analysis"])))
    return fixtures


# ------------------------------- 三家来源胜率（公布才收，绝不估算）
# 查直播吧比赛页、虎扑首页、懂球帝首页。只认页面明确写出的本场
# 「主胜 / 平 / 客胜」三项百分比（合计≈100）。本站不建模型、不拿历史战绩
# 反推、不引用赔率 / 竞猜 / 彩民支持率。查不到就留空，前端整块不渲染。
WINRATE_LABELS = ("胜平负", "支持率", "胜率", "主胜", "客胜")
BET_HINTS = ("彩民", "竞猜", "体彩", "赔率", "奖金", "盘口",
             "投注", "让球", "水位", "欧赔", "亚盘")
EXTRA_PAGES = (("虎扑", "https://www.hupu.com/"),
               ("懂球帝", "https://www.dongqiudi.com/"))
WINRATE_ITEM = re.compile(
    r"(主胜|主队胜|胜)\s*[:：]?\s*(\d{1,3}(?:\.\d+)?)\s*%"
    r"[\s|/、,，]{0,8}(平|平局|和局)\s*[:：]?\s*(\d{1,3}(?:\.\d+)?)\s*%"
    r"[\s|/、,，]{0,8}(客胜|客队胜|负)\s*[:：]?\s*(\d{1,3}(?:\.\d+)?)\s*%")


def _page_winrate(text):
    """三项齐全、合计≈100 才认；否则一律不收。"""
    m = WINRATE_ITEM.search(text)
    if not m:
        return None
    h, d, a = float(m.group(2)), float(m.group(4)), float(m.group(6))
    if not (0 < h <= 100 and 0 <= d <= 100 and 0 < a <= 100):
        return None
    if abs(h + d + a - 100) > 3:
        return None
    return {"home": h, "draw": d, "away": a, "quote": m.group(0)[:120]}


def _probe_zhibo(fx):
    """真实读一遍直播吧比赛页；只有明确公布三项胜平负百分比才返回。"""
    url = fx.get("source_url") or ""
    if not url.startswith("https://www.zhibo8.com/"):
        return None
    try:
        page = _get(url, timeout=12)
    except Exception:
        return None
    if not any(k in page for k in WINRATE_LABELS):
        return None
    w = _page_winrate(clean(page))
    if not w:
        return None
    w.update({"source": "直播吧比赛页公布", "source_url": url})
    return w


def _extra_segments():
    """虎扑 / 懂球帝首页各抓一次，只留非博彩的胜率相关文本片段。"""
    out = []
    for name, url in EXTRA_PAGES:
        try:
            page = _get(url, timeout=18)
        except Exception:
            continue
        for m in re.finditer("胜率|胜平负|支持率", page):
            seg = clean(page[max(0, m.start() - 260):m.start() + 260])
            if any(b in seg for b in BET_HINTS):
                continue
            out.append((name, url, seg))
    return out


def _probe_extra(fx, segments):
    """按两队名匹配虎扑 / 懂球帝公开报道里的本场胜率。"""
    for name, url, seg in segments:
        if fx["home"] not in seg or fx["away"] not in seg:
            continue
        w = _page_winrate(seg)
        if not w:
            continue
        w.update({"source": name + " 公布的赛前胜率",
                  "source_url": url, "quote": seg[:120]})
        return w
    return None


def attach_source_winrate(fixtures):
    """逐场查直播吧比赛页，再比对虎扑 / 懂球帝；查不到就留空，绝不填自算数字。"""
    if not fixtures:
        return fixtures
    segments = _extra_segments()
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = {ex.submit(_probe_zhibo, fx): fx for fx in fixtures}
        for f in as_completed(futs):
            fx = futs[f]
            try:
                w = f.result()
            except Exception:
                w = None
            fx["winrate"] = w or _probe_extra(fx, segments)
    found = sum(1 for fx in fixtures if fx.get("winrate"))
    print("  三家来源本场胜率：%d / %d 场有明确公布数据"
          "（直播吧比赛页 / 虎扑 / 懂球帝；其余不显示任何胜率数字）"
          % (found, len(fixtures)))
    return fixtures


# ---------------------------------------------------------------- 入口
def load_cached():
    try:
        with open(UPCOMING_JSON, encoding="utf-8") as f:
            return json.load(f).get("fixtures") or []
    except Exception:
        return []


def fetch_upcoming():
    """抓赛程 + 真实赛前分析 + 官方胜率 + 本站模型估算；失败沿用上次结果。"""
    window = _window_active()
    try:
        sched = _get(SCHEDULE_URL)
        fixtures = parse_schedule(sched)
        if not fixtures:
            raise RuntimeError("赛程表里没有未来 7 天内符合范围的比赛")
    except Exception as exc:
        print("  [警告] 未来赛程抓取失败：%s" % exc)
        fixtures = [x for x in load_cached()
                    if x.get("kickoff", "") >= datetime.now().strftime("%Y-%m-%d %H:%M")]
        if not fixtures:
            return []

    # 国际比赛日窗口内，桌面首页只有欧国联；再从移动首页补五大联赛，
    # 追加在国家队赛事后面（页面按 kickoff 排序，联赛 11/21 起自然排最后）。
    if window:
        try:
            msched = _get(MOBILE_SCHEDULE_URL)
            club = parse_mobile_schedule(msched)
            have = {x["id"] for x in fixtures}
            club = [x for x in club if x["id"] not in have]
            before = len(fixtures)
            fixtures.extend(club)
            fixtures.sort(key=lambda x: x["kickoff"])
            fixtures = fixtures[:INTL_MAX_FIXTURES]
            print("  国际比赛日：桌面 %d 场国家队 + 移动补 %d 场联赛 = %d 场"
                  % (before, len(club), len(fixtures)))
        except Exception as exc:
            print("  [警告] 移动首页联赛赛程抓取失败，仅保留国家队赛事：%s" % exc)
    else:
        fixtures = fixtures[:MAX_FIXTURES]

    fixtures = attach_analysis(fixtures)
    fixtures = attach_source_winrate(fixtures)
    # 模型估算单独一层：只写 estimate，绝不碰 winrate（来源站公布的官方数据）
    import model_winrate
    fixtures = model_winrate.attach_estimates(fixtures)
    model_winrate.save_cache(fixtures)
    found = sum(1 for fx in fixtures if fx.get("winrate"))
    estimated = sum(1 for fx in fixtures if fx.get("estimate"))
    with open(UPCOMING_JSON, "w", encoding="utf-8") as f:
        json.dump({"updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                   "winrate_found": found, "estimate_found": estimated,
                   "estimate_method": model_winrate.METHOD,
                   "fixtures": fixtures},
                  f, ensure_ascii=False, indent=1)
    print("  即将开赛：%d 场 · %d 场有真实赛前分析 · %d 场有来源站公布胜率 · %d 场有本站模型估算"
          % (len(fixtures), sum(1 for fx in fixtures if fx.get("analysis")),
             found, estimated))
    return fixtures


if __name__ == "__main__":
    rows = fetch_upcoming()
    for r in rows:
        e = r.get("estimate")
        print(r["kickoff"], r["league"].ljust(4), r["home"], "vs", r["away"],
              "| 分析", len(r.get("analysis") or []),
              "| 官方胜率", "有" if r.get("winrate") else "无",
              "| 本站估算", ("%.1f/%.1f/%.1f" % (e["home"], e["draw"], e["away"]))
              if e else "不输出")
