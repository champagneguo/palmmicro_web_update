import json
import threading
import time
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timezone, timedelta

class Dashboard:
    """轻量级 Web Dashboard，展示配对交易数据"""

    BEIJING_TZ = timezone(timedelta(hours=8))

    # 代码 → 中文名 (A股基金)
    SYMBOL_NAMES = {
        'SH501018': '南方原油',
        'SZ160719': '嘉实黄金',
        'SZ160723': '嘉实原油',
        'SZ161116': '黄金主题',
        'SZ161129': '原油易方达',
        'SZ161226': '国投白银',
        'SZ164701': '黄金LOF',
        'SZ164824': '印度基金',
        'SZ165513': '中信保诚商品',
    }
    # 对冲代码 → 中文名 (海外ETF/期货)
    HEDGE_NAMES = {
        'USO': '美国原油ETF',
        'GLD': '黄金ETF',
        'INDA': '印度ETF',
        'nf_AG0': '沪银主力',
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
<div class="table-wrap">
  <div id="main"><div class="empty">加载中...</div></div>
</div>
<div class="footer">每 3 秒自动刷新 · Palmmicro</div>

<script>
var allRows = [];
var sortKey = '对冲代码';
var sortDir = 'asc';
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

function renderTable() {
  var main = document.getElementById('main');
  var rows = allRows.slice().sort(compareRows);

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
    var res = await fetch('/api/data');
    var data = await res.json();
    if (data.error) throw new Error(data.error);
    allRows = data;
    document.getElementById('rowCount').textContent = allRows.length;
    document.getElementById('updateTime').textContent = new Date().toLocaleString('zh-CN', {hour12:false});
    renderTable();
  } catch(e) {
    document.getElementById('main').innerHTML = '<div class="empty">连接失败，重试中...</div>';
  }
}
refresh();
setInterval(refresh, 3000);
</script>
</body>
</html>'''

    def __init__(self, pdf, host='0.0.0.0', port=40006):
        self.pdf = pdf
        self.host = host
        self.port = port
        self.server = None
        self.thread = None
        # 数据缓存: 多页面共享, 避免每次请求都重算
        self._cache_lock = threading.Lock()
        self._cache_body = None
        self._cache_time = 0.0
        self.CACHE_TTL = 1.0  # 秒

    def start(self):
        """启动 HTTP 服务器（后台线程）"""
        dashboard = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                pass  # 静默日志

            def do_GET(self):
                if self.path == '/api/data':
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
                        lambda x: f"{x}({dashboard.SYMBOL_NAMES[x]})" if x in dashboard.SYMBOL_NAMES else str(x))
                    df['对冲代码'] = df['对冲代码'].apply(
                        lambda x: f"{x}({dashboard.HEDGE_NAMES[x]})" if x in dashboard.HEDGE_NAMES else str(x))
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
