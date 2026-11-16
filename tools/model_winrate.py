# -*- coding: utf-8 -*-
"""「本站模型估算」模块 —— 与「来源站公布的官方胜率」严格分离。

这一块是**估算**，不是任何机构公布的事实数据。页面上必须单独成块、
明确标注性质，并可由用户一键关闭；绝不能混进 winrate（官方胜率）字段。

------------------------------------------------------------------
数据输入（全部可核实，来自直播吧比赛页「赛前数据」官方接口）
------------------------------------------------------------------
  https://data.qiumibao.com/pre_match_data/v1/{开球日期}/{比赛id}.htm
  - type=recent : 本场两队各近 6 场真实赛果（赛事 / 日期 / 主队 / 比分 / 客队）
  - type=points : 本赛事官方积分榜（已赛 / 胜平负 / 进失球），只作对照展示，不参与计算
  - type=vs     : 两队交锋历史，只作对照展示，不参与计算
接口地址由直播吧比赛页脚本 ft_js0222.v5.js 给出，不是本站臆造。

------------------------------------------------------------------
模型：等权近 N 场泊松进球模型，无拟合参数、无外部经验系数
------------------------------------------------------------------
  1) 汇总两队近期比赛（按「日期 + 主队 + 客队 + 比分」去重），得到样本内
     主队场均进球 mu_h、客队场均进球 mu_a，以及全体球队每场平均进球 base。
     mu_h / mu_a 已经天然包含了主场效应，不再额外叠加任何主场系数。
  2) 每队强度按固定规则向样本均值折半回归（见下），再由
     lambda_home = mu_h * attack(主) * defence(客)
     lambda_away = mu_a * attack(客) * defence(主)
     得到两队期望进球数。
  3) 联合泊松 P(i,j) = Pois(i;lambda_home) * Pois(j;lambda_away)，i,j = 0..9，
     汇总「主胜 / 平 / 客胜」后按总质量归一化到合计 100.0%。

  小样本收缩：只有 6 场样本时，一场 7:0 会把强度比值放大到近 2 倍，
  乘上对手的失球比值后就会出现 97% / 0% 这种明显失真的结论。因此
  本站使用一条**固定、公开、可复算**的规则：
      attack  = 0.5 + 0.5 * (该队场均进球 / base)
      defence = 0.5 + 0.5 * (该队场均失球 / base)
  即把观测强度与「样本平均水平 1.0」各取一半。它不针对任何比赛调参，
  也不使用赔率、积分榜或交锋史去加权，页面会把系数与逐场比分全部列出。

------------------------------------------------------------------
门槛与克制
------------------------------------------------------------------
  - 两队各至少 4 场有效比分，且去重后样本 >= 8 场，否则不输出任何数字。
  - 接口失败 / 没有赛前数据 / 队名对不上，一律 estimate = None，前端整块不渲染。
  - 每场输入的原始比分随结果一起写入，页面可逐场核对；估算不用赔率、不用竞猜、
    不用任何投票支持率，也不用积分榜或交锋史去「调权重」。
"""
import json
import math
import os
import re
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import paths

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_JSON = paths.ESTIMATE_CACHE

DATA_API = "https://data.qiumibao.com/pre_match_data/v1/%s/%s.htm"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

MIN_GAMES_PER_TEAM = 4     # 每队至少 4 场有效比分
MIN_SAMPLE_GAMES = 8       # 去重后合计至少 8 场
MAX_GOALS = 9              # 泊松联合分布截断到 9 球
SHRINK = 0.5               # 强度向样本均值折半回归的固定系数（公开、可复算）

METHOD = "等权近 6 场泊松进球模型（含固定小样本收缩，无拟合参数）"
SOURCE_NAME = "直播吧比赛页 · 官方赛前数据「最近战绩」"


def _get(url, timeout=20):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Referer": "https://www.zhibo8.com/",
        "Accept-Language": "zh-CN,zh;q=0.9",
    })
    return json.loads(urllib.request.urlopen(req, timeout=timeout)
                      .read().decode("utf-8", "ignore"))


def api_url(fx):
    """从赛程条目推出官方赛前数据接口地址；推不出返回空串。"""
    m = re.search(r"match(\d+)v", fx.get("source_url") or "")
    kick = (fx.get("kickoff") or "")[:10]
    if not m or not re.match(r"^\d{4}-\d{2}-\d{2}$", kick):
        return ""
    return DATA_API % (kick, m.group(1))


def _score(s):
    m = re.match(r"^\s*(\d{1,2})\s*[:：\-]\s*(\d{1,2})\s*$", str(s or ""))
    return (int(m.group(1)), int(m.group(2))) if m else None


def _is_team(name, team):
    """接口队名与赛程队名一般完全一致；留一个包含匹配兜底。"""
    name, team = str(name or "").strip(), str(team or "").strip()
    if not name or not team:
        return False
    return name == team or (len(team) >= 2 and (team in name or name in team))


