// app.js — 沪金走势与因子预测原型
const COL = { gold: '#b8860b', blue: '#185FA5', muted: '#888', green: '#3B6D11', red: '#A32D2D' };

function loadJSON(p) {
  return fetch(p, { cache: 'no-store' }).then(r => r.json());
}
function ymd(d) {
  return d.getUTCFullYear() + '-' + String(d.getUTCMonth() + 1).padStart(2, '0') + '-' + String(d.getUTCDate()).padStart(2, '0');
}
function addDays(ds, n) {
  const d = new Date(ds + 'T00:00:00Z'); d.setUTCDate(d.getUTCDate() + n); return ymd(d);
}
function r2(x) { return Math.round(x * 100) / 100; }

let _sig = null, _bt = null, _rep = null;

// ---------- 当前信号卡 ----------
function renderSignal() {
  const s = _sig;
  document.getElementById('asof').textContent = `· 数据截至 ${s.as_of} · 样本 ${s.n_samples} 日`;
  const cards = [
    { k: '最新沪金', v: s.latest_gold.toFixed(2), cls: '' },
    { k: '21日 P(涨)', v: (s.latest_P_up_21d * 100).toFixed(1) + '%', cls: s.latest_P_up_21d >= 0.5 ? 'up' : 'down' },
    { k: '63日 P(涨)', v: (s.latest_P_up_63d * 100).toFixed(1) + '%', cls: s.latest_P_up_63d >= 0.5 ? 'up' : 'down' },
    { k: '21日预测收益', v: (s.latest_pred_ret_21d >= 0 ? '+' : '') + s.latest_pred_ret_21d + '%', cls: s.latest_pred_ret_21d >= 0 ? 'up' : 'down' },
    { k: '63日预测收益', v: (s.latest_pred_ret_63d >= 0 ? '+' : '') + s.latest_pred_ret_63d + '%', cls: s.latest_pred_ret_63d >= 0 ? 'up' : 'down' },
  ];
  document.getElementById('sig_cards').innerHTML = cards.map(c =>
    `<div class="card"><div class="k">${c.k}</div><div class="v ${c.cls}">${c.v}</div></div>`).join('');

  const vs = `21日方向准确率 <b>${ (s.rf_21d_accuracy*100).toFixed(1) }%</b>（盲赌总是涨仅 ${ (s.always_up_21d*100).toFixed(1) }%）· ` +
             `63日 <b>${ (s.rf_63d_accuracy*100).toFixed(1) }%</b>（盲赌 ${ (s.always_up_63d*100).toFixed(1) }%）。60日预测幅度带 ±${s.latest_pred_ret_63d_band}%（幅度难精确，方向更可靠）。`;
  document.getElementById('sig_line').innerHTML = vs;
}

