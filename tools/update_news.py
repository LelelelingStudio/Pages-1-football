# -*- coding: utf-8 -*-
"""
足球赛事日报 · 数据抓取
数据源：直播吧足球资讯（news.zhibo8.com）

流程：
  1. 抓足球资讯首页 + 全量滚动页，拿到候选标题与链接（URL 内含日期）
  2. 按「欧冠 / 英超 / 西甲 / 意甲 / 德甲 / 法甲」关键词筛选并配额挑 50 条
  3. 并发抓这 50 条的详情页，取真实正文、配图、精确到秒的发布时间、来源
  4. 抓「赛果集锦」：只收咪咕体育官方完整集锦，不给黑屏播放器。
     咪咕集锦（migu_clips.py：体育首页 SSR + 官方 playurl 接口核对标题 / 时长 /
     免费状态）由版权方提供，播放列表带 ddCalcu 签名校验，官方播放器实测也不
     允许第三方 iframe 嵌入（只有 logo / 导航 / 报错），因此这类卡片只带官方
     原站入口，用户主动点击后到咪咕自己的域名观看。
     带比分的咪咕全场集锦按「比分 + 主客两队」回挂到对应正赛赛果。
     已按用户要求删掉此前 6 段「进球实拍 / 扑救 / 现场镜头」零散比赛画面片段
     （kind=fragment）：不再抓取、不再沿用缓存；B 站嵌入播放器也已彻底停用。
  5. 另抓官方「比赛集锦页 / 全场录像页」（jijin / luxiang），补进
     英超 / 欧冠 / 西甲 / 意甲 / 法甲 / 德甲正赛的真实赛果（轮次、主客队、
     比分、开球时间、队徽、封面）。这些页面的官方集锦只有咪咕外链、没有
     可内嵌的 mp4，因此只记赛果、不伪造视频，前端如实标注「官方集锦未内嵌」。
  5b. 集锦与正赛赛果分成两个独立区域，分别写 section="clip" / "result"。
      源站视频列表轮换会让可播集锦整批下架，因此把已复验可播的往期官方
      集锦存在 archive_clips.json，每轮与本次抓到的合并去重，不覆盖历史。
  6. 保留通用直链解析能力（getplayinfo 逐档探测 H.264），仅供源站自带
     「带比分的完整集锦」使用；零散片段已停用，当前集锦区不含站内视频
  7. 写 news.json，并把数据注入 index.html 的内嵌数据块

更新节奏：资讯每次刷新都更新；赛果集锦与正赛赛果沿用上次结果，超过 3 天自动补抓。
  无参数 / 双击「更新新闻.bat」/ 页面点「刷新」 -> 更新 50 条资讯，赛果沿用上次结果
  python update_news.py --matches-only      -> 只重抓赛果集锦，资讯原样保留（定时任务用）
  python update_news.py --refresh-matches  -> 全量更新，并强制重抓赛果集锦（手动补更）
  若超过 MATCH_MAX_AGE_DAYS 天没更新过赛果，普通刷新也会自动补抓一次，避免长期不刷新。

原则：标题、摘要、配图、时间、来源全部原样取自来源页，不改写、不编造比分或赛果。
集锦只在「比分 + 队名」同时吻合时才关联到新闻，匹配不上就不硬塞。
零第三方依赖，Python 3.7+ 直接运行。
"""
import html as H
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta

import euro_clips
import migu_clips
import upcoming
import paths

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
NEWS_JSON = paths.NEWS_JSON
INDEX_HTML = paths.INDEX_HTML

LIST_URLS = [
    "https://news.zhibo8.com/zuqiu/",       # 当天最新
    "https://news.zhibo8.com/zuqiu/more.htm" # 近期全量
]
SOURCE_URL = "https://news.zhibo8.com/zuqiu/"

# 官方比赛集锦（www.zhibo8.com 视频频道，详情页自带腾讯 VOD 可嵌播放器）
VIDEO_URLS = [
    "https://www.zhibo8.com/zuqiu/",
    "https://www.zhibo8.com/zuqiu/more.htm",
]
VIDEO_HOST = "https://www.zhibo8.com"
# 官方播放器有两个 CDN 域名（新版 vodjzhs / 旧版 vodapphs），同为直播吧自有 VOD
VOD_RE = re.compile(r"^https://(?:vodjzhs|vodapphs)\.duoduocdn\.com/vod-player/")
# 腾讯云 VOD 播放信息接口：用它把「控制台预览播放器」换成真正可播的 mp4 直链
PLAYINFO_API = "https://playvideo.qcloud.com/getplayinfo/v4/%s/%s"
# 只放行腾讯云 VOD 存储域名的 mp4，避免把任意地址写进页面
MP4_RE = re.compile(r"^https://[\w.-]*vod2\.myqcloud\.com/[\w./-]+\.mp4$", re.I)
MAX_HIGHLIGHTS = 40

# 已停用：零散比赛画面片段（进球实拍 / 扑救 / 现场镜头）按用户要求删除。
# 下列常量与片段抓取函数仅作历史留存，抓取链路不再调用，缓存文件已清空。
FRAGMENT_CLIPS = paths.FRAGMENT_CLIPS
FRAGMENT_MAX = 16
FRAGMENT_TEAM_KEYS = [
    "英超", "西甲", "意甲", "德甲", "法甲", "欧冠", "曼联", "利物浦", "阿森纳",
    "曼城", "切尔西", "热刺", "巴萨", "皇马", "马竞", "国米", "尤文", "米兰",
    "那不勒斯", "拜仁", "多特", "巴黎", "马赛", "摩纳哥", "维拉", "纽卡",
    "森林", "富勒姆", "布莱顿", "埃弗顿", "利兹", "桑德兰", "水晶宫",
    "伯恩茅斯", "比利亚雷亚尔", "贝蒂斯", "皇家社会", "亚特兰大", "拉齐奥",
    "罗马", "佛罗伦萨", "弗赖堡", "斯图加特", "法兰克福", "勒沃库森",
    "费内巴切", "阿贾克斯", "埃因霍温", "波尔图", "本菲卡", "布鲁日",
    "斯拉维亚", "科莫", "热那亚", "朗斯", "赫尔城", "吉鲁",
    "小图拉姆", "斯彭斯", "比塞克",
]
FRAGMENT_GOOD = ["实拍", "破门", "进球", "扑救", "世界波", "补射", "高清",
                 "现场", "镜头", "绝平", "绝杀", "单刀", "点球", "攻门",
                 "得分", "配合", "助攻", "过人", "射门", "回放", "对抗",
                 "反击", "抢点", "头球", "凌空", "远射", "传中", "封堵",
                 "创造助攻", "杀到", "锁定胜局"]
FRAGMENT_BAD = ["采访", "博主", "名场面", "回顾", "经典", "个人集锦", "谈",
                "炮轰", "解析", "评选", "回忆", "当年", "时期", "生涯", "球迷",
                "主帅", "官宣", "退役", "合集", "U17", "U15", "女足", "青年",
                "训练", "签名", "队史", "小妖", "大搜集", "杂烩", "辟谣",
                "祝福", "最佳", "首发名单", "气象", "演播室", "美女", "内衣",
                "空座", "谢场", "抵达", "冲突", "看懵", "巡礼", "童年",
                # 历史画面 / 采访口播 / 球员个人介绍都不是「这场比赛的画面」
                "08年", "09年", "10年", "天才", "西蒙尼", "新援", "青训",
                "曾经的", "吧选之子", "全能中场", "技术型边锋", "怎么救",
                "你认为", "怎么看", "评分", "数据", "排名", "历史",
                "2016", "2017", "2018", "2019", "2020", "2021", "2022",
                "2023", "2024", "2025", "歌曲", "唱歌", "模仿"]

# 官方「比赛集锦页 / 全场录像页」：有权威正赛赛果，但集锦在咪咕，站内不可播
MATCH_LIST_URLS = [
    "https://www.zhibo8.com/zuqiu/",
    "https://www.zhibo8.com/zuqiu/more.htm",
    "https://www.zhibo8.com/zuqiu/luxiang.htm",
]
# 走 HTTPS/443：部分运行环境的沙箱会拦 80 端口，导致整批赛果详情页取不到、静默退化成沿用旧数据
MOBILE_HOST = "https://m.zhibo8.cc"
# 正赛赛果收录范围：五大联赛 + 欧冠。列表页的轮次标题是权威判据，不用队名猜。
# 用户指定英超要 10 场，其余赛事由本站自定义配额；源站每类近期可用 17~20 场。
MATCH_LEAGUES = ["英超", "欧冠", "西甲", "意甲", "法甲", "德甲"]
MATCH_PER_LEAGUE = {"英超": 10, "欧冠": 8, "西甲": 6, "意甲": 6, "法甲": 6, "德甲": 6}
# 国际比赛日窗口内，两个区域全部换成欧洲国家队比赛（俱乐部比赛一律撤下）；
# 窗口判定与国际比赛日日历在 migu_clips 单点定义，前后端共用。
NATIONS_LEAGUE = migu_clips.NATIONS_LEAGUE
NATIONS_PER_LEAGUE = 24
MATCH_WINDOW_MAX_AGE_HOURS = 12   # 窗口内最多 12 小时就重抓，比赛打完马上补
_NATIONS_WINDOW = None
# 滚动日期门槛：今天剔 8 天前那一天，明天再往后剔一天，依此类推。
# 真源在 migu_clips.rolling_min_date()（今天 - 7 天），两个抓取模块共用同一个值，
# 且每次运行脚本都会重算，定时任务每天跑就自动往前滚。
MIN_MATCH_DATE = migu_clips.rolling_min_date()
MIN_MATCH_LABEL = migu_clips.rolling_min_label()
MATCH_WINDOW_DAYS = migu_clips.ROLLING_DAYS + 1   # 含今天共 8 个自然日
# 国际比赛日结束后的清场下限（最近一个已结束窗口结束日的次日）。
# 用户要求：窗口过后既不展示国际比赛日的比赛，也不把窗口之前缓存的联赛集锦 /
# 赛果倒回来；所以窗口结束后两个区域只收这个日期起真正新打的比赛，没有就留空。
# 窗口内为空串，走正常的 8 天滚动窗口。每次运行重算，与前端同用一张窗口表。
POST_BREAK_MIN_DATE = migu_clips.post_window_min_date()


