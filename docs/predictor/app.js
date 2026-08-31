// app.js — 读取 signals.json / backtest.json 渲染 ECharts 面板
const COL = { ink:'#1a1a1a', muted:'#666', gold:'#c19a3f', red:'#c0392b', green:'#1e8f5f', line:'#e6e6e6', blue:'#2563eb' };

async function loadJSON(p){ const r = await fetch(p, {cache:'no-store'}); return r.json(); }

function cards(sig){
  const el = document.getElementById('cards');
  const items = [
    ['样本数', sig.n_samples],
    ['截至日期', sig.as_of],
    ['RF 21日准确率', (sig.rf_21d_accuracy*100).toFixed(1)+'%'],
    ['RF 63日准确率', (sig.rf_63d_accuracy*100).toFixed(1)+'%'],
    ['WGC基线 21日', (sig.wgc_21d_accuracy*100).toFixed(1)+'%'],
    ['最新 P(up) 21日', (sig.latest_P_up_21d*100).toFixed(1)+'%'],
  ];
  el.innerHTML = items.map(([k,v])=>`<div class="card"><div class="k">${k}</div><div class="v">${v}</div></div>`).join('');
  document.getElementById('sub').textContent =
    `数据：FRED 免key因子 + 金价历史 · walk-forward 随机森林 · 截至 ${sig.as_of}`;
}

function chartFactors(sig){
  const d = sig.factor_scores;
  const c = echarts.init(document.getElementById('c_factors'));
  c.setOption({
    tooltip:{}, grid:{left:90,right:20,top:20,bottom:30},
    xAxis:{type:'value',max:10,splitLine:{lineStyle:{color:COL.line}}},
    yAxis:{type:'category',data:d.map(x=>x.name)},
    series:[{type:'bar',data:d.map(x=>({value:x.score,
      itemStyle:{color:x.score>=5?COL.gold:COL.muted}})),
      label:{show:true,position:'right',formatter:'{c}'},
      barWidth:'55%'}]
  });
}

function chartForecast(sig){
  const g = document.getElementById('c_forecast');
  if(!g) return;
  const r21 = {h:'21日', p:sig.latest_pred_ret_21d, b:sig.latest_pred_ret_21d_band, tp:sig.latest_target_price_21d};
  const r63 = {h:'63日', p:sig.latest_pred_ret_63d, b:sig.latest_pred_ret_63d_band, tp:sig.latest_target_price_63d};
  const rows = [r21, r63];
  const c = echarts.init(g);
  c.setOption({
    tooltip:{trigger:'axis', formatter: ps=>{
      const r=rows[ps[0].dataIndex];
      return `${r.h}预测收益 ${(r.p>0?'+':'')+r.p}%<br/>历史典型波动 ±${r.b}%<br/>目标价位 ≈ ${r.tp}`;
    }},
    grid:{left:60,right:90,top:20,bottom:30},
    xAxis:{type:'value', name:'预测收益率 %', axisLabel:{formatter:'{value}%'}, splitLine:{lineStyle:{color:COL.line}}},
    yAxis:{type:'category', data:rows.map(r=>r.h)},
    series:[{
      type:'bar', barWidth:'45%',
      data: rows.map(r=>({value:r.p, itemStyle:{color: r.p>=0?COL.gold:COL.red}})),
      label:{show:true, position:'right', formatter: p=> (p.value>0?'+':'')+p.value+'%'},
      markLine:{silent:true, symbol:'none', data:[{xAxis:0}], lineStyle:{color:COL.muted}}
    }]
  });
  const latest = sig.latest_gold;
  const f1 = (r)=>`${(r.p>0?'+':'')+r.p}%（目标≈${r.tp}，±${r.b}%）`;
  document.getElementById('forecast_note').innerHTML =
    `当前金价 ≈ <b>${latest}</b>。下图是随机森林回归给出的<b>点估计（含两档窗口 = “多久”）</b>；`+
    `幅度置信度低（方向可预测、幅度难预测），区间 = 历史典型波动，非精确预测。`+
    ` 21日 ${f1(r21)} ／ 63日 ${f1(r63)}。模型不做连续路径/拐点预测，仅给 21天、63天 两个固定窗口。`;
}

