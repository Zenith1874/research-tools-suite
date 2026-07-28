'use strict';

const $=id=>document.getElementById(id);
const COLORS={optimistic:'#27d3b2',base:'#f5a623',stress:'#ff6b7d'};
const OFFICIAL_FOCUS=['北京','上海','广州','深圳','厦门','南京','合肥','无锡'];
const LISTING_FOCUS=['北京','上海','广州','深圳','厦门','南京','合肥','常州','苏州','无锡'];
const TIER1=['北京','上海','广州','深圳'];
let catalog=[],selected=new Set(),comparePayload=null,detailPayload=null,charts={};
const INITIAL_PARAMS=new URLSearchParams(location.search);
let requestedFocus=INITIAL_PARAMS.get('city')||'常州';
const fmt=(v,d=1)=>v==null?'—':Number(v).toLocaleString('zh-CN',{minimumFractionDigits:d,maximumFractionDigits:d});
const pct=(v,d=1)=>v==null?'—':`${fmt(v,d)}%`;
function destroy(key){if(charts[key]){charts[key].destroy();delete charts[key]}}
function showError(id,message){$(id).textContent=message||'';$(id).classList.toggle('hidden',!message)}
function setLoading(on){document.body.classList.toggle('loading',on)}
function scenarioMap(series){return Object.fromEntries((series.scenarios||[]).filter(x=>!x.status).map(x=>[x.key,x]))}
function scenarioEndPrice(item,currentPrice){
  if(item?.end_price!=null)return item.end_price;
  return item?.end_vs_now!=null&&currentPrice!=null?currentPrice*(1+item.end_vs_now/100):null;
}
function sourceMode(){return $('dataSource').value}
function activeKind(){return sourceMode()==='anjuke'?'listing':$('kind').value}
function focusCities(){return sourceMode()==='anjuke'?LISTING_FOCUS:OFFICIAL_FOCUS}
function sourceLabel(){return sourceMode()==='anjuke'?'安居客挂牌价·参考':'统计局官方指数'}

function renderCityChips(){
  const query=$('citySearch').value.trim();
  $('cityChips').innerHTML=catalog.filter(item=>!query||item.city.includes(query)).map(item=>
    `<button class="chip ${selected.has(item.city)?'active':''}" data-city="${item.city}">${item.city}</button>`).join('');
  document.querySelectorAll('[data-city]').forEach(button=>button.onclick=()=>{
    const city=button.dataset.city;
    if(selected.has(city))selected.delete(city);else if(selected.size<12)selected.add(city);
    renderCityChips();syncFocus();renderSelectionHint();
  });
}
function renderSelectionHint(){
  const total=catalog.length;
  $('selectionHint').textContent=`已选 ${selected.size} 城 · ${sourceLabel()}目录 ${total} 城`+(selected.size>=12?' · 已达到图表上限 12 城':'');
}
function applyGroup(group){
  if(group==='clear')selected.clear();
  else if(group==='all')selected=new Set(catalog.slice(0,12).map(x=>x.city));
  else selected=new Set((group==='tier1'?TIER1:focusCities()).filter(city=>catalog.some(x=>x.city===city)));
  renderCityChips();syncFocus();renderSelectionHint();
}
function syncFocus(preferred){
  const previous=preferred||$('focusCity').value;
  const names=selected.size?[...selected]:catalog.slice(0,1).map(x=>x.city);
  $('focusCity').innerHTML=names.map(city=>`<option>${city}</option>`).join('');
  $('focusCity').value=names.includes(previous)?previous:names[0]||'';
}
function updateUrlState(){
  const params=new URLSearchParams(location.search);
  params.set('source',sourceMode());
  if($('focusCity').value)params.set('city',$('focusCity').value);
  params.set('horizon',$('horizon').value);
  params.set('kind',$('kind').value);
  history.replaceState(null,'',`${location.pathname}?${params}`);
}