def effective_min_date():
    """本次采集 / 沿用数据时实际生效的最早比赛日期。"""
    return max(MIN_MATCH_DATE, POST_BREAK_MIN_DATE or MIN_MATCH_DATE)


# 两类数据分属两个独立区域：
#   section="clip"   -> 有 H.264 直链、站内可播的官方比赛集锦（赛果集锦区）
#   section="result" -> 只有官方赛果、源站集锦在咪咕没有可内嵌地址（正赛赛果区）
# 平时刷新沿用已有结果，只有超过 MATCH_MAX_AGE_DAYS 天没更新过才补抓一次。
MATCH_MAX_AGE_DAYS = 3
POST_BREAK_TXT = ("%s 起" % POST_BREAK_MIN_DATE) if POST_BREAK_MIN_DATE \
    else "按窗口结束次日自动抬高的门槛"
MATCH_SCHEDULE = ("只收录最近 %d 天（%s 起）的比赛，门槛每天自动后移一天；"
                  "国际比赛日窗口内「赛果集锦」「正赛赛果」两个区域全部换成欧洲"
                  "国家队比赛（俱乐部赛事一律撤下，窗口内每 12 小时补抓一次）；"
                  "窗口结束后不再展示国际比赛日的比赛，也不恢复窗口之前的俱乐部"
                  "集锦与赛果，只收窗口结束后新打的五大联赛 / 欧冠（%s），"
                  "没有新比赛就如实留空；页面打开时也会按当天日期再判定一次"
                  % (MATCH_WINDOW_DAYS, MIN_MATCH_DATE, POST_BREAK_TXT))
# 源站视频列表轮换后下架、但 H.264 直链仍可播的往期官方集锦，避免集锦区被清空
ARCHIVE_CLIPS = paths.ARCHIVE_CLIPS
# 队名简称 ↔ 官方全称：仅用于把「标题里的比分顺序」对齐到主客队，不参与生成任何数据
TEAM_ALIASES = {
    "国际米兰": ["国米"], "AC米兰": ["米兰"], "尤文图斯": ["尤文"],
    "拜仁慕尼黑": ["拜仁"], "巴塞罗那": ["巴萨"], "马德里竞技": ["马竞"],
    "巴黎圣日耳曼": ["巴黎", "大巴黎"], "曼彻斯特联": ["曼联", "红魔"],
    "曼彻斯特城": ["曼城", "蓝月亮"], "皇家马德里": ["皇马", "银河战舰"],
    "阿斯顿维拉": ["维拉"], "阿森纳": ["枪手"], "切尔西": ["蓝军"],
    "利物浦": ["红军"], "托特纳姆热刺": ["热刺", "白百合"],
    "布拉格斯拉维亚": ["斯拉维亚"], "RB莱比锡": ["莱比锡"],
    "毕尔巴鄂竞技": ["毕尔巴鄂"], "皇家贝蒂斯": ["贝蒂斯"],
    "LASK林茨": ["林茨"], "葡萄牙体育": ["葡体"], "顿涅茨克矿工": ["矿工"],
    "多特蒙德": ["多特", "大黄蜂"], "尤文图斯": ["尤文", "斑马军团"],
    "国际米兰": ["国米", "蓝黑"], "AC米兰": ["米兰", "红黑"],
    "勒沃库森": ["药厂"], "桑德兰": ["黑猫"], "马德里竞技": ["马竞", "床单军团"],
    "沙巴巴库": [], "加拉塔萨雷": [], "皇家社会": [], "塞维利亚": [],
    "瓦伦西亚": [], "埃尔切": [],
    # 11 月 7/8 日英超两队官方全称与标题简称，补齐后才能确认比分顺序
    "诺丁汉森林": ["森林"], "纽卡斯尔联": ["纽卡", "纽卡斯尔", "喜鹊"],
}

START = "<!--NEWS_DATA_START-->"
END = "<!--NEWS_DATA_END-->"
LIMIT = 50
QUOTA = {"欧冠": 10, "英超": 10, "西甲": 8, "意甲": 8, "德甲": 7, "法甲": 7}
LEAGUES = list(QUOTA.keys())

KEYWORDS = {
    "欧冠": ["欧冠", "欧联", "冠军联赛", "联赛阶段"],
    "英超": ["英超", "曼联", "利物浦", "曼城", "阿森纳", "切尔西", "热刺", "纽卡", "维拉",
             "埃弗顿", "西汉姆", "布莱顿", "伯恩茅斯", "诺丁汉森林", "水晶宫", "富勒姆",
             "布伦特福德", "利兹联", "狼队", "桑德兰", "伯恩利"],
    "西甲": ["西甲", "皇马", "皇家马德里", "巴萨", "巴塞罗那", "马竞", "马德里竞技",
             "塞维利亚", "皇家社会", "毕尔巴鄂", "贝蒂斯", "比利亚雷亚尔", "赫罗纳", "瓦伦西亚"],
    "意甲": ["意甲", "国米", "国际米兰", "AC米兰", "尤文", "那不勒斯", "拉齐奥",
             "亚特兰大", "佛罗伦萨", "博洛尼亚"],
    "德甲": ["德甲", "拜仁", "多特", "勒沃库森", "莱比锡", "法兰克福", "斯图加特",
             "门兴", "弗赖堡", "沃尔夫斯堡"],
    "法甲": ["法甲", "巴黎圣日耳曼", "大巴黎", "马赛", "摩纳哥", "里尔", "里昂", "尼斯", "朗斯"],
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9",
}

TAG_RULES = [
    ("官方", "官方"), ("转会", "转会"), ("伤停", "伤停"), ("受伤", "伤停"), ("伤", "伤停"),
    ("续约", "续约"), ("首发", "阵容"), ("名单", "阵容"), ("绝杀", "赛果"),
    ("战胜", "赛果"), ("击败", "赛果"), ("大胜", "赛果"), ("比分", "赛果"), ("平局", "赛果"),
    ("积分榜", "积分"), ("前瞻", "前瞻"), ("复盘", "复盘"),
]


def clean(s):
    return H.unescape(re.sub(r"<[^>]+>", "", str(s or ""))).strip()


def get(url, timeout=20):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "replace")


def abs_url(u):
    u = (u or "").strip()
    if u.startswith("//"):
        return "https:" + u
    if u.startswith("http://"):
        return "https://" + u[7:]
    return u


def classify(title):
    """按标题关键词判定赛事，优先级即 LEAGUES 顺序。"""
    for lg in LEAGUES:
        if any(k in title for k in KEYWORDS[lg]):
            return lg
    return ""


def tag_of(title):
    for k, label in TAG_RULES:
        if k in title:
            return label
    return ""


def fetch_list():
    """返回 [(detail_url, title, date_str, order)]，按列表原始顺序（大致时间倒序）。"""
    found, seen = [], set()
    order = 0
    for url in LIST_URLS:
        try:
            page = get(url, timeout=25)
        except Exception as exc:
            print("  [警告] 列表页抓取失败 %s: %s" % (url, exc))
            continue
        for href, raw_title in re.findall(
            r'<a[^>]+href="(//news\.zhibo8\.com/[^\"]+\.htm)"[^>]*>([^<]+)</a>', page
        ):
            title = clean(raw_title)
            if len(title) < 8:
                continue
            full = abs_url(href)
            if full in seen:
                continue
            seen.add(full)
            m = re.search(r"/zuqiu/(\d{4}-\d{2}-\d{2})/", full)
            date = m.group(1) if m else "1970-01-01"
            found.append({"url": full, "title": title, "date": date, "order": order})
            order += 1
        print("  列表 %s -> 累计 %d 条" % (url.split("/")[-1] or "首页", len(found)))
    return found


def pick(candidates):
    """按赛事配额挑 LIMIT 条，优先日期新的；不足配额由其它赛事补足。"""
    buckets = {lg: [] for lg in LEAGUES}
    for it in candidates:
        lg = classify(it["title"])
        if lg:
            it["league"] = lg
            buckets[lg].append(it)
    for lg in buckets:
        buckets[lg].sort(key=lambda x: (x["date"], -x["order"]), reverse=True)

    chosen, used = [], set()

    def take(lg, n):
        got = 0
        for it in buckets[lg]:
            if got >= n:
                break
            if it["url"] in used:
                continue
            used.add(it["url"])
            chosen.append(it)
            got += 1
        return got

    shortfall = 0
    for lg, n in QUOTA.items():
        shortfall += n - take(lg, n)
    # 某个赛事不够时，用其余赛事最新的条目补满
    if shortfall:
        pool = sorted(
            [it for lg in LEAGUES for it in buckets[lg] if it["url"] not in used],
            key=lambda x: (x["date"], -x["order"]), reverse=True,
        )
        for it in pool[:shortfall]:
            if it["url"] in used:
                continue
            used.add(it["url"])
            chosen.append(it)
    return chosen[:LIMIT]