function chartProb(sig){
  const c = echarts.init(document.getElementById('c_prob'));
  const v21 = Math.round(sig.latest_P_up_21d*100);
  const v63 = Math.round(sig.latest_P_up_63d*100);
  c.setOption({
    series:[
      {type:'gauge',center:['27%','55%'],radius:'80%',min:0,max:100,
        title:{show:true,offsetCenter:[0,'78%'],fontSize:12},
        progress:{show:true,width:12},axisLine:{lineStyle:{width:12}},
        detail:{formatter:'{value}%',fontSize:18,offsetCenter:[0,'45%']},
        data:[{value:v21,name:'21日'}]},
      {type:'gauge',center:['73%','55%'],radius:'80%',min:0,max:100,
        title:{show:true,offsetCenter:[0,'78%'],fontSize:12},
        progress:{show:true,width:12},axisLine:{lineStyle:{width:12}},
        detail:{formatter:'{value}%',fontSize:18,offsetCenter:[0,'45%']},
        data:[{value:v63,name:'63日'}]}
    ]
  });
}

const BT_LABEL = { h21: '21日信号', h63: '63日信号', hcomb: '综合(21+63)' };
function chartBacktest(bt, which){
  const h = bt[which];
  const c = echarts.init(document.getElementById('c_backtest'));
  const win = h.strat_final > h.bnh_final;
  c.setOption({
    tooltip:{trigger:'axis'}, legend:{data:['策略净值','买入持有'],top:0},
    grid:{left:50,right:20,top:36,bottom:40},
    xAxis:{type:'category',data:h.dates,axisLabel:{show:false}},
    yAxis:{type:'log',name:'净值(起点=1)'},
    series:[
      {name:'策略净值',type:'line',data:h.strat_curve,showSymbol:false,
        lineStyle:{color:COL.gold,width:2}},
      {name:'买入持有',type:'line',data:h.bnh_curve,showSymbol:false,
        lineStyle:{color:COL.muted,width:1.5}}
    ]
  }, true);
  const note = document.getElementById('bt_note');
  if (note) note.innerHTML =
    `<b>${BT_LABEL[which]}</b>：策略 <b>${h.strat_final}</b> vs 买入持有 <b>${h.bnh_final}</b> → ${win ? '跑赢 ✅' : '跑输 ❌'}（样本外 ${h.n} 点）`;
  return h;
}

function chartSignal(bt){
  const h = bt.h21;
  const c = echarts.init(document.getElementById('c_signal'));
  c.setOption({
    tooltip:{trigger:'axis'}, legend:{data:['P(up)','实际方向'],top:0},
    grid:{left:40,right:20,top:36,bottom:40},
    xAxis:{type:'category',data:h.dates,axisLabel:{show:false}},
    yAxis:[{type:'value',min:0,max:1,name:'P'},
           {type:'value',min:-1,max:1,name:'方向'}],
    series:[
      {name:'P(up)',type:'line',data:h.prob,showSymbol:false,
        lineStyle:{color:COL.gold}},
      {name:'实际方向',type:'line',data:h.actual,showSymbol:false,
        lineStyle:{color:COL.red,width:1}}
    ]
  });
}

function chartImp(sig){
  const d = sig.feature_importance.slice().reverse();
  const c = echarts.init(document.getElementById('c_imp'));
  c.setOption({
    tooltip:{}, grid:{left:120,right:20,top:10,bottom:20},
    xAxis:{type:'value'},
    yAxis:{type:'category',data:d.map(x=>x.name)},
    series:[{type:'bar',data:d.map(x=>x.imp),barWidth:'55%',
      itemStyle:{color:COL.gold},
      label:{show:true,position:'right'}}]
  });
}

