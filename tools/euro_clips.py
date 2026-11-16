# -*- coding: utf-8 -*-
"""国际比赛日：欧洲国家队比赛的「官方全场集锦」登记。

用户要求国际比赛日窗口内，「赛果集锦」「正赛赛果」两个区域里的俱乐部比赛
全部撤下，换成欧洲国家队比赛。咪咕体育首页在窗口内没有欧国联集锦，但直播吧
官方「比赛集锦页」逐场列出了该场的完整集锦（爱奇艺体育版权源）、官方封面、
发布时间与轮次，因此这里逐场登记**本场**全场集锦，而不是零散进球片段。

实测结论（2026-11-13，真实 Chrome + 官方页面）：
  1. 直播吧 PC 集锦页只有官方外链，没有可站内播放的 mp4 / m3u8；
  2. 爱奇艺体育播放页同样不允许第三方网页嵌入，硬塞 iframe 就是黑屏。
所以本模块只产出「官方集锦登记 + 原站观看入口」，不伪造直链、不生成播放器，
与咪咕卡片走同一套前端渲染（videoBox 的官方站点白名单）。

判定「欧洲国家队比赛」用页面 <meta name="keywords"> 里的官方轮次
（如「欧国联A3组第5轮」），真源是 migu_clips.is_euro_nations()。
"""
import html
import json
import os
import re
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import migu_clips
import paths

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
EURO_JSON = paths.EURO_JSON
MOBILE_HOST = "https://m.zhibo8.cc"
UA_PC = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
         "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
UA_MOBILE = ("Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
             "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 "
             "Mobile/15E148 Safari/604.1")
# 只认官方全场集锦 / 全场录像，进球视频、扑救、现场镜头等零散片段一律不收
IQ_LINK = re.compile(
    r'href="(https://sports\.iqiyi\.com/resource/pcw/play/[A-Za-z0-9]+)"')
FULL_MARK = re.compile(r'\[(?:爱奇艺)?(?:全场集锦|比赛集锦|全场录像)\]\s*([^<]{4,200})')
COVER_RE = re.compile(r'(?:v-img460|v-limg)"\s+src="([^"]+)"')
MAX_CANDIDATES = 90       # 滚动窗口内的集锦页候选上限，避免无意义的历史抓取
MAX_CLIPS = 40            # 国际比赛日窗口内最多登记的场次


def _get(url, mobile=False, timeout=20):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA_MOBILE if mobile else UA_PC,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Referer": "https://www.zhibo8.com/",
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "replace")