def fetch_detail(it):
    """抓详情页，补真实摘要 / 配图 / 时间 / 来源。失败则保留标题，摘要留空。"""
    out = dict(it)
    out.setdefault("desc", "")
    out.setdefault("img", "")
    out.setdefault("time", it["date"][5:])
    out.setdefault("source", "直播吧")
    out.setdefault("ts", 0)
    try:
        page = get(it["url"], timeout=20)
        h1 = re.search(r"<h1[^>]*>(.*?)</h1>", page, re.S)
        if h1:
            t = clean(h1.group(1))
            if len(t) > 8:
                out["title"] = t
        body = re.search(r'<div[^>]*id="signals"[^>]*>(.*?)</div>', page, re.S)
        if body:
            paras = [clean(p) for p in re.findall(r"<p[^>]*>(.*?)</p>", body.group(1), re.S)]
            paras = [p for p in paras if p]
            text = " ".join(paras)
            text = re.sub(r"\s+", " ", text).strip()
            if len(text) > 230:
                cut = text[:230]
                stop = max(cut.rfind("。"), cut.rfind("！"), cut.rfind("？"))
                text = cut[:stop + 1] if stop > 100 else cut + "…"
            out["desc"] = text
            pic = re.search(r'<img[^>]+src="([^"]+)"', body.group(1))
            if pic:
                out["img"] = abs_url(pic.group(1))
        tm = re.search(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", page)
        if tm:
            out["time"] = tm.group(1)[5:16]
            try:
                out["ts"] = int(datetime.strptime(tm.group(1), "%Y-%m-%d %H:%M:%S").timestamp())
            except ValueError:
                pass
        author = re.search(r'class="author-name"[^>]*>([^<]+)<', page)
        if author:
            out["source"] = "直播吧 · " + clean(author.group(1))
    except Exception as exc:
        out["error"] = "%s: %s" % (type(exc).__name__, exc)
    return out


# ---------- 官方比赛集锦 ----------
# 只用于从真实集锦标题里「检出」队名，不参与任何比分或赛果的生成。
TEAM_NAMES = [
    "阿斯顿维拉", "诺丁汉森林", "布伦特福德", "伯恩茅斯", "巴黎圣日耳曼", "比利亚雷亚尔",
    "马德里竞技", "皇家马德里", "巴塞罗那", "国际米兰", "沃尔夫斯堡", "勒沃库森",
    "法兰克福", "斯图加特", "皇家社会", "毕尔巴鄂", "塞维利亚", "瓦伦西亚",
    "亚特兰大", "佛罗伦萨", "博洛尼亚", "那不勒斯", "拉齐奥", "柏林联合",
    "斯特拉斯堡", "新英格兰革命", "广东广州豹", "石家庄功夫", "南京城市",
    "大连鲲城", "梅州客家", "延边龙鼎", "武汉联镇", "吴川青年", "AC米兰",
    "水晶宫", "富勒姆", "利兹联", "布莱顿", "西汉姆", "埃弗顿", "贝蒂斯",
    "赫罗纳", "埃尔切", "热那亚", "弗赖堡", "莱比锡", "摩纳哥", "马赛",
    "里尔", "里昂", "尼斯", "朗斯", "欧塞尔", "桑德兰", "伯恩利", "桑托斯",
    "巴伊亚", "迈阿密", "辛辛那提", "博卡", "河床", "尤文", "罗马", "莱切",
    "科隆", "汉堡", "门兴", "多特", "拜仁", "国米", "热刺", "曼联", "利物浦",
    "曼城", "阿森纳", "切尔西", "纽卡", "维拉", "皇马", "巴萨", "马竞",
    "狼队", "巴黎", "大巴黎",
]


# ---------- B 站 / 咪咕官方比赛集锦（滚动窗口） ----------
# 直播吧 11/5 之后的五大联赛 / 欧冠集锦全部指向咪咕，没有可内嵌地址。
# B 站上有俱乐部 / 联赛官方账号发的同场次全场集锦，且提供官方外链播放器，
# 实测在第三方页面能出画面；B 站 CDN 强制 Referer，mp4 直链不能直接用 <video>。
BILI_SEARCH_API = "https://api.bilibili.com/x/web-interface/search/type"
BILI_PLAYER_TPL = ("https://player.bilibili.com/player.html?bvid=%s"
                   "&page=1&high_quality=1&danmaku=0&autoplay=0")
BILI_HEADERS = {
    "User-Agent": HEADERS["User-Agent"],
    "Referer": "https://search.bilibili.com/",
    "Cookie": "buvid3=WBSTATIC-3F1C-4E2A-9B75-20261109infoc; b_nut=1762000000",
}
BILI_KEYWORDS = [
    "英超 全场集锦", "英超 比赛集锦", "西甲 全场集锦", "西甲 比赛集锦",
    "意甲 全场集锦", "意甲 比赛集锦", "德甲 精华集锦", "德甲 全场集锦",
    "法甲 比赛集锦", "欧冠 全场集锦", "欧冠 比赛集锦", "足球 全场集锦",
]
BILI_OFFICIAL = ("足球俱乐部", "俱乐部官方", "LALIGA", "德国足球甲级联赛",
                 "法国足球甲级联赛", "英超联赛", "西甲联赛", "意甲联赛",
                 "爱奇艺体育", "PP体育", "咪咕体育", "巴黎圣日耳曼")
BILI_BAD = (
    "个人集锦", "个人精彩", "个人触球", "全网首发", "精彩片段", "Cut", "cut",
    "触球", "评分", "锐评", "虎扑", "预测", "前瞻", "竞彩", "二串一", "推荐",
    "赛季全记录", "经典", "回顾",
    "历史", "怀旧", "名场面", "混剪", "剪辑", "十佳", "U18", "U21", "U17",
    "女超", "女足", "女排", "模拟", "搞笑", "梗图", "采访", "发布会",
    "游戏", "手游", "德云色", "NFL", "篮球", "扑克", "转会", "传闻",
    "应援", "花絮", "MV", "mv", "解说", "预测", "大数据",
)
BILI_GOOD = ("集锦", "全场", "精华", "高光")
BILI_MAX_CLIPS = 24
MIGU_SPORTS_URL = ("https://www.miguvideo.com/mgs/website/prd/"
                   "sportsHomePage.html?pageId=0c40bbc85fa345bbba20f8e5fd11a922")
BILI_SEED = paths.BILI_SEED


def bili_ts():
    """B 站搜索时间窗：滚动门槛当天 00:00 起到此刻（+1 天容错）。"""
    b = int(datetime.strptime(MIN_MATCH_DATE, "%Y-%m-%d").timestamp())
    return b, int(time.time()) + 86400


def bili_search(keyword, page=1):
    b, e = bili_ts()
    q = {"search_type": "video", "keyword": keyword, "order": "pubdate",
         "page": page, "pubtime_begin_s": b, "pubtime_end_s": e}
    req = urllib.request.Request(
        BILI_SEARCH_API + "?" + urllib.parse.urlencode(q), headers=BILI_HEADERS)
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode("utf-8", "replace"))
    if data.get("code") != 0:
        return []
    return (data.get("data") or {}).get("result") or []


def bili_title(v):
    return clean(re.sub(r"<[^>]+>", "", v.get("title") or ""))


def bili_official(v):
    return 1 if any(k in (v.get("author") or "") for k in BILI_OFFICIAL) else 0


def bili_duration(v):
    m = re.match(r"^(\d{1,2}):(\d{1,2})$", str(v.get("duration") or ""))
    return "%02d:%02d" % (int(m.group(1)), int(m.group(2))) if m else ""


def bili_match(title, rows):
    """必须同时命中「比分 + 主客两队」才认作这一场的集锦，绝不靠标题猜。"""
    sm = re.search(r"(\d{1,2})\s*[-:：比]\s*(\d{1,2})", title)
    if not sm:
        return None
    score = sm.group(1) + "-" + sm.group(2)
    rev = sm.group(2) + "-" + sm.group(1)

    def hit(name):
        return any(len(v) >= 2 and v in title for v in team_variants(name or ""))

    for r in rows:
        s = r.get("score") or ""
        if s != score and s != rev:
            continue
        if hit(r.get("home")) and hit(r.get("away")):
            return r
    return None


def bili_clip(v, r):
    """生成一段可站内嵌入播放的 B 站官方集锦，赛果字段全部继承官方比赛页。"""
    bvid = v.get("bvid") or ""
    t = bili_title(v)
    return {
        "section": "clip", "video_status": "embed", "provider": "bilibili",
        "bvid": bvid, "embed": BILI_PLAYER_TPL % bvid,
        "page_url": "https://www.bilibili.com/video/" + bvid,
        "play": "", "video": "",
        "title": t, "headline": t,
        "author": v.get("author") or "B 站官方账号",
        "comp": r.get("comp") or "比赛集锦", "round": r.get("round") or "",
        "league": r.get("league") or "", "score": r.get("score") or "",
        "teams": r.get("teams") or "", "team_list": r.get("team_list") or [],
        "home": r.get("home") or "", "away": r.get("away") or "",
        "date": (match_date_key(r) or "")[5:] or r.get("date") or "",
        "kickoff": r.get("kickoff") or "", "duration": bili_duration(v),
        "img": abs_url(v.get("pic") or "") or r.get("img") or "",
        "logos": r.get("logos") or [], "url": r.get("url") or "",
        "order_ok": True, "source": "B 站官方比赛集锦 · 站内嵌入播放",
        "published": (datetime.fromtimestamp(v["pubdate"]).strftime("%Y-%m-%d %H:%M")
                      if v.get("pubdate") else ""),
    }


