# -*- coding: utf-8 -*-
"""咪咕体育官方比赛集锦检索（滚动 8 天窗口，五大联赛 / 欧冠）。

实测结论（2026-11-09，真实 Chrome + 官方接口）：
  1. playurl/v3/play/playurl 能返回播放列表，但 CDN 强制校验 ddCalcu 签名，
     第三方直接取流返回 660 / 661，拿不到可给 <video> 用的公网直链；
  2. 咪咕官方播放页在第三方 iframe 里只有 logo / 整站导航 / 报错，
     出不了画面（X-Frame-Options 虽未设，但播放器自身拒绝跨域嵌入）。
因此本模块只产出「咪咕官方集锦登记 + 原站播放入口」，不伪造直链、
不生成会黑屏的播放器。用户点开后到咪咕自己的域名看，画面必定正常。

数据链路：体育首页 SSR 数据 → 抽出点播 contId（含 refPID 指向的全场集锦）
→ 官方 playurl 接口批量核对标题 / 时长 / 是否免费 → 只留五大联赛与欧冠的
真实比赛集锦 → 落盘 migu_clips.json 供 update_news.py 生成页面卡片。
"""
import json
import os
import re
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta

import paths

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MIGU_JSON = paths.MIGU_JSON
MIGU_SPORTS_URL = ("https://www.miguvideo.com/mgs/website/prd/"
                   "sportsHomePage.html?pageId=0c40bbc85fa345bbba20f8e5fd11a922")
MIGU_INDEX_URL = "https://www.miguvideo.com/mgs/website/prd/sportsHomePage.html"
MIGU_INDEX_URLS = (MIGU_SPORTS_URL, MIGU_INDEX_URL)
MIGU_DETAIL_TPL = "https://www.miguvideo.com/p/detail/%s"
MIGU_PLAY_API = "https://webapi.miguvideo.com/gateway/playurl/v3/play/playurl"
# ---------- 滚动日期门槛（全站唯一真源） ----------
# 用户要求：11/13 不要 11/5 的，11/14 不要 11/6 的，11/15 不要 11/7 的……
# 也就是门槛每天都往后挪一天，永远只保留「今天 + 往前 7 天」共 8 个自然日。
# 11/13 -> 11/06 起，11/14 -> 11/07 起，11/15 -> 11/08 起，依此类推。
ROLLING_DAYS = 7


def _as_date(today):
    if today is None:
        return datetime.now().date()
    return today.date() if isinstance(today, datetime) else today


def rolling_min_date(today=None):
    """当前允许展示的最早比赛日期（ISO YYYY-MM-DD，含当天）。"""
    return (_as_date(today) - timedelta(days=ROLLING_DAYS)).isoformat()


def rolling_min_label(today=None):
    """给页面提示用的中文日期标签，如「11 月 6 日起」。"""
    d = _as_date(today) - timedelta(days=ROLLING_DAYS)
    return "%d 月 %d 日起" % (d.month, d.day)


# 模块级常量在每次运行脚本时重新计算；定时任务每天跑，门槛自然跟着走。
MIN_MATCH_DATE = rolling_min_date()
MIGU_MAX_CLIPS = 24