function chartReplay(R, gold, dateStr, horizon){
  const info = document.getElementById('replay_info');
  if(!R || !gold){ info.textContent='回放数据缺失'; return; }
  let rp = null;
  for(const r of R){ if(r.date <= dateStr) rp = r; else break; }
  if(!rp){ info.textContent='该日期之前数据不足（最早回放日 2014-09-29）'; return; }
  const idx = gold.findIndex(g=>g[0]===rp.date);
  if(idx<0){ info.textContent='未找到对应金价'; return; }
  const s = Math.max(0, idx-60), e = Math.min(gold.length, idx+64);
  const slice = gold.slice(s,e);
  const offset = idx - s;
  const dates = slice.map(g=>g[0]);
  const known  = slice.map((g,i)=> i<=offset ? g[1] : null);
  const future = slice.map((g,i)=> i>=offset ? g[1] : null);
  const startP = slice[offset][1];
  const r2 = x => Math.round(x*100)/100;
  // 第三根线：模型预测的"未来 horizon 日"价格点（回归器预测的未来收益率反推）
  const predRet = horizon===21 ? rp.pred_ret21 : rp.pred_ret63;
  const offH = horizon===21 ? 21 : 63;
  const pred = slice.map((g,i)=>{
    if(i===offset) return startP;
    if(i===offset+offH && predRet!=null) return r2(startP*(1+predRet/100));
    return null;
  });
  const c = echarts.getInstanceByDom(document.getElementById('c_replay')) || echarts.init(document.getElementById('c_replay'));
  c.setOption({
    tooltip:{trigger:'axis'},
    legend:{data:['已知历史','模型预测路径','预测后实际'],top:0},
    grid:{left:55,right:20,top:36,bottom:60},
    xAxis:{type:'category',data:dates,axisLabel:{rotate:45,fontSize:10}},
    yAxis:{type:'value',scale:true,name:'金价'},
    series:[
      {name:'已知历史',type:'line',data:known,showSymbol:false,lineStyle:{color:COL.muted,width:1.5}},
      {name:'模型预测路径',type:'line',data:pred,showSymbol:true,symbolSize:8,connectNulls:true,
        lineStyle:{color:COL.blue,width:2,type:'dashed'},itemStyle:{color:COL.blue},
        markPoint:{symbol:'pin',symbolSize:46,data:[{coord:[offset+offH, r2(startP*(1+(predRet||0)/100))],
          value:(predRet==null?'—':(predRet>0?'+':'')+predRet.toFixed(1)+'%'),itemStyle:{color:COL.blue}}]},
        markLine:{silent:true,symbol:'none',lineStyle:{color:COL.red,type:'dashed'},
          data:[{xAxis:rp.date,label:{formatter:'预测日',position:'end',color:COL.red}}]}},
      {name:'预测后实际',type:'line',data:future,showSymbol:false,lineStyle:{color:COL.gold,width:2}}
    ]
  }, true);

  // “未来涨跌有多少” + 方向命中/未命中
  const fmt = v => v==null ? '未到期' : (v>0?'涨 ':'跌 ') + v.toFixed(2)+'%';
  const fmtP = v => v==null ? '未预测' : (v>0?'+':'') + v.toFixed(2)+'%';
  const pUp = horizon===21 ? rp.p21 : rp.p63;
  const act = horizon===21 ? rp.ret21 : rp.ret63;
  let verdict;
  if (act==null || predRet==null) verdict = '（尚未到期，无法判对错）';
  else verdict = (Math.sign(act) === Math.sign(predRet)) ? '方向命中 ✅' : '方向未命中 ❌';
  info.innerHTML = `截至 <b>${rp.date}</b>（预测窗口 <b>${horizon}日</b>）：模型 P(up)=<b>${(pUp*100).toFixed(1)}%</b>。`
    + ` 模型预测未来收益 <b>${fmtP(predRet)}</b>，实际 <b>${fmt(act)}</b>。 ${verdict}`;
}