def fetch_bili_clips(rows):
    """检索 B 站 11/5 之后的官方比赛集锦，逐条对齐到正赛赛果。"""
    if not rows:
        return []
    pool, fail = {}, 0
    for kw in BILI_KEYWORDS:
        try:
            got = bili_search(kw, 1)
        except Exception:
            fail += 1
            got = []
        for v in got:
            bv = v.get("bvid")
            if bv:
                pool.setdefault(bv, v)
        time.sleep(0.5)
        # B 站风控会直接返回 412；连续失败就停手，交给存档兜底，别继续空打
        if fail >= 3:
            break
    print("  B 站检索：%d 段候选（%d 次请求失败%s）"
          % (len(pool), fail, "，触发风控，本次改用存档" if fail >= 3 else ""))

    def pick_best():
        top = {}
        for v in pool.values():
            t = bili_title(v)
            # 官方账号的「【意甲】佛罗伦萨2-2尤文图斯」这类标题不带「集锦」二字，
            # 但确实是官方全场集锦；非官方标题则必须写明集锦 / 全场 / 精华 / 高光。
            good = (any(g in t for g in BILI_GOOD)
                    or (bili_official(v)
                        and re.search(r"\d{1,2}\s*[-:：]\s*\d{1,2}", t)))
            if not good or any(b in t for b in BILI_BAD):
                continue
            r = bili_match(t, rows)
            if not r or r.get("league") not in MATCH_LEAGUES:
                continue
            k = (r.get("home"), r.get("away"), r.get("score"))
            rank = (bili_official(v),
                    1 if ("全场集锦" in t or "比赛集锦" in t) else 0,
                    v.get("pubdate") or 0)
            if k not in top or rank > top[k][0]:
                top[k] = (rank, v, r)
        return top

    best = pick_best()
    # 宽搜没覆盖到的场次，再按「主队 客队 集锦」补一轮，尽量覆盖法甲 / 德甲
    rest = [r for r in rows
            if (r.get("home"), r.get("away"), r.get("score")) not in best]
    # 按联赛交错补搜，别让英超 / 欧冠把名额占满，法甲 / 德甲也要覆盖到
    by_lg = {lg: [r for r in rest if r.get("league") == lg]
             for lg in MATCH_LEAGUES}
    todo = []
    for i in range(12):
        for lg in MATCH_LEAGUES:
            if i < len(by_lg[lg]):
                todo.append(by_lg[lg][i])
    todo = todo[:12]
    added = 0
    for r in todo:
        if fail >= 3:
            break
        kw = "%s %s 集锦" % (r.get("home") or "", r.get("away") or "")
        try:
            got = bili_search(kw, 1)
        except Exception:
            fail += 1
            time.sleep(0.5)
            continue
        for v in got:
            bv = v.get("bvid")
            if bv and bv not in pool:
                pool[bv] = v
                added += 1
        time.sleep(0.5)
    print("  按对阵补搜：%d 场 · 新增 %d 段候选" % (len(todo), added))
    best = pick_best()
    clips = [bili_clip(v, r) for _, v, r in best.values()]
    clips.sort(key=lambda c: (c.get("kickoff") or "", c.get("published") or ""),
               reverse=True)
    clips = clips[:BILI_MAX_CLIPS]
    off = sum(1 for _, v, _ in best.values() if bili_official(v))
    print("  B 站集锦：%d 场对齐到正赛赛果（官方账号 %d 段）" % (len(clips), off))
    return clips


def load_bili_seed(rows):
    """B 站接口 412 风控时的兜底：把已复验可播的官方集锦对齐到正赛赛果。"""
    try:
        with open(BILI_SEED, "r", encoding="utf-8") as f:
            seeds = json.load(f).get("clips") or []
    except Exception:
        return []
    best = {}
    for s in seeds:
        t = clean(s.get("title") or "")
        r = bili_match(t, rows)
        if not r or r.get("league") not in MATCH_LEAGUES:
            continue
        k = (r.get("home"), r.get("away"), r.get("score"))
        rank = 1 if any(x in (s.get("author") or "") for x in BILI_OFFICIAL) else 0
        if k not in best or rank > best[k][0]:
            best[k] = (rank, s, r)
    out = []
    for _, s, r in best.values():
        v = {"bvid": s.get("bvid") or "", "title": clean(s.get("title") or ""),
             "author": s.get("author") or "", "pubdate": 0,
             "pic": "", "duration": ""}
        c = bili_clip(v, r)
        c["source"] = "B 站官方比赛集锦 · 存档复验"
        out.append(c)
    return out


def fetch_migu_index(rows, mrows=None):
    """把带比分的咪咕官方全场集锦按「比分 + 两队名」回挂到正赛赛果。

    mrows 由 migu_clips 抓一次后传入，避免同一轮重复请求官方接口。
    """
    mrows = mrows if mrows is not None else migu_clips.fetch_migu_clips(nations_window_active())
    found = {}
    for mc in mrows:
        if not mc.get("score"):
            continue
        r = bili_match(mc["title"], rows)
        if r:
            found[(r.get("home"), r.get("away"), r.get("score"))] = {
                "title": mc["title"], "published": mc["published"],
                "duration": mc.get("duration") or "",
                "cont_id": mc["cont_id"], "page_url": mc["page_url"],
                "source": "咪咕体育官方集锦",
            }
    print("  咪咕体育：%d 段带比分的官方集锦已回挂到正赛赛果（原站播放入口）"
          % len(found))
    return found


def is_embed(url):
    """已停用：B 站嵌入播放器实测全黑，本站不再接受任何第三方 iframe。

    留一个恒 False 的守卫，确保 merge_clips / previous_highlights 即使读到
    旧快照里残留的 embed 条目，也不会把它们带回赛果集锦区。
    """
    return False


def clip_key(x):
    return (x.get("provider") or "vod") + ":" + (
        x.get("bvid") or x.get("play") or x.get("url") or "")


def video_path(href):
    href = (href or "").strip()
    if href.startswith("http://"):
        return "https://" + href[7:]
    if href.startswith("https://"):
        return href
    if href.startswith("/"):
        return VIDEO_HOST + href
    if href.startswith("2026/"):
        return VIDEO_HOST + "/zuqiu/" + href
    return VIDEO_HOST + "/zuqiu/2026/" + href


def parse_highlight(title):
    """解析真实集锦标题里的赛事 / 比分 / 队名；解析不出来就留空，不猜。"""
    body = re.sub(r"^\s*[\[【](?:进球)?集锦[\]】]\s*", "", title).strip()
    comp = ""
    m = re.match(r"^([^\-—]{2,12})\s*[-—]\s*", body)
    if m:
        comp = m.group(1).strip()
        body = body[m.end():]
    sm = re.search(r"(\d{1,2})\s*[-:：]\s*(\d{1,2})", body)
    score = (sm.group(1) + "-" + sm.group(2)) if sm else ""
    found = []
    for name in TEAM_NAMES:
        if name in body and name not in found:
            found.append(name)
    # 「巴黎」被「巴黎圣日耳曼」包含时只保留长名
    found = [n for n in found if not any(n != o and n in o for o in found)]
    # 按标题中出现的先后排序，保证队名顺序与比分对应（不能用词典顺序）
    found.sort(key=lambda n: body.find(n))
    return {
        "comp": comp or "比赛集锦",
        "score": score,
        "team_list": found,
        "teams": " vs ".join(found[:2]) if len(found) >= 2 else (found[0] if found else ""),
        "headline": body,
    }


def fetch_video_list():
    """抓视频频道两页，只保留标题里带真实比分的『比赛集锦』（排除球员个人集锦）。"""
    found = {}
    for url in VIDEO_URLS:
        try:
            page = get(url, timeout=25)
        except Exception as exc:
            print("  [警告] 视频列表页抓取失败 %s: %s" % (url, exc))
            continue
        for href, raw in re.findall(
            r'<a[^>]+href="([^"]*svideo\.htm)"[^>]*>(.*?)</a>', page, re.S
        ):
            title = clean(raw)
            if not title or "集锦" not in title or "个人集锦" in title:
                continue
            if not re.search(r"\d{1,2}\s*[-:：]\s*\d{1,2}", title):
                continue
            path = video_path(href)
            if path in found:
                continue
            d = re.search(r"/(\d{4})-", path)
            found[path] = {"url": path, "title": title, "date": d.group(1) if d else ""}
    return list(found.values())


def fetch_video_detail(e):
    """取详情页里官方 VOD 播放地址 / 封面 / 时长；拿不到就丢弃这条。"""
    try:
        page = get(e["url"], timeout=15)
        v = re.search(r'video_url:\s*"([^"]+)"', page)
        if not v:
            return None
        video = v.group(1).replace("&amp;", "&")
        if not VOD_RE.match(video):   # 只认官方 VOD 域名，防止外站/注入
            return None
        img = re.search(r'class="thumb_img"[^>]+src="([^"]+)"', page)
        dur = re.search(r'class="video_time">([^<]+)<', page)
        info = parse_highlight(e["title"])
        return {
            "title": e["title"],
            "comp": info["comp"],
            "score": info["score"],
            "teams": info["teams"],
            "team_list": info["team_list"],
            "headline": info["headline"],
            "league": classify(e["title"]) or "其他赛事",
            "img": abs_url(img.group(1)) if img else "",
            "duration": dur.group(1).strip() if dur else "",
            "video": video,
            "url": e["url"],
            "date": (e["date"][:2] + "-" + e["date"][2:]) if len(e["date"]) == 4 else "",
            "source": "直播吧 · 官方比赛集锦",
        }
    except Exception:
        return None