// ---------- 历史回放：预测 vs 实际 两条线 ----------
function chartReplay(dateStr, horizon) {
  const info = document.getElementById('replay_info');
  const rep = _rep, gold = rep.gold;
  let rp = null;
  for (const r of rep.replay) { if (r.date <= dateStr) rp = r; else break; }
  if (!rp) { info.textContent = '该日期之前回放数据不足'; return; }
  const idx = gold.findIndex(g => g[0] === rp.date);
  if (idx < 0) { info.textContent = '未找到对应价格'; return; }
  const offH = horizon === 21 ? 21 : 63;
  const pr = horizon === 21 ? rp.pred_ret21 : rp.pred_ret63;
  const s = Math.max(0, idx - 60), endIdx = idx + offH;
  const dates = [], known = [], actual = [], pred = [];
  let cur = new Date(gold[s][0] + 'T00:00:00Z');
  const startP = gold[idx][1];
  for (let k = s; k <= endIdx; k++) {
    const gd = gold[k];
    const price = gd ? gd[1] : null;
    dates.push(gd ? gd[0] : ymd(cur));
    known.push((k <= idx && price != null) ? price : null);
    actual.push((k >= idx && price != null) ? price : null);
    if (k === idx) pred.push(price);
    else if (k === idx + offH && pr != null) pred.push(r2(startP * (1 + pr / 100)));
    else pred.push(null);
    cur.setUTCDate(cur.getUTCDate() + 1);
  }
  const c = echarts.getInstanceByDom(document.getElementById('c_replay')) || echarts.init(document.getElementById('c_replay'));
  c.setOption({
    tooltip: { trigger: 'axis' },
    legend: { data: ['已知历史', '模型预测路径', '预测后实际'], top: 0 },
    grid: { left: 55, right: 20, top: 36, bottom: 60 },
    xAxis: { type: 'category', data: dates, axisLabel: { rotate: 45, fontSize: 10 } },
    yAxis: { type: 'value', scale: true, name: '沪金(元/克)' },
    series: [
      { name: '已知历史', type: 'line', data: known, showSymbol: false, lineStyle: { color: COL.muted, width: 1.5 } },
      { name: '模型预测路径', type: 'line', data: pred, showSymbol: true, symbolSize: 9, connectNulls: true,
        lineStyle: { color: COL.blue, width: 2, type: 'dashed' }, itemStyle: { color: COL.blue },
        markPoint: { symbol: 'pin', symbolSize: 48, data: pr == null ? [] : [{ coord: [idx + offH - s, r2(startP * (1 + pr / 100))],
          value: (pr > 0 ? '+' : '') + pr.toFixed(1) + '%', itemStyle: { color: COL.blue } }] },
        markLine: { silent: true, symbol: 'none', lineStyle: { color: COL.red, type: 'dashed' },
          data: [{ xAxis: rp.date, label: { formatter: '预测日', position: 'end', color: COL.red } }] } },
      { name: '预测后实际', type: 'line', data: actual, showSymbol: false, lineStyle: { color: COL.gold, width: 2 } }
    ]
  }, true);

  const pUp = horizon === 21 ? rp.p21 : rp.p63;
  const act = horizon === 21 ? rp.ret21 : rp.ret63;
  const fmtP = v => v == null ? '未预测' : (v > 0 ? '+' : '') + v.toFixed(2) + '%';
  const fmt = v => v == null ? '未到期' : (v > 0 ? '涨 ' : '跌 ') + v.toFixed(2) + '%';
  let verdict = (act == null || pr == null) ? '（尚未到期，无法判对错）' : (Math.sign(act) === Math.sign(pr) ? '方向命中 ✅' : '方向未命中 ❌');
  info.innerHTML = `截至 <b>${rp.date}</b>（窗口 <b>${horizon}日</b>）：模型 P(up)=<b>${ (pUp*100).toFixed(1) }%</b>，` +
    `预测未来收益 <b>${fmtP(pr)}</b>，实际 <b>${fmt(act)}</b>。 ${verdict}`;
}

// ---------- 因子重要性 ----------
function chartFactors() {
  const imp = _sig.feature_importance.slice(0, 12).reverse();
  const c = echarts.init(document.getElementById('c_factors'));
  c.setOption({
    tooltip: { trigger: 'axis' },
    grid: { left: 120, right: 30, top: 20, bottom: 30 },
    xAxis: { type: 'value', name: '重要性' },
    yAxis: { type: 'category', data: imp.map(d => d.name) },
    series: [{ type: 'bar', data: imp.map(d => d.imp), itemStyle: { color: COL.gold },
      label: { show: true, position: 'right', formatter: p => (p.value * 100).toFixed(1) + '%' } }]
  });
}

// ---------- 策略回测 ----------
function chartBacktest() {
  const b = (_bt.h63 && _bt.h63.dates.length) ? _bt.h63 : (_bt.hcomb || _bt.h21);
  const c = echarts.init(document.getElementById('c_backtest'));
  c.setOption({
    tooltip: { trigger: 'axis' },
    legend: { data: ['模型信号策略', '买入持有'], top: 0 },
    grid: { left: 55, right: 20, top: 36, bottom: 50 },
    xAxis: { type: 'category', data: b.dates, axisLabel: { rotate: 45, fontSize: 10 } },
    yAxis: { type: 'value', scale: true, name: '净值' },
    series: [
      { name: '模型信号策略', type: 'line', data: b.strat_curve, showSymbol: false, lineStyle: { color: COL.blue, width: 2 } },
      { name: '买入持有', type: 'line', data: b.bnh_curve, showSymbol: false, lineStyle: { color: COL.gold, width: 1.5 } }
    ]
  });
}