// ---------- 上传 Excel/CSV 自分析走势（纯浏览器） ----------
function parseDate(v){
  if (v == null) return null;
  if (typeof v === 'number') {
    // Excel 序列日期（1900 日期系统，1=1900-01-01）；黄金历史可早至 1920，序列号约 7000+
    const d = new Date((v - 25569) * 86400000);
    const y = d.getUTCFullYear();
    return (y >= 1900 && y <= 2100) ? d : null;
  }
  const t = Date.parse(String(v).replace(/\//g, '-'));
  return isNaN(t) ? null : new Date(t);
}

function analyzeXlsx(buf, info){
  if (typeof XLSX === 'undefined') { info.textContent = 'XLSX 解析库未加载'; return; }
  const wb = XLSX.read(new Uint8Array(buf), { type: 'array' });
  // 选行数最多的表
  let sheet = wb.Sheets[wb.SheetNames[0]], best = -1;
  for (const nm of wb.SheetNames) {
    const ref = wb.Sheets[nm]['!ref'];
    if (!ref) continue;
    const er = XLSX.utils.decode_range(ref).e.r;
    if (er > best) { best = er; sheet = wb.Sheets[nm]; }
  }
  const rows = XLSX.utils.sheet_to_json(sheet, { header: 1, raw: true, defval: null });
  if (rows.length < 3) { info.textContent = '数据行太少'; return; }
  const header = rows[0].map((h, i) => ({ h: String(h == null ? '' : h).trim().toLowerCase(), i }));
  const dateIdx = header.find(c => /date|日期|时间|time/.test(c.h))?.i ?? -1;
  let priceIdx = header.find(c => /close|price|gold|收盘|价格|adj|value|数值/.test(c.h))?.i ?? -1;
  if (priceIdx < 0) {
    for (let c = 0; c < rows[1].length; c++) {
      if (c === dateIdx) continue;
      if (typeof rows[1][c] === 'number') { priceIdx = c; break; }
    }
  }
  if (priceIdx < 0) { info.textContent = '未找到价格列（需含数值的列）'; return; }
  const data = [];
  for (let r = 1; r < rows.length; r++) {
    const rv = rows[r];
    const d = dateIdx >= 0 ? parseDate(rv[dateIdx]) : null;
    const p = Number(rv[priceIdx]);
    if (isNaN(p) || p <= 0) continue;          // 跳过占位/空值行
    if (dateIdx >= 0 && !d) continue;          // 跳过无法解析的日期
    data.push({ t: d, p });
  }
  if (data.length < 10) { info.textContent = '有效数值不足（需 ≥10 行）'; return; }
  if (data[0].t) data.sort((a, b) => a.t - b.t);

  const prices = data.map(d => d.p);
  const dates = data.map(d => d.t ? d.t.toISOString().slice(0, 10) : '');
  const n = prices.length;
  const latest = prices[n - 1];
  const ma = w => prices.map((_, i) => i < w - 1 ? null : prices.slice(i - w + 1, i + 1).reduce((a, b) => a + b, 0) / w);
  const MA20 = ma(20), MA60 = ma(60), MA252 = ma(252);
  const ret = w => prices.map((_, i) => i < w ? null : prices[i] / prices[i - w] - 1);
  const mom20 = ret(20)[n - 1], mom60 = ret(60)[n - 1], mom252 = ret(252)[n - 1];
  let runmax = prices[0], maxdd = 0;
  for (const p of prices) { if (p > runmax) runmax = p; const dd = (p - runmax) / runmax; if (dd < maxdd) maxdd = dd; }
  const dr = []; for (let i = 1; i < n; i++) dr.push(prices[i] / prices[i - 1] - 1);
  const mean = dr.reduce((a, b) => a + b, 0) / dr.length;
  const variance = dr.reduce((a, b) => a + (b - mean) ** 2, 0) / dr.length;
  const vol = Math.sqrt(variance) * Math.sqrt(252);
  const aboveMA = latest >= (MA252[n - 1] || latest);
  const regime = mom252 > 0 ? (aboveMA ? '多头' : '反弹') : (aboveMA ? '高位震荡' : '空头');

  const c = echarts.getInstanceByDom(document.getElementById('c_xlsx')) || echarts.init(document.getElementById('c_xlsx'));
  c.setOption({
    tooltip: { trigger: 'axis' }, legend: { data: ['价格', 'MA20', 'MA60', 'MA252'], top: 0 },
    grid: { left: 55, right: 20, top: 36, bottom: 50 },
    xAxis: { type: 'category', data: dates, axisLabel: { rotate: 45, fontSize: 10 } },
    yAxis: { type: 'value', scale: true, name: '金价' },
    series: [
      { name: '价格', type: 'line', data: prices, showSymbol: false, lineStyle: { color: COL.gold, width: 2 } },
      { name: 'MA20', type: 'line', data: MA20, showSymbol: false, lineStyle: { color: COL.blue, width: 1.5 } },
      { name: 'MA60', type: 'line', data: MA60, showSymbol: false, lineStyle: { color: COL.muted, width: 1.5 } },
      { name: 'MA252', type: 'line', data: MA252, showSymbol: false, lineStyle: { color: COL.green, width: 1.5 } }
    ]
  }, true);

  const pct = x => (x == null ? '—' : (x * 100).toFixed(1) + '%');
  const sign = x => (x == null ? '' : (x > 0 ? '+' : ''));
  info.innerHTML = `解析 <b>${n}</b> 行 | 区间 ${dates[0]} ~ ${dates[n - 1]} | 最新 <b>${latest.toFixed(2)}</b>`
    + ` | 252日动量 ${sign(mom252)}${pct(mom252)} | 最大回撤 ${pct(maxdd)} | 年化波动率 ${pct(vol)} | 状态：<b>${regime}</b>`;
}

function ensureXLSX(cb){
  if (typeof XLSX !== 'undefined') return cb();
  // 主脚本未加载时，动态重试一次（应对偶发网络/缓存失败）
  const info = document.getElementById('xlsx_info');
  if (info) info.textContent = '正在加载 XLSX 解析库…';
  const s = document.createElement('script');
  s.src = './xlsx.full.min.js';
  s.onload = cb;
  s.onerror = () => { if (info) info.textContent = 'XLSX 解析库加载失败（检查网络后刷新页面重试）'; };
  document.head.appendChild(s);
}

function setupXlsxUpload(){
  const el = document.getElementById('xlsx_file');
  if (!el) return;
  el.addEventListener('change', e => {
    const f = e.target.files && e.target.files[0];
    if (!f) return;
    const info = document.getElementById('xlsx_info');
    info.textContent = '解析中…';
    const reader = new FileReader();
    reader.onload = ev => {
      ensureXLSX(() => {
        try { analyzeXlsx(ev.target.result, info); }
        catch (err) { info.textContent = '解析失败：' + err.message; }
      });
    };
    reader.onerror = () => info.textContent = '读取文件失败';
    reader.readAsArrayBuffer(f);
  });
}

// ---------- 上传即预测：纯浏览器内随机森林（用你自己的数据训练） ----------
// 与上方"自分析走势"相互独立：这里会把你上传的序列当训练集，训练一个
// 预测未来 21/63 日涨跌方向与幅度的模型（不含宏观因子，纯技术面自训练）。

// 读取第一个（行数最多的）工作表的所有行（含表头/数据），供解析与列选择复用
function readSheet(buf){
  if (typeof XLSX === 'undefined') throw new Error('XLSX 解析库未加载');
  const wb = XLSX.read(new Uint8Array(buf), { type: 'array' });
  let sheet = wb.Sheets[wb.SheetNames[0]], best = -1;
  for (const nm of wb.SheetNames) {
    const ref = wb.Sheets[nm]['!ref'];
    if (!ref) continue;
    const er = XLSX.utils.decode_range(ref).e.r;
    if (er > best) { best = er; sheet = wb.Sheets[nm]; }
  }
  return XLSX.utils.sheet_to_json(sheet, { header: 1, raw: true, defval: null });
}

// 解析 Excel/CSV -> {dates, prices}
//   dateIdx / priceIdx：列下标（用户在下拉框选择；可传 -1 表示无日期列）
//   若文件首行全为数值（无表头），则自动按列序号处理，从首行开始当作数据
function parseXlsxToSeries(buf, dateIdx, priceIdx){
  const rows = readSheet(buf);
  if (rows.length < 3) throw new Error('数据行太少（需 ≥3 行）');
  const headerIsText = rows[0].some(h => h != null && isNaN(Number(h)) && String(h).trim() !== '');
  const headerRow = headerIsText ? rows[0] : null;
  const startRow = headerIsText ? 1 : 0;
  if (priceIdx == null || priceIdx < 0) throw new Error('请先在下拉框选择“数值列”（价格/收盘价）');
  const data = [];
  for (let r = startRow; r < rows.length; r++) {
    const rv = rows[r];
    const d = dateIdx >= 0 ? parseDate(rv[dateIdx]) : null;
    const p = Number(rv[priceIdx]);
    if (isNaN(p) || p <= 0) continue;
    if (dateIdx >= 0 && !d) continue;
    data.push({ t: d, p });
  }
  if (data.length < 60) throw new Error('有效数值不足（需 ≥60 行）');
  if (data[0].t) data.sort((a, b) => a.t - b.t);
  return { dates: data.map(d => d.t ? d.t.toISOString().slice(0, 10) : ''), prices: data.map(d => d.p) };
}

// 读取首行作为列候选，填充“日期列 / 数值列”下拉框，并自动推断默认值
function populatePredictColumns(buf, dateSel, valSel){
  const rows = readSheet(buf);
  if (rows.length < 2) throw new Error('文件为空或无数据');
  const headerIsText = rows[0].some(h => h != null && isNaN(Number(h)) && String(h).trim() !== '');
  const cols = rows[0].map((h, i) => ({
    idx: i,
    name: (!headerIsText || h == null || String(h).trim() === '') ? `第 ${i + 1} 列` : String(h).trim()
  }));
  const opts = cols.map(c => `<option value="${c.idx}">${c.name}</option>`).join('');
  dateSel.innerHTML = `<option value="-1">无（按行顺序）</option>` + opts;
  valSel.innerHTML = opts;
  // 自动推断默认：日期列匹配 date/日期/时间，数值列匹配 close/price/gold/收盘/价格…
  const di = cols.findIndex(c => /date|日期|时间|time/i.test(c.name));
  let pi = cols.findIndex(c => /close|price|gold|收盘|价格|adj|value|数值/i.test(c.name));
  if (pi < 0) { // 退而求其次：第一个数值列（排除日期列）
    const r1 = headerIsText ? rows[1] : rows[0];
    pi = cols.findIndex((c, i) => i !== di && r1 && typeof r1[c.idx] === 'number');
  }
  if (di >= 0) dateSel.value = String(di);
  if (pi >= 0) valSel.value = String(pi);
  return cols.length;
}

// ---- 随机森林（分类 + 回归，从零实现） ----
function _agg(y, idx, regression){ let s = 0; for (const i of idx) s += y[i]; return s / idx.length; }
function _imp(y, idx, regression){
  if (regression){ const m = _agg(y, idx, true); let s = 0; for (const i of idx) s += (y[i] - m) ** 2; return s / idx.length; }
  const p = _agg(y, idx, false); return p * (1 - p); // gini
}
function _grow(X, y, idx, depth, cfg){
  if (depth >= cfg.maxDepth || idx.length <= cfg.minLeaf)
    return { leaf: true, val: _agg(y, idx, cfg.regression) };
  const d = X[0].length, all = [...Array(d).keys()], feats = [];
  for (let k = 0; k < cfg.mtry; k++){ const j = (Math.random() * all.length) | 0; feats.push(all.splice(j, 1)[0]); }
  const curImp = _imp(y, idx, cfg.regression);
  let best = null;
  for (const f of feats){
    const vals = idx.map(i => X[i][f]).sort((a, b) => a - b);
    const thr = []; const step = Math.max(1, Math.floor(vals.length / 8));
    for (let q = step; q < vals.length; q += step) thr.push(vals[q]);
    if (!thr.length) thr.push(vals[(vals.length / 2) | 0]);
    for (const t of thr){
      const left = [], right = [];
      for (const i of idx) (X[i][f] <= t ? left : right).push(i);
      if (left.length < cfg.minLeaf || right.length < cfg.minLeaf) continue;
      const imp = (left.length * _imp(y, left, cfg.regression) + right.length * _imp(y, right, cfg.regression)) / idx.length;
      if (best === null || imp < best.imp) best = { imp, f, t, left, right };
    }
  }
  if (best === null || best.imp >= curImp) return { leaf: true, val: _agg(y, idx, cfg.regression) };
  return { leaf: false, f: best.f, t: best.t,
    left: _grow(X, y, best.left, depth + 1, cfg), right: _grow(X, y, best.right, depth + 1, cfg) };
}
function _predTree(node, x){ while (!node.leaf) node = (x[node.f] <= node.t) ? node.left : node.right; return node.val; }
function buildForest(X, y, cfg){
  const n = X.length, trees = [];
  for (let t = 0; t < cfg.nTrees; t++){
    const idx = []; for (let k = 0; k < n; k++) idx.push((Math.random() * n) | 0);
    trees.push(_grow(X, y, idx, 0, cfg));
  }
  return { predict: x => { let s = 0; for (const tr of trees) s += _predTree(tr, x); return s / trees.length; }, trees };
}

// 构建单点特征（需 i>=252 才有完整回看）
function _featAt(prices, MA20, MA60, MA252, dr, i){
  if (i < 252) return null;
  const w = 5;
  const ret = k => prices[i] / prices[i - k] - 1;
  const std = (len) => { if (i < len) return null; let s = 0; for (let k = i - len + 1; k <= i; k++) s += dr[k]; const m = s / len; let v = 0; for (let k = i - len + 1; k <= i; k++) v += (dr[k] - m) ** 2; return Math.sqrt(v / len); };
  const f = [ret(5), ret(20), ret(60), ret(252), std(20), std(60),
             prices[i] / MA20[i] - 1, prices[i] / MA60[i] - 1, prices[i] / MA252[i] - 1];
  return f.some(v => v == null || !isFinite(v)) ? null : f;
}
function _MArr(prices, w){ const n = prices.length, out = new Array(n).fill(null); let s = 0; for (let i = 0; i < n; i++){ s += prices[i]; if (i >= w) s -= prices[i - w]; if (i >= w - 1) out[i] = s / w; } return out; }

// 训练：返回模型 + 样本外测试精度
function selfTrain(prices){
  const n = prices.length;
  const MA20 = _MArr(prices, 20), MA60 = _MArr(prices, 60), MA252 = _MArr(prices, 252);
  const dr = [0]; for (let i = 1; i < n; i++) dr.push(prices[i] / prices[i - 1] - 1);
  const rows = [];
  for (let i = 252; i + 63 < n; i++){
    const x = _featAt(prices, MA20, MA60, MA252, dr, i);
    if (!x) continue;
    const r21 = prices[i + 21] / prices[i] - 1, r63 = prices[i + 63] / prices[i] - 1;
    rows.push({ x, dir21: r21 > 0 ? 1 : 0, ret21: r21 * 100, dir63: r63 > 0 ? 1 : 0, ret63: r63 * 100 });
  }
  if (rows.length < 100) throw new Error('样本不足（需 ≥100 个可训练点，约 1 年以上日线）');
  const m = rows.length, cut = Math.floor(m * 0.8);
  let trainIdx = []; for (let k = 0; k < cut; k++) trainIdx.push(k);
  if (trainIdx.length > 4000){ const sel = []; const pool = trainIdx.slice(); while (sel.length < 4000 && pool.length){ sel.push(pool.splice((Math.random() * pool.length) | 0, 1)[0]); } trainIdx = sel; }
  const X = trainIdx.map(k => rows[k].x);
  const cfg = { nTrees: 120, maxDepth: 7, minLeaf: 30, mtry: 3, regression: false };
  const cfgR = { ...cfg, regression: true };
  const fDir21 = buildForest(X, trainIdx.map(k => rows[k].dir21), cfg);
  const fDir63 = buildForest(X, trainIdx.map(k => rows[k].dir63), cfg);
  const fRet21 = buildForest(X, trainIdx.map(k => rows[k].ret21), cfgR);
  const fRet63 = buildForest(X, trainIdx.map(k => rows[k].ret63), cfgR);
  const test = []; for (let k = cut; k < m; k++) test.push(k);
  const accDir = f => { let ok = 0; for (const k of test) if ((f.predict(rows[k].x) >= 0.5 ? 1 : 0) === rows[k].dir21) ok++; return ok / test.length; };
  const accRet = f => { let ok = 0, mae = 0; for (const k of test){ const p = f.predict(rows[k].x); mae += Math.abs(p - rows[k].ret21); if ((p >= 0 ? 1 : 0) === (rows[k].ret21 >= 0 ? 1 : 0)) ok++; } return { acc: ok / test.length, mae: mae / test.length }; };
  const finalX = _featAt(prices, MA20, MA60, MA252, dr, n - 1);
  if (!finalX) throw new Error('最新点回看不足（序列尾部数据异常）');
  return {
    fDir21, fDir63, fRet21, fRet63,
    lastX: finalX,
    testN: test.length,
    rDir21: accDir(fDir21), rDir63: accDir(fDir63),
    rRet21: accRet(fRet21), rRet63: accRet(fRet63),
  };
}

let _predictBuf = null;  // 已选文件的二进制 buffer（列选择 / 预测共用）
function setupSelfPredict(){
  const fileEl = document.getElementById('predict_file');
  const btn = document.getElementById('predict_btn');
  const dateSel = document.getElementById('predict_date');
  const valSel = document.getElementById('predict_value');
  const info = document.getElementById('predict_info');
  if (!fileEl || !btn || !dateSel || !valSel) return;

  // 选文件后立即读取列名，填充下拉框让用户确认/修改列映射
  fileEl.addEventListener('change', () => {
    const f = fileEl.files && fileEl.files[0];
    if (!f) { _predictBuf = null; dateSel.disabled = true; valSel.disabled = true; btn.disabled = true; return; }
    const reader = new FileReader();
    reader.onload = ev => {
      _predictBuf = ev.target.result;
      ensureXLSX(() => {
        try {
          const n = populatePredictColumns(_predictBuf, dateSel, valSel);
          dateSel.disabled = false; valSel.disabled = false; btn.disabled = false;
          info.innerHTML = `已识别 <b>${n}</b> 列。请确认下方“日期列 / 数值列”是否选对（不同文件格式不同，可下拉修改），再点“训练并预测”。`;
        } catch (e) { info.textContent = '读取文件失败：' + e.message; }
      });
    };
    reader.onerror = () => { info.textContent = '读取文件失败'; };
    reader.readAsArrayBuffer(f);
  });

  btn.addEventListener('click', () => {
    if (!_predictBuf) { info.textContent = '请先选择文件'; return; }
    btn.disabled = true;
    info.textContent = '解析 + 特征工程…';
    setTimeout(() => {
      ensureXLSX(() => {
        try {
          const di = parseInt(dateSel.value, 10), pi = parseInt(valSel.value, 10);
          const series = parseXlsxToSeries(_predictBuf, di, pi);
          info.textContent = `已解析 ${series.prices.length} 行。训练随机森林（用自己的数据，可能卡顿几秒）…`;
          setTimeout(() => {
            try {
              const model = selfTrain(series.prices);
              const latest = series.prices[series.prices.length - 1];
              const pUp21 = model.fDir21.predict(model.lastX);
              const pUp63 = model.fDir63.predict(model.lastX);
              const ret21 = model.fRet21.predict(model.lastX);
              const ret63 = model.fRet63.predict(model.lastX);
              const t21 = latest * (1 + ret21 / 100), t63 = latest * (1 + ret63 / 100);
              renderSelfPredict(series, latest, { pUp21, pUp63, ret21, ret63, t21, t63 }, model, info);
            } catch (err) { info.textContent = '预测失败：' + err.message; }
            finally { btn.disabled = false; }
          }, 40);
        } catch (err) { info.textContent = '解析失败：' + err.message; btn.disabled = false; }
      });
    }, 40);
  });
}

function renderSelfPredict(series, latest, pred, model, info){
  const chartEl = document.getElementById('c_predict');
  const fmtP = v => (v >= 0 ? '+' : '') + v.toFixed(1) + '%';
  const dir = p => p >= 0.5 ? '涨' : '跌';
  info.innerHTML =
    `基于你上传的 <b>${series.prices.length}</b> 行自训练模型（不看宏观因子，纯技术面）。` +
    ` 最新价 ≈ <b>${latest.toFixed(2)}</b>。<br/>` +
    `• 21日：P(涨)=<b>${(pred.pUp21 * 100).toFixed(1)}%</b> → 预测${dir(pred.pUp21)} ${fmtP(pred.ret21)}，目标≈${pred.t21.toFixed(2)}。` +
    ` <span style="color:var(--muted)">[样本外方向准确率 ${(model.rDir21 * 100).toFixed(0)}%]</span><br/>` +
    `• 63日：P(涨)=<b>${(pred.pUp63 * 100).toFixed(1)}%</b> → 预测${dir(pred.pUp63)} ${fmtP(pred.ret63)}，目标≈${pred.t63.toFixed(2)}。` +
    ` <span style="color:var(--muted)">[样本外方向准确率 ${(model.rDir63 * 100).toFixed(0)}%]</span><br/>` +
    `<span style="color:var(--muted)">幅度为点估计、误差较大；样本外测试点 ${model.testN} 个。此模型用你自己的历史训练，可能与上方宏观模型结论不同。</span>`;

  // 图：最后 120 日 + 预测的两个目标点
  const L = 120, n = series.prices.length, start = Math.max(0, n - L);
  const known = series.prices.slice(start);
  const kdates = series.dates.slice(start);
  const xlabels = kdates.concat(['+21d', '+63d']);
  const knownData = known.concat([null, null]);
  const projData = known.map(() => null); projData[known.length - 1] = latest;
  projData.push(pred.t21, pred.t63);
  const c = echarts.getInstanceByDom(chartEl) || echarts.init(chartEl);
  c.setOption({
    tooltip: { trigger: 'axis' },
    legend: { data: ['你的价格', '模型预测目标'], top: 0 },
    grid: { left: 55, right: 20, top: 36, bottom: 50 },
    xAxis: { type: 'category', data: xlabels, axisLabel: { rotate: 45, fontSize: 10 } },
    yAxis: { type: 'value', scale: true, name: '金价' },
    series: [
      { name: '你的价格', type: 'line', data: knownData, showSymbol: false, lineStyle: { color: COL.gold, width: 2 } },
      { name: '模型预测目标', type: 'line', data: projData, showSymbol: true, symbolSize: 9, connectNulls: false,
        lineStyle: { color: COL.blue, width: 2, type: 'dashed' }, itemStyle: { color: COL.blue } }
    ]
  }, true);
}

(async ()=>{
  try{
    const sig = await loadJSON('./data/signals.json');
    const bt = await loadJSON('./data/backtest.json');
    const rep = await loadJSON('./data/replay.json');
    cards(sig);
    chartFactors(sig);
    chartProb(sig);
    chartForecast(sig);
    // 回测：默认展示 63 日（真正跑赢买入持有的窗口），可由按钮切换
    chartBacktest(bt, 'h63');
    document.querySelectorAll('.toggle[data-bt]').forEach(btn=>{
      btn.addEventListener('click', ()=>{
        document.querySelectorAll('.toggle[data-bt]').forEach(b=>b.classList.remove('active'));
        btn.classList.add('active');
        chartBacktest(bt, btn.dataset.bt);
      });
    });
    chartSignal(bt);
    chartImp(sig);
    const replayEl = document.getElementById('replay_date');
    const horizonEl = document.getElementById('replay_horizon');
    const drawReplay = ()=> chartReplay(rep.replay, rep.gold, replayEl.value, parseInt(horizonEl.value,10));
    drawReplay();
    replayEl.addEventListener('change', drawReplay);
    horizonEl.addEventListener('change', drawReplay);
    setupXlsxUpload();
    setupSelfPredict();
    window.addEventListener('resize',()=>{
      ['c_factors','c_prob','c_forecast','c_backtest','c_signal','c_imp','c_replay','c_xlsx','c_predict']
        .forEach(id=>echarts.getInstanceByDom(document.getElementById(id))?.resize());
    });
  }catch(e){
    document.getElementById('sub').textContent = '加载失败：'+e.message+
      '（请通过本地服务器打开，见 README）';
  }
})();
