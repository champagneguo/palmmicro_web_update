import json
import os
import threading
import time
from urllib.parse import urlparse, parse_qs
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timezone, timedelta

class Dashboard:
    """轻量级 Web Dashboard，展示配对交易数据"""

    BEIJING_TZ = timezone(timedelta(hours=8))

    # 代码 → 中文名 (A股基金)
    SYMBOL_NAMES = {
        'SH501018': '南方原油',
        'SH513350': '标普油气ETF富国',
        'SZ159502': '标普生科',
        'SZ159518': '标普油气',
        'SZ159612': '标普500ETF',
        'SZ160125': '南方香港LOF',
        'SZ160719': '嘉实黄金',
        'SZ160723': '嘉实原油',
        'SZ161116': '黄金主题',
        'SZ161125': '标普500LOF',
        'SZ161126': '标普医药',
        'SZ161127': '标普生物',
        'SZ161129': '原油易方达',
        'SZ161130': '纳指LOF',
        'SZ161226': '国投白银',
        'SZ162411': '华宝油气',
        'SZ162415': '美国消费',
        'SZ162719': '广发石油',
        'SZ163208': '诺安油气',
        'SZ164701': '黄金LOF',
        'SZ164824': '印度基金',
        'SZ164906': '中国互联',
        'SZ165513': '中信保诚商品',
    }
    # 对冲代码 → 中文名 (海外ETF/期货)
    HEDGE_NAMES = {
        'DRIP': '标普油气2倍做空ETF',
        'GLD': '黄金ETF',
        'GUSH': '标普油气2倍做多ETF',
        'IEO': '美国油气勘探ETF',
        'INDA': '印度ETF',
        'KWEB': '中概网络股ETF',
        'nf_AG0': '沪银主力',
        'QQQ': '纳指100ETF',
        'RSPH': '标普医疗等权ETF',
        'SLV': '白银ETF',
        'SPY': '标普500ETF',
        'USO': '美国原油ETF',
        'XBI': '生物科技股ETF',
        'XLE': '能源ETF',
        'XLY': '可选消费ETF',
        'XOP': '油气勘探ETF',
        'hf_CL': '原油期货(小)',
        'hf_ES': '标普500期货(小)',
        'hf_GC': '黄金期货(小)',
        'hf_NQ': '纳指期货(小)',
        'hf_SI': '白银期货',
    }

    HTML = r'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Palmmicro 实时数据</title>