# ---------- 国际比赛日：窗口内两个区域全部换成欧洲国家队比赛 ----------
NATIONS_LEAGUE = "欧国联"
# 「明确的欧洲国家队赛事」关键词：命中即认定，无需再猜球队。
EURO_COMP_HINTS = (
    "欧国联", "欧洲国家联赛", "国家联赛", "Nations League",
    "欧洲杯", "欧预赛", "欧洲区预选", "欧洲区世预赛", "世预赛欧洲区",
    "欧洲杯预选赛", "欧锦赛",
)
# 友谊赛范围太宽（南美 / 亚洲也有），必须再用欧洲国家名单校验两队。
EURO_FRIENDLY_HINTS = ("国际友谊赛", "国际赛", "友谊赛")
EURO_TEAMS = (
    "英格兰", "苏格兰", "威尔士", "北爱尔兰", "爱尔兰", "法国", "德国", "意大利",
    "西班牙", "葡萄牙", "荷兰", "比利时", "瑞士", "奥地利", "波兰", "捷克",
    "斯洛伐克", "匈牙利", "克罗地亚", "塞尔维亚", "丹麦", "瑞典", "挪威",
    "芬兰", "冰岛", "希腊", "土耳其", "乌克兰", "俄罗斯", "罗马尼亚",
    "保加利亚", "阿尔巴尼亚", "黑山", "北马其顿", "马其顿", "斯洛文尼亚",
    "波黑", "波斯尼亚", "科索沃", "塞浦路斯", "马耳他", "卢森堡", "拉脱维亚",
    "立陶宛", "爱沙尼亚", "白俄罗斯", "摩尔多瓦", "格鲁吉亚", "亚美尼亚",
    "阿塞拜疆", "哈萨克斯坦", "以色列", "圣马力诺", "列支敦士登", "安道尔",
    "直布罗陀", "法罗群岛", "挪威", "斯洛伐克", "捷克",
)
NATIONS_HINTS = EURO_COMP_HINTS
# UEFA / FIFA 国际比赛日窗口（含首尾，按官方赛程维护）。
# 2026/27 欧国联联赛阶段第 5/6 轮为 11/12-11/17，落在 11/09-11/18 内。
INTERNATIONAL_WINDOWS = (
    ("2026-09-21", "2026-10-08"),
    ("2026-11-09", "2026-11-18"),
    ("2027-03-22", "2027-03-31"),
    ("2027-06-01", "2027-06-10"),
)


def international_windows():
    """窗口表输出给前端，页面按「打开当天」自己判断，快照过期也能自动切换。"""
    return [list(w) for w in INTERNATIONAL_WINDOWS]


def is_international_window(day=None):
    """当前是否处于国际比赛日窗口；day='YYYY-MM-DD' 可覆盖，方便回归测试。"""
    d = day or datetime.now().strftime("%Y-%m-%d")
    return any(a <= d <= b for a, b in INTERNATIONAL_WINDOWS)


def post_window_min_date(day=None):
    """国际比赛日结束后的「清场分界」：此后两个区域只收这一天起的新比赛。

    用户要求：国际比赛日过后，既不要国际比赛日的比赛，也不要国际比赛日之前
    缓存的联赛集锦 / 赛果。因此取「最近一个已结束窗口」结束日的次日作为下限，
    窗口内 / 窗口前的比赛（欧国联与旧联赛一起）全部不展示；没有就如实留空，
    等窗口结束后真正新打的五大联赛 / 欧冠自动补上。

    返回 ISO 日期字符串；当前仍在窗口内、或没有任何已结束窗口时返回 ""（不清场，
    走正常的 8 天滚动窗口）。前端在 app.js 里按同一张窗口表自己算一遍。
    """
    d = day or datetime.now().strftime("%Y-%m-%d")
    if is_international_window(d):
        return ""
    ended = [b for _a, b in INTERNATIONAL_WINDOWS if b < d]
    if not ended:
        return ""
    return (datetime.strptime(max(ended), "%Y-%m-%d").date()
            + timedelta(days=1)).isoformat()


def is_nations_title(text):
    """轮次 / 标题里是否明确写了欧洲国家队赛事。"""
    return any(k in (text or "") for k in EURO_COMP_HINTS)


def is_euro_nations(text, teams=()):
    """是否是「欧洲国家队比赛」：明确赛事直接认；友谊赛要两队都在欧洲名单里。"""
    t = text or ""
    if is_nations_title(t):
        return True
    if not any(k in t for k in EURO_FRIENDLY_HINTS):
        return False
    names = [str(x) for x in (teams or ()) if x]
    return bool(names) and all(any(c in n for c in EURO_TEAMS) for n in names)