function compareQuery(){
  return new URLSearchParams({cities:[...selected].join(','),source:sourceMode(),kind:$('kind').value,horizon:$('horizon').value}).toString();
}
async function loadComparison(){
  if(!selected.size){showError('compareError','请至少选择一个城市。');return}
  showError('compareError','');setLoading(true);
  try{
    const response=await fetch('/api/housing-scenario/compare?'+compareQuery());
    const payload=await response.json();if(!response.ok)throw Error(payload.error||`HTTP ${response.status}`);
    comparePayload=payload;renderComparison();await loadDetail();
  }catch(error){showError('compareError','多城比较加载失败：'+error.message)}finally{setLoading(false)}
}
function renderComparison(){
  const rows=comparePayload.rows||[],ok=rows.filter(row=>row.status==='ok');
  destroy('compare');
  const labels=ok.map(row=>row.city);
  const showPrice=sourceMode()==='anjuke'&&$('compareValueMode').value==='price';
  const value=(row,key)=>{const item=(row.scenarios||[]).find(x=>x.key===key);return item?(showPrice?scenarioEndPrice(item,row.current_price):item.end_vs_now):null};
  const axisTitle=showPrice?`${comparePayload.horizon_months}个月后挂牌均价（元/㎡）`:`${comparePayload.horizon_months}个月后较当前`;
  const tick=v=>showPrice?fmt(v,0):v+'%';
  charts.compare=new Chart($('compareChart'),{type:'bar',data:{labels,datasets:['optimistic','base','stress'].map(key=>({label:{optimistic:'乐观',base:'基准',stress:'压力'}[key],data:ok.map(row=>value(row,key)),backgroundColor:COLORS[key]}))},options:{responsive:true,maintainAspectRatio:false,interaction:{mode:'index',intersect:false},scales:{x:{ticks:{color:'#8fa4bd'},grid:{display:false}},y:{ticks:{color:'#8fa4bd',callback:v=>v+'%'},grid:{color:'#14263a'},title:{display:true,text:`${comparePayload.horizon_months}个月后较当前`,color:'#8fa4bd'}}},plugins:{legend:{position:'bottom',labels:{color:'#cbd8e6'}}}}});
  charts.compare.options.scales.y.ticks.callback=tick;
  charts.compare.options.scales.y.title.text=axisTitle;
  charts.compare.options.plugins.tooltip={callbacks:{label:context=>`${context.dataset.label}: ${showPrice?fmt(context.parsed.y,0)+' 元/㎡':pct(context.parsed.y)}`}};
  charts.compare.update();
  $('compareTable').innerHTML=rows.map(row=>{
    if(row.status!=='ok')return `<tr><td>${row.city}</td><td colspan="8">该来源最新连续历史不足</td></tr>`;
    const by=Object.fromEntries(row.scenarios.map(x=>[x.key,x]));
    const current=row.current_price==null?pct(row.current_vs_peak):`${fmt(row.current_price,0)} 元/㎡<small>较峰值 ${pct(row.current_vs_peak)}</small>`;
    const terminal=(item,css)=>{const price=scenarioEndPrice(item,row.current_price);return `<td class="${css}">${price==null?pct(item?.end_vs_now):`${fmt(price,0)} 元/㎡<small>较当前 ${pct(item.end_vs_now)}</small>`}</td>`};
    return `<tr><td>${row.city}</td><td>${row.sample_end}</td><td>${current}</td><td>${pct(row.momentum['6m'],2)}</td><td>${pct(row.momentum['12m'],2)}</td><td>${pct(row.momentum['36m'],2)}</td>${terminal(by.optimistic,'scenario-opt')}${terminal(by.base,'scenario-base')}${terminal(by.stress,'scenario-stress')}</tr>`;
  }).join('')||'<tr><td colspan="9">无可用城市</td></tr>';
  $('freshness').textContent=`${sourceLabel()} · 情景生成 ${new Date(comparePayload.generated_at).toLocaleString('zh-CN')}`;
}

