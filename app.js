/* 今日要闻 · 站内阅读版
 * 所有新闻点击都在本站内打开阅读面板，页面不含任何外部站点跳转。
 * 数据来自 index.html 内嵌的 news 快照（由 update_news.py 写入）。
 */
(function(){
  'use strict';
  var $  = function(s){ return document.querySelector(s); };
  var $$ = function(s){ return Array.prototype.slice.call(document.querySelectorAll(s)); };

  var DATA = {items:[], highlights:[], updated_at:'', count:0, source:'',
              highlights_updated_at:'', highlights_schedule:'',
              match_since:'', match_since_label:'',
              clip_count:0, result_count:0,
              clip_sources:{vod:0, migu:0},
              international_window:false, extra_leagues:[], match_leagues:[],
              upcoming:[], upcoming_count:0, upcoming_updated_at:''};
  try {
    var el = document.getElementById('embedded-news');
    if (el && el.textContent.trim()) DATA = JSON.parse(el.textContent);
  } catch(e){ console.warn('内嵌数据解析失败：', e); }

  /* ---------------- 滚动日期窗口 ----------------
     规则：11/13 不收 11/5，11/14 不收 11/6，11/15 不收 11/7……门槛每天往后挪一天，
     永远只保留「今天 + 往前 7 天」共 8 个自然日。
     后端每次更新会重算门槛；这里在打开页面时按「当天」再算一次，取快照门槛与
     今天推算值里更严的那个，所以即使某天没跑更新、内嵌快照还是昨天的，
     旧比赛也会自动消失，不会等发布才生效。 */
  function pad2(n){ n = Number(n); return n < 10 ? '0'+n : ''+n; }
  function isoDay(d){ return d.getFullYear()+'-'+pad2(d.getMonth()+1)+'-'+pad2(d.getDate()); }
  function rollingSince(){
    var d = new Date(); d.setHours(0,0,0,0); d.setDate(d.getDate()-7);
    return isoDay(d);
  }
  /* ---------------- 国际比赛日结束后的清场下限 ----------------
     用户要求：国际比赛日过后，既不要国际比赛日的比赛，也不要国际比赛日之前
     缓存下来的联赛集锦和赛果。取「最近一个已结束窗口」结束日的次日当下限，
     窗口内与窗口前的比赛（欧国联 + 旧联赛）一起清掉；没有就如实留空，
     等窗口结束后真正新打的五大联赛 / 欧冠自动补上。
     窗口内、或还没有任何已结束窗口时返回 ''，走正常的 8 天滚动窗口。 */
  function nextDay(iso){
    var p = String(iso||'').split('-');
    if (p.length !== 3) return '';
    var d = new Date(Number(p[0]), Number(p[1])-1, Number(p[2]));
    if (isNaN(d.getTime())) return '';
    d.setDate(d.getDate()+1);
    return isoDay(d);
  }
  function postBreakFloor(){
    var day = isoDay(new Date()), ws = DATA.international_windows || [];
    for (var i=0;i<ws.length;i++){
      if (ws[i] && ws[i].length>=2 && day>=ws[i][0] && day<=ws[i][1]) return '';
    }
    var last = '';
    for (var j=0;j<ws.length;j++){
      if (ws[j] && ws[j].length>=2 && ws[j][1] < day && ws[j][1] > last) last = ws[j][1];
    }
    return last ? nextDay(last) : '';
  }
  function sinceLabel(iso){
    var p = String(iso||'').split('-');
    return p.length===3 ? (Number(p[1])+' 月 '+Number(p[2])+' 日起') : '最近 8 天';
  }
  function itemDay(x){
    var s, m;
    s = String(x.kickoff||'');   m = s.match(/\d{4}-\d{2}-\d{2}/); if (m) return m[0];
    s = String(x.published||''); m = s.match(/\d{4}-\d{2}-\d{2}/); if (m) return m[0];
    s = String(x.date||'');      m = s.match(/(\d{1,2})-(\d{1,2})/);
    if (m){
      // MM-DD 没年份：跨年时不能拼成今年，否则 12-27 会变成「未来的比赛」绕过门槛
      var now = new Date(), y = now.getFullYear();
      var mm = pad2(m[1]), dd = pad2(m[2]);
      var tmr = new Date(); tmr.setHours(0,0,0,0); tmr.setDate(tmr.getDate()+1);
      var k = y+'-'+mm+'-'+dd;
      return k > isoDay(tmr) ? (y-1)+'-'+mm+'-'+dd : k;
    }
    s = String(x.url||''); m = s.match(/\/(20\d{2})\/(\d{2})(\d{2})-/);
    if (m) return m[1]+'-'+m[2]+'-'+m[3];
    return '';
  }
  function applyRollingWindow(){
    var floor = rollingSince();
    var stored = String(DATA.match_since||'');
    var post = postBreakFloor();
    // ISO 日期可直接按字典序比较；取更严（更晚）的那个当门槛。
    // 国际比赛日结束后，清场下限会高于 8 天滚动门槛，把窗口内 / 窗口前的
    // 比赛一起挡掉，页面提示里的「X 月 X 日起」也随之变成窗口结束次日。
    var min = stored > floor ? stored : floor;
    if (post > min) min = post;
    function fresh(rows){
      return (rows||[]).filter(function(x){
        var k = itemDay(x); return !!k && k >= min;
      });
    }
    DATA.highlights = fresh(DATA.highlights);
    DATA.alt_highlights = [];
    DATA.post_break_min_date = post;
    DATA.post_break_active = !!post;
    DATA.match_since = min;
    DATA.match_since_label = sinceLabel(min);
    DATA.highlight_count = DATA.highlights.length;
    DATA.clip_count = DATA.highlights.filter(function(x){ return sectionOf(x)==='clip'; }).length;
    DATA.result_count = DATA.highlights.filter(function(x){ return sectionOf(x)==='result'; }).length;
  }

  /* ---------------- 国际比赛日窗口 ----------------
     窗口内「赛果集锦」「正赛赛果」两个区域全部换成欧洲国家队比赛，俱乐部赛事
     一律不显示。窗口结束后按用户要求不再「恢复」：国际比赛日的比赛、以及窗口
     之前缓存的联赛集锦 / 赛果都不再展示，由 applyRollingWindow 的清场下限挡住，
     两个区域如实留空，等窗口结束后新打的五大联赛 / 欧冠自动补上。
     旧版会把另一套数据塞在 alt_highlights 里跨窗口换回，这套回灌已彻底停用。 */
  function inInternationalWindow(){
    var day = isoDay(new Date()), ws = DATA.international_windows || [];
    for (var i=0;i<ws.length;i++){
      if (ws[i] && ws[i].length>=2 && day>=ws[i][0] && day<=ws[i][1]) return true;
    }
    return false;
  }
  function isEuroItem(x){
    if (!x) return false;
    if (x.content_mode === 'international') return true;
    var t = [x.league||'', x.round||'', x.comp||''].join(' ');
    return /欧国联|欧洲国家联赛|国家联赛|欧洲杯|欧预赛|欧洲区预选|欧洲区世预赛|世预赛欧洲区|欧锦赛|Nations League/i.test(t);
  }
  function filterMode(rows, on){
    return (rows||[]).filter(function(x){ return on ? isEuroItem(x) : !isEuroItem(x); });
  }
  function applyInternationalMode(){
    var on = inInternationalWindow(), want = on ? 'international' : 'club';
    // 只按当前快照里的数据做模式过滤，不再从 alt_highlights 换回另一套。
    // 窗口结束时这样会得到空集（欧洲比赛被 filterMode 剔掉），正是用户要的：
    // 不显示国际比赛日的比赛，也不把窗口前的联赛集锦 / 赛果倒回来。
    // 窗口开始时若快照还是上一版俱乐部数据，同样如实留空，等下一次自动发布补上。
    DATA.highlights = filterMode(DATA.highlights || [], on);
    DATA.alt_highlights = [];
    DATA.content_mode = want;
    DATA.international_window = on;
    DATA.extra_leagues = on ? ['欧国联'] : [];
    DATA.match_leagues = on ? ['欧国联']
      : ['英超','欧冠','西甲','意甲','法甲','德甲'];
  }
  applyInternationalMode();
  applyRollingWindow();

  var LS = {
    get:function(k,d){ try{ var v=JSON.parse(localStorage.getItem(k)); return v==null?d:v; }catch(e){ return d; } },
    set:function(k,v){ try{ localStorage.setItem(k,JSON.stringify(v)); }catch(e){} }
  };
  var favs      = LS.get('bd50_fav', {}),
      reads     = LS.get('bd50_read', {}),
      collapsed = LS.get('bd50_drawer', {});

  var state = {
    q:'', cat:'全部', view:'全部', mode:'board', cur:0, matchId:0, fixtureId:0,
    theme: LS.get('bd50_theme','light'),
    // 本站模型估算默认开启，可一键关闭并记住；与来源站公布的官方胜率无关
    showEstimate: LS.get('bd50_estimate_on', true)
  };

  var CAT_ORDER = ['欧冠','英超','西甲','意甲','德甲','法甲','其他足球'];
  // 分类标签只给六大赛事，不再提供「其他」入口（内容与集锦都已按此范围收窄）
  var CHIP_CATS = ['全部','欧冠','英超','西甲','意甲','德甲','法甲'];
  // 顶部 chips 只统计 50 条资讯；欧国联只进「赛果集锦 / 正赛赛果」两个区域，
  // 不占资讯配额，所以这里不加欧国联入口。窗口状态由 mHint / rHint 与卡片标签体现。

  // 赛事由抓取脚本按标题关键词判定并写入 league 字段，前端直接用，不重复猜
  function classify(it){ return it.league || '其他足球'; }
  function esc(s){
    return String(s==null?'':s).replace(/[&<>"']/g, function(c){
      return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];
    });
  }
  function safeImg(u){
    u = String(u||'');
    return /^https?:\/\//i.test(u) ? esc(u) : '';
  }
  function key(it){ return 'k_' + (it.title||'') + '_' + it.rank; }
  function all(){ return DATA.items || []; }
  function highlights(){ return DATA.highlights || []; }
  // 两类数据分属两个区域；老快照没有 section 时按「有没有可播直链」兜底判定
  function sectionOf(m){ return (m && m.section) || (hasClip(m) ? 'clip' : 'result'); }
  function clipsArr(){ return highlights().filter(function(m){ return sectionOf(m)==='clip'; }); }
  function resultsArr(){ return highlights().filter(function(m){ return sectionOf(m)==='result'; }); }
  function fixturesArr(){ return DATA.upcoming || []; }
  function byFixture(id){ var a=fixturesArr(); for (var i=0;i<a.length;i++) if (a[i].id===id) return a[i]; return null; }
  function filteredFixtures(){
    var q = state.q.trim().toLowerCase();
    return fixturesArr().filter(function(f){
      if (state.cat!=='全部' && f.league!==state.cat) return false;
      if (q && ((f.home||'')+' '+(f.away||'')+' '+(f.league||'')+' '+(f.round||'')).toLowerCase().indexOf(q)<0) return false;
      return true;
    });
  }
  function byRank(r){ var a=all(); for (var i=0;i<a.length;i++) if (a[i].rank===r) return a[i]; return null; }
  function byMatch(id){ var a=highlights(); for (var i=0;i<a.length;i++) if (a[i].id===id) return a[i]; return null; }
  // 只放行腾讯云 VOD 的 H.264 mp4 直链，避免把任意地址塞进 <video>
  function safeVideo(u){
    u = String(u||'');
    return /^https:\/\/[\w.-]*vod2\.myqcloud\.com\/[\w./-]+\.mp4$/i.test(u) ? esc(u) : '';
  }
  // 咪咕是版权方：播放列表带签名校验，官方播放器实测也不允许第三方网页嵌入
  // （iframe 里只有 logo / 导航 / 报错）。因此只放行咪咕官方播放页，
  // 作为用户主动点击的「去原站看」入口，绝不在本页塞会黑屏的 iframe。
  function safeMigu(u){
    u = String(u||'');
    return /^https:\/\/www\.miguvideo\.com\/p\/detail\/\d+\/?$/i.test(u) ? esc(u) : '';
  }
  // 国际比赛日的欧洲国家队全场集锦：直播吧官方集锦页列出的爱奇艺体育播放页。
  // 同样是版权方、同样不允许第三方网页嵌入，只给原站入口，不塞黑屏 iframe。
  function safeIqiyi(u){
    u = String(u||'');
    return /^https:\/\/sports\.iqiyi\.com\/resource\/pcw\/play\/[A-Za-z0-9]+\/?$/i.test(u)
      ? esc(u) : '';
  }
  function safeOfficial(u){ return safeMigu(u) || safeIqiyi(u); }
  // 只放行官方来源页 / 官方数据接口的 https 链接；顺带补上旧版 winrateHtml
  // 里引用了但没定义的 safeUrl（此前 0 场有官方胜率，一直没被触发）。
  function safeUrl(u){
    u = String(u||'');
    return /^https:\/\/(?:www\.zhibo8\.com|data\.qiumibao\.com|www\.hupu\.com|www\.dongqiudi\.com)\/[^\s"'<>]*$/i.test(u)
      ? esc(u) : '';
  }
  function toast(msg){
    var t = $('#toast'); t.textContent = msg; t.classList.add('show');
    clearTimeout(t._t); t._t = setTimeout(function(){ t.classList.remove('show'); }, 3000);
  }
  function themeIcon(){
    $('#themeIcon').innerHTML = state.theme==='dark'
      ? '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>'
      : '<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>';
  }
  function applyTheme(){
    document.documentElement.setAttribute('data-theme', state.theme);
    LS.set('bd50_theme', state.theme); themeIcon();
  }

  var I_FAV  = '<svg viewBox="0 0 24 24"><path d="m12 2 3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"/></svg>';
  var I_READ = '<svg viewBox="0 0 24 24"><path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="2.6"/></svg>';

  /* ---------------- 顶部信息 ---------------- */
  function renderHeader(){
    var a = all();
    $('#sCount').innerHTML = (DATA.count||a.length) + '<small>条</small>';
    $('#sHot').textContent = a.length ? (a[0].time || '—') : '—';
    $('#sTime').textContent = DATA.updated_at || '—';
    var nc = clipsArr().length, nr = resultsArr().length;
    $('#clipCount').textContent = nc;
    $('#resultCount').textContent = nr;
    var nf = fixturesArr().length;
    var uc = $('#upcomingCount'); if (uc) uc.textContent = nf;
    $('#clipBanner').hidden = !(nc + nr + nf);
    var cbGo = $('#clipBanner .cb-go');
    if (cbGo) cbGo.textContent = nc ? '查看赛果集锦 →' : '查看正赛赛果 →';
    var d = new Date(), wk = ['日','一','二','三','四','五','六'][d.getDay()];
    $('#hdDate').innerHTML = '<b>'+(d.getMonth()+1)+' 月 '+d.getDate()+' 日</b> · 星期'+wk;
    if (!state.cur) document.title = '今日球报 · 五大联赛与欧冠 50 条';
  }

  /* ---------------- 筛选 ---------------- */
  function filtered(){
    var q = state.q.trim().toLowerCase();
    return all().filter(function(it){
      var k = key(it);
      if (state.cat!=='全部' && classify(it)!==state.cat) return false;
      if (state.view==='已收藏' && !favs[k]) return false;
      if (state.view==='未读' && reads[k]) return false;
      if (q && ((it.title||'')+' '+(it.desc||'')+' '+classify(it)).toLowerCase().indexOf(q)<0) return false;
      return true;
    });
  }
  function isDefault(){ return !state.q.trim() && state.cat==='全部' && state.view==='全部'; }

  function buildChips(){
    var items = all(), counts = {'全部':items.length};
    items.forEach(function(it){ var c=classify(it); counts[c]=(counts[c]||0)+1; });
    var html = '';
    CHIP_CATS.forEach(function(c){
      if (!counts[c] && c!=='全部') return;
      html += '<button class="chip'+(state.cat===c?' on':'')+'" data-type="cat" data-v="'+esc(c)+'">'+esc(c)+'<span class="n">'+counts[c]+'</span></button>';
    });
    html += '<span style="width:1px;height:20px;background:var(--line);margin:4px 4px;flex:none"></span>';
    ['已收藏','未读'].forEach(function(v){
      var n = v==='已收藏' ? Object.keys(favs).length : 0;
      html += '<button class="chip'+(state.view===v?' on':'')+'" data-type="view" data-v="'+v+'">'+v+(n?'<span class="n">'+n+'</span>':'')+'</button>';
    });
    $('#chips').innerHTML = html;
  }

  /* ---------------- 榜单视图 ---------------- */
  function cardMeta(it, cat){
    return '<div class="meta">'
      + '<span class="cat">'+esc(cat)+'</span>'
      + (it.tag ? '<span class="tag">'+esc(it.tag)+'</span>' : '')
      + (it.top ? '<span class="tag">置顶</span>' : '')
      + (it.match && byMatch(it.match)
          ? '<span class="vbadge">'+(hasClip(byMatch(it.match)) ? '▶ 本场集锦' : '▣ 本场赛果')+'</span>' : '')
      + '<span class="hot-n">'+esc(it.time||'')+(it.source?' · '+esc(it.source):'')+'</span></div>';
  }
  function picHtml(it, cls){
    var u = safeImg(it.img);
    return '<div class="'+cls+'">'+(u
      ? '<img loading="lazy" referrerpolicy="no-referrer" src="'+u+'" alt="" onerror="this.parentNode.style.background=\'var(--line-2)\';this.remove()">'
      : '')+'</div>';
  }
  function linkAttrs(it){ return 'href="#/read/'+it.rank+'" data-read="'+it.rank+'"'; }
  function leadHtml(it, cat){
    return '<article class="lead fade">'
      + '<span class="num-badge">NO.'+it.rank+'</span>' + picHtml(it,'pic')
      + '<div class="txt">'+cardMeta(it,cat)
      + '<h3 class="card-title"><a '+linkAttrs(it)+'>'+esc(it.title)+'</a></h3>'
      + '<p class="card-desc">'+esc(it.desc || '这条暂无摘要，点开在站内查看。')+'</p>'
      + '<div class="card-foot"><span>第 '+it.rank+' 位 · 站内阅读</span>'
      + '<a class="go" '+linkAttrs(it)+'>打开阅读 ↗</a></div></div></article>';
  }
  function miniHtml(it, cat){
    return '<article class="mini fade">'
      + '<span class="num-badge">NO.'+it.rank+'</span>' + picHtml(it,'pic')
      + '<div class="txt">'+cardMeta(it,cat)
      + '<h3 class="card-title"><a '+linkAttrs(it)+'>'+esc(it.title)+'</a></h3>'
      + '<p class="card-desc">'+esc(it.desc||'')+'</p>'
      + '<div class="card-foot"><a class="go" '+linkAttrs(it)+'>打开阅读 ↗</a></div></div></article>';
  }
  function rowHtml(it, cat, idx){
    var k = key(it), w = Math.max(10, 100 - (it.rank-1)*1.7);
    var rk = it.rank<=3 ? ' t'+it.rank : '';
    return '<article class="row fade'+(reads[k]?' read':'')+'" data-k="'+esc(k)+'" style="animation-delay:'+Math.min(idx,12)*22+'ms">'
      + '<div class="rk'+rk+'">'+String(it.rank).padStart(2,'0')+'</div>'
      + picHtml(it,'thumb')
      + '<div class="main">'+cardMeta(it,cat)
      + '<h3><a '+linkAttrs(it)+'>'+esc(it.title)+'</a></h3>'
      + (it.desc ? '<p class="desc">'+esc(it.desc)+'</p>' : '')
      + '<div class="bottom"><div class="heat"><i data-w="'+w+'"></i></div>'
      + '<button class="mini-toggle" data-expand="1">展开摘要</button></div></div>'
      + '<div class="tools">'
      + '<button class="tool fav'+(favs[k]?' on':'')+'" data-fav="1" title="收藏">'+I_FAV+'</button>'
      + '<a class="tool" '+linkAttrs(it)+' title="站内阅读">'+I_READ+'</a>'
      + '</div></article>';
  }
  function renderBoard(list){
    var def = isDefault();
    $('#focusWrap').style.display = (def && list.length>=3) ? '' : 'none';
    if (def && list.length>=3){
      $('#focus').innerHTML = leadHtml(list[0],classify(list[0]))
        + '<div class="side">'+miniHtml(list[1],classify(list[1]))+miniHtml(list[2],classify(list[2]))+'</div>';
    }
    var shown = def ? list.slice(3) : list;
    $('#listTitle').textContent = def ? '完整榜单' : '筛选结果';
    $('#listSub').textContent = def
      ? '第 4 – '+all().length+' 位 · 按发布时间排序 · 点击站内阅读'
      : '匹配 '+list.length+' 条 · 按发布时间排序';
    $('#list').innerHTML = shown.map(function(it,i){ return rowHtml(it,classify(it),i); }).join('');
    $('#empty').hidden = shown.length>0;
    $('#shown').textContent = shown.length;
    requestAnimationFrame(function(){
      $$('.heat i').forEach(function(el){ el.style.width = el.dataset.w+'%'; });
    });
  }

  /* ---------------- 收纳柜视图 ---------------- */
  function tileHtml(it){
    var k = key(it);
    return '<div class="tile'+(reads[k]?' read':'')+(favs[k]?' fav':'')+'" data-read="'+it.rank+'">'
      + '<span class="t-rk">'+String(it.rank).padStart(2,'0')+'</span>'
      + '<div class="t-main"><div class="t-title">'+esc(it.title)+'</div>'
      + '<div class="t-sub">'+esc(it.time||'')+(it.tag?' · '+esc(it.tag):'')+' · 站内阅读</div></div>'
      + '<span class="t-star'+(favs[k]?' on':'')+'">'+(favs[k]?'★':'☆')+'</span></div>';
  }
  function renderCabinet(list){
    var groups = {};
    list.forEach(function(it){ var c=classify(it); (groups[c]||(groups[c]=[])).push(it); });
    var order = CAT_ORDER.filter(function(c){ return groups[c] && groups[c].length; });
    var html = order.map(function(c){
      var arr = groups[c];
      return '<section class="drawer'+(collapsed[c]?' collapsed':'')+'">'
        + '<button class="drawer-head" data-toggle="'+esc(c)+'">'
        + '<span class="drawer-dot"></span><span class="drawer-name">'+esc(c)+'</span>'
        + '<span class="drawer-count">'+arr.length+' 条</span>'
        + '<span class="drawer-arrow">▾</span></button>'
        + '<div class="drawer-body">'+arr.map(tileHtml).join('')+'</div></section>';
    }).join('');
    $('#cabinet').innerHTML = html;
    $('#cabEmpty').hidden = order.length>0;
    $('#cabHint').textContent = '共 '+order.length+' 个抽屉 · '+list.length+' 条新闻 · 搜索对柜内同样生效';
  }

  /* ---------------- 赛果 & 官方集锦 ---------------- */
  function filteredSection(arr){
    var q = state.q.trim().toLowerCase();
    return arr.filter(function(m){
      if (state.cat!=='全部' && m.league!==state.cat) return false;
      if (q && ((m.title||'')+' '+(m.teams||'')+' '+(m.comp||'')+' '+(m.round||'')
                +' '+(m.home||'')+' '+(m.away||'')+' '+(m.league||'')
                +' '+(m.score||'')).toLowerCase().indexOf(q)<0) return false;
      return true;
    });
  }
  function filteredMatches(){ return filteredSection(clipsArr()); }
  function filteredResults(){ return filteredSection(resultsArr()); }
  // 赛果集锦区只放官方完整集锦（给原站入口）；零散比赛画面片段按用户要求已删除。
  // 不出现点开全黑的假播放器，也不再有站内零散片段。
  function hasClip(m){
    return !!(m && (safeVideo(m.play)
                    || safeOfficial(m.official_url || m.migu_url)));
  }
  function clipSite(m){
    return (m && m.official_site) || '咪咕体育';
  }
  function matchCardHtml(m, idx){
    var cover = safeImg(m.img), clip = hasClip(m);
    var scoreTxt = m.score || '—';
    return '<article class="mcard fade'+(clip?'':' no-clip')+'" data-match="'+esc(m.id)+'" style="animation-delay:'+Math.min(idx,12)*22+'ms">'
      + '<div class="mc-pic">'
      + (cover ? '<img loading="lazy" referrerpolicy="no-referrer" src="'+cover+'" alt="">'
               : '<div class="mc-ph"><span>'+esc(m.league||'比赛')+'</span><b>'+esc(scoreTxt)+'</b></div>')
      + (clip ? '<span class="mc-play">▶</span>' : '<span class="mc-flag">官方赛果</span>')
      + (m.duration ? '<span class="mc-dur">'+esc(m.duration)+'</span>' : '')
      + '</div><div class="mc-body">'
      + '<div class="mc-top"><span class="mc-league">'+esc(m.league||'比赛')+'</span>'
      + '<span>'+esc(m.round || m.comp || '')+'</span><span class="mc-date">'+esc(m.date||'')+'</span></div>'
      + '<div class="mc-score">'+esc(scoreTxt)+'</div>'
      + '<div class="mc-teams">'+esc(m.teams || m.headline || m.title)+'</div>'
      + '<div class="mc-title">'+esc(m.title)+'</div>'
      + '<div class="mc-src">'+(clip
          ? esc(clipSite(m))+'官方完整集锦 · 前往'+esc(clipSite(m))+'观看 ↗'
          : '官方赛果 · 点击查看轮次、队徽与开球时间')+'</div>'
      + '</div></article>';
  }
  function renderMatches(list){
    var cs = clipsArr();
    $('#mgrid').innerHTML = list.map(matchCardHtml).join('');
    $('#mEmpty').hidden = list.length > 0;
    $('#mShown').textContent = list.length;
    $('#mTotal').textContent = cs.length;
    var stamp = DATA.highlights_updated_at || DATA.updated_at || '';
    var since = DATA.match_since_label || sinceLabel(rollingSince());
    var intl = !!DATA.international_window;
    var post = !!DATA.post_break_active;
    var site = intl ? '爱奇艺体育' : '咪咕体育';
    var scope = intl ? '国际比赛日：只收欧洲国家队比赛，俱乐部集锦已全部撤下'
                     : (post ? '国际比赛日已结束：国际比赛日的比赛与此前的联赛集锦都不再展示，只等新联赛赛果'
                             : '只收五大联赛 / 欧冠');
    $('#mHint').textContent = cs.length
      ? ('只收 ' + since + ' · 共 ' + cs.length + ' 段' + site + '官方完整集锦（点按钮到原站观看）'
         + (stamp ? ' · 上次更新 ' + stamp.slice(5, 16) : '')
         + ' · ' + scope
         + ' · 已删除零散比赛片段，无第三方嵌入播放器、不会黑屏')
      : (post
          ? ('国际比赛日已结束 · 只收 ' + since + '新打的联赛官方完整集锦 · '
             + '国际比赛日的比赛与此前的联赛集锦一律不再展示；目前还没有新集锦，'
             + '这里如实留空，不拿旧比赛、零散片段或其它赛事凑数，新比赛打完会自动补上')
          : ('只收 ' + since + '的' + site + '官方完整集锦 · 本次没有抓到符合范围的集锦，'
             + '这里如实留空，不拿旧比赛、零散片段或其它赛事凑数；有新的官方集锦会自动补上'));
    // 没有数据时给出原因；有数据但被筛选清空时仍显示通用提示
    var p = $('#mEmpty p');
    if (p) p.textContent = cs.length ? '当前没有符合范围的官方集锦'
        : (post ? '国际比赛日已结束 · ' + since + '暂无新联赛官方集锦'
                : since + '暂无' + site + '官方集锦');
    var note = $('#mEmptyNote');
    if (note) note.hidden = cs.length > 0;
  }
  function renderResults(list){
    var rs = resultsArr(), byLg = {}, intl = !!DATA.international_window,
        post = !!DATA.post_break_active;
    rs.forEach(function(m){ var k=m.league||'其它'; byLg[k]=(byLg[k]||0)+1; });
    var order = intl
      ? ['欧国联','欧洲杯预选赛','欧洲杯','世预赛欧洲区','国际友谊赛']
      : ['英超','欧冠','西甲','意甲','法甲','德甲'];
    var parts = order.concat(Object.keys(byLg).filter(function(k){
      return order.indexOf(k) < 0;
    })).filter(function(k){ return byLg[k]; })
      .map(function(k){ return k+' '+byLg[k]+' 场'; });
    $('#rgrid').innerHTML = list.map(matchCardHtml).join('');
    $('#rEmpty').hidden = list.length > 0;
    $('#rShown').textContent = list.length;
    $('#rTotal').textContent = rs.length;
    $('#rHint').textContent = (DATA.match_since_label || sinceLabel(rollingSince())) + ' · '
      + (parts.length ? parts.join(' · ') + ' · ' : '') + '共 ' + rs.length
      + ' 场真实赛果'
      + (intl ? ' · 国际比赛日：只收欧洲国家队比赛，俱乐部赛果已全部撤下'
              : (post ? ' · 国际比赛日已结束：国际比赛日与此前的联赛赛果都不再展示，只等新联赛赛果'
                      : ' · 只收五大联赛 / 欧冠'))
      + ' · 轮次 / 主客队 / 比分 / 开球时间取自直播吧官方比赛页';
  }

  /* ---------------- 即将开赛 ---------------- */
  function fxCountdown(fx, plain){
    var t = new Date(String(fx.kickoff||'').replace(/-/g,'/')).getTime();
    if (!t) return '';
    var d = t - Date.now();
    if (d <= 0) return '已开球';
    var tail = plain ? '' : '后';
    var hh = Math.floor(d/3600000), mm = Math.floor(d%3600000/60000);
    if (hh >= 24) return Math.floor(hh/24)+' 天'+tail;
    return hh > 0 ? (hh+' 小时 '+mm+' 分'+tail) : (mm+' 分'+tail);
  }
  function fixtureCardHtml(fx){
    var lg = fx.logos || [];
    function logo(i){
      var u = safeImg(lg[i]);
      return u ? '<img referrerpolicy="no-referrer" src="'+u+'" alt="">' : '';
    }
    var n = (fx.analysis||[]).length;
    var estChip = (state.showEstimate && fx.estimate)
      ? '<span class="fx-chip est-chip">模型估算</span>' : '';
    return '<article class="fxcard" data-fixture="'+esc(fx.id)+'" tabindex="0" role="button" aria-label="查看 '+esc(fx.home)+' 对 '+esc(fx.away)+' 的赛前分析">'
      + '<div class="fx-top"><span class="fx-lg">'+esc(fx.league||'')+'</span>'
      + '<span class="fx-round">'+esc(fx.round||'')+'</span>'
      + '<span class="fx-when">'+esc(fx.date||'')+' '+esc(fx.time||'')+'</span></div>'
      + '<div class="fx-body">'
      + '<div class="fx-side">'+logo(0)+'<span>'+esc(fx.home||'—')+'</span></div>'
      + '<div class="fx-vs"><b>VS</b><small>'+esc(fxCountdown(fx))+'</small></div>'
      + '<div class="fx-side">'+logo(1)+'<span>'+esc(fx.away||'—')+'</span></div></div>'
      + '<div class="fx-foot"><span class="fx-chip'+(n?'':' gray')+'">'+(n?n+' 条赛前分析':'暂无前瞻')+'</span>'
      + estChip + '<span>赛前分析</span><span class="fx-go">点开查看 →</span></div></article>';
  }
  function renderUpcoming(list){
    var fs = fixturesArr();
    $('#ugrid').innerHTML = list.map(fixtureCardHtml).join('');
    $('#uEmpty').hidden = list.length > 0;
    $('#uShown').textContent = list.length;
    $('#uTotal').textContent = fs.length;
    var stamp = DATA.upcoming_updated_at || '';
    var wr = fs.filter(function(x){ return x && x.winrate; }).length;
    var es = fs.filter(function(x){ return x && x.estimate; }).length;
    var estTxt = es
      ? (state.showEstimate ? ' · '+es+' 场有本站模型估算（可关闭）' : ' · 本站模型估算已关闭')
      : '';
    $('#uHint').textContent = fs.length
      ? ('未来 7 天 · 共 '+fs.length+' 场 · 赛程取自直播吧官方直播表'
         + (wr ? ' · '+wr+' 场有来源站公布的本场胜率' : ' · 三家来源均未公布本场胜率')
         + estTxt
         + (stamp ? ' · 更新 '+stamp.slice(5,16) : '')
         + (DATA.international_window ? ' · 国际比赛日：赛程含欧国联等欧洲国家队比赛' : ''))
      : '未来 7 天暂无符合范围的比赛；这里如实留空，不拿已结束的比赛凑数';
    var p = $('#uEmpty p');
    if (p) p.textContent = fs.length ? '当前筛选下没有即将开赛的比赛' : '未来 7 天暂无符合范围的比赛';
  }
  // 只有直播吧比赛页明确公布「主胜 / 平 / 客胜」百分比时才渲染；
  // 没有数据就返回空串，整块胜率区不出现在页面上，也不写占位数字。
  function winrateHtml(fx){
    var w = fx.winrate;
    if (!w) return '';
    var ph = Number(w.home), pd = Number(w.draw), pa = Number(w.away);
    if (!isFinite(ph) || !isFinite(pd) || !isFinite(pa)) return '';
    var rawUrl = String(w.source_url||'');
    var srcLink = /^https:\/\/www\.zhibo8\.com\/zhibo\/zuqiu\/[^\s"'<>]+$/.test(rawUrl)
      ? ' · <a href="'+esc(rawUrl)+'" target="_blank" rel="noopener noreferrer">查看来源 ↗</a>'
      : '';
    return '<section class="rd-sec"><h3>本场胜率 · 来源站公布</h3>'
      + '<div class="odds-wrap">'
      + '<div class="odds-head"><b>主胜 / 平 / 客胜</b>'
      + '<span class="odds-tag">'+esc(w.source||'直播吧比赛页公布')+'</span></div>'
      + '<div class="odds-bar">'
      + '<i class="o-h" style="width:'+ph+'%">'+ph+'%</i>'
      + '<i class="o-d" style="width:'+pd+'%">'+pd+'%</i>'
      + '<i class="o-a" style="width:'+pa+'%">'+pa+'%</i></div>'
      + '<div class="odds-legend"><span><b>'+esc(fx.home||'主队')+'</b> 主胜</span>'
      + '<span><b>平局</b></span><span><b>'+esc(fx.away||'客队')+'</b> 客胜</span></div>'
      + '<div class="odds-note">以上数字原样取自来源站公布的本场胜平负数据，'
      + '本站不估算、不改写、不引用赔率或竞猜。原文：'+esc(w.quote||'—')
      + ' · <a href="'+esc(safeUrl(w.source_url))+'" target="_blank" rel="noopener noreferrer">查看来源 ↗</a></div></div>'
      + '<div class="rd-note">胜率仅在本场有官方公布数据时才显示；没有就整块不写。仅供参考，不构成投注建议。</div></section>';
  }
  // 本站模型估算：独立字段 fx.estimate、独立区块，与「来源站公布」绝不混用。
  // 关闭开关或没有可核实数据时整块不渲染，也不写任何占位百分比。
  function estimateHtml(fx){
    if (!state.showEstimate) return '';
    var e = fx.estimate;
    if (!e) return '';
    var ph = Number(e.home), pd = Number(e.draw), pa = Number(e.away);
    if (!isFinite(ph) || !isFinite(pd) || !isFinite(pa)) return '';
    var sh = ph.toFixed(1), sd = pd.toFixed(1), sa = pa.toFixed(1);
    function recentTable(list, name){
      var body = (list || []).map(function(r){
        return '<tr><td>'+esc(r.date||'')+'</td><td>'+esc(r.league||'')+'</td>'
          + '<td>'+esc(r.home||'')+'</td><td class="est-sc">'+esc(r.score||'')+'</td>'
          + '<td>'+esc(r.away||'')+'</td><td>'+esc(r.venue||'')+'</td>'
          + '<td class="est-num">'+esc(r.gf)+' : '+esc(r.ga)+'</td></tr>';
      }).join('');
      return '<div class="est-tbl-wrap"><div class="est-tname">'+esc(name)+' · 近 '
        + ((list||[]).length) + ' 场（含友谊赛）</div>'
        + '<table class="est-table"><thead><tr><th>日期</th><th>赛事</th><th>主队</th>'
        + '<th>比分</th><th>客队</th><th>身份</th><th>本队进:失</th></tr></thead>'
        + '<tbody>'+body+'</tbody></table></div>';
    }
    var kv = [
      ['主队期望进球 λ', e.lambda_home], ['客队期望进球 λ', e.lambda_away],
      ['样本主队场均', e.mu_home], ['样本客队场均', e.mu_away],
      ['样本均进球 base', e.base], ['强度收缩系数', e.shrink],
      ['去重样本场次', e.sample_games], ['逐场权重', '等权']
    ].map(function(x){
      return '<div class="est-kv"><span>'+esc(x[0])+'</span><b>'+esc(x[1])+'</b></div>';
    }).join('');
    var official = '';
    if ((e.official_points||[]).length){
      official += '<div class="est-sub">官方积分榜对照（不参与计算）</div>'
        + '<table class="est-table"><thead><tr><th>球队</th><th>已赛</th><th>胜/平/负</th>'
        + '<th>进/失</th><th>积分</th></tr></thead><tbody>'
        + e.official_points.map(function(p){
            return '<tr><td>'+esc(p.team)+'</td><td>'+esc(p.games)+'</td><td>'+esc(p.wdl)+'</td>'
              + '<td>'+esc(p.goal)+'</td><td>'+esc(p.point)+'</td></tr>';
          }).join('') + '</tbody></table>';
    }
    if ((e.head_to_head||[]).length){
      official += '<div class="est-sub">两队交锋历史对照（不参与计算）</div>'
        + '<table class="est-table"><thead><tr><th>日期</th><th>赛事</th><th>主队</th>'
        + '<th>比分</th><th>客队</th></tr></thead><tbody>'
        + e.head_to_head.map(function(p){
            return '<tr><td>'+esc(p.date)+'</td><td>'+esc(p.league)+'</td>'
              + '<td>'+esc(p.home_team)+'</td><td class="est-sc">'+esc(p.score)+'</td>'
              + '<td>'+esc(p.visit_team)+'</td></tr>';
          }).join('') + '</tbody></table>';
    }
    var raw = safeUrl(e.data_url);
    var rawLink = raw ? ' · <a href="'+raw+'" target="_blank" rel="noopener noreferrer">核对官方原始 JSON ↗</a>' : '';
    return '<section class="rd-sec"><h3>本场胜率 · 本站模型估算（非官方数据）</h3>'
      + '<div class="est-wrap">'
      + '<div class="est-alert"><b>请注意：</b>下面三个百分比不是任何来源站公布的胜率，'
      + '也不是赔率或竞猜数据，而是<b>本站用直播吧官方比赛页给出的两队近 6 场真实比分</b>，'
      + '按下方公开公式算出来的模型估算。它可以在列表页一键关闭；'
      + '来源站若公布官方胜率，会在另一个单独区块里原样展示，两者绝不混用。</div>'
      + '<div class="odds-head"><b>主胜 / 平 / 客胜</b>'
      + '<span class="est-tag">本站模型估算</span>'
      + '<span class="est-tag ghost">'+esc(e.method||'')+'</span>'
      + '<button class="est-off" data-est-toggle="off" type="button">关闭模型估算</button></div>'
      + '<div class="est-bar">'
      + '<i class="e-h" style="width:'+ph+'%">'+sh+'%</i>'
      + '<i class="e-d" style="width:'+pd+'%">'+sd+'%</i>'
      + '<i class="e-a" style="width:'+pa+'%">'+sa+'%</i></div>'
      + '<div class="odds-legend"><span><b>'+esc(fx.home||'主队')+'</b> 主胜</span>'
      + '<span><b>平局</b></span><span><b>'+esc(fx.away||'客队')+'</b> 客胜</span></div>'
      + '<div class="est-kvs">'+kv+'</div>'
      + '<div class="est-formula"><b>计算方法</b>　'+esc(e.formula||'')+'</div>'
      + '<div class="est-sub">输入明细 · 直播吧比赛页「赛前数据 / 最近战绩」原样比分</div>'
      + '<div class="est-tables">'+recentTable(e.recent_home, fx.home||'主队')
      + recentTable(e.recent_away, fx.away||'客队')+'</div>'
      + official
      + '<div class="odds-note"><b>数据来源</b>　'+esc(e.source||'')+rawLink
      + ' · 生成于 '+esc(e.generated_at||'')+'</div>'
      + '<div class="est-warn">'+esc(e.warning||'')+'</div>'
      + '</div></section>';
  }
  function analysisHtml(fx){
    var arr = fx.analysis || [];
    if (!arr.length){
      return '<div class="ax-none">来源站近两日没有针对本场比赛的赛前报道（前瞻 / 首发预测 / 伤停 / 备战）。'
        + '本站不编造「专家观点」，有真实报道时会自动补上；下方比赛信息仍按官方直播表原样展示。</div>';
    }
    return '<div class="ax-list">' + arr.map(function(a){
      return '<div class="ax-item"><div class="ax-meta">'
        + '<span class="ax-cat">'+esc(a.category||'赛前动态')+'</span>'
        + '<span>'+esc(a.source||'直播吧')+'</span><span>'+esc(a.time||'')+'</span></div>'
        + '<p class="ax-title">'+esc(a.title||'')+'</p>'
        + (a.desc ? '<p class="ax-desc">'+esc(a.desc)+'</p>'
                  : '<p class="ax-desc">来源页未提供摘要，本站不补写。</p>')
        + '</div>';
    }).join('') + '</div>';
  }
  function fixtureReaderBody(fx){
    var lg = fx.logos || [];
    function logo(i){
      var u = safeImg(lg[i]);
      return u ? '<img class="rc-logo" referrerpolicy="no-referrer" src="'+u+'" alt="">' : '';
    }
    var facts = '<div class="rd-facts">'
      + '<div class="rd-fact"><div class="k">赛事</div><div class="v">'+esc(fx.league||'—')+'</div></div>'
      + '<div class="rd-fact"><div class="k">轮次</div><div class="v" style="font-size:12px">'+esc(fx.round||'—')+'</div></div>'
      + '<div class="rd-fact"><div class="k">开球时间</div><div class="v" style="font-size:12px">'+esc(fx.kickoff||'—')+'</div></div>'
      + '<div class="rd-fact"><div class="k">距开球</div><div class="v" style="font-size:12px">'+esc(fxCountdown(fx,true)||'—')+'</div></div>'
      + '</div>';
    var matchCard = '<div class="rd-matchcard">'
      + '<div class="rc-side">'+logo(0)+'<span>'+esc(fx.home||'—')+'</span></div>'
      + '<div class="rc-mid"><b>VS</b><span>'+esc(fx.league||'')+'</span></div>'
      + '<div class="rc-side">'+logo(1)+'<span>'+esc(fx.away||'—')+'</span></div></div>';
    var rel = fixturesArr().filter(function(x){ return x.id!==fx.id; }).slice(0,4).map(function(x){
      return '<button class="rd-rel" data-fixture="'+esc(x.id)+'">'
        + '<span class="rr-rk">'+esc(x.time||'')+'</span>'
        + '<span class="rr-t">'+esc(x.home+' vs '+x.away)+'</span>'
        + '<span class="rr-c">'+esc(x.league||'')+' ›</span></button>';
    }).join('');
    return '<div class="rd-meta"><span class="cat">'+esc(fx.league||'比赛')+'</span>'
      + '<span class="tag">'+esc(fx.round||'即将开赛')+'</span>'
      + '<span class="hot-n">'+esc(fx.date||'')+' '+esc(fx.time||'')+' 开球 · 直播吧官方直播表</span></div>'
      + '<h1 class="rd-title">'+esc(fx.home+' vs '+fx.away)+'</h1>'
      + facts
      + '<section class="rd-sec"><h3>对阵</h3>'+matchCard+'</section>'
      + winrateHtml(fx)
      + estimateHtml(fx)
      + '<section class="rd-sec"><h3>专家分析 · 真实赛前报道</h3>'+analysisHtml(fx)
      + '<div class="rd-note">以上标题、来源、时间与摘要<b>原样取自来源页赛前报道</b>，按两队名匹配到本场，'
      + '本站不改写、不代写观点、不跳转外站；内容版权归原作者及来源媒体所有。没有对应报道时如实留空。</div></section>'
      + (rel ? '<section class="rd-sec"><h3>其它即将开赛</h3><div class="rd-related">'+rel+'</div></section>' : '');
  }
  function renderFixtureReader(){
    var fx = byFixture(state.fixtureId);
    if (!fx){ state.fixtureId = 0; hideReader(); renderHeader(); return; }
    $('#rdPos').textContent = '即将开赛 · '
      + (fx.winrate ? '官方胜率 · ' : '')
      + (state.showEstimate && fx.estimate ? '本站模型估算 · ' : '')
      + '赛前分析';
    $('#rdFav').style.display = 'none';
    var img = $('#rdImg'); img.removeAttribute('src'); img.style.display = 'none';
    $('#rdBody').innerHTML = fixtureReaderBody(fx);
    $('#overlay').classList.add('show');
    $('#reader').classList.add('show');
    $('#reader').scrollTop = 0;
    document.body.style.overflow = 'hidden';
    document.title = fx.home+' vs '+fx.away+' · 今日球报';
  }
  // 播放器采用「封面占位 → 点击才创建 <video>」，避免一次加载几十路视频
  // 来源页给的是腾讯云控制台预览播放器（第三方页面只有黑屏 UI），且 720p 档是 H.265；
  // 抓取脚本已改调 getplayinfo 逐档探测编码，这里拿到的 play 是 H.264 直链。
  function resultCardHtml(m){
    var lg = m.logos || [];
    function logo(i){
      var u = safeImg(lg[i]);
      return u ? '<img class="rc-logo" referrerpolicy="no-referrer" src="'+u+'" alt="">' : '';
    }
    return '<div class="rd-matchcard">'
      + '<div class="rc-side">'+logo(0)+'<span>'+esc(m.home||'—')+'</span></div>'
      + '<div class="rc-mid"><b>'+esc(m.score||'—')+'</b><span>'+esc(m.round||m.comp||'')+'</span></div>'
      + '<div class="rc-side">'+logo(1)+'<span>'+esc(m.away||'—')+'</span></div>'
      + '</div>'
      + (m.kickoff ? '<div class="rd-vcap">开球时间：'+esc(m.kickoff)
          +' · 比分、轮次与队名原样取自直播吧官方赛果页</div>' : '');
  }
  // 官方集锦卡片：封面 + 官方标题 + 原站播放按钮，绝不内嵌播放器。
  // 咪咕 / 爱奇艺都是版权方，实测官方播放器在第三方网页里只有 logo / 导航 / 黑屏。
  function miguPanel(m, mi){
    var page = safeOfficial((mi && mi.page_url) || m.official_url || m.migu_url);
    if (!page) return '';
    var site = (mi && mi.site) || m.official_site || '咪咕体育';
    var title = (mi && mi.title) || m.official_title || m.title || site + '官方集锦';
    var dur = (mi && mi.duration) || m.duration || '';
    var pub = (mi && mi.published) || m.published || '';
    var cover = safeImg(m.img);
    return '<div class="rd-video migu-box">'
      + (cover ? '<img class="vd-cover" referrerpolicy="no-referrer" src="'+cover+'" alt="">' : '')
      + '<div class="migu-mask">'
      + '<div class="migu-badge">'+esc(site)+' · 官方集锦</div>'
      + '<div class="migu-title">'+esc(title)+'</div>'
      + '<div class="migu-sub">'+esc(m.league||'')
      + (dur ? ' · 时长 '+esc(dur) : '')
      + (pub ? ' · '+esc(pub.slice(5,16))+' 发布' : '')+'</div>'
      + '<a class="migu-go" href="'+page+'" target="_blank" rel="noopener noreferrer">▶ 在'+esc(site)+'观看完整版 ↗</a>'
      + '<div class="migu-why">'+esc(site)+'是版权方，官方播放器不允许第三方网页嵌入；'
      + '这里不放会黑屏的假播放器，点上方按钮到'+esc(site)+'自己的页面看，画面必定正常。</div>'
      + '</div></div>';
  }
  function videoBox(m){
    if (!m) return '';
    var v = safeVideo(m.play), mu = safeOfficial(m.official_url || m.migu_url);
    // 赛果集锦区的官方完整集锦卡片（平时咪咕，国际比赛日爱奇艺体育）
    if (!v && mu) return miguPanel(m, null);
    // 国际比赛日的欧洲国家队正赛赛果：给本场官方全场集锦入口，没有就只展示赛果
    if (!v && m.video_status === 'official'){
      var oc = m.official_clip;
      return resultCardHtml(m)
        + (oc && safeOfficial(oc.page_url) ? miguPanel(m, oc) : '')
        + '<div class="rd-vcap">本场为欧洲国家队比赛的官方赛果，轮次 / 主客队 / 比分 / '
        + '开球时间原样取自直播吧官方比赛页。'
        + (oc ? '直播吧官方集锦页同时登记了本场完整集锦，点上方按钮到官方站点观看。'
              : '本场暂无官方全场集锦登记，可到「赛果集锦」区域查看其它场次。')
        + '版权方不允许第三方网页嵌入，本站不塞会黑屏的假播放器。</div>';
    }
    // 正赛赛果：登记了咪咕官方集锦的给原站入口，没有的只展示赛果
    if (!v && m.video_status === 'migu'){
      var mi = m.migu_clip;
      return resultCardHtml(m)
        + (mi && safeMigu(mi.page_url) ? miguPanel(m, mi) : '')
        + '<div class="rd-vcap">本场为官方正赛赛果，轮次 / 主客队 / 比分 / 开球时间原样取自直播吧官方比赛页。'
        + (mi ? '咪咕体育另有本场官方集锦，点上方按钮到咪咕观看完整版。'
              : '本场暂无官方集锦登记。')
        + '咪咕播放流带签名保护，第三方网页内嵌会黑屏，这里不塞假播放器。</div>';
    }
    if (!v) return '<div class="rd-video na">这段集锦暂时没有可播放的地址。<br>点页面右上「刷新」或运行「更新新闻.bat」重新抓取后再试。</div>';
    var cover = safeImg(m.img);
    var cap = '集锦为来源站官方完整比赛视频，在本页用浏览器原生播放器播放；点右上角 <b>⛶ 全屏</b> 可放大观看（按 Esc 退出）。若提示加载失败，多为源站链接过期，重新抓取即可。';
    return '<div class="rd-video" data-video="'+v+'"'+(cover ? ' data-cover="'+cover+'"' : '')+'>'
      + (cover ? '<img class="vd-cover" referrerpolicy="no-referrer" src="'+cover+'" alt="">' : '')
      + '<button class="vd-play" data-play="1" aria-label="播放集锦"><svg viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg></button>'
      + '<button class="vd-fs" data-fs="1" type="button" title="全屏播放（浏览器限制时自动改为铺满窗口）" aria-label="全屏播放">'
      + '<svg class="i-in" viewBox="0 0 24 24"><path d="M4 9V4h5M15 4h5v5M20 15v5h-5M9 20H4v-5"/></svg>'
      + '<svg class="i-out" viewBox="0 0 24 24"><path d="M9 4v5H4M20 9h-5V4M15 20v-5h5M4 15h5v5"/></svg>'
      + '</button>'
      + (m.duration ? '<span class="vd-dur">'+esc(m.duration)+'</span>' : '')
      + '</div><div class="rd-vcap">'+cap+'</div>';
  }
  function playVideo(box){
    if (box.classList.contains('playing') || box.querySelector('video')) return;
    var url = box.getAttribute('data-video') || '';
    box.classList.add('playing');
    if (!url) return;
    var cover = box.getAttribute('data-cover') || '';
    var v = document.createElement('video');
    v.src = url;
    v.setAttribute('controls', '');
    v.setAttribute('playsinline', '');
    v.setAttribute('preload', 'metadata');
    v.setAttribute('title', '比赛集锦播放器');
    if (cover) v.setAttribute('poster', cover);
    v.autoplay = true;
    box.appendChild(v);
    v.addEventListener('loadeddata', function(){ box.classList.add('ready'); });
    v.addEventListener('error', function(){
      if (box.querySelector('.vd-err')) return;
      var tip = document.createElement('div');
      tip.className = 'vd-err';
      tip.innerHTML = '视频加载失败：源站链接可能已过期，或当前网络不通。<br>点右上「刷新」/ 运行「更新新闻.bat」重新抓取后再试。';
      box.appendChild(tip);
    });
    v.setAttribute('webkit-playsinline', '');
    v.setAttribute('x5-playsinline', '');
    var p = v.play();  // 被浏览器拦截自动播放时，用户点原生控件即可
    if (p && p.catch) p.catch(function(){});
  }

  /* ---------------- 全屏 ----------------
     原生 <video> 控件的全屏按钮在部分嵌入面板 / iframe 里会被浏览器直接禁用，
     所以另给一个自己的按钮：优先调 Fullscreen API；被拒或抛错就降级成
     「剧场模式」（fixed 铺满窗口 + 锁滚动），保证任何环境都能放大看。 */
  function fsEl(){
    return document.fullscreenElement || document.webkitFullscreenElement ||
           document.mozFullScreenElement || document.msFullscreenElement || null;
  }
  function fsActive(box){ return !!fsEl() || box.classList.contains('theater'); }
  function fsTheater(box){
    box.classList.add('theater','is-fs');
    document.body.classList.add('fs-lock');
    var rd = document.getElementById('reader');
    if (rd) rd.classList.add('fs-host');   // 清掉阅读面板的 transform，fixed 才能相对视口
  }
  function fsExit(box){
    var d = document;
    if (fsEl()){
      try {
        if (d.exitFullscreen) d.exitFullscreen();
        else if (d.webkitExitFullscreen) d.webkitExitFullscreen();
        else if (d.msExitFullscreen) d.msExitFullscreen();
      } catch(err){}
    }
    box.classList.remove('theater','is-fs');
    if (!d.querySelector('.rd-video.theater')){
      d.body.classList.remove('fs-lock');
      var rd = d.getElementById('reader');
      if (rd) rd.classList.remove('fs-host');
    }
  }
  function fsToggle(box){
    if (fsActive(box)){ fsExit(box); return; }
    var req = box.requestFullscreen || box.webkitRequestFullscreen ||
              box.msRequestFullscreen || box.mozRequestFullScreen;
    if (req){
      try {
        var p = req.call(box);
        if (p && p.then) p.then(function(){ box.classList.add('is-fs'); },
                                function(){ fsTheater(box); });
        else box.classList.add('is-fs');
      } catch(err){ fsTheater(box); }
    } else {
      var v = box.querySelector('video');
      if (v && v.webkitEnterFullscreen){   // iOS Safari 只有 <video> 自带全屏接口
        try { v.webkitEnterFullscreen(); box.classList.add('is-fs'); }
        catch(err){ fsTheater(box); }
      } else fsTheater(box);
    }
  }
  function fsSync(){
    var el = fsEl();
    $$('.rd-video').forEach(function(b){
      if (el === b) b.classList.add('is-fs');
      else if (!b.classList.contains('theater')) b.classList.remove('is-fs');
    });
    if (!el && !document.querySelector('.rd-video.theater')){
      document.body.classList.remove('fs-lock');
      var rd = document.getElementById('reader');
      if (rd) rd.classList.remove('fs-host');
    }
  }
  function fsCleanup(){
    var b = document.querySelector('.rd-video.theater');
    if (b){ fsExit(b); return; }
    if (fsEl()){
      try {
        if (document.exitFullscreen) document.exitFullscreen();
        else if (document.webkitExitFullscreen) document.webkitExitFullscreen();
      } catch(err){}
    }
  }
  document.addEventListener('fullscreenchange', fsSync);
  document.addEventListener('webkitfullscreenchange', fsSync);

  function setMode(m){
    state.mode = (m==='cabinet' || m==='matches' || m==='results' || m==='upcoming') ? m : 'board';
    $('#viewBoard').hidden   = state.mode!=='board';
    $('#viewCabinet').hidden = state.mode!=='cabinet';
    $('#viewMatches').hidden = state.mode!=='matches';
    $('#viewResults').hidden = state.mode!=='results';
    $('#viewUpcoming').hidden = state.mode!=='upcoming';
    $$('#viewSwitch button').forEach(function(b){ b.classList.toggle('on', b.dataset.view===state.mode); });
    var inList = (state.mode==='matches' || state.mode==='results' || state.mode==='upcoming');
    $('#metaNews').hidden    = inList;
    $('#metaMatch').hidden   = state.mode!=='matches';
    $('#metaResults').hidden = state.mode!=='results';
    $('#metaUpcoming').hidden = state.mode!=='upcoming';
  }
  function viewHash(){
    return state.mode==='board' ? '' : '#/'+state.mode;
  }
  function syncViewHash(){
    try { history.replaceState(null, '', location.pathname+location.search+viewHash()); }
    catch(e){ /* file:// 下忽略 */ }
  }
  function render(){
    var list = filtered();
    renderBoard(list);
    renderCabinet(list);
    renderMatches(filteredMatches());
    renderResults(filteredResults());
    renderUpcoming(filteredFixtures());
    buildChips();
    $('#total').textContent = all().length;
  }

  /* ---------------- 站内阅读面板 ---------------- */
  function bigrams(s){
    s = String(s||'').replace(/[^\u4e00-\u9fa5a-zA-Z0-9]/g,'');
    var out = {};
    for (var i=0;i<s.length-1;i++) out[s.slice(i,i+2)] = 1;
    return Object.keys(out);
  }
  function related(it){
    var c = classify(it), a = all();
    var same = a.filter(function(x){ return x!==it && classify(x)===c; }).slice(0,4);
    if (same.length<4){
      var bg = bigrams(it.title), scored = [];
      a.forEach(function(x){
        if (x===it || same.indexOf(x)>-1) return;
        var bx = bigrams(x.title), hit = 0;
        bg.forEach(function(g){ if (bx.indexOf(g)>-1) hit++; });
        scored.push({x:x, s:hit + (Number(x.hot)||0)/1e9});
      });
      scored.sort(function(p,q){ return q.s-p.s; });
      same = same.concat(scored.slice(0,4-same.length).map(function(o){ return o.x; }));
    }
    return same;
  }
  function readerBody(it){
    var k = key(it), cat = classify(it);
    var facts = '<div class="rd-facts">'
      + '<div class="rd-fact"><div class="k">赛事</div><div class="v">'+esc(cat)+'</div></div>'
      + '<div class="rd-fact"><div class="k">发布时间</div><div class="v" style="font-size:13px">'+esc(it.time||'—')+'</div></div>'
      + '<div class="rd-fact"><div class="k">来源</div><div class="v" style="font-size:12px">'+esc(it.source||'直播吧')+'</div></div>'
      + '<div class="rd-fact"><div class="k">日报位次</div><div class="v">NO.'+it.rank+'</div></div>'
      + '</div>';
    var summary = it.desc
      ? '<p class="rd-summary">'+esc(it.desc)+'</p>'
      : '<p class="rd-summary none">来源页未提供这条的内容摘要，本站不编造内容。可返回列表查看其它条目。</p>';
    var note = '<div class="rd-note">本页为<b>站内阅读</b>，标题与正文节选自来源页，属于索引式呈现，<b>并非全文转载</b>。发布时间与来源按来源页原样标注；内容版权归原作者及来源媒体所有，本站不改写比分与赛果，也不提供外站跳转。</div>';
    // 只有赛果类资讯、且比分与队名都吻合时，抓取脚本才会写入 match 字段
    var clip = '';
    var m = it.match ? byMatch(it.match) : null;
    if (m){
      clip = '<section class="rd-sec"><h3>'+(hasClip(m)?'本场集锦':'本场赛果')+'</h3>'
        + '<div class="rd-vcap" style="margin:0 0 10px">'+esc(m.league||'')+' · '
        + esc(m.round||m.comp||'')+' · 比分 '+esc(m.score||'—')+'</div>'
        + videoBox(m) + '</section>';
    }
    var rel = related(it).map(function(x){
      return '<button class="rd-rel" data-read="'+x.rank+'">'
        + '<span class="rr-rk">'+String(x.rank).padStart(2,'0')+'</span>'
        + '<span class="rr-t">'+esc(x.title)+'</span>'
        + '<span class="rr-c">'+esc(classify(x))+' ›</span></button>';
    }).join('');
    var prev = byRank(it.rank-1), next = byRank(it.rank+1);
    var nav = '<div class="rd-nav">'
      + '<button data-read="'+(prev?prev.rank:it.rank)+'"'+(prev?'':' disabled')+'><span class="lab">← 上一条</span><span class="tt">'+esc(prev?prev.title:'已是第一条')+'</span></button>'
      + '<button data-read="'+(next?next.rank:it.rank)+'"'+(next?'':' disabled')+'><span class="lab">下一条 →</span><span class="tt">'+esc(next?next.title:'已是最后一条')+'</span></button>'
      + '</div>';
    return '<div class="rd-meta">'+cardMeta(it,cat)+'</div>'
      + '<h1 class="rd-title">'+esc(it.title)+'</h1>'
      + facts
      + clip
      + '<section class="rd-sec"><h3>内容摘要</h3>'+summary+note+'</section>'
      + '<section class="rd-sec"><h3>站内相关</h3><div class="rd-related">'+rel+'</div></section>'
      + nav;
  }
  function matchReaderBody(m){
    var clip = hasClip(m);
    var facts = '<div class="rd-facts">'
      + '<div class="rd-fact"><div class="k">赛事</div><div class="v">'+esc(m.league||'—')+'</div></div>'
      + '<div class="rd-fact"><div class="k">比分</div><div class="v">'+esc(m.score||'—')+'</div></div>'
      + (clip
          ? '<div class="rd-fact"><div class="k">集锦时长</div><div class="v" style="font-size:13px">'+esc(m.duration||'—')+'</div></div>'
          : '<div class="rd-fact"><div class="k">开球时间</div><div class="v" style="font-size:12px">'+esc(m.kickoff||m.date||'—')+'</div></div>')
      + '<div class="rd-fact"><div class="k">比赛日期</div><div class="v" style="font-size:13px">'+esc(m.date||'—')+'</div></div>'
      + '</div>';
    var note = (clip && m.provider === 'migu')
      ? '<div class="rd-note">本条为<b>咪咕体育官方集锦</b>：标题、时长、发布时间与封面取自咪咕官方页面，比分与队名不改写、不推测。咪咕是版权方，播放流带签名校验、官方播放器也不允许第三方网页嵌入（实测只有黑屏壳），因此本站不内嵌播放器，只在你主动点击后到咪咕原站播放；视频版权归咪咕所有，本站不托管、不下载、不二次剪辑。</div>'
      : (clip
         ? '<div class="rd-note">本条为来源站官方完整比赛集锦，在本页用浏览器原生播放器播放；比分与队名不改写、不推测。视频版权归来源方所有，本站不托管、不下载、不二次剪辑。</div>'
         : '<div class="rd-note">本场为<b>官方正赛赛果</b>：轮次、主客队、开球时间与比分原样取自直播吧官方比赛页，本站不改写、不推测。对应的官方集锦来自咪咕体育，若已登记会给出咪咕原站入口；<b>不内嵌会黑屏的播放器、不塞无关片段</b>；视频版权归来源方所有。</div>');
    var same = highlights().filter(function(x){ return x.id!==m.id && x.league===m.league; }).slice(0,4);
    highlights().forEach(function(x){
      if (x.id!==m.id && same.indexOf(x)<0 && same.length<4) same.push(x);
    });
    var rel = same.map(function(x){
      return '<button class="rd-rel" data-match="'+esc(x.id)+'">'
        + '<span class="rr-rk">'+esc(x.score||'▶')+'</span>'
        + '<span class="rr-t">'+esc(x.teams || x.headline || x.title)+'</span>'
        + '<span class="rr-c">'+esc(x.league)+' ›</span></button>';
    }).join('');
    return '<div class="rd-meta"><span class="cat">'+esc(m.league||'比赛')+'</span>'
      + '<span class="tag">'+esc(m.round||m.comp||'官方赛果')+'</span>'
      + '<span class="hot-n">'+esc(m.date||'')+' · 直播吧官方'+(clip?'比赛集锦':'比赛赛果')+'</span></div>'
      + '<h1 class="rd-title">'+esc(m.teams ? (m.teams+' '+m.score) : (m.headline||m.title))+'</h1>'
      + facts
      + '<section class="rd-sec"><h3>'+(clip?'比赛集锦':'本场赛果')+'</h3>'+videoBox(m)+note+'</section>'
      + (rel ? '<section class="rd-sec"><h3>其它赛果集锦</h3><div class="rd-related">'+rel+'</div></section>' : '');
  }
  function hideReader(){
    $('#overlay').classList.remove('show');
    $('#reader').classList.remove('show');
    document.body.style.overflow = '';
    $('#rdFav').style.display = '';
  }
  function renderMatchReader(){
    var m = byMatch(state.matchId);
    if (!m){ state.matchId = 0; hideReader(); renderHeader(); return; }
    $('#rdPos').textContent = m.provider === 'migu'
      ? '咪咕体育官方集锦 · 原站观看'
      : (hasClip(m) ? '官方完整集锦 · 原站观看' : '正赛赛果 · 站内查看');
    $('#rdFav').style.display = 'none';
    var img = $('#rdImg'); img.removeAttribute('src'); img.style.display = 'none';
    $('#rdBody').innerHTML = matchReaderBody(m);
    $('#overlay').classList.add('show');
    $('#reader').classList.add('show');
    $('#reader').scrollTop = 0;
    document.body.style.overflow = 'hidden';
    document.title = ((m.teams ? m.teams+' '+m.score : '') || m.title) + ' · 今日球报';
  }
  function renderReader(){
    fsCleanup();   // 换内容前先退出全屏，避免留下锁滚动或悬空的播放器
    if (state.fixtureId){ renderFixtureReader(); return; }
    if (state.matchId){ renderMatchReader(); return; }
    var it = byRank(state.cur);
    if (!it){ hideReader(); renderHeader(); return; }
    $('#rdFav').style.display = '';
    var k = key(it);
    reads[k] = 1; LS.set('bd50_read', reads);
    $('#rdPos').textContent = '第 ' + it.rank + ' / ' + all().length + ' 条 · 站内阅读';
    $('#rdFav').classList.toggle('on', !!favs[k]);
    var u = safeImg(it.img), img = $('#rdImg');
    if (u){ img.src = u; img.style.display = 'block'; } else { img.removeAttribute('src'); img.style.display = 'none'; }
    $('#rdBody').innerHTML = readerBody(it);
    $('#overlay').classList.add('show');
    $('#reader').classList.add('show');
    $('#reader').scrollTop = 0;
    document.body.style.overflow = 'hidden';
    document.title = it.title + ' · 今日球报';
    render();  // 同步已读状态与收藏计数
  }
  function openFixture(id, push){
    if (!byFixture(id)) return;
    state.cur = 0; state.matchId = 0; state.fixtureId = id;
    if (push !== false){
      try { history.pushState({fixture:id}, '', '#/fixture/'+id); }
      catch(e){ location.hash = '#/fixture/'+id; }
    }
    renderReader();
  }
  function openMatch(id, push){
    if (!byMatch(id)) return;
    state.cur = 0; state.matchId = id; state.fixtureId = 0;
    if (push !== false){
      try { history.pushState({match:id}, '', '#/match/'+id); }
      catch(e){ location.hash = '#/match/'+id; }
    }
    renderReader();
  }
  function openReader(rank, push){
    if (!byRank(rank)) return;
    state.matchId = 0; state.fixtureId = 0; state.cur = rank;
    if (push !== false){
      try { history.pushState({read:rank}, '', '#/read/'+rank); }
      catch(e){ location.hash = '#/read/'+rank; }
    }
    renderReader();
  }
  function closeReader(){
    state.cur = 0; state.matchId = 0; state.fixtureId = 0;
    try { history.replaceState(null, '', location.pathname + location.search + viewHash()); }
    catch(e){ location.hash = viewHash(); }
    renderReader();
  }
  function readFromHash(){
    var h = decodeURIComponent(location.hash || '');
    var ff = h.match(/^#\/fixture\/([A-Za-z0-9_-]+)/);
    if (ff && byFixture(ff[1])){
      state.cur = 0; state.matchId = 0; state.fixtureId = ff[1]; renderReader(); return;
    }
    var mm = h.match(/^#\/match\/([A-Za-z0-9_-]+)/);
    if (mm && byMatch(mm[1])){
      state.cur = 0; state.matchId = mm[1]; renderReader(); return;
    }
    var m = h.match(/^#\/read\/(\d+)/);
    if (m){ state.matchId = 0; state.cur = parseInt(m[1],10); renderReader(); return; }
    if (h.indexOf('#/cabinet') === 0) setMode('cabinet');
    else if (h.indexOf('#/matches') === 0) setMode('matches');
    else if (h.indexOf('#/results') === 0) setMode('results');
    else if (h.indexOf('#/upcoming') === 0) setMode('upcoming');
    else setMode('board');
    if (state.cur || state.matchId || state.fixtureId){
      state.cur = 0; state.matchId = 0; state.fixtureId = 0; renderReader();
    }
  }

  /* ---------------- 事件 ---------------- */
  function applyEstimateToggle(){
    var btn = $('#uEstToggle');
    if (btn){
      btn.setAttribute('aria-pressed', String(state.showEstimate));
      btn.textContent = state.showEstimate
        ? '模型估算：已开启（点击关闭）' : '模型估算：已关闭（点击开启）';
    }
    renderUpcoming(filteredFixtures());
    if (state.fixtureId && $('#reader').classList.contains('show')) renderFixtureReader();
  }
  document.addEventListener('click', function(e){
    // 阅读面板内的「关闭模型估算」：关掉后整块立即消失并记住选择
    if (e.target.closest('[data-est-toggle]')){
      state.showEstimate = false;
      LS.set('bd50_estimate_on', false);
      applyEstimateToggle();
      return;
    }
    // 自定义全屏按钮（原生控件的全屏在嵌入面板里可能被禁用）
    var fsb = e.target.closest('[data-fs]');
    if (fsb){
      e.preventDefault();
      var fbox = fsb.closest('.rd-video');
      if (fbox) fsToggle(fbox);
      return;
    }
    // 咪咕官方集锦是主动点击的原站入口，交给浏览器正常新开标签
    if (e.target.closest('.migu-go')) return;
    // 播放器：点一下才创建播放器，避免同时加载几十路视频
    var pl = e.target.closest('[data-play]');
    if (pl){
      var box = pl.closest('.rd-video');
      if (box) playVideo(box);
      return;
    }
    // 即将开赛卡片 / 相关比赛
    var fc = e.target.closest('[data-fixture]');
    if (fc){
      e.preventDefault();
      var fid = fc.getAttribute('data-fixture');
      if (!byFixture(fid)) return;
      if (state.fixtureId === fid){ $('#reader').scrollTop = 0; return; }
      if (state.cur || state.matchId || state.fixtureId){
        try { history.replaceState({fixture:fid}, '', '#/fixture/'+fid); }
        catch(err){ location.hash = '#/fixture/'+fid; }
        state.cur = 0; state.matchId = 0; state.fixtureId = fid; renderReader();
      } else openFixture(fid);
      return;
    }
    // 赛果卡片 / 相关集锦
    var mc = e.target.closest('[data-match]');
    if (mc){
      e.preventDefault();
      var mid = mc.getAttribute('data-match');
      if (!byMatch(mid)) return;
      if (state.matchId === mid){ $('#reader').scrollTop = 0; return; }
      if (state.matchId || state.cur){
        try { history.replaceState({match:mid}, '', '#/match/'+mid); } catch(err){ location.hash='#/match/'+mid; }
        state.cur = 0; state.matchId = mid; state.fixtureId = 0; renderReader();
      } else openMatch(mid);
      return;
    }
    // 站内阅读：拦截所有 data-read
    var rd = e.target.closest('[data-read]');
    if (rd){
      e.preventDefault();
      if (rd.disabled) return;
      var r = parseInt(rd.dataset.read,10);
      if (state.cur === r){ $('#reader').scrollTop = 0; return; }
      if (state.cur || state.matchId) { // 已在阅读中：替换当前历史项，避免堆积
        try { history.replaceState({read:r}, '', '#/read/'+r); } catch(err){ location.hash='#/read/'+r; }
        state.matchId = 0; state.fixtureId = 0; state.cur = r; renderReader();
      } else openReader(r);
      return;
    }
    var chip = e.target.closest('[data-type]');
    if (chip){
      if (chip.dataset.type==='cat') state.cat = chip.dataset.v;
      else state.view = (state.view===chip.dataset.v) ? '全部' : chip.dataset.v;
      render(); return;
    }
    var vs = e.target.closest('#viewSwitch button');
    if (vs){ setMode(vs.dataset.view); syncViewHash(); return; }
    var toggle = e.target.closest('[data-toggle]');
    if (toggle){
      var c = toggle.dataset.toggle;
      collapsed[c] = !collapsed[c]; LS.set('bd50_drawer', collapsed);
      toggle.parentNode.classList.toggle('collapsed'); return;
    }
    var fav = e.target.closest('[data-fav]');
    if (fav){
      var fk = fav.closest('[data-k]').dataset.k;
      if (favs[fk]) delete favs[fk]; else favs[fk]=1;
      LS.set('bd50_fav', favs); fav.classList.toggle('on');
      render(); toast(favs[fk]?'已收藏':'已取消收藏'); return;
    }
    var exp = e.target.closest('[data-expand]');
    if (exp){
      var p = exp.closest('.main').querySelector('.desc');
      if (p){ p.classList.toggle('open'); exp.textContent = p.classList.contains('open')?'收起摘要':'展开摘要'; }
      return;
    }
    if (e.target.id === 'overlay') { closeReader(); return; }
  });

  $('#rdClose').addEventListener('click', closeReader);
  $('#rdFav').addEventListener('click', function(){
    var it = byRank(state.cur); if (!it) return;
    var k = key(it);
    if (favs[k]) delete favs[k]; else favs[k]=1;
    LS.set('bd50_fav', favs);
    $('#rdFav').classList.toggle('on', !!favs[k]);
    render(); toast(favs[k]?'已收藏':'已取消收藏');
  });
  $('#rdCopy').addEventListener('click', function(){
    var url = location.href.split('#')[0]
      + (state.fixtureId ? '#/fixture/'+state.fixtureId
         : (state.matchId ? '#/match/'+state.matchId : '#/read/'+state.cur));
    function fallback(){
      var ta = document.createElement('textarea');
      ta.value = url; ta.style.position='fixed'; ta.style.opacity='0';
      document.body.appendChild(ta); ta.select();
      try { document.execCommand('copy'); toast('已复制这条新闻的站内链接'); }
      catch(err){ toast('复制失败，地址栏里可直接看到：#/read/'+state.cur); }
      ta.remove();
    }
    if (navigator.clipboard && navigator.clipboard.writeText){
      navigator.clipboard.writeText(url).then(function(){ toast('已复制这条新闻的站内链接'); }, fallback);
    } else fallback();
  });

  $('#q').addEventListener('input', function(e){ state.q = e.target.value; render(); });
  function clearFilter(){
    state.q=''; state.cat='全部'; state.view='全部'; $('#q').value=''; render();
  }
  $('#clearBtn').addEventListener('click', clearFilter);
  $('#cabClearBtn').addEventListener('click', clearFilter);
  $('#mClearBtn').addEventListener('click', clearFilter);
  $('#rClearBtn').addEventListener('click', clearFilter);
  $('#uClearBtn').addEventListener('click', clearFilter);
  // 列表页开关：开启 / 关闭「本站模型估算」，选择记在本地
  var estBtn = $('#uEstToggle');
  if (estBtn){
    estBtn.addEventListener('click', function(){
      state.showEstimate = !state.showEstimate;
      LS.set('bd50_estimate_on', state.showEstimate);
      applyEstimateToggle();
    });
    estBtn.setAttribute('aria-pressed', String(state.showEstimate));
    estBtn.textContent = state.showEstimate
      ? '模型估算：已开启（点击关闭）' : '模型估算：已关闭（点击开启）';
  }
  $('#themeBtn').addEventListener('click', function(){
    state.theme = state.theme==='dark'?'light':'dark'; applyTheme();
  });
  // 没有可播集锦时，顶部横幅直接把人带到有内容的「正赛赛果」
  function gotoMatches(){ setMode(clipsArr().length ? 'matches' : 'results'); syncViewHash(); }
  $('#clipBanner').addEventListener('click', gotoMatches);
  $('#clipBanner').addEventListener('keydown', function(e){
    if (e.key==='Enter' || e.key===' '){ e.preventDefault(); gotoMatches(); }
  });

  document.addEventListener('keydown', function(e){
    if (e.key==='Escape'){
      var tb = document.querySelector('.rd-video.theater');
      if (tb){ e.preventDefault(); fsExit(tb); return; }  // 剧场模式：Esc 先退全屏
      if (fsEl()) return;                                 // 原生全屏交给浏览器自己退
      if (state.cur || state.matchId || state.fixtureId){ closeReader(); return; }
      if (document.activeElement===$('#q')){ clearFilter(); $('#q').blur(); return; }
    }
    if (state.cur){
      if (e.key==='ArrowLeft' && byRank(state.cur-1)){ e.preventDefault(); openReader(state.cur-1,false); }
      if (e.key==='ArrowRight' && byRank(state.cur+1)){ e.preventDefault(); openReader(state.cur+1,false); }
      return;
    }
    if (state.matchId || state.fixtureId) return;
    if ((e.key==='Enter' || e.key===' ') && document.activeElement
        && document.activeElement.hasAttribute('data-fixture')){
      e.preventDefault(); document.activeElement.click(); return;
    }
    if (e.key==='/' && document.activeElement!==$('#q')){ e.preventDefault(); $('#q').focus(); }
  });

  window.addEventListener('popstate', readFromHash);
  window.addEventListener('hashchange', readFromHash);

  var toTop = $('#toTop');
  window.addEventListener('scroll', function(){ toTop.classList.toggle('show', window.scrollY>600); }, {passive:true});
  toTop.addEventListener('click', function(){ window.scrollTo({top:0, behavior:'smooth'}); });

  $('#refreshBtn').addEventListener('click', function(){
    if (location.protocol === 'file:'){
      toast('离线快照模式：运行同目录「更新新闻.bat」即可抓取最新数据');
      return;
    }
    var btn = $('#refreshBtn'); btn.classList.add('spin'); btn.disabled = true;
    fetch('news.json', {cache:'no-store'})
      .then(function(r){ if(!r.ok) throw new Error('HTTP '+r.status); return r.json(); })
      .catch(function(){ return fetch('/api/news?refresh=1', {cache:'no-store'})
                          .then(function(r){ if(!r.ok) throw new Error('HTTP '+r.status); return r.json(); }); })
      .then(function(r){ if(!r.ok) throw new Error('HTTP '+r.status); return r.json(); })
      .then(function(d){
        if (!d.items || !d.items.length) throw new Error('返回数据为空');
        DATA = d;
        try { applyRollingWindow(); applyInternationalMode(); } catch (e) {}
        renderHeader(); render();
        if (state.cur || state.matchId || state.fixtureId) renderReader();
        $('#sMode').innerHTML = '<i></i>最新快照';
        toast('已载入最新 '+d.items.length+' 条 · '+d.updated_at);
      })
      .catch(function(err){
        var m = String(err && err.message || '');
        // 线上静态分享版没有 /api/news 接口（404 或直接返回 HTML），给准确说明而不是报错
        if (/404|405|501|Unexpected token|JSON|SyntaxError|Failed to fetch/i.test(m)) {
          toast('暂未取到新快照，页面仍是上次成功的数据；新数据每天由 GitHub Actions 同步一次');
        } else {
          toast('刷新失败：'+m+'（页面仍显示上次成功的数据）');
        }
      })
      .finally(function(){ btn.classList.remove('spin'); btn.disabled=false; });
  });

  /* ---------------- 启动 ---------------- */
  applyTheme();
  renderHeader();
  render();
  var h0 = decodeURIComponent(location.hash || '');
  if (h0.indexOf('#/cabinet') === 0) setMode('cabinet');
  else if (h0.indexOf('#/matches') === 0) setMode('matches');
  else if (h0.indexOf('#/results') === 0) setMode('results');
  else if (h0.indexOf('#/upcoming') === 0) setMode('upcoming');
  else setMode('board');
  if (h0.indexOf('#/search/') === 0){ state.q = h0.slice(9); $('#q').value = state.q; render(); }
  var m0  = h0.match(/^#\/read\/(\d+)/),
      mm0 = h0.match(/^#\/match\/([A-Za-z0-9_-]+)/),
      ff0 = h0.match(/^#\/fixture\/([A-Za-z0-9_-]+)/);
  if (m0){ state.cur = parseInt(m0[1],10); renderReader(); }
  else if (mm0 && byMatch(mm0[1])){ state.matchId = mm0[1]; renderReader(); }
  else if (ff0 && byFixture(ff0[1])){ state.fixtureId = ff0[1]; renderReader(); }
})();