<style>
:root {
  --bg: #f7f8fa;
  --card: #ffffff;
  --border: #e1e4e8;
  --text: #24292f;
  --muted: #57606a;
  --green: #1a7f37;
  --red: #cf222e;
  --header-bg: #f0f2f5;
}
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family: -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif; background:var(--bg); color:var(--text); padding:20px; }
.header { display:flex; justify-content:space-between; align-items:flex-end; margin-bottom:16px; flex-wrap:wrap; gap:8px; }
.header h1 { font-size:20px; font-weight:700; letter-spacing:0.5px; }
.header h1 .badge { display:inline-block; font-size:11px; font-weight:600; color:#fff; background:#24292f; border-radius:10px; padding:2px 8px; vertical-align:middle; margin-left:6px; }
.meta { font-size:12px; color:var(--muted); }
.meta .rowcount { font-weight:600; color:var(--text); }
.table-wrap { background:var(--card); border:1px solid var(--border); border-radius:8px; overflow:auto; box-shadow:0 1px 3px rgba(0,0,0,0.05); }
table { border-collapse:collapse; width:100%; font-size:13px; }
thead th { position:sticky; top:0; background:var(--header-bg); z-index:1; }
th { border-bottom:1px solid var(--border); padding:8px 12px; text-align:left; white-space:nowrap; cursor:pointer; user-select:none; font-weight:600; }
th:hover { background:#e6e9ed; }
th .arrow { color:#0969da; font-size:11px; margin-left:4px; }
td { border-bottom:1px solid #f0f1f3; padding:6px 12px; white-space:nowrap; }
tbody tr:nth-child(even) { background:#fafbfc; }
tbody tr:hover { background:#f0f6ff; }
td.pct.pos { color:var(--green); font-weight:600; }
td.pct.neg { color:var(--red); font-weight:600; }
td.dir { font-weight:500; }
td.dir.buy { color:var(--green); }
td.dir.sell { color:var(--red); }
.note-cell { white-space:normal; min-width:180px; max-width:400px; color:var(--muted); font-size:12px; }
.empty { text-align:center; color:var(--muted); padding:60px; font-size:14px; }
.footer { text-align:center; color:#8b949e; font-size:11px; margin-top:12px; }
.filter-bar { display:flex; align-items:center; gap:10px; margin-bottom:12px; flex-wrap:wrap; }
.filter-bar label { font-size:13px; font-weight:600; color:var(--muted); }
.filter-bar select { padding:4px 8px; border:1px solid var(--border); border-radius:6px; font-size:13px; background:var(--card); color:var(--text); cursor:pointer; }
.filter-bar select:focus { outline:2px solid #0969da; outline-offset:-1px; }
.filter-badge { display:inline-block; font-size:11px; background:#ddf4ff; color:#0969da; border-radius:10px; padding:1px 8px; cursor:pointer; }
.filter-badge.active { background:#0969da; color:#fff; }
</style>
</head>
<body>
<div class="header">
  <h1>Palmmicro 实时数据<span class="badge" id="live">LIVE</span></h1>
  <div class="meta">
    共 <span class="rowcount" id="rowCount">--</span> 行
    &nbsp;|&nbsp; 更新于 <span id="updateTime">--</span>
    &nbsp;|&nbsp; <span id="sortHint">点击表头排序</span>
  </div>
</div>
<div class="filter-bar">
  <label for="hedgeFilter">对冲代码:</label>
  <select id="hedgeFilter" onchange="applyFilter(this.value)">
    <option value="">全部</option>
  </select>
  <span id="filterCount" style="font-size:12px;color:var(--muted);"></span>
</div>
<div class="table-wrap">
  <div id="main"><div class="empty">加载中...</div></div>
</div>
<div class="footer">每 3 秒自动刷新 · Palmmicro</div>

<script>
var allRows = [];
var sortKey = '对冲代码';
var sortDir = 'asc';
var filterHedge = '';
var TOKEN = new URLSearchParams(location.search).get('token') || '';
var COLUMNS = [
  {key:'代码',      type:'text'},
  {key:'对冲代码',   type:'text'},
  {key:'方向',      type:'text'},
  {key:'时间',      type:'text'},
  {key:'溢价',      type:'pct'},
  {key:'数量',      type:'num'},
  {key:'价格',      type:'num'},
  {key:'对冲数量',   type:'num'},
  {key:'对冲价格',   type:'num'},
  {key:'补充内容',   type:'text'}
];

function esc(s) { return String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }

function valNum(v) {
  if (v == null) return -Infinity;
  if (typeof v === 'number') return v;
  var s = String(v).replace('%','').trim();
  var n = parseFloat(s);
  return isNaN(n) ? -Infinity : n;
}

function compareRows(a, b) {
  var col = COLUMNS.find(function(c){ return c.key === sortKey; });
  var va = a[sortKey], vb = b[sortKey];
  var cmp;
  if (col && col.type === 'num') {
    cmp = valNum(va) - valNum(vb);
  } else if (col && col.type === 'pct') {
    cmp = valNum(va) - valNum(vb);
  } else {
    cmp = String(va||'').localeCompare(String(vb||''));
  }
  return sortDir === 'asc' ? cmp : -cmp;
}

function applyFilter(value) {
  filterHedge = value;
  var filtered = allRows;
  if (filterHedge) {
    filtered = allRows.filter(function(r) {
      var code = String(r['对冲代码']||'').replace(/\(.*\)$/, '');
      return code === filterHedge;
    });
  }
  document.getElementById('filterCount').textContent = filterHedge ? '(筛选后 ' + filtered.length + ' / ' + allRows.length + ' 行)' : '';
  renderTable();
}

function populateFilter() {
  var sel = document.getElementById('hedgeFilter');
  var selected = sel.value;
  var seen = {};
  var opts = ['<option value="">全部</option>'];
  for (var i=0; i<allRows.length; i++) {
    var raw = allRows[i]['对冲代码'];
    // 提取纯代码 (去掉中文名后缀)
    var code = String(raw||'').replace(/\(.*\)$/, '');
    if (code && !seen[code]) {
      seen[code] = true;
      var selectedAttr = code === selected ? ' selected' : '';
      opts.push('<option value="' + esc(code) + '"' + selectedAttr + '>' + esc(raw) + '</option>');
    }
  }
  sel.innerHTML = opts.join('');
}

function renderTable() {
  var main = document.getElementById('main');
  var rows = allRows.slice().sort(compareRows);

  // 按对冲代码筛选
  if (filterHedge) {
    rows = rows.filter(function(r) {
      var raw = String(r['对冲代码']||'');
      var code = raw.replace(/\(.*\)$/, '');
      return code === filterHedge;
    });
  }

  if (!rows.length) {
    main.innerHTML = '<div class="empty">暂无数据</div>';
    return;
  }

  var h = '<table><thead><tr>';
  for (var i=0; i<COLUMNS.length; i++) {
    var c = COLUMNS[i];
    var arrow = c.key === sortKey ? (sortDir==='asc' ? '▲' : '▼') : '';
    h += '<th onclick="setSort(\''+c.key+'\')">'+c.key+'<span class="arrow">'+arrow+'</span></th>';
  }
  h += '</tr></thead><tbody>';

  for (var r=0; r<rows.length; r++) {
    var row = rows[r];
    var isNeg = row['折价'] || valNum(row['溢价']) < 0;
    var pctClass = isNeg ? 'neg' : 'pos';
    var dirClass = row['方向'] === '买入' ? 'buy' : 'sell';
    h += '<tr>';
    h += '<td>'+esc(row['代码'])+'</td>';
    h += '<td>'+esc(row['对冲代码'])+'</td>';
    h += '<td class="dir '+dirClass+'">'+esc(row['方向'])+'</td>';
    h += '<td>'+esc(row['时间'])+'</td>';
    h += '<td class="pct '+pctClass+'">'+esc(row['溢价'])+'</td>';
    h += '<td>'+esc(row['数量'])+'</td>';
    h += '<td>'+esc(row['价格'])+'</td>';
    h += '<td>'+esc(row['对冲数量'])+'</td>';
    h += '<td>'+esc(row['对冲价格'])+'</td>';
    h += '<td class="note-cell">'+esc(row['补充内容'])+'</td>';
    h += '</tr>';
  }
  h += '</tbody></table>';
  main.innerHTML = h;
}

function setSort(key) {
  if (sortKey === key) {
    sortDir = sortDir === 'asc' ? 'desc' : 'asc';
  } else {
    sortKey = key;
    sortDir = key === '对冲代码' ? 'asc' : 'desc';
  }
  renderTable();
}

async function refresh() {
  try {
    var url = '/api/data' + (TOKEN ? '?token=' + encodeURIComponent(TOKEN) : '');
    var res = await fetch(url);
    if (res.status === 401) {
      document.getElementById('main').innerHTML = '<div class="empty">⚠ 访问令牌无效</div>';
      return;
    }
    var data = await res.json();
    if (data.error) throw new Error(data.error);
    allRows = data;
    document.getElementById('rowCount').textContent = allRows.length;
    document.getElementById('updateTime').textContent = new Date().toLocaleString('zh-CN', {hour12:false});
    populateFilter();
    renderTable();
    // 更新筛选计数
    var filtered = allRows;
    if (filterHedge) {
      filtered = allRows.filter(function(r) {
        var code = String(r['对冲代码']||'').replace(/\(.*\)$/, '');
        return code === filterHedge;
      });
    }
    document.getElementById('filterCount').textContent = filterHedge ? '(筛选后 ' + filtered.length + ' 行)' : '';
  } catch(e) {
    document.getElementById('main').innerHTML = '<div class="empty">连接失败，重试中...</div>';
  }
}
refresh();
setInterval(refresh, 3000);

// ngrok 免费版提示: 如果其他电脑打开是空白页, 说明被 ngrok 拦截页挡住了
// 请在空白页按 F12 打开控制台, 执行下面这行后刷新:
// document.cookie = 'ngrok-skip-browser-warning=1; path=/'; location.reload();
// 推荐改用 cloudflared: winget install Cloudflare.cloudflared
(function() {
  if (location.hostname.includes('ngrok-free')) {
    var banner = document.createElement('div');
    banner.style.cssText = 'background:#fff3cd;color:#856404;padding:8px 16px;font-size:12px;text-align:center;border-bottom:1px solid #ffc107;';
    banner.innerHTML = '桌面浏览器空白? <a href="https://downloads.cloudflared.com/" target="_blank">安装cloudflared</a> 替代ngrok, 或在空白页F12控制台执行: <code>document.cookie="ngrok-skip-browser-warning=1;path=/";location.reload()</code>';
    document.body.insertBefore(banner, document.body.firstChild);
  }
})();
</script>
</body>
</html>'''

    def __init__(self, pdf, host='0.0.0.0', port=40006, token=None,
                 extra_symbol_names=None, extra_hedge_names=None):
        self.pdf = pdf
        self.host = host
        self.port = port
        # 访问令牌: 优先用显式参数, 否则从环境变量读取; 空表示不鉴权(仅本地)
        self.token = token if token is not None else os.environ.get('DASHBOARD_TOKEN', '')
        self.server = None
        self.thread = None
        # 数据缓存: 多页面共享, 避免每次请求都重算
        self._cache_lock = threading.Lock()
        self._cache_body = None
        self._cache_time = 0.0
        self.CACHE_TTL = 1.0  # 秒
        # 合并额外传入的中文名映射（可运行时动态扩展）
        self.symbol_names = dict(self.SYMBOL_NAMES)
        if extra_symbol_names:
            self.symbol_names.update(extra_symbol_names)
        self.hedge_names = dict(self.HEDGE_NAMES)
        if extra_hedge_names:
            self.hedge_names.update(extra_hedge_names)

    def start(self):
        """启动 HTTP 服务器（后台线程）"""
        dashboard = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                pass  # 静默日志

            def _check_auth(self):
                """返回 True 表示通过校验; False 表示未授权(已发送401)"""
                if not dashboard.token:
                    return True
                q = parse_qs(urlparse(self.path).query)
                provided = q.get('token', [''])[0]
                if provided == dashboard.token:
                    return True
                self.send_response(401)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.end_headers()
                self.wfile.write(json.dumps({'error': 'unauthorized'}).encode('utf-8'))
                return False

            def do_GET(self):
                if not self._check_auth():
                    return
                if self.path.split('?')[0] == '/api/data':
                    self._serve_data()
                else:
                    self._serve_html()

            def _get_data(self):
                """带缓存地生成数据, 多请求共享"""
                now = time.monotonic()
                with dashboard._cache_lock:
                    if dashboard._cache_body is not None and now - dashboard._cache_time < dashboard.CACHE_TTL:
                        return dashboard._cache_body
                try:
                    df = dashboard.pdf.GetDisplayDataFrame()
                    # GetDisplayDataFrame 会把重复的代码/对冲代码置空(树形显示用)
                    # web 表格需要每行都显示完整代码, 用前向填充补全
                    df['代码'] = df['代码'].replace('', None).ffill()
                    df['对冲代码'] = df['对冲代码'].replace('', None).ffill()
                    # 补充内容也替换 NaN 为空字符串, 保证 JSON 干净
                    df = df.fillna('')
                    # 追加简短中文名: 代码(中文名)
                    df['代码'] = df['代码'].apply(
                        lambda x: f"{x}({dashboard.symbol_names[x]})" if x in dashboard.symbol_names else str(x))
                    df['对冲代码'] = df['对冲代码'].apply(
                        lambda x: f"{x}({dashboard.hedge_names[x]})" if x in dashboard.hedge_names else str(x))
                    data = df.to_dict(orient='records')
                    body = json.dumps(data, ensure_ascii=False, default=str).encode('utf-8')
                except Exception as e:
                    body = json.dumps({'error': str(e)}).encode('utf-8')
                with dashboard._cache_lock:
                    dashboard._cache_body = body
                    dashboard._cache_time = now
                return body

            def _serve_data(self):
                body = self._get_data()

                self.send_response(200)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(body)

            def _serve_html(self):
                body = Dashboard.HTML.encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.end_headers()
                self.wfile.write(body)

        self.server = ThreadingHTTPServer((self.host, self.port), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True, name='Dashboard')
        self.thread.start()
        print(f"Dashboard 已启动: http://127.0.0.1:{self.port}")

    def stop(self):
        """停止服务器"""
        if self.server:
            self.server.shutdown()
            print("Dashboard 已停止")