def _rows(recent, team):
    """取出某队近 N 场的逐场明细，含本队进/失球与主客身份。"""
    out = []
    for block in recent or []:
        if not _is_team(block.get("name"), team):
            continue
        for g in block.get("list") or []:
            sc = _score(g.get("score"))
            if not sc:
                continue
            h, a = sc
            home_name = str(g.get("home_team") or "").strip()
            away_name = str(g.get("visit_team") or "").strip()
            if _is_team(home_name, team):
                gf, ga, venue = h, a, "主"
            elif _is_team(away_name, team):
                gf, ga, venue = a, h, "客"
            else:
                continue
            out.append({
                "date": g.get("date") or "", "league": g.get("league") or "",
                "home": home_name, "score": "%d:%d" % (h, a), "away": away_name,
                "venue": venue, "gf": gf, "ga": ga,
                "key": (g.get("date") or "", home_name, away_name, "%d:%d" % (h, a)),
            })
        break
    return out


def _rates(rows):
    n = len(rows)
    if not n:
        return 0.0, 0.0, 0
    return (sum(r["gf"] for r in rows) / float(n),
            sum(r["ga"] for r in rows) / float(n), n)


def _pmf(k, lam):
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return math.exp(-lam) * (lam ** k) / math.factorial(k)


def _outcome(lh, la):
    ph = [ _pmf(i, lh) for i in range(MAX_GOALS + 1) ]
    pa = [ _pmf(j, la) for j in range(MAX_GOALS + 1) ]
    hw = dw = aw = 0.0
    for i in range(MAX_GOALS + 1):
        for j in range(MAX_GOALS + 1):
            p = ph[i] * pa[j]
            if i > j:
                hw += p
            elif i == j:
                dw += p
            else:
                aw += p
    total = hw + dw + aw
    if total <= 0:
        return None
    vals = [hw / total * 100, dw / total * 100, aw / total * 100]
    vals = [round(v, 1) for v in vals]
    vals[vals.index(max(vals))] = round(vals[vals.index(max(vals))]
                                        + (100.0 - sum(vals)), 1)
    return vals


def compute(recent, fx):
    """纯计算，不发网络请求；便于本地用真实接口数据单独复算。"""
    home, away = fx.get("home"), fx.get("away")
    rh, ra = _rows(recent, home), _rows(recent, away)
    if len(rh) < MIN_GAMES_PER_TEAM or len(ra) < MIN_GAMES_PER_TEAM:
        return None, "近期战绩样本不足（每队需至少 %d 场有效比分）" % MIN_GAMES_PER_TEAM

    # 两队交锋的同一场会在两边各出现一次，按 key 去重后再估主客基准
    sample, seen = [], set()
    for r in rh + ra:
        if r["key"] in seen:
            continue
        seen.add(r["key"])
        sample.append(r)
    if len(sample) < MIN_SAMPLE_GAMES:
        return None, "去重后样本不足 %d 场" % MIN_SAMPLE_GAMES

    hg = sum(int(r["score"].split(":")[0]) for r in sample)
    ag = sum(int(r["score"].split(":")[1]) for r in sample)
    n = float(len(sample))
    mu_h, mu_a = hg / n, ag / n
    base = (mu_h + mu_a) / 2.0
    if base <= 0:
        return None, "样本总进球为 0，无法估计进球强度"

    gfh, gah, nh = _rates(rh)
    gfa, gaa, na = _rates(ra)
    # 固定收缩：观测强度与样本平均水平 1.0 各占一半，避免 6 场小样本放大极端比分
    at_h = SHRINK + (1 - SHRINK) * (gfh / base)
    df_h = SHRINK + (1 - SHRINK) * (gah / base)
    at_a = SHRINK + (1 - SHRINK) * (gfa / base)
    df_a = SHRINK + (1 - SHRINK) * (gaa / base)
    lh = mu_h * at_h * df_a
    la = mu_a * at_a * df_h
    probs = _outcome(lh, la)
    if not probs:
        return None, "进球分布计算失败"
    extreme = max(probs) >= 85 or min(probs) <= 2

    def brief(rows):
        return [{k: r[k] for k in ("date", "league", "home", "score",
                                  "away", "venue", "gf", "ga")} for r in rows]

    return {
        "home": probs[0], "draw": probs[1], "away": probs[2],
        "method": METHOD,
        "source": SOURCE_NAME,
        "source_url": fx.get("source_url") or "",
        "data_url": api_url(fx),
        "lambda_home": round(lh, 3), "lambda_away": round(la, 3),
        "mu_home": round(mu_h, 3), "mu_away": round(mu_a, 3),
        "sample_games": len(sample),
        "home_games": nh, "away_games": na,
        "home_gf": round(gfh, 2), "home_ga": round(gah, 2),
        "away_gf": round(gfa, 2), "away_ga": round(gaa, 2),
        "base": round(base, 3), "shrink": SHRINK,
        "attack_home": round(at_h, 3), "defence_home": round(df_h, 3),
        "attack_away": round(at_a, 3), "defence_away": round(df_a, 3),
        "extreme": extreme,
        "recent_home": brief(rh), "recent_away": brief(ra),
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "formula": "样本：两队近 6 场真实比分去重；mu主/客为样本内主队、客队场均进球，"
                   "base=(mu主+mu客)/2。强度按固定系数 0.5 折半回归：attack=0.5+0.5×(场均进球/base)，"
                   "defence=0.5+0.5×(场均失球/base)。"
                   "λ主=mu主×attack主×defence客，λ客=mu客×attack客×defence主；"
                   "最后对 0–9 球的联合泊松分布汇总胜 / 平 / 负并归一化到 100%。",
        "warning": "这是本站按公开比分算出的模型估算，不是来源站公布的数据，"
                   "不含伤停、首发、赛意与临场信息；样本含不同赛事（含友谊赛）。"
                   + ("本场两队近期强弱差距很大，估算偏极端，请结合下方逐场比分自行判断。" if extreme else "")
                   + "仅供参考，不构成投注建议。",
    }, ""