def clean(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", s or ""))).strip()


def abs_url(u):
    u = (u or "").strip()
    if u.startswith("//"):
        return "https:" + u
    if u.startswith("http://"):
        return "https://" + u[7:]
    return u


def url_day(url):
    m = re.search(r"/(20\d{2})/(\d{2})(\d{2})-", url or "")
    return "%s-%s-%s" % (m.group(1), m.group(2), m.group(3)) if m else ""


def match_id(url):
    m = re.search(r"match(\d+)v", url or "")
    return m.group(1) if m else ""


def mobile_url(u):
    return re.sub(r"^https?://www\.zhibo8\.com", MOBILE_HOST, u or "")


def candidates(raw, min_date):
    """按 URL 上的官方日期筛出滚动窗口内的比赛集锦页，近的优先。"""
    today = datetime.now().date()
    ceiling = (today + timedelta(days=1)).isoformat()
    rows = []
    seen = set()
    for e in raw or []:
        u = e.get("url") or ""
        if "-jijin.htm" not in u or match_id(u) in seen:
            continue
        k = url_day(u)
        if not k or k < min_date or k > ceiling:
            continue
        seen.add(match_id(u))
        rows.append({"url": u, "title": e.get("title") or "", "day": k})
    rows.sort(key=lambda x: x["day"], reverse=True)
    return rows[:MAX_CANDIDATES]


def parse_pc(page):
    """PC 集锦页：官方轮次 / 全场集锦链接 / 封面 / 发布时间。"""
    kw = re.search(r'<meta name="keywords" content="([^"]*)"', page)
    keywords = clean(kw.group(1)) if kw else ""
    if not migu_clips.is_euro_nations(keywords):
        return None
    head = re.search(r'<h1[^>]*>(.*?)</h1>', page, re.S)
    title = clean(head.group(1)) if head else ""
    pub = re.search(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})', page)
    published = pub.group(1) if pub else ""
    # 逐块找「全场集锦」：单集锦页是 v-thumb + pcenter，多视频页是 li 列表。
    # 按块切可以让 [进球视频] 块因为没有全场集锦标题而被自然排除。
    blocks = re.split(r'<li>\s*<div class="v-img">|<div class="v-thumb">', page)
    picks = []
    for b in blocks[1:]:
        link = IQ_LINK.search(b)
        mark = FULL_MARK.search(b)
        if not link or not mark:
            continue
        cov = COVER_RE.search(b)
        picks.append({
            "official_url": link.group(1),
            "official_title": clean(mark.group(0)).lstrip("[").strip(),
            "img": abs_url(cov.group(1)) if cov else "",
        })
    if not picks:
        # 兜底：整页只有一个官方链接且写了全场集锦时，按单集锦页收
        links = list(dict.fromkeys(IQ_LINK.findall(page)))
        mark = FULL_MARK.search(page)
        cov = COVER_RE.search(page)
        if len(links) == 1 and mark:
            picks.append({"official_url": links[0],
                          "official_title": clean(mark.group(0)).lstrip("[").strip(),
                          "img": abs_url(cov.group(1)) if cov else ""})
    if not picks:
        return None
    return {"keywords": keywords, "title": title, "published": published,
            "picks": picks}


def parse_mobile(page):
    """移动赛果页：官方轮次 / 主客队 / 比分 / 开球时间。"""
    def one(pat):
        m = re.search(pat, page, re.S)
        return clean(m.group(1)) if m else ""
    rnd = one(r'<h2 class="title[^"]*">([^<]+)</h2>')
    h1 = one(r'<h1 class="t-tlt">([^<]+)</h1>')
    names = [clean(x) for x in re.findall(
        r'<div class="team-name">([^<]+)</div>', page)]
    sm = re.search(r"(\d{1,2})\s*[-:：]\s*(\d{1,2})", h1)
    kickoff = one(r'id="period_cn">([^<]+)<')
    pub = one(r'class="t-time">([^<]+)<')
    if not migu_clips.is_euro_nations(rnd + " " + h1, names[:2]):
        return None
    if not sm or len(names) < 2:
        return None
    # 注意：h1 是新闻叙述顺序（常把赢球方写在前面），移动页 team-name 是主客顺序。
    # 两者不经过 align_score 校验就会错配，所以这里**不产出比分 / 队名**，
    # 卡片统一改用 fetch_league_matches() 已经校验过的正赛赛果字段。
    return {"round": rnd or "欧洲国家队比赛", "headline": h1,
            "kickoff": kickoff, "mobile_pub": pub}


def _fetch_pair(e):
    try:
        pc = _get(e["url"])
    except Exception:
        return None
    info = parse_pc(pc)
    if not info:
        return None
    try:
        mob = _get(mobile_url(e["url"]), mobile=True)
        detail = parse_mobile(mob)
    except Exception:
        detail = None
    return e, info, detail