def fetch_highlights():
    raw = fetch_video_list()
    if not raw:
        return []
    # 五大联赛 / 欧冠相关优先，其次按 MMDD 倒序
    raw.sort(key=lambda e: (1 if classify(e["title"]) else 0, e["date"]), reverse=True)
    picked = raw[:MAX_HIGHLIGHTS]
    out = [None] * len(picked)
    with ThreadPoolExecutor(max_workers=8) as pool:
        futs = {pool.submit(fetch_video_detail, e): i for i, e in enumerate(picked)}
        for fut in as_completed(futs):
            out[futs[fut]] = fut.result()
    res = [x for x in out if x]
    # 同一场比赛可能有两个详情页地址（其中一个已失效），按标题去重
    seen, uniq = set(), []
    for x in res:
        if x["title"] in seen:
            continue
        seen.add(x["title"])
        uniq.append(x)
    # 范围：只要五大联赛 + 欧冠相关比赛。中甲/中冠/亚冠/美职联/沙特联/足协杯等一律不收。
    # classify() 用球队名判定；联赛杯、德国杯由五大联赛球队参赛，归入对应联赛保留。
    scoped = [x for x in uniq if x["league"] in LEAGUES]
    if len(uniq) > len(scoped):
        print("  范围过滤：剔除 %d 段不在当前收录范围的比赛（国际比赛日窗口另收欧国联）"
              % (len(uniq) - len(scoped)))
    for i, x in enumerate(scoped, 1):
        x["id"] = "m" + str(i)
    return scoped


def load_fragment_clips():
    """已停用：零散片段按用户要求删除，恒返回空，定时更新不会把片段读回来。"""
    return []


def fragment_league(title):
    """片段标题未必写联赛名，用队名关键词归到五大联赛 / 欧冠。"""
    lg = classify(title)
    if lg:
        return lg
    for name in MATCH_LEAGUES:
        if any(k in title for k in KEYWORDS.get(name, [])):
            return name
    return "五大联赛"


def fetch_fragment_clips():
    """已停用：不再抓「进球实拍 / 扑救 / 现场镜头」零散比赛画面片段。

    用户明确要求删掉这几段片段：它们不是一场比赛的完整集锦。当前赛果集锦区
    只收咪咕体育官方完整集锦，见 collect_highlights()。
    """
    return []

# ---------- 四类正赛赛果（官方集锦页 / 全场录像页） ----------
# 这两类页面没有可内嵌的 mp4（官方集锦在咪咕），但有权威的真实赛果。
# 只记录源站给出的轮次 / 主客队 / 比分 / 开球时间 / 队徽 / 封面，不生成任何视频。

def mobile_url(u):
    return re.sub(r"^https?://www\.zhibo8\.com", MOBILE_HOST, u or "")


def get_mobile(url, timeout=18):
    hdr = dict(HEADERS)
    hdr["User-Agent"] = (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1"
    )
    req = urllib.request.Request(url, headers=hdr)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "replace")


def match_path(href):
    href = (href or "").strip()
    if href.startswith("//"):
        return "https:" + href
    if href.startswith("http://"):
        return "https://" + href[7:]
    if href.startswith("https://"):
        return href
    if href.startswith("/"):
        return VIDEO_HOST + href
    return VIDEO_HOST + "/zuqiu/2026/" + href


def fetch_match_list():
    """收集官方比赛集锦页 / 全场录像页，按比赛 id 去重（同一场两页只留一次）。"""
    found = {}
    for url in MATCH_LIST_URLS:
        try:
            page = get(url, timeout=25)
        except Exception as exc:
            print("  [警告] 赛果列表页抓取失败 %s: %s" % (url.split("/")[-1], exc))
            continue
        for href, raw in re.findall(
            r'<a[^>]+href="([^"]+-(?:jijin|luxiang)\.htm)"[^>]*>(.*?)</a>', page, re.S
        ):
            title = clean(raw)
            if len(title) < 8:
                continue
            path = match_path(href)
            mid = re.search(r"match(\d+)v", path)
            key = mid.group(1) if mid else path
            is_jijin = "-jijin.htm" in path
            old = found.get(key)
            if old and (old["jijin"] or not is_jijin):
                continue
            found[key] = {"url": path, "title": title, "jijin": is_jijin}
        print("  赛果列表 %s -> 累计 %d 场" % (
            url.split("/")[-1] or "首页", len(found)), flush=True)
    return list(found.values())


def set_nations_window(value):
    """--nations-league / 源站近期欧国联比赛可强制开启窗口。"""
    global _NATIONS_WINDOW
    _NATIONS_WINDOW = bool(value)


def nations_window_active():
    """当前是否额外收录欧国联。"""
    if _NATIONS_WINDOW is not None:
        return _NATIONS_WINDOW
    return migu_clips.is_international_window()


def active_leagues(window=None):
    """国际比赛日只收欧洲国家队比赛；窗口结束回到五大联赛 / 欧冠的抓取口径
    （只抓窗口结束后新打的比赛，不回灌窗口之前缓存的俱乐部集锦 / 赛果）。"""
    window = nations_window_active() if window is None else window
    return [NATIONS_LEAGUE] if window else list(MATCH_LEAGUES)


def current_mode():
    return "international" if nations_window_active() else "club"


def is_euro_item(x):
    """判断一条赛果 / 集锦是否属于欧洲国家队比赛（不靠新闻标题，避免误判）。"""
    if x.get("content_mode") == "international":
        return True
    text = " ".join(str(x.get(k) or "") for k in ("league", "round", "comp"))
    return migu_clips.is_nations_title(text)


def is_mode_item(x, mode=None):
    mode = mode or current_mode()
    return is_euro_item(x) if mode == "international" else not is_euro_item(x)


def recent_nations_match(raw):
    """源站是否出现 7 天内、且过了清场下限的欧洲国家队比赛。

    luxiang.htm 有几万条历史录像，不能让旧比赛把窗口常年打开；只看近 7 天。
    更关键的是：国际比赛日结束后源站还挂着上一窗口的欧国联录像，这些旧比赛
    绝不能把模式自动翻回「国际比赛日」（用户要求窗口后不要国际比赛日的比赛）。
    所以下限取 effective_min_date()，只有窗口结束后真正新打的欧洲比赛才可能
    触发数据驱动开窗（日历表没维护到未来时的兜底仍然保留）。
    """
    today = datetime.now().date()
    floor = effective_min_date()
    for e in raw:
        text = (e.get("title") or "") + " " + (e.get("url") or "")
        if not migu_clips.is_nations_title(text):
            continue
        k = match_date_key({"url": e.get("url") or ""})
        if not k or k < floor:
            continue
        try:
            d = datetime.strptime(k, "%Y-%m-%d").date()
        except ValueError:
            continue
        if 0 <= (today - d).days <= 7:
            return True
    return False


def team_variants(name):
    """官方全称 + 常见简称，仅用于把标题里的比分顺序对齐到主客队。"""
    out = [name]
    for full, als in TEAM_ALIASES.items():
        if name == full or name in als or full in name:
            out.append(full)
            out.extend(als)
    return [v for v in dict.fromkeys(out) if v]


def last_pos(text, name):
    best = -1
    for v in team_variants(name):
        p = text.rfind(v)
        if p > best:
            best = p
    return best


def first_pos(text, name):
    best = 10 ** 6
    for v in team_variants(name):
        p = text.find(v)
        if 0 <= p < best:
            best = p
    return -1 if best == 10 ** 6 else best


def align_score(before, after, home, away, x, y):
    """标题里的比分是叙述顺序（常把客队写在前面），按主客队重排。

    只有「比分前的队名」与「比分后的队名」能分别对应上主/客队时才重排；
    对不上就退回官方标题原序，绝不猜测谁赢。
    """
    ph, pa = last_pos(before, home), last_pos(before, away)
    qh, qa = first_pos(after, home), first_pos(after, away)
    a = "home" if ph >= 0 and ph > pa else ("away" if pa >= 0 and pa > ph else "")
    b = "home" if qh >= 0 and (qa < 0 or qh <= qa) else ("away" if qa >= 0 else "")
    if a == "home" and b == "away":
        return x + "-" + y, home + " vs " + away, True
    if a == "away" and b == "home":
        return y + "-" + x, home + " vs " + away, True
    return x + "-" + y, "", False


def fetch_match_detail(e):
    """解析官方赛果页：轮次 / 主客队 / 队徽 / 开球时间 / 封面 / 真实比分。"""
    try:
        page = get_mobile(mobile_url(e["url"]))
    except Exception:
        return None

    def one(pat, default=""):
        m = re.search(pat, page, re.S)
        return clean(m.group(1)) if m else default

    rnd = one(r'<h2 class="title[^"]*">([^<]+)</h2>')
    if nations_window_active():
        # 国际比赛日：轮次必须是欧洲国家队赛事，俱乐部联赛一律不进两个区域
        if not migu_clips.is_euro_nations(rnd + " " + (e.get("title") or "")):
            return None
        lg = migu_clips.euro_league_of(rnd + " " + (e.get("title") or ""))
    else:
        lg = ""
        for name in MATCH_LEAGUES:
            if rnd.startswith(name):   # 轮次标题是权威判据：欧联杯 / 英超 / 德甲等一律排除
                lg = name
                break
        if not lg:
            return None
    h1 = one(r'<h1 class="t-tlt">([^<]+)</h1>') or e["title"]
    sm = re.search(r"(\d{1,2})\s*[-:：]\s*(\d{1,2})", h1)
    if not sm:
        return None
    names = [clean(x) for x in re.findall(r'<div class="team-name">([^<]+)</div>', page)]
    if len(names) < 2:
        return None
    home, away = names[0], names[1]
    logos = re.findall(r'https?://duihui\.duoduocdn\.com/zuqiu/[^"\']+\.png', page)[:2]
    imgs = re.findall(r'(?:https?:)?//tu\.duoduocdn\.com/v/img/[^"\']+\.(?:jpg|png)', page)
    img = abs_url(imgs[0]) if imgs else ""
    kickoff = one(r'id="period_cn">([^<]+)<')
    pub = one(r'class="t-time">([^<]+)<')
    dm = re.search(r"(\d{4})-(\d{2})-(\d{2})", kickoff or pub)
    date = (dm.group(2) + "-" + dm.group(3)) if dm else ""

    score, teams, ok = align_score(
        h1[:sm.start()], h1[sm.end():], home, away, sm.group(1), sm.group(2))
    return {
        "title": h1,
        "headline": h1,
        "comp": rnd,
        "round": rnd,
        "score": score,
        "teams": teams,                       # 顺序确定才写，否则用官方标题原序
        "team_list": [home, away],
        "home": home,
        "away": away,
        "logos": logos if ok and len(logos) >= 2 else [],
        "league": lg,
        "img": img,
        "duration": "",
        "video": "",                          # 源站无站内可播地址，绝不伪造
        "play": "",
        "url": e["url"],
        "date": date,
        "kickoff": kickoff,
        "order_ok": ok,
        "video_status": "migu",               # 官方集锦为咪咕版权内容，本站不内嵌
        "source": "直播吧 · 官方比赛赛果",
    }