function detailQuery(){
  const q=new URLSearchParams({city:$('focusCity').value,source:sourceMode(),kind:$('kind').value,horizon:$('horizon').value,down_payment:(Number($('downPayment').value)||35)/100});
  for(const [key,id] of [['optimistic','rateOptimistic'],['base','rateBase'],['stress','rateStress']]){const value=$(id).value.trim();if(value!=='')q.set(key,value)}
  return q.toString();
}
async function loadDetail(){
  if(!$('focusCity').value)return;
  showError('detailError','');setLoading(true);
  try{
    const response=await fetch('/api/housing-scenario/data?'+detailQuery());
    const payload=await response.json();if(!response.ok)throw Error(payload.error||`HTTP ${response.status}`);
    detailPayload=payload;renderDetail();
  }catch(error){showError('detailError','单城推演失败：'+error.message)}finally{setLoading(false)}
}
function chartValue(value,peak,series){
  if($('indexMode').value==='peak')return value/peak*100;
  return series.value_kind==='price_level'?value*series.price_scale:value;
}
function yScale(){
  const mode=$('axisMode').value;
  if(mode==='70110')return{min:70,max:110};
  if(mode==='custom'){
    const min=Number($('axisMin').value),max=Number($('axisMax').value);
    return Number.isFinite(min)&&Number.isFinite(max)&&min<max?{min,max}:{};
  }
  return{};
}
function renderDetail(){
  const kind=activeKind(),series=detailPayload.series[kind];
  destroy('detail');destroy('anchor');
  if(!series||series.status!=='ok'){showError('detailError','该城市该口径连续历史不足，无法推演。');return}
  const by=scenarioMap(series),horizon=detailPayload.horizon_months;
  const currentHeadline=series.value_kind==='price_level'?`${fmt(series.current.price,0)} 元/㎡`:pct(series.current_vs_peak);
  const currentSmall=series.value_kind==='price_level'?`较峰值 ${pct(series.current_vs_peak)} · 峰值 ${series.peak.period}`:`峰值 ${series.peak.period} · 最新 ${series.current.period}`;
  $('detailKpis').innerHTML=`<div class="kpi">${series.value_kind==='price_level'?'当前挂牌均价':'当前较峰值'}<b>${currentHeadline}</b><small>${currentSmall}</small></div>`+
    ['optimistic','base','stress'].map(key=>{const headline=series.value_kind==='price_level'?`${fmt(scenarioEndPrice(by[key],series.current.price),0)} 元/㎡`:pct(by[key]?.end_vs_now);return `<div class="kpi"><span class="scenario-${key==='optimistic'?'opt':key}">${{optimistic:'乐观',base:'基准',stress:'压力'}[key]}</span> ${horizon}月后<b>${headline}</b><small>${series.value_kind==='price_level'?`较当前 ${pct(by[key]?.end_vs_now)} · `:''}较峰值 ${pct(by[key]?.end_vs_peak)} · 月速 ${pct(by[key]?.monthly_rate,3)}<br>${by[key]?.overridden?'自定义假设':`锚定近 ${by[key]?.window_months} 月`}</small></div>`}).join('')+
    `<div class="kpi">模拟 P50<b>${series.value_kind==='price_level'?`${fmt(series.simulation?.points?.at(-1)?.p50_price,0)} 元/㎡`:pct(series.simulation?.end_vs_now?.p50)}</b><small>${series.value_kind==='price_level'?`较当前 ${pct(series.simulation?.end_vs_now?.p50)} · `:''}${series.simulation?.simulations||0}条路径 · 敏感性中位</small></div>`;
  $('momentumText').textContent=`复合月速：近6月 ${pct(series.momentum['6m'],3)} · 近12月 ${pct(series.momentum['12m'],3)} · 近36月 ${pct(series.momentum['36m'],3)}`;
  for(const [key,id] of [['optimistic','rateOptimistic'],['base','rateBase'],['stress','rateStress']])$(id).placeholder=by[key]?by[key].derived_monthly_rate.toFixed(3):'—';
  renderDetailChart(series,by);
  renderBacktest(series.backtest);
  renderSimulation(series.simulation);
  renderEquity(series.equity);
  renderAnchor(detailPayload.valuation_anchor);
  const source=series.source||{};
  const available=detailPayload.available_sample_start&&detailPayload.available_sample_start!==series.sample_start?`<p>原始可用起点 ${detailPayload.available_sample_start}；因中间缺月，推演只取 ${series.sample_start} 起最新连续段。</p>`:'';
  const imputation=series.imputation||{};
  const imputed=imputation.count?`<p>前值插补：${imputation.count}个月（${imputation.periods.join('、')}），状态 derived_imputed；仅用于情景计算，不回写原始库。</p>`:'';
  $('sourceInfo').innerHTML=`<p>城市：${detailPayload.city}</p><p>样本：${series.sample_start} 至 ${series.sample_end}，${series.n_obs}个月。</p>${available}${imputed}<p>历史状态：${source.data_status||'—'}；来源：${source.name||'—'}</p><p>${source.url?`<a href="${source.url}" target="_blank" rel="noopener">打开最新来源页（${source.latest_period}）</a>`:'无来源链接'}</p>`;
  $('methodNotes').innerHTML=`<p>• ${detailPayload.method.index}</p><p>• ${detailPayload.method.scenario}</p>`+detailPayload.caveats.map(note=>`<p>• ${note}</p>`).join('');
}
function renderDetailChart(series,by){
  const windowSize=Number($('historyWindow').value),history=windowSize?series.points.slice(-windowSize):series.points;
  const future=(by.base?.path||[]),labels=history.map(x=>x.period).concat(future.map(x=>x.period));
  const peak=series.peak.index,pad=new Array(history.length-1).fill(null),futureNull=new Array(future.length).fill(null);
  const transform=value=>value==null?null:chartValue(value,peak,series);
  const actualLabel=series.value_kind==='price_level'?'实际（安居客挂牌）':'实际（统计局）';
  const datasets=[{label:actualLabel,data:history.map(x=>transform(x.index)).concat(futureNull),borderColor:'#5795ff',borderWidth:2,pointRadius:0,spanGaps:false}];
  if(history.some(x=>x.imputed))datasets.push({label:'前值插补（derived）',data:history.map(x=>x.imputed?transform(x.index):null).concat(futureNull),borderColor:'#f5a623',backgroundColor:'#f5a623',showLine:false,pointRadius:5,pointHoverRadius:7});
  const sim=series.simulation?.status==='ok'?series.simulation.points:[];
  if(sim.length){datasets.push({label:'模拟 P90',data:pad.concat([transform(series.current.index)],sim.map(x=>transform(x.p90))),borderColor:'rgba(167,139,250,.35)',pointRadius:0,borderWidth:1});datasets.push({label:'模拟 P10–P90',data:pad.concat([transform(series.current.index)],sim.map(x=>transform(x.p10))),borderColor:'rgba(167,139,250,.35)',backgroundColor:'rgba(167,139,250,.12)',fill:'-1',pointRadius:0,borderWidth:1});datasets.push({label:'模拟 P50',data:pad.concat([transform(series.current.index)],sim.map(x=>transform(x.p50))),borderColor:'#a78bfa',borderDash:[2,3],pointRadius:0,borderWidth:1.3})}
  for(const key of ['optimistic','base','stress'])if(by[key])datasets.push({label:`${{optimistic:'乐观',base:'基准',stress:'压力'}[key]} ${pct(by[key].monthly_rate,3)}/月`,data:pad.concat([transform(series.current.index)],by[key].path.map(x=>transform(x.index))),borderColor:COLORS[key],borderDash:[6,3],pointRadius:0,borderWidth:1.8});
  const rawLabel=series.value_kind==='price_level'?'挂牌均价（元/㎡）':'定基指数';
  const kindLabel=series.value_kind==='price_level'?'二手房挂牌价':$('kind').selectedOptions[0].text;
  $('detailChartTitle').textContent=`${detailPayload.city} · ${kindLabel} · ${$('indexMode').value==='peak'?'峰值=100':rawLabel}`;
  charts.detail=new Chart($('detailChart'),{type:'line',data:{labels,datasets},options:{responsive:true,maintainAspectRatio:false,interaction:{mode:'index',intersect:false},scales:{x:{ticks:{color:'#8fa4bd',maxTicksLimit:16},grid:{color:'#14263a'}},y:{...yScale(),ticks:{color:'#8fa4bd'},grid:{color:'#14263a'},title:{display:true,text:$('indexMode').value==='peak'?'峰值=100':rawLabel,color:'#8fa4bd'}}},plugins:{legend:{position:'bottom',labels:{color:'#cbd8e6',boxWidth:15,usePointStyle:true}}}}});
}
function renderBacktest(backtest){
  if(!backtest||backtest.status!=='ok'){$('backtestKpis').innerHTML='<div class="muted">历史不足</div>';$('backtestNote').textContent='';return}
  $('backtestKpis').innerHTML=`<div class="kpi">中位绝对误差<b>${pct(backtest.median_absolute_error_pp)}</b><small>百分点</small></div><div class="kpi">区间覆盖<b>${pct(backtest.envelope_coverage_pct,0)}</b><small>${backtest.n_obs}个历史起点</small></div><div class="kpi">方向命中<b>${pct(backtest.direction_hit_pct,0)}</b><small>${backtest.horizon_months}个月规则</small></div>`;
  const latest=backtest.latest;
  $('backtestNote').textContent=`最近一次可验证：${latest.as_of} 起，基准 ${pct(latest.base_change)}，实际至 ${latest.target_period} 为 ${pct(latest.actual_change)}。${backtest.method}`;
}
function renderSimulation(sim){
  if(!sim||sim.status!=='ok'){$('simulationSummary').innerHTML='<div class="muted">历史不足</div>';return}
  const listing=activeKind()==='listing',end=sim.points.at(-1)||{};
  $('simulationTitle').textContent=listing?'模拟区间期末挂牌价':'模拟区间期末变化';
  $('simulationSummary').innerHTML=['p10','p50','p90'].map(key=>`<div class="kpi">${key.toUpperCase()}<b>${listing?`${fmt(end[`${key}_price`],0)} 元/㎡`:pct(sim.end_vs_now[key])}</b><small>${listing?`较当前 ${pct(sim.end_vs_now[key])}`:'较当前'}</small></div>`).join('');
}
function renderEquity(equity){
  // 权益变化会跌破 -100%，必须说清含义，否则读者会读成"亏掉了本金的 137%"
  $('equityNote').textContent=`首付 ${fmt(equity.down_payment*100,0)}%。自有资金变化＝价格变化 ÷ 首付比，`+
    `是价格变动对首付的杠杆放大；未计已还本金与利息支出，因此不等于家庭净值变动。`+
    `低于 -100% 表示价格跌幅已超过首付，账面上房产价值低于剩余贷款余额，并非"亏掉本金的一倍以上"。`;
  $('equityTable').innerHTML=(equity.rows||[]).map(row=>`<tr><td>${row.purchase_period}</td><td>${pct(row.price_change_to_now)}</td><td>${pct(row.equity_change_to_now,0)}</td><td class="scenario-opt">${pct(row.by_scenario.optimistic?.equity_change,0)}</td><td class="scenario-base">${pct(row.by_scenario.base?.equity_change,0)}</td><td class="scenario-stress">${pct(row.by_scenario.stress?.equity_change,0)}</td></tr>`).join('')||'<tr><td colspan="6">无可用买入时点</td></tr>';
}
function renderAnchor(anchor){
  $('anchorChartWrap').classList.toggle('hidden',!anchor);
  if(!anchor){
    $('anchorTitle').textContent=sourceMode()==='anjuke'?'估值锚（挂牌口径不计算）':'估值锚：房价指数 / 工资指数';
    $('anchorNote').textContent=sourceMode()==='anjuke'?'挂牌均价不是官方同质指数，本页不把它与工资序列拼成估值锚。':'该城市缺少可对齐的工资序列，保持缺失。';
    return;
  }
  $('anchorTitle').textContent='估值锚：房价指数 / 工资指数';
  $('anchorNote').textContent=`${anchor.note} 最新 ${anchor.latest.period}，较峰值 ${pct(anchor.latest_vs_peak)}。`;
  charts.anchor=new Chart($('anchorChart'),{type:'line',data:{labels:anchor.points.map(x=>x.period),datasets:[{label:'房价/工资指数',data:anchor.points.map(x=>x.ratio),borderColor:'#a78bfa',pointRadius:2}]},options:{responsive:true,maintainAspectRatio:false,scales:{x:{ticks:{color:'#8fa4bd'},grid:{color:'#14263a'}},y:{ticks:{color:'#8fa4bd'},grid:{color:'#14263a'}}},plugins:{legend:{display:false}}}});
}
function downloadCsv(){
  if(!comparePayload)return;
  const lines=[['城市','最新期','当前挂牌价(元/㎡)','当前较峰值(%)','近6月月速(%)','近12月月速(%)','近36月月速(%)','乐观期末挂牌价(元/㎡)','乐观期末较当前(%)','基准期末挂牌价(元/㎡)','基准期末较当前(%)','压力期末挂牌价(元/㎡)','压力期末较当前(%)']];
  for(const row of comparePayload.rows){const by=Object.fromEntries((row.scenarios||[]).map(x=>[x.key,x]));lines.push([row.city,row.sample_end||'',row.current_price??'',row.current_vs_peak??'',row.momentum?.['6m']??'',row.momentum?.['12m']??'',row.momentum?.['36m']??'',scenarioEndPrice(by.optimistic,row.current_price)??'',by.optimistic?.end_vs_now??'',scenarioEndPrice(by.base,row.current_price)??'',by.base?.end_vs_now??'',scenarioEndPrice(by.stress,row.current_price)??'',by.stress?.end_vs_now??''])}
  const blob=new Blob(['\ufeff'+lines.map(row=>row.join(',')).join('\n')],{type:'text/csv;charset=utf-8'}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=`housing-scenario-${sourceMode()}-${activeKind()}-${$('horizon').value}m.csv`;a.click();URL.revokeObjectURL(url);
}
function syncSourceUi(){
  const listing=sourceMode()==='anjuke';
  ['rateOptimistic','rateBase','rateStress'].forEach(id=>$(id).value='');
  $('kind').disabled=listing;
  $('historyBadge').className=`badge ${listing?'listing':'official'}`;
  $('historyBadge').textContent=listing?'历史 listing_reference · 未来 scenario':'历史 official · 未来 scenario';
  $('sourceNotice').innerHTML=listing?'<b>挂牌价·参考，不是成交价。</b> 安居客为商业平台；情景层只对孤立单月缺口采用前值法并标记，连续缺失不补，且不与统计局指数拼接。全部未来路径仍是情景，不是预测。':'<b>这里展示情景，不是价格预测。</b> 历史为统计局 70 城同质可比指数；常州不在官方 70 城名单中，请切换到“安居客挂牌价·参考”查看。模拟分位不代表真实概率。';
  $('compareValueMode').disabled=!listing;
  $('compareValueMode').value=listing?'price':'change';
  $('indexMode').querySelector('[value="raw"]').textContent=listing?'挂牌价（元/㎡）':'定基指数';
  $('indexMode').value=listing?'raw':'peak';
  $('historyWindow').value=listing?'0':'120';
  $('axisMode').value='auto';
  $('axisMin').disabled=true;$('axisMax').disabled=true;
}
async function loadCatalog(){
  try{
    syncSourceUi();showError('compareError','');setLoading(true);
    const response=await fetch('/api/housing-scenario/cities?'+new URLSearchParams({source:sourceMode()})),payload=await response.json();if(!response.ok)throw Error(payload.error||`HTTP ${response.status}`);
    catalog=payload.cities||[];selected=new Set(focusCities().filter(city=>catalog.some(x=>x.city===city)));renderCityChips();syncFocus(requestedFocus);requestedFocus=null;renderSelectionHint();updateUrlState();
    $('freshness').textContent=`${payload.source_label||sourceLabel()} ${payload.city_count} 城 · 最新 ${payload.latest_period||'—'}`;
    await loadComparison();
  }catch(error){showError('compareError','来源目录加载失败：'+error.message)}finally{setLoading(false)}
}
async function init(){
  const source=INITIAL_PARAMS.get('source');
  if(source==='official'||source==='anjuke')$('dataSource').value=source;
  const horizon=INITIAL_PARAMS.get('horizon');
  if([...$('horizon').options].some(option=>option.value===horizon))$('horizon').value=horizon;
  const kind=INITIAL_PARAMS.get('kind');
  if(kind==='new'||kind==='second')$('kind').value=kind;
  await loadCatalog();
}
document.querySelectorAll('[data-group]').forEach(button=>button.onclick=()=>applyGroup(button.dataset.group));
$('citySearch').oninput=renderCityChips;$('compareRun').onclick=loadComparison;$('downloadCsv').onclick=downloadCsv;
$('focusCity').onchange=()=>{updateUrlState();loadDetail()};$('detailRun').onclick=loadDetail;$('kind').onchange=()=>{updateUrlState();loadComparison()};$('horizon').onchange=()=>{updateUrlState();loadComparison()};$('dataSource').onchange=()=>{requestedFocus=sourceMode()==='anjuke'?'常州':'北京';loadCatalog()};
$('compareValueMode').onchange=()=>comparePayload&&renderComparison();
$('historyWindow').onchange=()=>detailPayload&&renderDetail();$('indexMode').onchange=()=>detailPayload&&renderDetail();
$('axisMode').onchange=()=>{const enabled=$('axisMode').value==='custom';if($('axisMode').value==='70110')$('indexMode').value='peak';$('axisMin').disabled=!enabled;$('axisMax').disabled=!enabled;if(detailPayload)renderDetail()};
['axisMin','axisMax'].forEach(id=>$(id).onchange=()=>detailPayload&&renderDetail());$('downPayment').onchange=loadDetail;
$('resetRates').onclick=()=>{['rateOptimistic','rateBase','rateStress'].forEach(id=>$(id).value='');loadDetail()};
init();