def euro_league_of(text):
    """给卡片一个可读的赛事名；认不出来统一归到欧国联类别。"""
    t = text or ""
    for key, label in (
        ("欧洲杯预选赛", "欧洲杯预选赛"), ("欧预赛", "欧洲杯预选赛"),
        ("欧洲杯", "欧洲杯"), ("欧锦赛", "欧洲杯"),
        ("世预赛欧洲区", "世预赛欧洲区"), ("欧洲区世预赛", "世预赛欧洲区"),
        ("欧洲区预选", "世预赛欧洲区"),
        ("国际友谊赛", "国际友谊赛"), ("友谊赛", "国际友谊赛"),
    ):
        if key in t:
            return label
    return NATIONS_LEAGUE


def window_active(titles=()):
    """窗口判定只认日历这张单点真源。

    以前这里还有「标题出现欧国联就自动开窗」的兜底，会在国际比赛日结束后被
    源站残留的往期欧国联录像重新打开窗口，把国际比赛日的比赛又带回来。
    按用户要求，窗口结束后不再因旧欧洲比赛标题自动开窗；titles 仅为兼容保留。
    """
    return is_international_window()

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
PLAY_HEADERS = {
    "User-Agent": UA, "Appcode": "miguvideo_default_www",
    "Appid": "miguvideo", "Channel": "H5",
    "x-up-client-channel-id": "0132_10010001005",
    "Referer": "https://www.miguvideo.com/",
}

LEAGUE_HINTS = {
    "欧冠": ("欧冠", "欧战", "联赛阶段"),
    "英超": ("英超", "曼联", "曼城", "利物浦", "阿森纳", "切尔西", "热刺",
             "纽卡斯尔", "纽卡", "森林", "布莱顿", "阿斯顿维拉", "维拉",
             "水晶宫", "伯恩茅斯", "埃弗顿", "富勒姆", "西汉姆", "狼队",
             "布伦特福德", "桑德兰", "利兹联", "伯恩利"),
    "西甲": ("西甲", "皇马", "巴萨", "马竞", "皇家马德里", "巴塞罗那",
             "比利亚雷亚尔", "毕尔巴鄂", "塞维利亚", "贝蒂斯", "瓦伦西亚"),
    "意甲": ("意甲", "国米", "国际米兰", "AC米兰", "米兰", "尤文", "那不勒斯",
             "罗马", "拉齐奥", "亚特兰大", "佛罗伦萨", "科莫", "热那亚"),
    "德甲": ("德甲", "拜仁", "多特", "勒沃库森", "莱比锡", "法兰克福",
             "斯图加特", "霍芬海姆", "弗赖堡", "柏林联合", "门兴"),
    "法甲": ("法甲", "巴黎", "巴黎圣日耳曼", "马赛", "摩纳哥", "里昂",
             "里尔", "尼斯", "朗斯", "雷恩"),
    "欧国联": NATIONS_HINTS,
}
ALL_HINTS = tuple(k for v in LEAGUE_HINTS.values() for k in v) + (
    "红魔", "蓝月", "红军", "蓝军", "枪手", "白百合", "大巴黎",
)
OTHER_SPORTS = (
    "篮球", "CBA", "NBA", "UFC", "斯诺克", "排球", "乒乓", "网球", "F1",
    "中超", "国足", "女足", "电竞", "拳击", "羽毛球", "跳水", "游泳",
    "田径", "棒球", "橄榄球", "冰球", "赛车", "高尔夫", "台球",
)
BAD_HINTS = (
    "快评", "前瞻", "预测", "传闻", "转会", "采访", "发布会", "训练", "签名",
    "球迷", "效力", "生涯", "回顾", "致敬", "最佳球员", "最佳教头", "MVP",
    "社媒", "联动", "行为艺术", "心疼", "忍不了", "诸葛亮", "SIU",
    "添衣", "保暖", "名场面", "混剪", "应援", "解说", "评分", "大数据",
    "堪比", "谁是你心中", "哪位", "怒批", "教训深刻", "必须做得更好",
    "CBS Sports", "Sky Sports", "赛后情书", "嘿哈说", "英超故事",
    "未尝一胜", "经典", "前方-", "前方—", "talkshow", "称重",
    "踢了场", "入选", "候选", "有收获", "评利物浦", "轻松",
)
# 官方比赛画面：全场集锦 / 单场进球精华 / 联赛官方五佳球十佳球
MATCH_MARKS = ("全场集锦", "比赛集锦", "官方集锦", "全场录像", "精华",
               "五佳球", "十佳球")