// ---------- 上传自分析（技术面 + 缩放） ----------
function computeMA(prices, w) {
  const out = [], r = prices.map((_, i) => i === 0 ? 0 : prices[i] / prices[i - 1] - 1);
  for (let k = 0; k < prices.length; k++) {
    if (k < w - 1) { out.push(null); continue; }
    let s = 0; for (let j = k - w + 1; j <= k; j++) s += r[j];
    out.push(r2((prices[k] / prices[k - w + 1] - 1) * 100));
  }
  return out;
}
function readSheet(buf) {
  const wb = XLSX.read(buf, { type: 'array' });
  const ws = wb.Sheets[wb.SheetNames[0]];
  return XLSX.utils.sheet_to_json(ws, { header: 1, raw: false, defval: '' });
}
function parseRows(rows) {
  const header = rows[0].map(h => String(h).trim());
  const hasHeader = header.some(h => /date|日期|时间/i.test(h) || /close|price|gold|收盘|价格|au/i.test(h));
  const startRow = hasHeader ? 1 : 0;
  const dateIdx = header.findIndex(h => /date|日期|时间/i.test(h));
  const valIdx = header.findIndex(h => /close|price|gold|收盘|价格|au/i.test(h));
  const di = dateIdx >= 0 ? dateIdx : 0;
  const vi = valIdx >= 0 ? valIdx : (header.length > 1 ? 1 : 0);
  const dates = [], prices = [];
  for (let i = startRow; i < rows.length; i++) {
    const row = rows[i]; if (!row || row.length === 0) continue;
    const dv = row[di], pv = row[vi];
    const dt = new Date(String(dv)); const p = parseFloat(String(pv).replace(/,/g, ''));
    if (isNaN(p)) continue;
    dates.push(isNaN(dt) ? String(dv) : ymd(dt)); prices.push(p);
  }
  return { dates, prices };
}
function chartSelfAnalysis(dates, prices) {
  const ma20 = computeMA(prices, 20), ma60 = computeMA(prices, 60), ma252 = computeMA(prices, 252);
  const c = echarts.getInstanceByDom(document.getElementById('c_xlsx')) || echarts.init(document.getElementById('c_xlsx'));
  c.setOption({
    tooltip: { trigger: 'axis' }, legend: { data: ['价格', 'MA20', 'MA60', 'MA252'], top: 0 },
    grid: { left: 55, right: 20, top: 36, bottom: 80 },
    xAxis: { type: 'category', data: dates, axisLabel: { rotate: 45, fontSize: 10 } },
    yAxis: { type: 'value', scale: true, name: '价格' },
    dataZoom: [
      { type: 'inside', zoomOnMouseWheel: true, moveOnMouseMove: true, moveOnMouseWheel: false },
      { type: 'slider', bottom: 10, height: 18 }
    ],
    series: [
      { name: '价格', type: 'line', data: prices, showSymbol: false, lineStyle: { color: COL.gold, width: 2 } },
      { name: 'MA20', type: 'line', data: ma20, showSymbol: false, lineStyle: { color: COL.blue, width: 1.5 } },
      { name: 'MA60', type: 'line', data: ma60, showSymbol: false, lineStyle: { color: COL.muted, width: 1.5 } },
      { name: 'MA252', type: 'line', data: ma252, showSymbol: false, lineStyle: { color: COL.green, width: 1.5 } }
    ]
  }, true);
}
function setupUpload() {
  const fileEl = document.getElementById('shgold_file');
  const dateSel = document.getElementById('sa_date'), valSel = document.getElementById('sa_value');
  fileEl.addEventListener('change', () => {
    const f = fileEl.files && fileEl.files[0]; if (!f) return;
    const reader = new FileReader();
    reader.onload = e => {
      try {
        let rows;
        if (/\.csv$/i.test(f.name)) rows = String(e.target.result).split('\n').map(l => l.split(','));
        else rows = readSheet(e.target.result);
        const { dates, prices } = parseRows(rows);
        if (!prices.length) { alert('未解析到有效价格列'); return; }
        chartSelfAnalysis(dates, prices);
      } catch (err) { alert('解析失败：' + err.message); }
    };
    if (/\.csv$/i.test(f.name)) reader.readAsText(f); else reader.readAsArrayBuffer(f);
  });
}

// ---------- 初始化 ----------
function init() {
  Promise.all([
    loadJSON('./data/signals_shgold.json'),
    loadJSON('./data/backtest_shgold.json'),
    loadJSON('./data/replay_shgold.json')
  ]).then(([sig, bt, rep]) => {
    _sig = sig; _bt = bt; _rep = rep;
    renderSignal(); chartFactors(); chartBacktest();
    const dates = rep.replay.map(r => r.date).sort();
    const dateEl = document.getElementById('replay_date');
    dateEl.min = dates[0]; dateEl.max = dates[dates.length - 1];
    // 默认选“其后 63 日仍在真实数据内”的最晚回放点
    const goldEnd = rep.gold[rep.gold.length - 1][0];
    let def = dates[0];
    for (const d of dates) if (addDays(d, 63) <= goldEnd) def = d;
    dateEl.value = def;
    const hSel = document.getElementById('replay_horizon');
    chartReplay(def, +hSel.value);
    dateEl.addEventListener('change', () => chartReplay(dateEl.value, +hSel.value));
    hSel.addEventListener('change', () => chartReplay(dateEl.value, +hSel.value));
    setupUpload();
  }).catch(err => { document.getElementById('asof').textContent = '数据加载失败：' + err.message; });
}
window.addEventListener('DOMContentLoaded', init);
