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

function chartBacktest(bt){
  const h = bt.h21;
  const c = echarts.init(document.getElementById('c_backtest'));
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
  });
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

function chartReplay(R, gold, dateStr){
  const info = document.getElementById('replay_info');
  if(!R || !gold){ info.textContent='回放数据缺失'; return; }
  let rp = null;
  for(const r of R){ if(r.date <= dateStr) rp = r; else break; }
  if(!rp){ info.textContent='该日期之前数据不足（最早回放日 2019-07-19）'; return; }
  const idx = gold.findIndex(g=>g[0]===rp.date);
  if(idx<0){ info.textContent='未找到对应金价'; return; }
  const s = Math.max(0, idx-60), e = Math.min(gold.length, idx+64);
  const slice = gold.slice(s,e);
  const offset = idx - s;
  const dates = slice.map(g=>g[0]);
  const known  = slice.map((g,i)=> i<=offset ? g[1] : null);
  const future = slice.map((g,i)=> i>=offset ? g[1] : null);
  // 第三根线：模型预测路径（由回归器预测的未来收益率推算的价格轨迹）
  const startP = slice[offset][1];
  const r2 = x => Math.round(x*100)/100;
  const pred = slice.map((g,i)=>{
    if(i===offset) return startP;
    if(i===offset+21 && rp.pred_ret21!=null) return r2(startP*(1+rp.pred_ret21/100));
    if(i===offset+63 && rp.pred_ret63!=null) return r2(startP*(1+rp.pred_ret63/100));
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
      {name:'模型预测路径',type:'line',data:pred,showSymbol:true,symbolSize:7,connectNulls:true,
        lineStyle:{color:COL.blue,width:2,type:'dashed'},itemStyle:{color:COL.blue},
        markLine:{silent:true,symbol:'none',lineStyle:{color:COL.red,type:'dashed'},
          data:[{xAxis:rp.date,label:{formatter:'预测日',position:'end',color:COL.red}}]}},
      {name:'预测后实际',type:'line',data:future,showSymbol:false,lineStyle:{color:COL.gold,width:2}}
    ]
  }, true);
  const fmt = v => v==null ? '未到期' : (v>0?'涨 ':'跌 ') + v.toFixed(2)+'%';
  const fmtP = v => v==null ? '未预测' : (v>0?'+':'') + v.toFixed(2)+'%';
  info.innerHTML = `截至 <b>${rp.date}</b>：模型预测 P(up) 21日 <b>${(rp.p21*100).toFixed(1)}%</b> / 63日 <b>${(rp.p63*100).toFixed(1)}%</b>。`
    + ` 模型预测收益 — 21日 ${fmtP(rp.pred_ret21)}，63日 ${fmtP(rp.pred_ret63)}；`
    + ` 实际收益 — 21日 ${fmt(rp.ret21)}，63日 ${fmt(rp.ret63)}。`;
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
      try { analyzeXlsx(ev.target.result, info); }
      catch (err) { info.textContent = '解析失败：' + err.message; }
    };
    reader.onerror = () => info.textContent = '读取文件失败';
    reader.readAsArrayBuffer(f);
  });
}

(async ()=>{
  try{
    const sig = await loadJSON('./data/signals.json');
    const bt = await loadJSON('./data/backtest.json');
    const rep = await loadJSON('./data/replay.json');
    cards(sig);
    chartFactors(sig);
    chartProb(sig);
    chartBacktest(bt);
    chartSignal(bt);
    chartImp(sig);
    const replayEl = document.getElementById('replay_date');
    chartReplay(rep.replay, rep.gold, replayEl.value);
    replayEl.addEventListener('change', e=>chartReplay(rep.replay, rep.gold, e.target.value));
    setupXlsxUpload();
    window.addEventListener('resize',()=>{
      ['c_factors','c_prob','c_backtest','c_signal','c_imp','c_replay','c_xlsx']
        .forEach(id=>echarts.getInstanceByDom(document.getElementById(id))?.resize());
    });
  }catch(e){
    document.getElementById('sub').textContent = '加载失败：'+e.message+
      '（请通过本地服务器打开，见 README）';
  }
})();