GOOD_HINTS = ("集锦", "进球", "破门", "绝平", "制胜", "客胜", "主场", "战胜",
              "不敌", "爆冷", "扳平", "点球", "助攻", "扑救", "红牌", "VAR",
              "全场", "精华", "锁定胜局", "补时", "头球", "世界波",
              "一条龙", "传射", "梅开二度", "帽子戏法", "读秒", "传中")


def _get(url, timeout=25):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Referer": "https://www.miguvideo.com/"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "ignore")


def clean(s):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", s or "")).strip()


def league_of(title):
    for lg, keys in LEAGUE_HINTS.items():
        if any(k in title for k in keys):
            return lg
    return "五大联赛"


def _pick_cover(seg):
    urls = re.findall(r'https?://[^"\\\s]+?\.(?:webp|jpg|png|jpeg)', seg)
    flat = [u for u in urls if "H169" in u or "1O7" in u]
    for u in flat or [u for u in urls if "cmvideo.cn" in u]:
        return u.replace("\\/", "/")
    return ""


def _field(v):
    return clean(str(v or "").split('","')[0])


def parse_index(html):
    """首页 SSR 数据逐条切出 name/pID/时间/时长/封面。"""
    cands, pat = [], r'\{"name":"(.*?)","pID":"(\d+)","publishTime":"(.*?)"'
    for m in re.finditer(pat, html):
        name, pid, pub = _field(m.group(1)), m.group(2), m.group(3)
        if pub[:10] < MIN_MATCH_DATE or not name:
            continue
        if name.startswith("PROGRAM_") or "CLICK" in name:
            continue
        cands.append((m.start(), name, pid, pub))
    out, seen = [], set()
    for pos, name, pid, pub in cands:
        if pid in seen:
            continue
        seg = html[pos:pos + 4200]
        dm = re.search(r'"duration":"(\d{1,2}:\d{2})"', seg)
        dd = re.search(r'"detail":"(.*?)"', seg)
        detail = _field(dd.group(1)) if dd else ""
        seen.add(pid)
        out.append({
            "cont_id": pid, "title": name, "name": name,
            "official_title": (detail if detail and not detail.startswith("PROGRAM_")
                               else name),
            "published": pub, "duration": dm.group(1) if dm else "",
            "img": _pick_cover(seg), "page_url": MIGU_DETAIL_TPL % pid,
        })
    return out


def _near_meta(htmls, cid):
    """refPID 指向的全场集锦在首页没有独立记录，就近取发布时间与封面。"""
    for h in htmls:
        i = h.find('"%s"' % cid)
        if i < 0:
            continue
        seg = h[max(0, i - 2600):i + 2200]
        pubs = re.findall(r'"publishTime":"(\d{4}-\d{2}-\d{2}[^"]*)"', seg)
        cover = _pick_cover(seg)
        return (pubs[0] if pubs else ""), cover
    return "", ""