def safe_match_detail(e):
    """单个页面解析异常不能拖垮整批赛果。"""
    try:
        return fetch_match_detail(e)
    except Exception:
        return None


def match_date_key(x):
    """把比赛日期统一成 YYYY-MM-DD，用于滚动窗口门槛。

    优先用官方开球时间 / 发布时间，其次 MM-DD，最后从详情页 URL 的
    /2026/1108- 兜底；三者都取不到就返回空串（会被门槛剔除，绝不把
    日期不明的旧比赛混进来）。

    MM-DD 缺年份时不能写死年份：跨年时（例如 2027 年 1 月看到 12-27）
    拼成当年会变成「未来的比赛」而绕过门槛，所以按「不晚于明天」回推年份。
    """
    for field in ("kickoff", "published"):
        m = re.search(r"\d{4}-\d{2}-\d{2}", (x.get(field) or "").strip())
        if m:
            return m.group(0)
    d = (x.get("date") or "").strip()
    m = re.search(r"(\d{1,2})-(\d{1,2})", d)
    if m:
        today = datetime.now().date()
        limit = today + timedelta(days=1)
        for y in (today.year, today.year - 1):
            try:
                cand = date(y, int(m.group(1)), int(m.group(2)))
            except ValueError:
                continue
            if cand <= limit:
                return cand.isoformat()
        return ""
    m = re.search(r"/(20\d{2})/(\d{2})(\d{2})-", x.get("url") or "")
    if m:
        return "%s-%s-%s" % (m.group(1), m.group(2), m.group(3))
    return ""


def within_date(x):
    """滚动门槛 + 国际比赛日后清场下限，取更严的那个。

    窗口结束后 effective_min_date() 会抬到窗口结束次日，窗口内的欧洲比赛与
    窗口前的俱乐部集锦 / 赛果会一起被挡在外面，不会从旧快照里回灌。
    """
    k = match_date_key(x)
    return bool(k) and k >= effective_min_date()


def is_playable(url):
    """只认腾讯云 VOD 的 mp4 直链，和前端 safeVideo() 的白名单保持一致。"""
    return bool(re.match(r"^https://[\w.-]*vod2\.myqcloud\.com/[\w./-]+\.mp4$", url or ""))


def load_archive_clips():
    """源站视频列表轮换后下架、但 H.264 直链仍可播的往期官方集锦。

    超出滚动窗口的存档一律不再展示，这里直接过日期门槛。
    """
    try:
        with open(ARCHIVE_CLIPS, "r", encoding="utf-8") as f:
            rows = json.load(f).get("clips") or []
        return [x for x in rows if is_playable(x.get("play")) and within_date(x)]
    except Exception:
        return []


def merge_clips(groups):
    """按直链 / BV 号去重合并：本次新抓 > 上次成功结果 > 往期存档，绝不覆盖历史。"""
    seen, out = set(), []
    for group in groups:
        for x in group or []:
            # 硬闸：零散比赛画面片段已按用户要求删除，任何来源都不接收
            if x.get("kind") == "fragment" or x.get("comp") == "比赛片段":
                continue
            p = x.get("play") or ""
            e = x.get("embed") or ""
            k = clip_key(x)
            if not (is_playable(p) or is_embed(e)):
                continue
            if not k or k in seen or not within_date(x):
                continue
            seen.add(k)
            y = dict(x)
            y["section"] = "clip"
            if is_embed(e):
                # 官方外链播放器：不写伪造的 mp4，前端改成懒加载 iframe
                y["video_status"] = "embed"
                y["provider"] = y.get("provider") or "bilibili"
                y["play"] = ""
            else:
                y["video_status"] = "playable"
            out.append(y)
    return out


def previous_highlights(kind, mode=None):
    """读上一次成功写入的数据：本次抓取失败时沿用，避免刷新后内容倒退。

    只沿用与当前窗口模式一致、且过了清场下限的数据：国际比赛日不能把俱乐部
    赛果带回来；窗口结束既不能继续挂着欧洲国家队比赛，也不能回灌窗口之前
    缓存的俱乐部集锦 / 赛果（within_date 会按窗口结束次日一并挡掉）。
    """
    try:
        with open(NEWS_JSON, "r", encoding="utf-8") as f:
            rows = json.load(f).get("highlights") or []
        rows = [x for x in rows if is_mode_item(x, mode)]
        if kind == "matches":
            # 只沿用「真实正赛赛果」：必须有主客队。咪咕集锦条目虽然也带
            # video_status=migu，但 home/away 为空，混进来会被改成 section=result，
            # 导致正赛赛果区出现没有对阵双方的集锦卡片。
            return [x for x in rows
                    if x.get("section") == "result"
                    and x.get("home") and x.get("away")
                    and x.get("order_ok") is not False
                    and within_date(x)]
        # 零散比赛画面片段已按用户要求删除，快照 / 缓存里的片段都不再沿用。
        # 国际比赛日的欧洲集锦只带官方原站入口，用 official_url 判定即可。
        return [x for x in rows
                if (is_playable(x.get("play")) or is_embed(x.get("embed"))
                    or str(x.get("official_url") or "").startswith(
                        "https://sports.iqiyi.com/resource/pcw/play/"))
                and x.get("kind") != "fragment"
                and x.get("section") != "result" and within_date(x)]
    except Exception:
        return []


def fetch_league_matches(raw=None):
    """正赛赛果：平时五大联赛 / 欧冠，国际比赛日全部换成欧洲国家队比赛。"""
    raw = raw if raw is not None else fetch_match_list()
    if not raw:
        return []
    # 数据驱动兜底：源站出现近期欧国联比赛就自动放开窗口，日历表过期也能生效。
    if recent_nations_match(raw):
        set_nations_window(True)
    out = [None] * len(raw)
    with ThreadPoolExecutor(max_workers=10) as pool:
        futs = {pool.submit(safe_match_detail, e): i for i, e in enumerate(raw)}
        for fut in as_completed(futs):
            out[futs[fut]] = fut.result()
    rows = [x for x in out if x]
    buckets = {lg: [] for lg in active_leagues()}
    seen = set()
    for r in rows:
        # 超出滚动窗口的旧比赛一律不进配额，避免占掉英超 10 场名额
        if not within_date(r):
            continue
        # 队名简称对不上时无法确定主客队与比分的对应顺序，宁可不收，也不展示错配比分
        if not r.get("order_ok"):
            continue
        k = (r.get("home"), r.get("away"), r.get("score"))
        if k in seen:      # 同一场比赛可能有集锦页与录像页两个地址
            continue
        seen.add(k)
        r["section"] = "result"
        if nations_window_active():
            r["content_mode"] = "international"
        # 窗口内所有欧洲赛事统一归到一个配额桶，避免细分赛事名把 bucket 撑出 KeyError
        bucket = NATIONS_LEAGUE if nations_window_active() else r["league"]
        if bucket in buckets:
            buckets[bucket].append(r)
    picked, stat = [], []
    for lg in active_leagues():
        cap = (NATIONS_PER_LEAGUE if lg == NATIONS_LEAGUE
               else MATCH_PER_LEAGUE.get(lg, 6))
        arr = sorted(buckets[lg],
                     key=lambda r: (r.get("kickoff") or "", r.get("date") or ""),
                     reverse=True)
        picked.extend(arr[:cap])
        stat.append("%s %d" % (lg, min(len(arr), cap)))
    print("  正赛赛果：%s" % ", ".join(stat))
    return picked


def probe_codec(url):
    """读 mp4 头部 stsd 判断视频编码。

    faststart 文件的 moov 在开头，取前 64KB 足够。720p 档是 hvc1(H.265)，
    Chrome/Edge 默认解不了，会「有声音有时间轴但全黑」——必须排除。
    """
    try:
        hdr = dict(HEADERS)
        hdr["Range"] = "bytes=0-65535"
        req = urllib.request.Request(url, headers=hdr)
        with urllib.request.urlopen(req, timeout=12) as r:
            b = r.read(65536)
        i = b.find(b"stsd")
        seg = b[i:i + 160] if i >= 0 else b""
        if re.search(rb"avc1", seg):
            return "h264"
        if re.search(rb"hvc1|hev1", seg):
            return "h265"
    except Exception:
        pass
    return ""