def build_for_fixture(fx):
    """抓官方赛前数据 → 算估算；任何一步失败都返回 (None, 原因)。"""
    url = api_url(fx)
    if not url:
        return None, "本场没有可核对的直播吧比赛页地址"
    try:
        data = _get(url)
    except Exception as exc:
        return None, "官方赛前数据接口不可达（%s）" % type(exc).__name__
    if data.get("status") != "success":
        return None, "官方赛前数据未返回成功状态"
    groups = data.get("data") or []
    recent = next((g.get("list") for g in groups if g.get("type") == "recent"), None)
    if not recent:
        return None, "来源站没有公布本场两队近期战绩"

    est, reason = compute(recent, fx)
    if not est:
        return None, reason

    # 积分榜 / 交锋史只作对照展示，明确标注「不参与计算」
    pts = next((g.get("data") for g in groups if g.get("type") == "points"), None)
    if isinstance(pts, dict):
        est["official_points"] = [
            {k: p.get(k, "") for k in ("team", "games", "wdl", "goal", "point")}
            for p in (pts.get("all") or []) if isinstance(p, dict)
        ][:4]
    h2h = next((g.get("list") for g in groups if g.get("type") == "vs"), None)
    if h2h:
        est["head_to_head"] = [
            {k: p.get(k, "") for k in ("date", "league", "home_team",
                                       "score", "visit_team")}
            for p in h2h[:3] if isinstance(p, dict)
        ]
    return est, ""


def attach_estimates(fixtures):
    """逐场并发；只写 fx['estimate']，绝不碰 fx['winrate']。"""
    if not fixtures:
        return fixtures
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = {ex.submit(build_for_fixture, fx): fx for fx in fixtures}
        for f in as_completed(futs):
            fx = futs[f]
            try:
                est, reason = f.result()
            except Exception as exc:
                est, reason = None, "估算异常（%s）" % type(exc).__name__
            fx["estimate"] = est
            fx["estimate_status"] = reason
    ok = sum(1 for fx in fixtures if fx.get("estimate"))
    print("  本站模型估算：%d / %d 场有可核实近期战绩，%d 场不输出任何估算数字"
          % (ok, len(fixtures), len(fixtures) - ok))
    for fx in fixtures:
        if not fx.get("estimate"):
            print("    · %s vs %s：%s" % (fx.get("home"), fx.get("away"),
                                         fx.get("estimate_status") or "—"))
    return fixtures


def save_cache(fixtures):
    """把估算明细单独留一份，便于线下复算核对；失败不影响主流程。"""
    try:
        rows = [{"id": x["id"], "home": x["home"], "away": x["away"],
                 "estimate": x.get("estimate"), "status": x.get("estimate_status")}
                for x in fixtures]
        with open(CACHE_JSON, "w", encoding="utf-8") as f:
            json.dump({"updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                       "method": METHOD, "rows": rows}, f, ensure_ascii=False, indent=1)
    except Exception:
        pass


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    import upcoming
    rows = upcoming.load_cached() or []
    if not rows:
        print("upcoming.json 里没有赛程，先跑 python upcoming.py")
    else:
        attach_estimates(rows)
        save_cache(rows)
        for r in rows:
            e = r.get("estimate")
            print(r["kickoff"], r["home"], "vs", r["away"], "|",
                  ("%.1f / %.1f / %.1f" % (e["home"], e["draw"], e["away"]))
                  if e else "不输出：" + (r.get("estimate_status") or ""))