def _mmss(sec):
    try:
        n = int(sec)
        return "%02d:%02d" % (n // 60, n % 60) if n > 0 else ""
    except Exception:
        return ""


def probe_playurl(ids):
    """用咪咕官方接口核对每个点播 ID 的真实标题、时长、是否免费。"""
    def one(cid):
        q = ("?contId=%s&rateType=3&chip=mgwww&channelId=0132_10010001005" % cid)
        try:
            req = urllib.request.Request(MIGU_PLAY_API + q, headers=PLAY_HEADERS)
            d = json.loads(urllib.request.urlopen(req, timeout=15)
                           .read().decode("utf-8", "ignore"))
            body = d.get("body") or {}
            c = body.get("content") or {}
            ui = body.get("urlInfo") or {}
            if not ui.get("url"):
                return None
            return {
                "cont_id": cid, "title": clean(c.get("contName") or ""),
                "duration": _mmss(c.get("duration")),
                "fee": str(c.get("fee") or "0"),
            }
        except Exception:
            return None
    with ThreadPoolExecutor(max_workers=6) as pool:
        rows = list(pool.map(one, ids))
    return [x for x in rows if x and x["title"]]


FOOTBALL_WORDS = ("破门", "进球", "足球", "世界波", "扑救", "门将", "传射",
                  "绝平", "客胜", "不敌", "集锦", "英超", "西甲", "意甲",
                  "德甲", "法甲", "欧冠", "欧国联", "越位", "点球", "禁区", "头球")


def is_match_clip(title, window=False):
    """官方比赛集锦：平时只认五大联赛 / 欧冠，国际比赛日窗口额外认欧国联。"""
    if any(o in title for o in OTHER_SPORTS) or any(b in title for b in BAD_HINTS):
        return False
    if is_nations_title(title) and not window:
        return False
    # 篮球 / 格斗也有「十佳球」栏目，标题里必须出现足球动作或赛事名
    if not any(w in title for w in FOOTBALL_WORDS):
        return False
    has_mark = any(k in title for k in MATCH_MARKS)
    has_score = bool(re.search(r"\d{1,2}\s*[-:：比]\s*\d{1,2}", title))
    is_ucl = title.startswith("欧冠-") or "欧冠-" in title[:8]
    if not (has_mark or is_ucl or (has_score and any(g in title for g in GOOD_HINTS))):
        return False
    return bool(any(k in title for k in ALL_HINTS) or has_score or has_mark)


def _split_score(title):
    """从「全场集锦：诺丁汉森林3:1曼城」拆出主客队与比分。"""
    m = re.search(r"集锦[：:]\s*(.+?)\s*(\d{1,2})\s*[:：]\s*(\d{1,2})\s*(.+)$", title)
    if m:
        return m.group(1).strip(), m.group(4).strip(), "%s-%s" % (m.group(2), m.group(3))
    m = re.search(r"(\d{1,2})\s*[-:：比]\s*(\d{1,2})", title)
    return "", "", ("%s-%s" % (m.group(1), m.group(2))) if m else ""


def build_clips(window=False):
    htmls = []
    for u in MIGU_INDEX_URLS:
        try:
            htmls.append(_get(u))
        except Exception:
            pass
    if not htmls:
        raise RuntimeError("咪咕体育首页不可达")

    index = {}
    for h in htmls:
        for x in parse_index(h):
            index.setdefault(x["cont_id"], x)
    ids = set(index)
    for h in htmls:
        ids |= set(re.findall(r'"(?:pID|refPID|contId)":"(9\d{8})"', h))

    meta = probe_playurl(sorted(ids))
    rows = []
    for x in meta:
        t = x["title"]
        if x["fee"] not in ("0", "", None) or not is_match_clip(t, window):
            continue
        ix = index.get(x["cont_id"], {})
        pub = ix.get("published") or ""
        cover = ix.get("img") or ""
        if not pub or not cover:
            p2, c2 = _near_meta(htmls, x["cont_id"])
            pub = pub or p2
            cover = cover or c2
        # 拿不到官方发布时间就不能判断是否在滚动窗口内，宁可不收，也不能
        # 用「当前时间」把一条往期集锦伪装成今天的新片。
        if not pub or pub[:10] < MIN_MATCH_DATE:
            continue
        home, away, score = _split_score(t)
        rows.append({
            "cont_id": x["cont_id"], "title": t, "name": t,
            "official_title": ix.get("official_title") or t,
            "published": pub, "duration": x["duration"] or ix.get("duration") or "",
            "img": cover, "page_url": MIGU_DETAIL_TPL % x["cont_id"],
            "league": league_of(t), "home": home, "away": away, "score": score,
        })
    # 首页带时间但接口临时失败的旧结果也要保留，避免刷新把内容冲掉
    seen = {x["cont_id"] for x in rows}
    for x in load_migu_clips():
        # 窗口结束后自动撤下欧国联卡片，避免「国际比赛日过了还挂着」
        if is_nations_title(x.get("title", "")) and not window:
            continue
        if x["cont_id"] not in seen:
            rows.append(x)
            seen.add(x["cont_id"])
    rows.sort(key=lambda x: x["published"], reverse=True)
    return rows[:MIGU_MAX_CLIPS]


def fetch_migu_clips(window=None):
    """抓咪咕体育官方集锦；window 为真时额外收欧国联（国际比赛日）。"""
    if window is None:
        window = is_international_window()
    try:
        rows = build_clips(window)
        if not rows:
            raise RuntimeError("没有解析到 %s 起的官方比赛集锦" % MIN_MATCH_DATE)
        with open(MIGU_JSON, "w", encoding="utf-8") as f:
            json.dump({"updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                       "clips": rows}, f, ensure_ascii=False, indent=1)
        print("  咪咕体育：%d 段 %s 起的官方比赛集锦（原站播放）"
              % (len(rows), MIN_MATCH_DATE))
        return rows
    except Exception as exc:
        print("  [警告] 咪咕体育集锦抓取失败：%s" % exc)
        return [x for x in load_migu_clips()
                if window or not is_nations_title(x.get("title", ""))]


def load_migu_clips():
    try:
        with open(MIGU_JSON, "r", encoding="utf-8") as f:
            rows = json.load(f).get("clips") or []
        return [x for x in rows
                if x.get("page_url", "").startswith("https://www.miguvideo.com/p/detail/")
                and x.get("published", "")[:10] >= MIN_MATCH_DATE]
    except Exception:
        return []


def as_clip(x):
    """转成赛果集锦卡片：不带 play / embed，只带咪咕官方原站入口。"""
    pub = x.get("published") or ""
    return {
        # 用官方视频 ID 生成固定地址（#/match/migu_<contId>），定时重抓也不变
        "id": "migu_" + str(x.get("cont_id") or x["page_url"].rsplit("/", 1)[-1]),
        "section": "clip", "video_status": "migu", "provider": "migu",
        "play": "", "embed": "", "migu_url": x["page_url"],
        "cont_id": x.get("cont_id", ""),
        "title": x["title"], "headline": x["title"],
        "teams": ("%s %s" % (x.get("home") or "", x.get("away") or "")).strip(),
        "score": x.get("score") or "", "home": x.get("home") or "",
        "away": x.get("away") or "", "league": x.get("league") or "五大联赛",
        "comp": "咪咕体育官方集锦", "round": "官方集锦",
        "date": pub[5:10] if len(pub) >= 10 else "",
        "kickoff": "", "duration": x.get("duration") or "",
        "img": x.get("img") or "", "logos": [], "published": pub,
        "order_ok": True,
        "source": "咪咕体育官方比赛集锦 · 在咪咕原站观看（版权方）",
    }


if __name__ == "__main__":
    rows = fetch_migu_clips()
    for r in rows:
        print(r["published"][:16], r["duration"].rjust(5),
              r["league"].ljust(5), r["score"].ljust(4),
              r["title"][:58], "| cover", bool(r["img"]))