def resolve_playable(video_url):
    """从控制台播放器地址解出可在浏览器直接播放的 H.264 mp4 直链。"""
    m = re.search(r"/vod-player/(\d+)/(\d+)/", video_url or "")
    if not m:
        return ""
    try:
        api = PLAYINFO_API % (m.group(1), m.group(2))
        req = urllib.request.Request(api, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
        if data.get("code") != 0:
            return ""
        vi = data.get("videoInfo") or {}
        cands = []
        for x in (vi.get("transcodeList") or []):
            u = (x.get("url") or "").replace("http://", "https://")
            if u and MP4_RE.match(u):
                cands.append((x.get("width") or 0, u))
        # 高分辨率优先，但逐档验编码，H.265 直接跳过
        cands.sort(key=lambda t: -t[0])
        for _, u in cands:
            if probe_codec(u) == "h264":
                return u
        # 兜底：原片通常也是 H.264，但动辄数百 MB，放最后
        sv = ((vi.get("sourceVideo") or {}).get("url") or "").replace("http://", "https://")
        if sv and MP4_RE.match(sv) and probe_codec(sv) == "h264":
            return sv
    except Exception:
        pass
    return ""


def attach_playable(hs):
    """并发给每段集锦补 play 字段；解不出就留空，前端明确提示而不是给个黑屏。"""
    if not hs:
        return 0
    def work(h):
        # 咪咕 / 爱奇艺官方集锦只带原站入口，第三方嵌入播放器已停用；都别去解析直链
        if (h.get("video_status") in ("embed", "migu", "official")
                or h.get("provider") in ("migu", "iqiyi")
                or h.get("official_url") or is_embed(h.get("embed"))):
            return 0
        # 已复验的 H.264 直链（含往期存档与上次成功结果）原样保留，别被空 video 覆盖掉
        if is_playable(h.get("play")):
            return 1
        h["play"] = resolve_playable(h.get("video", ""))
        return 1 if h["play"] else 0
    with ThreadPoolExecutor(max_workers=8) as pool:
        return sum(pool.map(work, hs))


def attach_matches(items, hs):
    """给『赛果类』资讯挂对应比赛（可播集锦或正赛赛果），比分 + 队名同时吻合才挂。

    正赛赛果用的是官方全称（如「纽卡斯尔联」），资讯标题常用简称（「纽卡」），
    所以队名比对走 team_variants 的别名表；比分不吻合一律不挂，避免张冠李戴。
    """
    n = 0
    for it in items:
        t = it.get("title", "")
        if it.get("tag") != "赛果" and not re.search(r"\d{1,2}\s*[-:：]\s*\d{1,2}", t):
            continue
        flat = t.replace(" ", "")
        for h in hs:
            if not h.get("score") or h["score"] not in flat:
                continue
            names = []
            for tm in (h.get("team_list") or []):
                names.extend(team_variants(tm))
            if any(len(v) >= 2 and v in t for v in names):
                it["match"] = h["id"]
                n += 1
                break
    return n


def load_payload():
    """读上一次成功写入的数据（用于沿用资讯或赛果）。"""
    try:
        with open(NEWS_JSON, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def parse_stamp(s):
    try:
        return datetime.strptime(s or "", "%Y-%m-%d %H:%M:%S")
    except Exception:
        return None


def matches_stale(old):
    """赛果集锦是否该重新抓了：没数据、没时间戳、或超过间隔天数。"""
    if not (old.get("highlights") or []):
        return True
    # 国际比赛日开始 / 结束时必须立刻重抓：两个区域要整批换内容
    if (old.get("content_mode") or "club") != current_mode():
        return True
    # 窗口结束当天清场下限刚生效：必须重抓一次，把窗口内的欧洲比赛与窗口前
    # 缓存的俱乐部集锦 / 赛果从两个区域彻底清出去（否则会沿用旧快照）。
    if (old.get("post_break_min_date") or "") != POST_BREAK_MIN_DATE:
        return True
    stamp = parse_stamp(old.get("highlights_updated_at") or old.get("updated_at"))
    if stamp is None:
        return True
    # 跨天了：滚动门槛已往后挪一天，必须重抓一次，才能把新一天的比赛补进来
    # （只在跨天后的第一次刷新触发，之后回到正常的 12 小时 / 3 天节奏）。
    if (old.get("match_since") or "") != MIN_MATCH_DATE:
        return True
    # 国际比赛日窗口内每 12 小时补抓一次，新一场欧国联打完就能自动收进来
    limit = (MATCH_WINDOW_MAX_AGE_HOURS * 3600 if nations_window_active()
             else MATCH_MAX_AGE_DAYS * 86400)
    return (datetime.now() - stamp).total_seconds() >= limit


def build_payload(items, highlights, news_stamp=None, highlights_stamp=None,
                  fixtures=None, upcoming_stamp=None):
    for i, it in enumerate(items, 1):
        it["rank"] = i
        it["tag"] = tag_of(it["title"])
    counts = {}
    for it in items:
        counts[it.get("league", "其他")] = counts.get(it.get("league", "其他"), 0) + 1
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return {
        "source": "直播吧足球资讯 · 五大联赛 & 欧冠",
        "source_url": SOURCE_URL,
        "updated_at": now,
        "news_updated_at": news_stamp or now,
        "highlights_updated_at": highlights_stamp or now,
        "highlights_schedule": MATCH_SCHEDULE,
        "match_since": MIN_MATCH_DATE,
        "match_since_label": MIN_MATCH_LABEL,
        "international_window": nations_window_active(),
        "international_windows": migu_clips.international_windows(),
        "content_mode": current_mode(),
        # 窗口结束后两个区域的最早比赛日期；窗口内为空串。前端按同一张窗口表
        # 自己再算一遍，所以某天没发布也不会残留窗口内 / 窗口前的比赛。
        "post_break_min_date": POST_BREAK_MIN_DATE,
        # 旧版会在这里塞「另一种窗口模式」的备用数据供前端跨窗口换回。
        # 按用户要求已彻底停用：窗口结束后不回灌国际比赛日之前的联赛集锦 / 赛果。
        "alt_highlights": [],
        "extra_leagues": [NATIONS_LEAGUE] if nations_window_active() else [],
        "match_leagues": active_leagues(),
        "count": len(items),
        "leagues": counts,
        "items": items,
        "highlights": highlights,
        "highlight_count": len(highlights),
        "clip_count": sum(1 for x in highlights if x.get("section") == "clip"),
        "result_count": sum(1 for x in highlights if x.get("section") == "result"),
        "clip_sources": {
            "migu": sum(1 for x in highlights
                        if x.get("section") == "clip" and x.get("provider") == "migu"),
            "migu_indexed": sum(1 for x in highlights if x.get("migu_clip")),
            "vod": sum(1 for x in highlights
                       if x.get("section") == "clip" and is_playable(x.get("play"))),
        },
        "highlight_url": "https://www.zhibo8.com/zuqiu/",
        # 即将开赛：赛程 + 真实赛前分析。winrate 只在来源站公布时由数据带出；
        # estimate 是本站模型估算，两者字段与前端区块严格分开。
        "upcoming": fixtures or [],
        "upcoming_count": len(fixtures or []),
        "upcoming_updated_at": upcoming_stamp or now,
        "estimate_count": sum(1 for x in (fixtures or []) if x.get("estimate")),
        "official_winrate_count": sum(1 for x in (fixtures or []) if x.get("winrate")),
    }


def safe_inline_json(payload):
    return json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")


def write_json(payload):
    with open(NEWS_JSON, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def inject_html(payload):
    if not os.path.exists(INDEX_HTML):
        return False
    with open(INDEX_HTML, "r", encoding="utf-8") as f:
        html = f.read()
    if START not in html or END not in html:
        print("[警告] index.html 缺少数据标记，跳过注入")
        return False
    block = (
        START + "\n"
        + '<script id="embedded-news" type="application/json">'
        + safe_inline_json(payload)
        + "</script>\n" + END
    )
    new_html, n = re.subn(
        re.escape(START) + r".*?" + re.escape(END),
        lambda _m: block, html, count=1, flags=re.S,
    )
    if n:
        with open(INDEX_HTML, "w", encoding="utf-8") as f:
            f.write(new_html)
    return bool(n)


def collect_highlights():
    """收集两个区域。

    国际比赛日窗口：赛果集锦 + 正赛赛果**全部换成欧洲国家队比赛**，
    俱乐部联赛一条都不留。
    窗口结束后按用户要求不再「恢复」：既不收国际比赛日的比赛，也不回灌窗口
    之前缓存的俱乐部集锦 / 赛果；统一由 effective_min_date() 的清场下限把关，
    只收窗口结束后真正新打的五大联赛 / 欧冠，没有就留空。
    """
    raw = fetch_match_list()
    # 先取正赛赛果：集锦要按「比分 + 两队名」对齐到真实比赛。
    try:
        league_rows = fetch_league_matches(raw)
        if not league_rows:
            league_rows = previous_highlights("matches")
            if league_rows:
                print("  正赛赛果本次未抓到，沿用上次成功抓取的 %d 场" % len(league_rows))
        print("补充正赛赛果：%d 场（%s）" % (
            len(league_rows), "国际比赛日：欧洲国家队比赛"
            if nations_window_active() else "英超 10 场，其余按赛事配额"))
    except Exception as exc:
        print("  [警告] 正赛赛果抓取失败：%s" % exc)
        league_rows = previous_highlights("matches")
        if league_rows:
            print("  已沿用上次成功抓取的 %d 场正赛赛果" % len(league_rows))
    # fetch_league_matches 里若源站出现近期欧洲国家队比赛，会自动翻转窗口，
    # 所以模式要在赛果抓完之后再定，避免集锦与赛果用了两套口径。
    mode = current_mode()
    for r in league_rows:
        r["section"] = "result"

    if mode == "international":
        # 国际比赛日：逐场登记直播吧官方集锦页里本场的完整集锦（爱奇艺体育版权源）
        try:
            clips = euro_clips.fetch_euro_clips(raw, effective_min_date(), league_rows)
        except Exception as exc:
            print("  [警告] 欧洲国家队集锦抓取失败：%s" % exc)
            clips = []
        if not clips:
            clips = previous_highlights("clips", "international")
            if clips:
                print("  已沿用上次登记的 %d 段欧洲国家队全场集锦" % len(clips))
        # 把同一场的官方全场集锦挂到赛果详情，用户在两个区域都能直达本场集锦
        clip_by_mid = {}
        for c in clips:
            mid = euro_clips.match_id(c.get("url") or "")
            if mid:
                clip_by_mid[mid] = c
        for r in league_rows:
            r.pop("migu_clip", None)
            r["video_status"] = "official"
            c = clip_by_mid.get(euro_clips.match_id(r.get("url") or ""))
            if c:
                r["official_clip"] = {
                    "title": c.get("official_title") or c.get("title") or "",
                    "published": c.get("published") or "",
                    "duration": c.get("duration") or "",
                    "page_url": c.get("official_url") or "",
                    "site": c.get("official_site") or "官方站点",
                }
        print("赛果集锦：欧洲国家队官方全场集锦 %d 段（爱奇艺体育原站观看）"
              % len(clips))
    else:
        # 平时：源站自带的「带比分完整集锦」（近期基本为 0）。零散比赛画面片段
        # 已按用户要求删除：不抓 fetch_fragment_clips()、不读存档，
        # merge_clips 里还有一道 kind=fragment 硬闸。
        fresh = []
        try:
            fresh = fetch_highlights()
        except Exception as exc:
            print("  [警告] 集锦抓取失败：%s" % exc)
        vod = merge_clips([fresh])
        # 咪咕体育官方集锦：只带官方原站入口，绝不内嵌会黑屏的播放器
        try:
            mrows = migu_clips.fetch_migu_clips(False)
        except Exception as exc:
            print("  [警告] 咪咕体育集锦抓取失败：%s" % exc)
            mrows = migu_clips.load_migu_clips()
        migu = [migu_clips.as_clip(x) for x in mrows]
        clips = vod + migu
        print("赛果集锦：源站完整集锦 %d 段 · 咪咕官方 %d 段 · 合计 %d 段（零散片段已停用）"
              % (len(vod), len(migu), len(clips)))
        # 带比分的咪咕全场集锦按「比分 + 两队名」回挂到正赛赛果
        try:
            idx = fetch_migu_index(league_rows, mrows)
            for r in league_rows:
                k = (r.get("home"), r.get("away"), r.get("score"))
                r.pop("migu_clip", None)
                if k in idx:
                    r["migu_clip"] = idx[k]
        except Exception as exc:
            print("  [警告] 咪咕集锦回挂失败：%s" % exc)

    # 最后一道统一门槛：旧比赛、以及不属于当前窗口模式的内容一律不落盘。
    merged = clips + league_rows
    dated = [h for h in merged if within_date(h)]
    if len(dated) != len(merged):
        print("  滚动门槛 %s：剔除 %d 场早于该日的比赛"
              % (MIN_MATCH_DATE, len(merged) - len(dated)))
    highlights = [h for h in dated if is_mode_item(h, mode)]
    if len(highlights) != len(dated):
        print("  窗口模式 %s：剔除 %d 条另一模式的比赛"
              % (mode, len(dated) - len(highlights)))
    # 官方集锦用官方视频 ID 生成稳定地址（#/match/migu_<contId>、
    # #/match/euro_<matchId>），每周重抓也不会让收藏 / 地址栏链接失效。
    for i, h in enumerate(highlights, 1):
        hid = str(h.get("id") or "")
        if not (hid.startswith("migu_") or hid.startswith("euro_")):
            h["id"] = "m" + str(i)
    print("两类合计：%d 条（%d 段集锦 + %d 场正赛赛果）" % (
        len(highlights), sum(1 for h in highlights if h.get("section") == "clip"),
        sum(1 for h in highlights if h.get("section") == "result")))
    try:
        playable = attach_playable(highlights)
        print("站内直链完整集锦 %d 段 · 咪咕原站 %d 段 · 欧洲国家队官方入口 %d 段"
              " · 正赛赛果不内嵌播放器"
              % (playable, sum(1 for h in clips if h.get("provider") == "migu"),
                 sum(1 for h in clips if h.get("provider") == "iqiyi")))
    except Exception as exc:
        print("  [警告] 直链解析失败，本次视频不可播：%s" % exc)
    return highlights


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    matches_only = "--matches-only" in argv
    force_matches = "--refresh-matches" in argv
    if "--nations-league" in argv:
        set_nations_window(True)
        print("  国际比赛日：已强制开启欧国联收录")
    t0 = time.time()
    old = load_payload()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 资讯：每次普通刷新都更新；--matches-only 时原样沿用。
    # 赛果集锦：定时任务（--matches-only）或显式 --refresh-matches 才抓；
    #            平时刷新沿用已有结果，只有超过 MATCH_MAX_AGE_DAYS 天才补抓。
    do_news = not matches_only
    do_matches = matches_only or force_matches or matches_stale(old)

    if do_news:
        print("正在抓取直播吧足球资讯...")
        candidates = fetch_list()
        if len(candidates) < 100:
            raise RuntimeError("候选列表只有 %d 条，可能页面结构变了，已放弃写入" % len(candidates))
        picked = pick(candidates)
        if len(picked) < 30:
            raise RuntimeError("筛出的赛事新闻只有 %d 条，太少，已放弃写入" % len(picked))
        print("命中 %d 条，正在抓取详情页..." % len(picked))
        items = [None] * len(picked)
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = {pool.submit(fetch_detail, it): i for i, it in enumerate(picked)}
            for fut in as_completed(futures):
                items[futures[fut]] = fut.result()
        items = [x for x in items if x]
        with_desc = sum(1 for x in items if x.get("desc"))
        with_img = sum(1 for x in items if x.get("img"))
        print("详情完成：%d 条有正文，%d 条有配图" % (with_desc, with_img))
        items.sort(key=lambda x: (x.get("ts") or 0, x.get("date", "")), reverse=True)
        news_stamp = now
    else:
        items = old.get("items") or []
        if not items:
            raise RuntimeError("news.json 里没有资讯，无法只更新赛果集锦；请先跑一次完整更新")
        news_stamp = old.get("news_updated_at") or old.get("updated_at") or now
        print("沿用现有 %d 条资讯（本次只更新赛果集锦）" % len(items))

    if do_matches:
        print("正在抓取赛果集锦（也可手动 --refresh-matches 强制重抓）...")
        highlights = collect_highlights()
        if not highlights and old.get("highlights"):
            keep = [h for h in old["highlights"]
                    if within_date(h) and is_mode_item(h)]
            if keep:
                highlights = keep
                print("  本次赛果集锦抓取为空，沿用上次成功结果（已按日期与窗口模式过滤）")
        highlights_stamp = now
        print("赛果集锦已重新抓取：%d 场" % len(highlights))
    else:
        # 普通刷新沿用上次结果时也要过日期门槛与窗口模式，不能把旧比赛带回来
        highlights = [h for h in (old.get("highlights") or [])
                      if within_date(h) and is_mode_item(h)]
        highlights_stamp = old.get("highlights_updated_at") or old.get("updated_at") or now
        print("赛果集锦沿用上次结果：%d 场（更新于 %s，已按日期与窗口模式过滤）" % (
            len(highlights), highlights_stamp))

    # 旧版会把「另一种窗口模式」的数据写进 alt_highlights，供前端在跨窗口那天
    # 整批换回（窗口结束后自动恢复俱乐部集锦 / 赛果）。按用户要求已彻底停用：
    # 国际比赛日过后不展示国际比赛日的比赛，也不回灌窗口之前的联赛数据。
    # 两个区域只保留符合当前窗口与清场下限的内容，没有新比赛就如实留空。
    if POST_BREAK_MIN_DATE:
        print("国际比赛日已结束：清场下限 %s，两个区域不展示窗口内 / 窗口前的比赛"
              % POST_BREAK_MIN_DATE)

    # 赛果 id 可能重新编号，关联关系每次重算，避免指向旧编号
    for it in items:
        it.pop("match", None)
    linked = attach_matches(items, highlights)
    print("赛果关联：%d 条资讯匹配到对应比赛集锦" % linked)

    # 即将开赛：赛程按小时变化，每次刷新都重抓；失败沿用上次结果并剔除已开球的场次
    try:
        print("正在抓取即将开赛赛程、真实赛前报道，查三家来源是否公布本场胜率，"
              "并按官方近期战绩计算可核实的本站模型估算...")
        fixtures = upcoming.fetch_upcoming()
        fx_stamp = now
    except Exception as exc:
        print("  [警告] 即将开赛抓取失败，沿用上次结果：%s" % exc)
        fixtures = [x for x in (old.get("upcoming") or [])
                    if x.get("kickoff", "") >= datetime.now().strftime("%Y-%m-%d %H:%M")]
        fx_stamp = old.get("upcoming_updated_at") or old.get("updated_at") or now

    payload = build_payload(items, highlights, news_stamp, highlights_stamp,
                            fixtures, fx_stamp)
    write_json(payload)
    injected = inject_html(payload)
    print("完成：%d 条资讯 + %d 段集锦 + %d 场即将开赛 · 耗时 %.1fs"
          % (len(items), len(highlights), len(fixtures), time.time() - t0))
    print("赛事分布：%s" % ", ".join("%s %d" % (k, v) for k, v in payload["leagues"].items()))
    print("最新一条：%s（%s）" % (items[0]["title"], items[0].get("time", "")))
    print("已写 news.json；" + ("已注入 index.html" if injected else "未找到 index.html，仅写 json"))
    # 离线单文件跟着数据一起重建，避免安装弹窗里的「下载离线版」给到旧快照
    if injected:
        try:
            import build_offline
            build_offline.build()
        except Exception as exc:
            print("[警告] 离线单文件重建失败（不影响站内数据）：%s" % exc)
    return payload


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("[失败] %s: %s" % (type(exc).__name__, exc))
        print("数据未改动，页面仍显示上一次成功抓取的内容。")
        sys.exit(1)
