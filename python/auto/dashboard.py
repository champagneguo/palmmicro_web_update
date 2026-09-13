import json
import os
import threading
import time
from urllib.parse import urlparse, parse_qs
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timezone, timedelta

import qmt_client
import qmt_trade

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
        'SZ159985': '豆粕ETF',
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
        'nf_M0': '豆粕主力',
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
    # 对冲代码分类 (用于分组筛选)
    HEDGE_CATEGORIES = {
        '原油': ['USO', 'hf_CL'],
        'XOP油气': ['DRIP', 'GUSH', 'IEO', 'XLE', 'XOP'],
        '黄金白银': ['GLD', 'SLV', 'nf_AG0', 'hf_GC', 'hf_SI'],
        '其他': ['INDA', 'KWEB', 'QQQ', 'RSPH', 'SPY', 'XBI', 'XLY', 'hf_ES', 'hf_NQ'],
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
.filter-badges { display:inline-flex; gap:6px; flex-wrap:wrap; }
.filter-badge { display:inline-block; font-size:12px; background:#eef2f6; color:var(--text); border:1px solid var(--border); border-radius:16px; padding:4px 12px; cursor:pointer; user-select:none; transition:all .15s; }
.filter-badge:hover { border-color:#0969da; color:#0969da; }
.filter-badge.active { background:#0969da; color:#fff; border-color:#0969da; }
.order-btn { padding:3px 10px; border-radius:5px; font-size:12px; cursor:pointer; border:1px solid; margin:1px 2px; white-space:nowrap; }
.order-btn.buy { background:#e6ffec; color:#1a7f37; border-color:#1a7f37; }
.order-btn.sell { background:#ffebe9; color:#cf222e; border-color:#cf222e; }
.order-btn:hover { opacity:0.85; }
.modal-overlay { display:none; position:fixed; inset:0; background:rgba(0,0,0,0.4); align-items:center; justify-content:center; z-index:100; }
.modal { background:var(--card); border-radius:8px; padding:20px; min-width:300px; box-shadow:0 8px 24px rgba(0,0,0,0.2); }
.modal-title { font-size:15px; font-weight:700; margin-bottom:14px; }
.modal-row { margin-bottom:12px; }
.modal-row label { display:block; font-size:13px; color:var(--muted); margin-bottom:4px; }
.modal-row input { width:100%; padding:6px 8px; border:1px solid var(--border); border-radius:6px; font-size:14px; }
.modal-actions { display:flex; justify-content:flex-end; gap:8px; margin-top:16px; }
.modal-actions button { padding:6px 16px; border-radius:6px; font-size:13px; cursor:pointer; border:none; }
.modal-actions .cancel { background:#eef2f6; color:var(--text); }
.modal-actions .ok { background:#0969da; color:#fff; font-weight:600; }
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
  <label>大类:</label>
  <span id="categoryFilter" class="filter-badges"></span>
  <label for="hedgeFilter">对冲代码:</label>
  <select id="hedgeFilter" onchange="applyFilter(this.value)">
    <option value="">全部</option>
  </select>
  <span id="filterCount" style="font-size:12px;color:var(--muted);"></span>
</div>
<div class="table-wrap">
  <div id="main"><div class="empty">加载中...</div></div>
</div>

<div class="header" style="margin-top:28px; margin-bottom:12px;">
  <h1 style="font-size:16px;">通达信 FUTURESETF 期货ETF溢价率
    <a href="/history" id="histLink" style="font-size:12px; font-weight:600; color:#0969da; margin-left:12px; text-decoration:none;">历史溢价率 →</a>
  </h1>
</div>
<div class="table-wrap">
  <div id="futureEtf"><div class="empty">加载中...</div></div>
</div>

<div class="footer">每 3 秒自动刷新 · Palmmicro</div>

<div class="modal-overlay" id="orderModal">
  <div class="modal">
    <div class="modal-title" id="modalTitle">下单</div>
    <div class="modal-row">
      <label for="modalPrice">价格</label>
      <input id="modalPrice" type="number" step="0.001" placeholder="价格">
    </div>
    <div class="modal-row">
      <label for="modalVolume">数量(股)</label>
      <input id="modalVolume" type="number" min="100" step="100" placeholder="数量">
    </div>
    <div class="modal-actions">
      <button class="cancel" onclick="closeModal()">取消</button>
      <button class="ok" onclick="confirmOrder()">确认</button>
    </div>
  </div>
</div>

<script>
var HEDGE_NAMES = __HEDGE_NAMES_JSON__;
var HEDGE_GROUPS = __HEDGE_GROUPS_JSON__;
var CATEGORY_ORDER = Object.keys(HEDGE_GROUPS);
var allRows = [];
var sortKey = '对冲代码';
var sortDir = 'asc';
var filterCategory = '';
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
  {key:'下单',      type:'text'},
  {key:'补充内容',   type:'text'},
  {key:'通达信溢价率', type:'pct'}
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

function rowCode(row) {
  return String(row['对冲代码'] || '').replace(/\(.*\)$/, '');
}

function rowMatches(row) {
  var code = rowCode(row);
  if (filterHedge) return code === filterHedge;
  if (filterCategory) {
    var codes = HEDGE_GROUPS[filterCategory] || [];
    return codes.indexOf(code) >= 0;
  }
  return true;
}

function updateFilterCount() {
  var filtered = allRows.filter(rowMatches);
  document.getElementById('filterCount').textContent =
    (filterCategory || filterHedge) ? '(筛选后 ' + filtered.length + ' / ' + allRows.length + ' 行)' : '';
}

function setCategory(btn) {
  filterCategory = btn.getAttribute('data-cat');
  filterHedge = '';  // 切换大类时重置具体对冲代码
  // 更新大类按钮高亮
  var btns = document.querySelectorAll('#categoryFilter .filter-badge');
  for (var i = 0; i < btns.length; i++) {
    var c = btns[i].getAttribute('data-cat');
    btns[i].className = 'filter-badge' + (c === filterCategory ? ' active' : '');
  }
  populateFilter();
  updateFilterCount();
  renderTable();
}

function applyFilter(value) {
  filterHedge = value;
  updateFilterCount();
  renderTable();
}

function populateCategoryFilter() {
  var box = document.getElementById('categoryFilter');
  var btns = ['<button type="button" class="filter-badge active" data-cat="" onclick="setCategory(this)">全部</button>'];
  for (var i = 0; i < CATEGORY_ORDER.length; i++) {
    var cat = CATEGORY_ORDER[i];
    btns.push('<button type="button" class="filter-badge" data-cat="' + esc(cat) + '" onclick="setCategory(this)">' + esc(cat) + '</button>');
  }
  box.innerHTML = btns.join('');
}

function populateFilter() {
  // 对冲代码静态列出并按大类分组 (不用等数据下载), 点击即可筛选
  var sel = document.getElementById('hedgeFilter');
  var selected = filterHedge;
  var opts = ['<option value="">全部</option>'];
  var cats = filterCategory ? [filterCategory] : CATEGORY_ORDER;
  for (var i = 0; i < cats.length; i++) {
    var cat = cats[i];
    var codes = HEDGE_GROUPS[cat] || [];
    opts.push('<optgroup label="' + esc(cat) + '">');
    for (var j = 0; j < codes.length; j++) {
      var code = codes[j];
      if (!(code in HEDGE_NAMES)) continue;
      var label = code + '(' + HEDGE_NAMES[code] + ')';
      var selectedAttr = code === selected ? ' selected' : '';
      opts.push('<option value="' + esc(code) + '"' + selectedAttr + '>' + esc(label) + '</option>');
    }
    opts.push('</optgroup>');
  }
  sel.innerHTML = opts.join('');
}

function renderTable() {
  var main = document.getElementById('main');
  var rows = allRows.slice().sort(compareRows);

  // 按大类/对冲代码筛选
  rows = rows.filter(rowMatches);

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
    var tdx = row['通达信溢价率'];
    var tdxClass = (tdx && tdx !== '') ? (valNum(tdx) < 0 ? 'neg' : 'pos') : '';
    var dirClass = row['方向'] === '开仓' ? 'buy' : 'sell';
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
    h += '<td>'+orderCell(row)+'</td>';
    h += '<td class="note-cell">'+esc(row['补充内容'])+'</td>';
    h += '<td class="pct '+tdxClass+'">'+esc(row['通达信溢价率'])+'</td>';
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
    renderTable();
    updateFilterCount();
  } catch(e) {
    document.getElementById('main').innerHTML = '<div class="empty">连接失败，重试中...</div>';
  }
}
var pendingOrder = null;

function stripSuffix(v) { return String(v==null?'':v).replace(/\(.*\)$/, ''); }

function orderBtn(text, action, code, label, price) {
  return '<button type="button" class="order-btn ' + (action === '买入' ? 'buy' : 'sell') + '"'
    + ' data-action="' + esc(action) + '" data-code="' + esc(code) + '"'
    + ' data-label="' + esc(label) + '" data-price="' + esc(price) + '"'
    + ' onclick="openOrderModal(this)">' + esc(text) + '</button>';
}

function orderCell(row) {
  var dir = row['方向'];
  var code = stripSuffix(row['代码']);
  var hedge = stripSuffix(row['对冲代码']);
  var codePrice = row['价格'];
  var hedgePrice = row['对冲价格'];
  if (dir === '开仓') {
    return orderBtn('买入 ' + code, '买入', code, row['代码'], codePrice)
         + orderBtn('卖出 ' + hedge, '卖出', hedge, row['对冲代码'], hedgePrice);
  }
  return orderBtn('卖出 ' + code, '卖出', code, row['代码'], codePrice)
       + orderBtn('买入 ' + hedge, '买入', hedge, row['对冲代码'], hedgePrice);
}

function openOrderModal(btn) {
  pendingOrder = {
    action: btn.getAttribute('data-action'),
    code: btn.getAttribute('data-code'),
    label: btn.getAttribute('data-label')
  };
  document.getElementById('modalTitle').textContent = pendingOrder.action + ' ' + pendingOrder.label;
  document.getElementById('modalPrice').value = btn.getAttribute('data-price');
  document.getElementById('modalVolume').value = '';
  document.getElementById('orderModal').style.display = 'flex';
}

function closeModal() {
  document.getElementById('orderModal').style.display = 'none';
  pendingOrder = null;
}

function confirmOrder() {
  var price = document.getElementById('modalPrice').value;
  var volume = document.getElementById('modalVolume').value;
  if (!volume || !price) { alert('请填写数量 / 价格'); return; }
  // 占位实现: 具体下单逻辑待接入
  alert('下单(占位): ' + pendingOrder.action + ' ' + pendingOrder.code
        + ' 数量=' + volume + ' 价格=' + price);
  closeModal();
}

function renderFutureEtf(rows) {
  var box = document.getElementById('futureEtf');
  if (!rows.length) {
    box.innerHTML = '<div class="empty">暂无 FUTURESETF 数据</div>';
    return;
  }
  var cols = ['代码','底层主力合约','主力价格','最新价','基金净值(盘中)','溢价率(盘中)','历史百分位','买一价','卖一价','买一量','卖一量','更新时间','报告'];
  var h = '<table><thead><tr>';
  for (var i=0;i<cols.length;i++) { h += '<th>'+cols[i]+'</th>'; }
  h += '</tr></thead><tbody>';
  for (var r=0;r<rows.length;r++) {
    var row = rows[r];
    var code = String(row['代码']).split('(')[0];
    var pct = row['溢价率'];
    var pctClass = (pct && pct !== '') ? (valNum(pct) < 0 ? 'neg' : 'pos') : '';
    var hp = row['历史百分位'];
    var hpNum = valNum(hp);
    var hpClass = '', hpLabel = '';
    if (hp && hp !== '') {
      if (hpNum >= 80) { hpClass = 'neg'; hpLabel = ' 高估'; }
      else if (hpNum <= 20) { hpClass = 'pos'; hpLabel = ' 低估'; }
    }
    h += '<tr data-code="'+esc(code)+'" style="cursor:pointer">';
    h += '<td>'+esc(row['代码'])+'</td>';
    h += '<td>'+esc(row['底层主力合约'])+'</td>';
    h += '<td>'+esc(row['主力价格'])+'</td>';
    h += '<td>'+esc(row['最新价'])+'</td>';
    h += '<td>'+esc(row['基金净值'])+'</td>';
    h += '<td class="pct '+pctClass+'">'+esc(pct)+'</td>';
    h += '<td class="pct '+hpClass+'">'+esc(hp)+esc(hpLabel)+'</td>';
    h += '<td>'+esc(row['买一价'])+'</td>';
    h += '<td>'+esc(row['卖一价'])+'</td>';
    h += '<td>'+esc(row['买一量'])+'</td>';
    h += '<td>'+esc(row['卖一量'])+'</td>';
    h += '<td>'+esc(row['更新时间'])+'</td>';
    h += '<td><a href="'+esc(row['报告链接'])+'" target="_blank" rel="noopener">查看</a></td>';
    h += '</tr>';
  }
  h += '</tbody></table>';
  box.innerHTML = h;
}

// 点击 FUTURESETF 表格行 -> 跳转该 ETF 的历史溢价率页
document.getElementById('futureEtf').addEventListener('click', function(e) {
  if (e.target.closest('a')) return;  // "报告"链接自己跳转
  var tr = e.target.closest('tr[data-code]');
  if (!tr) return;
  var code = tr.getAttribute('data-code');
  window.location.href = '/history?code=' + encodeURIComponent(code) + (TOKEN ? '&token=' + encodeURIComponent(TOKEN) : '');
});

async function refreshFutureEtf() {
  try {
    var url = '/api/futuresetf' + (TOKEN ? '?token=' + encodeURIComponent(TOKEN) : '');
    var res = await fetch(url);
    if (res.status === 401) { return; }
    var data = await res.json();
    if (data && data.error) throw new Error(data.error);
    renderFutureEtf(Array.isArray(data) ? data : []);
  } catch(e) {
    document.getElementById('futureEtf').innerHTML = '<div class="empty">连接失败，重试中...</div>';
  }
}

populateCategoryFilter();
populateFilter();
refresh();
setInterval(refresh, 3000);
refreshFutureEtf();
setInterval(refreshFutureEtf, 3000);

// 历史溢价率二级页面链接(带上访问令牌)
var histLink = document.getElementById('histLink');
if (histLink) histLink.href = '/history' + (TOKEN ? '?token=' + encodeURIComponent(TOKEN) : '');

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

    # 历史溢价率二级页面 (通达信日K + 天天基金历史净值)
    HTML_HISTORY = r'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>历史溢价率 - Palmmicro</title>
<style>
:root {
  --bg:#f7f8fa; --card:#ffffff; --border:#e1e4e8; --text:#24292f; --muted:#57606a;
  --green:#1a7f37; --red:#cf222e; --link:#0969da;
  --chart-surface:#fcfcfb; --chart-ink:#0b0b0b; --chart-secondary:#52514e;
  --chart-muted:#898781; --chart-grid:#e1e0d9; --chart-baseline:#c3c2b7;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg:#0d1117; --card:#161b22; --border:#30363d; --text:#e6edf3; --muted:#8b949e;
    --green:#3fb950; --red:#f85149; --link:#58a6ff;
    --chart-surface:#1a1a19; --chart-ink:#ffffff; --chart-secondary:#c3c2b7;
    --chart-muted:#898781; --chart-grid:#2c2c2a; --chart-baseline:#383835;
  }
}
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family:-apple-system,"Segoe UI","Microsoft YaHei",sans-serif; background:var(--bg); color:var(--text); padding:20px; }
.header { display:flex; justify-content:space-between; align-items:center; margin-bottom:16px; flex-wrap:wrap; gap:8px; }
.header h1 { font-size:20px; font-weight:700; }
.header a.back { font-size:13px; color:var(--link); text-decoration:none; }
.filters { display:flex; gap:10px; align-items:center; margin-bottom:16px; flex-wrap:wrap; }
.filters label { font-size:13px; color:var(--muted); font-weight:600; }
.filters select { padding:5px 8px; border:1px solid var(--border); border-radius:6px; font-size:13px; background:var(--card); color:var(--text); cursor:pointer; }
.card { background:var(--card); border:1px solid var(--border); border-radius:8px; padding:16px; box-shadow:0 1px 3px rgba(0,0,0,0.05); margin-bottom:16px; }
.card h2 { font-size:13px; font-weight:600; color:var(--muted); margin-bottom:10px; }
.chart-wrap { position:relative; }
#chart { width:100%; height:auto; display:block; background:var(--chart-surface); border-radius:6px; }
#chart .area-pos { fill:var(--green); opacity:0.10; }
#chart .area-neg { fill:var(--red); opacity:0.10; }
#chart .line { fill:none; stroke:var(--chart-ink); stroke-width:2; stroke-linejoin:round; stroke-linecap:round; }
#chart .zero { stroke:var(--chart-baseline); stroke-width:1; }
#chart .grid { stroke:var(--chart-grid); stroke-width:1; }
#chart .axis { stroke:var(--chart-baseline); stroke-width:1; }
#chart .tick { fill:var(--chart-muted); font-size:11px; }
#chart .crosshair { stroke:var(--chart-secondary); stroke-width:1; }
.tooltip { position:absolute; pointer-events:none; background:var(--card); border:1px solid var(--border); border-radius:6px; padding:8px 10px; font-size:12px; box-shadow:0 4px 12px rgba(0,0,0,0.12); display:none; white-space:nowrap; }
.tooltip .k { color:var(--muted); line-height:1.6; }
.tooltip .v { font-weight:700; color:var(--text); }
.tooltip .pos { color:var(--green); font-weight:700; }
.tooltip .neg { color:var(--red); font-weight:700; }
.table-wrap { overflow:auto; }
table { border-collapse:collapse; width:100%; font-size:13px; }
th { text-align:right; border-bottom:1px solid var(--border); padding:6px 10px; color:var(--muted); font-weight:600; white-space:nowrap; }
th:first-child, td:first-child { text-align:left; }
td { border-bottom:1px solid var(--border); padding:5px 10px; text-align:right; font-variant-numeric:tabular-nums; white-space:nowrap; }
td.prem.pos { color:var(--green); font-weight:600; }
td.prem.neg { color:var(--red); font-weight:600; }
.empty { text-align:center; color:var(--muted); padding:40px; font-size:14px; }
.stats { display:flex; gap:12px; margin-bottom:16px; flex-wrap:wrap; }
.stat { flex:1; min-width:120px; background:var(--card); border:1px solid var(--border); border-radius:8px; padding:10px 14px; }
.stat .lbl { font-size:12px; color:var(--muted); }
.stat .val { font-size:20px; font-weight:700; margin-top:2px; font-variant-numeric:tabular-nums; }
.stat .val.pos { color:var(--green); }
.stat .val.neg { color:var(--red); }
#chart .refline-mean { stroke:var(--chart-muted); stroke-width:1; }
#chart .refline-low { stroke:var(--green); stroke-width:1; }
#chart .refline-high { stroke:var(--red); stroke-width:1; }
#chart .reflabel-mean { fill:var(--chart-muted); font-size:10px; }
#chart .reflabel-low { fill:var(--green); font-size:10px; }
#chart .reflabel-high { fill:var(--red); font-size:10px; }
</style>
</head>
<body>
<div class="header">
  <h1>历史溢价率</h1>
  <a class="back" href="/" id="backLink">← 返回实时面板</a>
</div>
<div class="filters">
  <label for="codeSelect">ETF:</label>
  <select id="codeSelect"></select>
  <label for="rangeSelect">区间:</label>
  <select id="rangeSelect">
    <option value="22">近1月</option>
    <option value="66">近3月</option>
    <option value="120">近半年</option>
    <option value="250" selected>近1年</option>
  </select>
</div>
<div class="stats">
  <div class="stat"><div class="lbl">百分位</div><div class="val" id="statPct">--</div></div>
  <div class="stat"><div class="lbl">平均值</div><div class="val" id="statMean">--</div></div>
  <div class="stat"><div class="lbl">低估线</div><div class="val" id="statLow">--</div></div>
  <div class="stat"><div class="lbl">高估线</div><div class="val" id="statHigh">--</div></div>
</div>
<div class="card">
  <h2>历史溢价率 (%) = 收盘价 / 收盘净值 − 1 · 绿=溢价 · 红=折价</h2>
  <div class="chart-wrap">
    <svg id="chart" viewBox="0 0 940 320" preserveAspectRatio="xMidYMid meet"></svg>
    <div class="tooltip" id="tooltip"></div>
  </div>
</div>
<div class="card">
  <h2>数据明细</h2>
  <div class="table-wrap"><div id="tableBox"><div class="empty">加载中...</div></div></div>
</div>
<script>
var TOKEN = new URLSearchParams(location.search).get('token') || '';
document.getElementById('backLink').href = '/' + (TOKEN ? '?token=' + encodeURIComponent(TOKEN) : '');
var SERIES = [];

function esc(s){ return String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
function api(path){ return path + (TOKEN ? ((path.indexOf('?')>=0?'&':'?') + 'token=' + encodeURIComponent(TOKEN)) : ''); }

async function loadCodes() {
  try {
    var res = await fetch(api('/api/futuresetf'));
    var data = await res.json();
    if (data && data.error) throw new Error(data.error);
    var labels = (data || []).map(function(r){ return String(r['代码']); });
    var initial = new URLSearchParams(location.search).get('code') || '';
    var sel = document.getElementById('codeSelect');
    var html = '';
    for (var i = 0; i < labels.length; i++) {
      var code = labels[i].split('(')[0];
      var selected = (initial && code === initial) || (!initial && i === 0);
      html += '<option value="'+esc(code)+'"'+(selected?' selected':'')+'>'+esc(labels[i])+'</option>';
    }
    sel.innerHTML = html;
    if (labels.length) loadHistory();
    else document.getElementById('tableBox').innerHTML = '<div class="empty">暂无 FUTURESETF 数据</div>';
  } catch(e) {
    document.getElementById('tableBox').innerHTML = '<div class="empty">连接失败</div>';
  }
}

async function loadHistory() {
  var code = document.getElementById('codeSelect').value;
  var count = document.getElementById('rangeSelect').value;
  try {
    var res = await fetch(api('/api/futuresetf/history?code=' + encodeURIComponent(code) + '&count=' + count));
    var data = await res.json();
    if (data && data.error) throw new Error(data.error);
    SERIES = (data && data.series) || [];
    renderChart(SERIES);
    renderTable(SERIES);
  } catch(e) {
    document.getElementById('tableBox').innerHTML = '<div class="empty">连接失败，重试中...</div>';
  }
}

function buildArea(series, X, Y, y0, sign) {
  var d = '', i = 0, n = series.length;
  while (i < n) {
    var p = series[i].premium;
    var ok = sign > 0 ? p >= 0 : p < 0;
    if (!ok) { i++; continue; }
    var j = i;
    while (j < n && (sign > 0 ? series[j].premium >= 0 : series[j].premium < 0)) j++;
    var x0 = X(i), x1 = X(j-1);
    var seg = 'M ' + x0 + ' ' + Y(series[i].premium);
    for (var k = i+1; k < j; k++) seg += ' L ' + X(k) + ' ' + Y(series[k].premium);
    seg += ' L ' + x1 + ' ' + y0 + ' L ' + x0 + ' ' + y0 + ' Z';
    d += seg;
    i = j;
  }
  return d;
}

function quantile(arr, q) {
  var a = arr.slice().sort(function(x,y){ return x-y; });
  var pos = (a.length - 1) * q;
  var base = Math.floor(pos);
  var rest = pos - base;
  if (a[base+1] !== undefined) return a[base] + rest * (a[base+1] - a[base]);
  return a[base];
}
function fmtPct(v) { return (v*100).toFixed(2) + '%'; }

function renderChart(series) {
  var svg = document.getElementById('chart');
  var W = 940, H = 320, padL = 58, padR = 88, padT = 16, padB = 34;
  var iw = W - padL - padR, ih = H - padT - padB;
  var n = series.length;
  var sp = document.getElementById('statPct');
  var sm = document.getElementById('statMean');
  var sl = document.getElementById('statLow');
  var sh = document.getElementById('statHigh');
  if (!n) {
    svg.innerHTML = '<text class="tick" x="470" y="160" text-anchor="middle">暂无数据</text>';
    sp.textContent = '--'; sp.className = 'val';
    sm.textContent = '--'; sl.textContent = '--'; sh.textContent = '--';
    return;
  }
  var prem = series.map(function(d){ return d.premium; });
  var lo = Math.min(0, Math.min.apply(null, prem));
  var hi = Math.max(0, Math.max.apply(null, prem));
  if (hi - lo < 0.002) { lo -= 0.001; hi += 0.001; }
  var span = hi - lo;
  lo -= span * 0.10; hi += span * 0.10; span = hi - lo;
  var X = function(i){ return padL + (n <= 1 ? iw/2 : i * iw / (n - 1)); };
  var Y = function(v){ return padT + (hi - v) / span * ih; };
  var y0 = Y(0);
  // 统计量
  var mean = prem.reduce(function(a,b){ return a+b; }, 0) / n;
  var low = quantile(prem, 0.2);
  var high = quantile(prem, 0.8);
  var last = prem[n-1];
  var below = 0;
  for (var i = 0; i < n; i++) if (prem[i] < last) below++;
  var pct = below / n * 100;
  var s = '';
  var steps = 5;
  for (var g = 0; g <= steps; g++) {
    var v = lo + span * g / steps;
    var y = Y(v);
    s += '<line class="grid" x1="'+padL+'" y1="'+y+'" x2="'+(W-padR)+'" y2="'+y+'"/>';
    s += '<text class="tick" x="'+(padL-6)+'" y="'+(y+4)+'" text-anchor="end">'+(v*100).toFixed(2)+'%</text>';
  }
  var tickN = Math.min(6, n);
  for (var t = 0; t < tickN; t++) {
    var idx = Math.round(t * (n-1) / Math.max(1, tickN-1));
    s += '<text class="tick" x="'+X(idx)+'" y="'+(H-10)+'" text-anchor="middle">'+esc(series[idx].date.slice(5))+'</text>';
  }
  s += '<path class="area-pos" d="'+buildArea(series, X, Y, y0, +1)+'"/>';
  s += '<path class="area-neg" d="'+buildArea(series, X, Y, y0, -1)+'"/>';
  s += '<line class="zero" x1="'+padL+'" y1="'+y0+'" x2="'+(W-padR)+'" y2="'+y0+'"/>';
  function refLine(label, value, lineClass, labelClass) {
    var y = Y(value);
    return '<line class="'+lineClass+'" x1="'+padL+'" y1="'+y+'" x2="'+(W-padR)+'" y2="'+y+'"/>'
         + '<text class="'+labelClass+'" x="'+(W-padR+6)+'" y="'+(y+3)+'">'+label+' '+fmtPct(value)+'</text>';
  }
  s += refLine('均值', mean, 'refline-mean', 'reflabel-mean');
  s += refLine('低估', low, 'refline-low', 'reflabel-low');
  s += refLine('高估', high, 'refline-high', 'reflabel-high');
  var dLine = 'M ' + X(0) + ' ' + Y(series[0].premium);
  for (var i = 1; i < n; i++) dLine += ' L ' + X(i) + ' ' + Y(series[i].premium);
  s += '<path class="line" d="'+dLine+'"/>';
  s += '<line class="axis" x1="'+padL+'" y1="'+padT+'" x2="'+padL+'" y2="'+(H-padB)+'"/>';
  s += '<line class="axis" x1="'+padL+'" y1="'+(H-padB)+'" x2="'+(W-padR)+'" y2="'+(H-padB)+'"/>';
  s += '<line class="crosshair" id="ch" x1="0" y1="'+padT+'" x2="0" y2="'+(H-padB)+'" style="display:none"/>';
  svg.innerHTML = s;
  svg._series = series; svg._X = X; svg._Y = Y;
  // 头部统计
  var tag = pct >= 80 ? ' 高估' : (pct <= 20 ? ' 低估' : '');
  sp.textContent = pct.toFixed(1) + '%' + tag;
  sp.className = 'val ' + (pct >= 80 ? 'neg' : (pct <= 20 ? 'pos' : ''));
  sm.textContent = fmtPct(mean);
  sl.textContent = fmtPct(low);
  sh.textContent = fmtPct(high);
}

function renderTable(series) {
  var box = document.getElementById('tableBox');
  if (!series.length) { box.innerHTML = '<div class="empty">暂无数据</div>'; return; }
  var h = '<table><thead><tr><th>日期</th><th>收盘价</th><th>收盘净值</th><th>溢价率(收盘)</th></tr></thead><tbody>';
  for (var i = series.length - 1; i >= 0; i--) {
    var d = series[i];
    var p = d.premium * 100;
    var cls = p < 0 ? 'neg' : 'pos';
    h += '<tr><td>'+esc(d.date)+'</td><td>'+d.price.toFixed(4)+'</td><td>'+d.nav.toFixed(4)+'</td><td class="prem '+cls+'">'+(p>=0?'+':'')+p.toFixed(2)+'%</td></tr>';
  }
  h += '</tbody></table>';
  box.innerHTML = h;
}

(function(){
  var svg = document.getElementById('chart');
  var tip = document.getElementById('tooltip');
  svg.addEventListener('mousemove', function(e){
    var s = svg._series; if (!s || !s.length) return;
    var rect = svg.getBoundingClientRect();
    var mx = (e.clientX - rect.left) / rect.width * 940;
    var best = 0, bd = Infinity;
    for (var i = 0; i < s.length; i++) { var dx = Math.abs(svg._X(i) - mx); if (dx < bd) { bd = dx; best = i; } }
    var d = s[best];
    var p = d.premium * 100;
    tip.innerHTML = '<div class="k">'+esc(d.date)+'</div>'
      + '<div class="k">溢价率 <span class="'+(p<0?'neg':'pos')+'">'+(p>=0?'+':'')+p.toFixed(2)+'%</span></div>'
      + '<div class="k">收盘价 <span class="v">'+d.price.toFixed(4)+'</span></div>'
      + '<div class="k">净值 <span class="v">'+d.nav.toFixed(4)+'</span></div>';
    tip.style.display = 'block';
    var ch = document.getElementById('ch');
    if (ch) { ch.setAttribute('x1', svg._X(best)); ch.setAttribute('x2', svg._X(best)); ch.style.display = ''; }
    tip.style.left = Math.min(svg._X(best) / 940 * rect.width + 14, rect.width - 160) + 'px';
    tip.style.top = Math.max(svg._Y(d.premium) / 320 * rect.height - 12, 0) + 'px';
  });
  svg.addEventListener('mouseleave', function(){
    tip.style.display = 'none';
    var ch = document.getElementById('ch'); if (ch) ch.style.display = 'none';
  });
})();

document.getElementById('codeSelect').addEventListener('change', loadHistory);
document.getElementById('rangeSelect').addEventListener('change', loadHistory);
loadCodes();
</script>
</body>
</html>'''

    def __init__(self, pdf, host='0.0.0.0', port=40006, token=None,
                 extra_symbol_names=None, extra_hedge_names=None,
                 future_etf_stock=None):
        self.pdf = pdf
        self.host = host
        self.port = port
        # 通达信 FUTURESETF 板块数据源(可选), 用于第二个表格展示溢价率等接口数据
        self.future_etf_stock = future_etf_stock
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
        # 按大类分组; 未分类的对冲代码并入"其他"
        self.hedge_groups = {}
        for cat, codes in self.HEDGE_CATEGORIES.items():
            self.hedge_groups[cat] = [c for c in codes if c in self.hedge_names]
        extra = [c for c in self.hedge_names
                 if not any(c in codes for codes in self.hedge_groups.values())]
        if extra:
            self.hedge_groups.setdefault('其他', [])
            self.hedge_groups['其他'] += extra

    def start(self):
        """启动 HTTP 服务器（后台线程）"""
        dashboard = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                pass  # 静默日志

            def _is_local_host(self):
                """判断请求是否来自本机 (Host 头为 localhost/127.0.0.1/::1)"""
                host = self.headers.get('Host', '')
                hostname = host.rsplit(':', 1)[0].lower()
                return hostname in ('localhost', '127.0.0.1', '[::1]', '::1')

            def _check_auth(self):
                """返回 True 表示通过校验; False 表示未授权(已发送401)"""
                if not dashboard.token:
                    return True
                # 本地 4006 端口直接访问无需令牌, 只有公网隧道访问才校验
                if self._is_local_host():
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
                elif self.path.split('?')[0] == '/api/futuresetf':
                    self._serve_future_etf()
                elif self.path.split('?')[0] == '/api/futuresetf/history':
                    self._serve_future_etf_history()
                elif self.path.split('?')[0] == '/history':
                    self._serve_history_html()
                else:
                    self._serve_html()

            def do_POST(self):
                if not self._check_auth():
                    return
                if self.path.split('?')[0] == '/api/order':
                    self._handle_order()
                else:
                    self.send_response(404)
                    self.end_headers()

            def _handle_order(self):
                """处理手动下单请求（POST /api/order）"""
                try:
                    length = int(self.headers.get('Content-Length', 0))
                    body = self.rfile.read(length).decode('utf-8')
                    data = json.loads(body)
                except Exception:
                    data = {}

                code = (data.get('code') or '').strip()          # 通达信格式 SZ159985
                action = (data.get('action') or '').strip().upper()
                try:
                    volume = int(data.get('volume', 0))
                    price = float(data.get('price', 0))
                except (TypeError, ValueError):
                    volume = 0
                    price = 0.0
                account = (data.get('account') or '').strip()

                if not code or action not in ('BUY', 'SELL') or volume <= 0 or price <= 0:
                    resp = {"ok": False, "error": "参数错误: 需要 code/action/volume/price"}
                else:
                    qmt_code = qmt_client.tdx_to_qmt_code(code)
                    try:
                        resp = qmt_trade.place_order(action, qmt_code, volume, price, account or None)
                    except Exception as e:
                        resp = {"ok": False, "error": str(e)}

                out = json.dumps(resp, ensure_ascii=False, default=str).encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.end_headers()
                self.wfile.write(out)

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

            def _get_future_etf(self):
                """生成通达信 FUTURESETF 板块数据(第二个表格), 无数据源时返回空列表"""
                if dashboard.future_etf_stock is None:
                    return []
                try:
                    df = dashboard.future_etf_stock.GetDisplayDataFrame()
                    if df is None or df.empty:
                        return []
                    df = df.fillna('')
                    return df.to_dict(orient='records')
                except Exception as e:
                    return {'error': str(e)}

            def _serve_future_etf(self):
                data = self._get_future_etf()
                body = json.dumps(data, ensure_ascii=False, default=str).encode('utf-8')

                self.send_response(200)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(body)

            def _get_future_etf_history(self):
                """生成某只期货ETF 的历史溢价率序列 (GET /api/futuresetf/history)"""
                if dashboard.future_etf_stock is None:
                    return {'error': '无 FUTURESETF 数据源'}
                q = parse_qs(urlparse(self.path).query)
                code = q.get('code', [''])[0]
                try:
                    count = int(q.get('count', ['120'])[0])
                except ValueError:
                    count = 120
                if not code:
                    return {'error': '缺少 code 参数'}
                try:
                    series = dashboard.future_etf_stock.GetHistoricalPremium(code, count)
                    return {'code': code, 'series': series}
                except Exception as e:
                    return {'error': str(e)}

            def _serve_future_etf_history(self):
                data = self._get_future_etf_history()
                body = json.dumps(data, ensure_ascii=False, default=str).encode('utf-8')

                self.send_response(200)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(body)

            def _serve_history_html(self):
                body = Dashboard.HTML_HISTORY.encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.end_headers()
                self.wfile.write(body)

            def _serve_html(self):
                # 把静态对冲代码中文名与分类注入页面, 前端直接列出无需额外请求
                hedge_json = json.dumps(dashboard.hedge_names, ensure_ascii=False)
                groups_json = json.dumps(dashboard.hedge_groups, ensure_ascii=False)
                body = (Dashboard.HTML
                        .replace('__HEDGE_NAMES_JSON__', hedge_json)
                        .replace('__HEDGE_GROUPS_JSON__', groups_json)).encode('utf-8')
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