def as_card(e, info, pick, detail, result=None):
    """转成赛果集锦卡片；字段与咪咕卡片对齐，只是官方站点换成爱奇艺体育。

    比分 / 主客队一律取 update_news.fetch_league_matches() 里经 align_score
    校验过的同一场赛果；对不上就留空显示官方标题，绝不按新闻标题顺序猜比分。
    """
    d = detail or {}
    r = result or {}
    pub = info.get("published") or d.get("mobile_pub") or ""
    day = (r.get("kickoff") or pub or e["day"])[:10]
    home, away = r.get("home") or "", r.get("away") or ""
    teams = r.get("teams") or (("%s vs %s" % (home, away)) if home and away
                               else (e.get("title") or ""))
    rnd = r.get("round") or d.get("round") or info.get("keywords") or "欧洲国家队比赛"
    league = r.get("league") or migu_clips.euro_league_of(
        rnd + " " + info.get("keywords", ""))
    return {
        "id": "euro_" + (match_id(e["url"]) or re.sub(r"\D", "", e["url"])[-9:]),
        "section": "clip",
        "content_mode": "international",
        "provider": "iqiyi",
        "official_site": "爱奇艺体育",
        "official_url": pick["official_url"],
        "official_title": pick["official_title"],
        "title": r.get("headline") or d.get("headline") or info.get("title")
                 or e.get("title") or "",
        "headline": r.get("headline") or d.get("headline") or e.get("title") or "",
        "comp": rnd, "round": rnd, "league": league,
        "teams": teams, "team_list": [x for x in (home, away) if x],
        "home": home, "away": away, "score": r.get("score") or "",
        "img": pick["img"] or r.get("img") or "",
        "published": pub, "kickoff": r.get("kickoff") or d.get("kickoff") or "",
        "date": r.get("date") or (day[5:] if len(day) >= 10 else day),
        "duration": "",
        "url": e["url"],
        "source": "直播吧官方比赛集锦页 · 爱奇艺体育全场集锦",
        "video_status": "official",
        "play": "", "embed": "",
    }


def load_euro_clips(min_date):
    try:
        with open(EURO_JSON, "r", encoding="utf-8") as f:
            rows = json.load(f).get("clips") or []
        return [x for x in rows
                if str(x.get("official_url") or "").startswith(
                    "https://sports.iqiyi.com/resource/pcw/play/")
                and url_day(x.get("url") or "") >= min_date]
    except Exception:
        return []


def fetch_euro_clips(raw, min_date=None, results=None):
    """抓窗口内欧洲国家队比赛的官方全场集锦；失败则沿用上次登记。

    results 是同一批正赛赛果（主客队与比分已经过 align_score 校验），
    按官方比赛 ID 对齐，保证集锦卡与赛果卡指向同一场、比分顺序一致。
    """
    min_date = min_date or migu_clips.rolling_min_date()
    by_mid = {}
    for r in results or []:
        mid = match_id(r.get("url") or "")
        if mid:
            by_mid[mid] = r
    cand = candidates(raw, min_date)
    if not cand:
        print("  欧洲国家队集锦：滚动窗口内没有比赛集锦页候选")
        return load_euro_clips(min_date)
    with ThreadPoolExecutor(max_workers=10) as pool:
        pairs = [x for x in pool.map(_fetch_pair, cand) if x]
    rows, seen = [], set()
    for e, info, detail in pairs:
        result = by_mid.get(match_id(e["url"]))
        for pick in info["picks"]:
            if pick["official_url"] in seen:
                continue
            seen.add(pick["official_url"])
            rows.append(as_card(e, info, pick, detail, result))
    rows.sort(key=lambda x: (x.get("published") or "", x.get("kickoff") or ""),
              reverse=True)
    rows = rows[:MAX_CLIPS]
    if not rows:
        print("  欧洲国家队集锦：本次没有抓到官方全场集锦，沿用上次登记")
        return load_euro_clips(min_date)
    with open(EURO_JSON, "w", encoding="utf-8") as f:
        json.dump({"updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                   "clips": rows}, f, ensure_ascii=False, indent=1)
    print("  欧洲国家队集锦：%d 场官方全场集锦（%d 个候选集锦页）"
          % (len(rows), len(cand)))
    return rows


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    import update_news
    raw = update_news.fetch_match_list()
    cand = candidates(raw, migu_clips.rolling_min_date())
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = [x for x in pool.map(
            update_news.safe_match_detail,
            [{"url": c["url"], "title": c["title"]} for c in cand]) if x]
    rows = fetch_euro_clips(raw, results=results)
    for r in rows:
        print(" ", r["date"], r["league"], r["home"], r["score"] or "—", r["away"],
              "|", r["official_url"][-14:], "|", r["title"][:40])
