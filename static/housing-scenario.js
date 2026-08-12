'use strict';

const $=id=>document.getElementById(id);
const COLORS={optimistic:'#27d3b2',base:'#f5a623',stress:'#ff6b7d'};
const OFFICIAL_FOCUS=['北京','上海','广州','深圳','厦门','南京','合肥','无锡'];
const LISTING_CORE=['北京','上海','广州','深圳','厦门','南京','合肥','常州','苏州','无锡'];
const LISTING_ADDED=['武汉','长沙','成都','杭州','福州'];
const LISTING_FOCUS=[...LISTING_CORE,...LISTING_ADDED];
const TIER1=['北京','上海','广州','深圳'];
let catalog=[],selected=new Set(),comparePayload=null,detailPayload=null,demographicPayload=null,charts={};
const INITIAL_PARAMS=new URLSearchParams(location.search);
let requestedFocus=INITIAL_PARAMS.get('city')||'常州';
const fmt=(v,d=1)=>v==null?'—':Number(v).toLocaleString('zh-CN',{minimumFractionDigits:d,maximumFractionDigits:d});
const pct=(v,d=1)=>v==null?'—':`${fmt(v,d)}%`;
const periodOrdinal=period=>Number(period?.slice(0,4))*12+Number(period?.slice(5,7))-1;
function addMonths(period,months){const total=periodOrdinal(period)+Number(months),year=Math.floor(total/12),month=total%12+1;return `${year}-${String(month).padStart(2,'0')}`}
function monthRange(start,end){const count=periodOrdinal(end)-periodOrdinal(start);return count<0?[]:Array.from({length:count+1},(_,index)=>addMonths(start,index))}
function detailXAxisLabel(labels,index,currentPeriod){
  const period=labels[index];
  if(!period)return '';
  if(index===0||index===labels.length-1||period===currentPeriod)return period;
  if(period.slice(0,4)===currentPeriod?.slice(0,4))return '';
  const startYear=Number(labels[0]?.slice(0,4)),endYear=Number(labels.at(-1)?.slice(0,4)),year=Number(period.slice(0,4));
  const yearStep=endYear-startYear>18?3:endYear-startYear>10?2:1;
  return period.endsWith('-01')&&(year-startYear)%yearStep===0?String(year):'';
}
function destroy(key){if(charts[key]){charts[key].destroy();delete charts[key]}}
function showError(id,message){$(id).textContent=message||'';$(id).classList.toggle('hidden',!message)}
function setLoading(on){document.body.classList.toggle('loading',on)}
function useStructural(){return $('forecastMode')?.value==='structural'}
function scenarioItems(container){
  const structural=container?.structural_scenarios||[];
  return useStructural()&&structural.length?structural:(container?.scenarios||[]);
}
function scenarioMap(series){return Object.fromEntries(scenarioItems(series).filter(x=>!x.status).map(x=>[x.key,x]))}
function momentumScenarioMap(series){return Object.fromEntries((series?.scenarios||[]).filter(x=>!x.status).map(x=>[x.key,x]))}
function modelLabel(){return useStructural()?'结构驱动修正':'纯价格动能'}
function structuralWeight(){return Math.max(0,Math.min(100,Number($('structuralWeight')?.value)||0))/100}
function horizonLabel(payload){return payload?.end_period?`到${payload.end_period}`:`${payload?.horizon_months}个月后`}
function scenarioEndPrice(item,currentPrice){
  if(item?.end_price!=null)return item.end_price;
  return item?.end_vs_now!=null&&currentPrice!=null?currentPrice*(1+item.end_vs_now/100):null;
}
function sourceMode(){return $('dataSource').value}
function isYearlySource(){return sourceMode()==='anjuke_yearly'}
function isListingSource(){return sourceMode()==='anjuke'||isYearlySource()}
function activeKind(){return isListingSource()?'listing':$('kind').value}
function defaultCities(){return isListingSource()?LISTING_CORE:OFFICIAL_FOCUS}
function sourceLabel(){return sourceMode()==='anjuke'?'安居客月度·15城目录':isYearlySource()?'安居客年度·15城目录':'统计局官方指数'}
function momentumSpecs(){return isYearlySource()?[['36m','近3年'],['60m','近5年'],['120m','近10年']]:[['6m','近6月'],['12m','近12月'],['36m','近36月']]}
function selectSource(source){
  if(!['anjuke','anjuke_yearly','official'].includes(source))return;
  $('dataSource').value=source;
  requestedFocus=source==='anjuke'?'常州':source==='anjuke_yearly'?'上海':'北京';
  loadCatalog();
}

function renderCityChips(){
  const query=$('citySearch').value.trim();
  $('cityChips').innerHTML=catalog.filter(item=>!query||item.city.includes(query)).map(item=>{
    const missing=item.status==='missing';
    return `<button class="chip ${selected.has(item.city)?'active':''} ${missing?'missing':''}" data-city="${item.city}" title="${missing?'当前来源暂无可信记录':'当前来源已有记录'}">${item.city}${missing?'<small>缺</small>':''}</button>`;
  }).join('');
  document.querySelectorAll('[data-city]').forEach(button=>button.onclick=()=>{
    const city=button.dataset.city;
    if(selected.has(city))selected.delete(city);else if(selected.size<12)selected.add(city);
    renderCityChips();syncFocus();renderSelectionHint();
  });
}
function renderSelectionHint(){
  const total=catalog.length;
  $('selectionHint').textContent=`已选 ${selected.size} 城 · ${sourceLabel()}目录 ${total} 城`+(selected.size>=12?' · 已达到图表上限 12 城':'');
  if(demographicPayload)renderCityCapacityChart();
}
function applyGroup(group){
  if(group==='clear')selected.clear();
  else if(group==='all')selected=new Set(catalog.slice(0,12).map(x=>x.city));
  else {
    const names=group==='tier1'?TIER1:group==='added'?LISTING_ADDED:
      group==='core'?LISTING_CORE:defaultCities();
    selected=new Set(names.filter(city=>catalog.some(x=>x.city===city)).slice(0,12));
  }
  renderCityChips();syncFocus();renderSelectionHint();
}
function syncFocus(preferred){
  const previous=preferred||$('focusCity').value;
  const available=catalog.filter(item=>item.status!=='missing');
  const firstAvailable=available[0]?.city||'';
  $('focusCity').innerHTML=catalog.map(item=>`<option value="${item.city}" ${item.status==='missing'?'disabled':''}>${item.city}${item.status==='missing'?'（缺数据）':''}</option>`).join('');
  $('focusCity').value=available.some(item=>item.city===previous)?previous:firstAvailable;
}
function updateUrlState(){
  const params=new URLSearchParams(location.search);
  params.set('source',sourceMode());
  if($('focusCity').value)params.set('city',$('focusCity').value);
  params.set('horizon',$('horizon').value);
  params.set('kind',$('kind').value);
  params.set('model',$('forecastMode').value);
  params.set('structural_weight',String(Math.round(structuralWeight()*100)));
  const formation=formationAdjustments();
  params.set('formation_optimistic',String(formation.optimistic));
  params.set('formation_base',String(formation.base));
  params.set('formation_stress',String(formation.stress));
  history.replaceState(null,'',`${location.pathname}?${params}${location.hash}`);
}
function scrollToPageAnchor(){
  if(!location.hash)return;
  const target=document.querySelector(location.hash);
  if(target)requestAnimationFrame(()=>target.scrollIntoView({block:'start'}));
}

function compareQuery(){
  const formation=formationAdjustments();
  return new URLSearchParams({cities:[...selected].join(','),source:sourceMode(),kind:$('kind').value,horizon:$('horizon').value,structural_weight:structuralWeight(),formation_optimistic:formation.optimistic,formation_base:formation.base,formation_stress:formation.stress}).toString();
}
async function loadComparison(){
  if(!selected.size){showError('compareError','请至少选择一个城市。');return}
  if(!validateFormationInputs())return;
  showError('compareError','');setLoading(true);
  try{
    const response=await fetch('/api/housing-scenario/compare?'+compareQuery());
    const payload=await response.json();if(!response.ok)throw Error(payload.error||`HTTP ${response.status}`);
    comparePayload=payload;renderComparison();await loadDetail();scrollToPageAnchor();
  }catch(error){showError('compareError','多城比较加载失败：'+error.message)}finally{setLoading(false)}
}
function renderComparison(){
  const rows=comparePayload.rows||[],ok=rows.filter(row=>row.status==='ok');
  renderDemographicCapacity(comparePayload.demographic_capacity);
  destroy('compare');
  const labels=ok.map(row=>row.city);
  const showPrice=isListingSource()&&$('compareValueMode').value==='price';
  const value=(row,key)=>{const item=scenarioItems(row).find(x=>x.key===key);return item?(showPrice?scenarioEndPrice(item,row.current_price):item.end_vs_now):null};
  const horizonText=horizonLabel(comparePayload);
  const axisTitle=showPrice?`${horizonText}挂牌均价（元/㎡）`:`${horizonText}较当前`;
  const tick=v=>showPrice?fmt(v,0):v+'%';
  charts.compare=new Chart($('compareChart'),{type:'bar',data:{labels,datasets:['optimistic','base','stress'].map(key=>({label:{optimistic:'乐观',base:'基准',stress:'压力'}[key],data:ok.map(row=>value(row,key)),backgroundColor:COLORS[key]}))},options:{responsive:true,maintainAspectRatio:false,interaction:{mode:'index',intersect:false},scales:{x:{ticks:{color:'#8fa4bd'},grid:{display:false}},y:{ticks:{color:'#8fa4bd',callback:v=>v+'%'},grid:{color:'#14263a'},title:{display:true,text:`${horizonText}较当前`,color:'#8fa4bd'}}},plugins:{legend:{position:'bottom',labels:{color:'#cbd8e6'}}}}});
  charts.compare.options.scales.y.ticks.callback=tick;
  charts.compare.options.scales.y.title.text=axisTitle;
  charts.compare.options.plugins.tooltip={callbacks:{label:context=>`${context.dataset.label}: ${showPrice?fmt(context.parsed.y,0)+' 元/㎡':pct(context.parsed.y)}`}};
  charts.compare.update();
  $('compareTable').innerHTML=rows.map(row=>{
    if(row.status!=='ok')return `<tr><td>${row.city}</td><td colspan="8">${row.n_obs===0?'暂无有效挂牌记录（missing）':isYearlySource()?'年度真实观测不足':'该来源最新连续历史不足'}</td></tr>`;
    const by=Object.fromEntries(scenarioItems(row).map(x=>[x.key,x]));
    const current=row.current_price==null?pct(row.current_vs_peak):`${fmt(row.current_price,0)} 元/㎡<small>较峰值 ${pct(row.current_vs_peak)}</small>`;
    const terminal=(item,css)=>{const price=scenarioEndPrice(item,row.current_price);return `<td class="${css}">${price==null?pct(item?.end_vs_now):`${fmt(price,0)} 元/㎡<small>较当前 ${pct(item.end_vs_now)}</small>`}</td>`};
    const momentumCells=momentumSpecs().map(([key])=>{const meta=row.momentum_windows?.[key];const note=meta?`<small>${meta.start_period}→${meta.end_period}，实际${meta.actual_months}月</small>`:'';return `<td>${pct(row.momentum[key],2)}${note}</td>`}).join('');
    const coverage=row.driver_coverage||{},driverNote=useStructural()?`<small>结构：本市${coverage.city_specific_used||0}项 / 全国回退${coverage.national_fallback_used||0}项</small>`:'';
    return `<tr><td>${row.city}${driverNote}</td><td>${row.sample_end}</td><td>${current}</td>${momentumCells}${terminal(by.optimistic,'scenario-opt')}${terminal(by.base,'scenario-base')}${terminal(by.stress,'scenario-stress')}</tr>`;
  }).join('')||'<tr><td colspan="9">无可用城市</td></tr>';
  $('freshness').textContent=`${sourceLabel()} · ${modelLabel()} · 情景生成 ${new Date(comparePayload.generated_at).toLocaleString('zh-CN')}`;
}

function detailQuery(){
  const q=new URLSearchParams({city:$('focusCity').value,source:sourceMode(),kind:$('kind').value,horizon:$('horizon').value,down_payment:(Number($('downPayment').value)||35)/100,structural_weight:structuralWeight()});
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
  destroy('detail');destroy('anchor');destroy('driverContribution');destroy('nationalDriver');
  if(!series||series.status!=='ok'){showError('detailError',isYearlySource()?'该城市年度真实观测不足，无法形成三档趋势。':'该城市该口径连续历史不足，无法推演。');return}
  const by=scenarioMap(series),momentumBy=momentumScenarioMap(series),horizonText=horizonLabel(detailPayload);
  const currentHeadline=series.value_kind==='price_level'?`${fmt(series.current.price,0)} 元/㎡`:pct(series.current_vs_peak);
  const currentSmall=series.value_kind==='price_level'?`较峰值 ${pct(series.current_vs_peak)} · 峰值 ${series.peak.period}`:`峰值 ${series.peak.period} · 最新 ${series.current.period}`;
  const scenarioAnchor=item=>isYearlySource()?`锚定约 ${fmt((item?.requested_window_months||0)/12,0)} 年（实际 ${item?.window_months||'—'} 月）`:`锚定近 ${item?.window_months||'—'} 月`;
  const simOk=series.simulation?.status==='ok',simEnd=series.simulation?.points?.at(-1)||{};
  const simulationKpi=simOk?`<div class="kpi">模拟 P50<b>${series.value_kind==='price_level'?`${fmt(simEnd.p50_price,0)} 元/㎡`:pct(series.simulation?.end_vs_now?.p50)}</b><small>${series.value_kind==='price_level'?`较当前 ${pct(series.simulation?.end_vs_now?.p50)} · `:''}${series.simulation?.simulations||0}条路径 · 敏感性中位</small></div>`:`<div class="kpi">月度模拟<b>不适用</b><small>${series.simulation?.reason||'历史不足'}</small></div>`;
  $('detailKpis').innerHTML=`<div class="kpi">${series.value_kind==='price_level'?'当前挂牌均价':'当前较峰值'}<b>${currentHeadline}</b><small>${currentSmall}</small></div>`+
    ['optimistic','base','stress'].map(key=>{const item=by[key],headline=series.value_kind==='price_level'?`${fmt(scenarioEndPrice(item,series.current.price),0)} 元/㎡`:pct(item?.end_vs_now);const rawDelta=Number(item?.structural_delta_pp),delta=Math.abs(rawDelta)<0.005?0:rawDelta;const modelNote=useStructural()?`动能年化 ${pct(item?.momentum_annualised,2)} · 结构修正 ${delta>0?'+':''}${fmt(delta,2)}pp`:(item?.overridden?'自定义假设':scenarioAnchor(item));return `<div class="kpi"><span class="scenario-${key==='optimistic'?'opt':key}">${{optimistic:'乐观',base:'基准',stress:'压力'}[key]}</span> ${horizonText}<b>${headline}</b><small>${series.value_kind==='price_level'?`较当前 ${pct(item?.end_vs_now)} · `:''}较峰值 ${pct(item?.end_vs_peak)} · 年化 ${pct(item?.annualised,2)}<br>${modelNote}</small></div>`}).join('')+simulationKpi;
  $('momentumText').textContent='复合月速：'+momentumSpecs().map(([key,label])=>{const meta=series.momentum_windows?.[key];return `${label} ${pct(series.momentum[key],3)}${meta?`（实际${meta.actual_months}月）`:''}`}).join(' · ');
  for(const [key,id] of [['optimistic','rateOptimistic'],['base','rateBase'],['stress','rateStress']])$(id).placeholder=momentumBy[key]?momentumBy[key].derived_monthly_rate.toFixed(3):'—';
  renderDetailChart(series,by,momentumBy);
  renderStructuralDrivers(detailPayload.structural_drivers,series.structural_scenarios||[]);
  renderBacktest(series.backtest);
  renderSimulation(series.simulation);
  renderEquity(useStructural()&&series.structural_equity?series.structural_equity:series.equity);
  renderAnchor(detailPayload.valuation_anchor);
  const source=series.source||{};
  const available=detailPayload.available_sample_start&&detailPayload.available_sample_start!==series.sample_start?`<p>原始可用起点 ${detailPayload.available_sample_start}；因中间缺月，推演只取 ${series.sample_start} 起最新连续段。</p>`:'';
  const imputation=series.imputation||{};
  const imputed=imputation.count?`<p>前值插补：${imputation.count}个月（${imputation.periods.join('、')}），状态 derived_imputed；仅用于情景计算，不回写原始库。</p>`:'';
  const observationUnit=series.observation_unit||'个月';
  const grain=source.source_grains?.length?`<p>源粒度：${source.source_grains.join(' / ')}。</p>`:'';
  const coverage=detailPayload.structural_drivers?.coverage||{};
  $('sourceInfo').innerHTML=`<p>城市：${detailPayload.city}</p><p>样本：${series.sample_start} 至 ${series.sample_end}，${series.n_obs}${observationUnit}。</p>${available}${imputed}<p>历史状态：${source.data_status||'—'}；来源：${source.name||'—'}</p>${grain}<p>结构驱动：模型使用 ${coverage.model_drivers_used||0} 项，其中本市 ${coverage.city_specific_used||0} 项、全国回退 ${coverage.national_fallback_used||0} 项。</p><p>${source.url?`<a href="${source.url}" target="_blank" rel="noopener">打开最新来源页（${source.latest_period}）</a>`:'无来源链接'}</p>`;
  $('methodNotes').innerHTML=`<p>• ${detailPayload.method.index}</p><p>• ${detailPayload.method.scenario}</p>${detailPayload.method.structural?`<p>• ${detailPayload.method.structural}</p>`:''}`+detailPayload.caveats.map(note=>`<p>• ${note}</p>`).join('');
}
function renderDetailChart(series,by,momentumBy){
  const windowSize=Number($('historyWindow').value),latestOrdinal=periodOrdinal(series.current.period);
  const history=windowSize?series.points.filter(point=>periodOrdinal(point.period)>=latestOrdinal-windowSize):series.points;
  const future=(by.base?.path||[]),lastPeriod=future.at(-1)?.period||series.current.period;
  $('detailHorizonBadge').textContent=`情景终点 ${lastPeriod}`;
  const labels=monthRange(history[0]?.period||series.current.period,lastPeriod);
  const peak=series.peak.index;
  const transform=value=>value==null?null:chartValue(value,peak,series);
  const actualLabel=series.value_kind==='price_level'?(isYearlySource()?'真实年点（安居客年度）':'实际月点（安居客挂牌）'):'实际（统计局）';
  const historyMap=new Map(history.map(point=>[point.period,point]));
  const datasets=[{label:actualLabel,data:labels.map(period=>transform(historyMap.get(period)?.index)),borderColor:'#5795ff',borderWidth:2,pointRadius:isYearlySource()?3:0,spanGaps:isYearlySource()}];
  if(history.some(x=>x.imputed))datasets.push({label:'前值插补（derived）',data:labels.map(period=>historyMap.get(period)?.imputed?transform(historyMap.get(period).index):null),borderColor:'#f5a623',backgroundColor:'#f5a623',showLine:false,pointRadius:5,pointHoverRadius:7});
  const sim=series.simulation?.status==='ok'?series.simulation.points:[];
  if(sim.length){const simMap=new Map(sim.map(point=>[point.period,point])),simData=key=>labels.map(period=>period===series.current.period?transform(series.current.index):transform(simMap.get(period)?.[key]));datasets.push({label:'模拟 P90',data:simData('p90'),borderColor:'rgba(167,139,250,.35)',pointRadius:0,borderWidth:1});datasets.push({label:'模拟 P10–P90',data:simData('p10'),borderColor:'rgba(167,139,250,.35)',backgroundColor:'rgba(167,139,250,.12)',fill:'-1',pointRadius:0,borderWidth:1});datasets.push({label:'模拟 P50',data:simData('p50'),borderColor:'#a78bfa',borderDash:[2,3],pointRadius:0,borderWidth:1.3})}
  if(useStructural()&&momentumBy?.base){const rawMap=new Map(momentumBy.base.path.map(point=>[point.period,point.index]));datasets.push({label:'纯动能基准（对照）',data:labels.map(period=>period===series.current.period?transform(series.current.index):transform(rawMap.get(period))),borderColor:'#7890a8',borderDash:[2,5],pointRadius:0,borderWidth:1.2})}
  for(const key of ['optimistic','base','stress'])if(by[key]){const pathMap=new Map(by[key].path.map(point=>[point.period,point.index]));datasets.push({label:`${{optimistic:'乐观',base:'基准',stress:'压力'}[key]} ${pct(by[key].monthly_rate,3)}/月`,data:labels.map(period=>period===series.current.period?transform(series.current.index):transform(pathMap.get(period))),borderColor:COLORS[key],borderDash:[6,3],pointRadius:0,borderWidth:1.8,spanGaps:false})}
  const rawLabel=series.value_kind==='price_level'?'挂牌均价（元/㎡）':'定基指数';
  const kindLabel=series.value_kind==='price_level'?'二手房挂牌价':$('kind').selectedOptions[0].text;
  $('detailChartTitle').textContent=`${detailPayload.city} · ${kindLabel} · ${$('indexMode').value==='peak'?'峰值=100':rawLabel}`;
  charts.detail=new Chart($('detailChart'),{type:'line',data:{labels,datasets},options:{responsive:true,maintainAspectRatio:false,interaction:{mode:'index',intersect:false},scales:{x:{offset:true,ticks:{color:'#8fa4bd',autoSkip:false,maxRotation:0,minRotation:0,callback:(value,index)=>detailXAxisLabel(labels,index,series.current.period)},grid:{color:context=>context.tick?.label?'#14263a':'transparent'},title:{display:true,text:`历史实际 + 情景路径（终点 ${lastPeriod}）`,color:'#8fa4bd'}},y:{...yScale(),ticks:{color:'#8fa4bd'},grid:{color:'#14263a'},title:{display:true,text:$('indexMode').value==='peak'?'峰值=100':rawLabel,color:'#8fa4bd'}}},plugins:{legend:{position:'bottom',labels:{color:'#cbd8e6',boxWidth:15,usePointStyle:true}}}}});
}
function driverAssumption(driver,key){
  const value=driver?.scenario_values?.[key];
  if(value==null)return '—';
  if(driver.metric_kind==='level_ratio')return `${fmt(value,2)}倍`;
  if(driver.metric_kind==='change_pp')return `${value>=0?'+':''}${fmt(value,2)}pp`;
  return pct(value,2);
}
function renderStructuralDrivers(snapshot,structuralScenarios){
  const drivers=snapshot?.drivers||[],coverage=snapshot?.coverage||{};
  const missing=(coverage.missing_optional||[]).join('、');
  const unavailable=(coverage.unavailable_comparable_fields||[]).join('、');
  const effectiveWeight=useStructural()?structuralWeight()*100:0;
  $('driverCoverage').innerHTML=`使用 <b>${coverage.model_drivers_used||0}</b> 项：本市 <b>${coverage.city_specific_used||0}</b> 项、全国回退 <b>${coverage.national_fallback_used||0}</b> 项。${missing?`本城缺失：${missing}。`:''} 当前模型实际修正强度 <b>${fmt(effectiveWeight,0)}%</b>。${unavailable?`<small>当前本地库尚无同口径序列：${unavailable}。</small>`:''}`;
  $('driverTable').innerHTML=drivers.map(driver=>{
    const scopeClass=driver.scope==='city'?'scope-city':driver.scope==='national_fallback'?'scope-fallback':'';
    const source=driver.source_url?`<a href="${driver.source_url}" target="_blank" rel="noopener">${driver.scope_label}</a>`:driver.scope_label;
    return `<tr><td>${driver.label}</td><td class="${scopeClass}">${source}<small>${driver.sample_start}—${driver.sample_end} · ${driver.n_obs}点 · ${driver.data_status||'—'}</small></td><td>${driverAssumption(driver,'optimistic')}</td><td>${driverAssumption(driver,'base')}</td><td>${driverAssumption(driver,'stress')}</td><td>${fmt(driver.coefficient,2)}×<small>贡献上限 ±${fmt(driver.contribution_cap_pp,1)}pp${driver.scenario_guardrail?`<br>${driver.scenario_guardrail}`:''}</small></td></tr>`;
  }).join('')||'<tr><td colspan="6">结构驱动不足，未运行修正。</td></tr>';
  $('driverMethod').textContent=(snapshot?.method||'')+' '+(snapshot?.caveats||[]).slice(0,2).join(' ');

  destroy('driverContribution');
  if(structuralScenarios.length){
    const labels=['乐观','基准','压力'],keys=['optimistic','base','stress'];
    const driverKeys=[...new Set(structuralScenarios.flatMap(row=>(row.driver_contributions||[]).map(item=>item.key)))];
    const palette=['#5795ff','#27d3b2','#a78bfa','#f5a623','#ff6b7d','#55c2d8'];
    const scenarios=Object.fromEntries(structuralScenarios.map(row=>[row.key,row]));
    const datasets=driverKeys.map((driverKey,index)=>({
      label:drivers.find(row=>row.key===driverKey)?.label||driverKey,
      data:keys.map(key=>scenarios[key]?.driver_contributions?.find(item=>item.key===driverKey)?.contribution_pp??0),
      backgroundColor:palette[index%palette.length],borderWidth:0,
    }));
    charts.driverContribution=new Chart($('driverContributionChart'),{type:'bar',data:{labels,datasets},options:{indexAxis:'y',responsive:true,maintainAspectRatio:false,interaction:{mode:'index',intersect:false},scales:{x:{stacked:true,ticks:{color:'#8fa4bd',callback:v=>v+'pp'},grid:{color:'#14263a'},title:{display:true,text:'对年化房价速度的机械贡献（百分点）',color:'#8fa4bd'}},y:{stacked:true,ticks:{color:'#cbd8e6'},grid:{display:false}}},plugins:{legend:{position:'bottom',labels:{color:'#cbd8e6',boxWidth:12}},tooltip:{callbacks:{label:c=>`${c.dataset.label}: ${c.parsed.x>=0?'+':''}${fmt(c.parsed.x,2)}pp`}}}}});
  }

  destroy('nationalDriver');
  const history=(snapshot?.national_history||[]).filter(row=>Number(row.period)>=2010);
  if(history.length){
    charts.nationalDriver=new Chart($('nationalDriverChart'),{type:'line',data:{labels:history.map(row=>row.period),datasets:[
      {label:'全国人口增速',data:history.map(row=>row.national_population_growth),borderColor:'#5795ff',pointRadius:1,spanGaps:true},
      {label:'人均可支配收入增速',data:history.map(row=>row.national_disposable_income_growth),borderColor:'#27d3b2',pointRadius:1,spanGaps:true},
      {label:'粗结婚率增速',data:history.map(row=>row.national_crude_marriage_rate_growth),borderColor:'#ff6b7d',pointRadius:1,spanGaps:true},
    ]},options:{responsive:true,maintainAspectRatio:false,interaction:{mode:'index',intersect:false},scales:{x:{ticks:{color:'#8fa4bd',maxTicksLimit:10},grid:{color:'#14263a'}},y:{ticks:{color:'#8fa4bd',callback:v=>v+'%'},grid:{color:'#14263a'}}},plugins:{legend:{position:'bottom',labels:{color:'#cbd8e6',boxWidth:12}},tooltip:{callbacks:{label:c=>`${c.dataset.label}: ${pct(c.parsed.y,2)}`}}}}});
  }
  const context=snapshot?.context_drivers||[];
  $('contextDriverCards').innerHTML=context.map(item=>item.status==='ok'?`<div class="kpi">${item.label}${item.is_stale?' <span class="scenario-stress">（过旧）</span>':''}<b>${fmt(item.latest_value,1)} ${item.unit||''}</b><small>最新 ${item.latest_period}${item.is_stale?` · 距房价期 ${item.staleness_years} 年`:''}${item.latest_growth==null?(item.latest_vs_recent_median_pct==null?'':` · 较近年中位 ${pct(item.latest_vs_recent_median_pct)}`):` · 年化变化 ${pct(item.latest_growth)}`}<br>${item.note}</small></div>`:`<div class="kpi">${item.label}<b>缺失</b><small>${item.note}</small></div>`).join('')||'<div class="muted">暂无观察项。</div>';
}
function formationAdjustments(){
  const value=id=>Number($(id)?.value);
  return {optimistic:value('formationOptimistic'),base:value('formationBase'),stress:value('formationStress')};
}
function validateFormationInputs(){
  const values=formationAdjustments();
  if(Object.values(values).some(value=>!Number.isFinite(value)||value < -50||value > 50)){
    showError('demographicError','家庭形成倾向请输入 -50% 到 +50% 之间的数字。');
    return false;
  }
  if(!(values.optimistic>=values.base&&values.base>=values.stress)){
    showError('demographicError','长期情景必须满足：乐观 ≥ 基准 ≥ 压力。');
    return false;
  }
  showError('demographicError','');
  return true;
}
function demographicScenario(container,key){return (container?.scenarios||[]).find(row=>row.key===key)}
function demographicPoint(container,key,year){return demographicScenario(container,key)?.points?.find(row=>Number(row.year)===Number(year))}
function renderDemographicCapacity(payload){
  demographicPayload=payload||null;
  if(!payload||payload.status!=='ok'){
    showError('demographicError','长期人口容量层暂无可用数据。');
    $('demographicKpis').innerHTML='';$('demographicTable').innerHTML='';$('demographicMethod').textContent='';
    destroy('demographicCapacity');destroy('cityCapacity');return;
  }
  showError('demographicError','');
  const national=payload.national||{},projections=national.projections||[],terminal=projections.find(row=>row.year===2050)||projections.at(-1)||{};
  const base2050=demographicPoint(national,'base',2050)||{},optimistic2050=demographicPoint(national,'optimistic',2050)||{},stress2050=demographicPoint(national,'stress',2050)||{};
  const actual=national.latest_actual||{};
  $('demographicKpis').innerHTML=`<div class="kpi">2025实际总人口<b>${fmt((actual.total_population_million||0)/100,2)} 亿人</b><small>国家统计局年末锚点 · ${actual.data_status||'—'}</small></div><div class="kpi">2050总人口中方案<b>${fmt((terminal.total_population_nbs_anchored_million||0)/100,2)} 亿人</b><small>按WPP相对路径缩放至2025实际锚点</small></div><div class="kpi">2050家庭形成容量<b>${fmt(base2050.demand_capacity_index,1)}</b><small>2025=100；乐观 ${fmt(optimistic2050.demand_capacity_index,1)} / 压力 ${fmt(stress2050.demand_capacity_index,1)}</small></div><div class="kpi">2050年60+占比<b>${pct(terminal.population_60_plus_share_pct,1)}</b><small>${fmt(terminal.population_60_plus_wpp_million,0)} 百万人 · WPP中方案</small></div><div class="kpi">固定存量负担<b>${fmt(base2050.fixed_stock_burden_index,1)}</b><small>2025=100；仅人口侧压力，不等于库存或房价</small></div>`;

  destroy('demographicCapacity');
  const labels=projections.map(row=>String(row.year));
  const demandDataset=key=>({label:`${{optimistic:'乐观',base:'基准',stress:'压力'}[key]}家庭形成容量`,data:demographicScenario(national,key)?.points?.map(row=>row.demand_capacity_index)||[],borderColor:COLORS[key],borderDash:[6,3],pointRadius:3,borderWidth:1.8});
  charts.demographicCapacity=new Chart($('demographicCapacityChart'),{type:'line',data:{labels,datasets:[
    {label:'总人口指数（WPP）',data:projections.map(row=>row.total_population_index),borderColor:'#5795ff',pointRadius:3,borderWidth:2},
    {label:'20—39岁人口指数（WPP）',data:projections.map(row=>row.population_20_39_index),borderColor:'#7890a8',borderDash:[2,4],pointRadius:3,borderWidth:1.5},
    demandDataset('optimistic'),demandDataset('base'),demandDataset('stress'),
  ]},options:{responsive:true,maintainAspectRatio:false,interaction:{mode:'index',intersect:false},scales:{x:{ticks:{color:'#8fa4bd'},grid:{color:'#14263a'}},y:{suggestedMin:45,suggestedMax:110,ticks:{color:'#8fa4bd'},grid:{color:'#14263a'},title:{display:true,text:'指数（2025=100）',color:'#8fa4bd'}}},plugins:{legend:{position:'bottom',labels:{color:'#cbd8e6',boxWidth:12}},tooltip:{callbacks:{label:c=>`${c.dataset.label}: ${fmt(c.parsed.y,1)}`}}}}});

  $('demographicTable').innerHTML=(payload.cities||[]).map(city=>{
    const b2030=demographicPoint(city,'base',2030)||{},b2040=demographicPoint(city,'base',2040)||{},b2050=demographicPoint(city,'base',2050)||{},o2050=demographicPoint(city,'optimistic',2050)||{},s2050=demographicPoint(city,'stress',2050)||{};
    const cityTrend=city.coverage_status==='city_trend';
    const scope=cityTrend?`<span class="scope-city">本市趋势</span><small>${city.sample_start}—${city.sample_end} · ${city.n_growth_obs}个增速</small>`:`<span class="scope-fallback">全国回退</span><small>${city.fallback_reason||'本市连续值不足'}</small>`;
    return `<tr><td>${city.city}</td><td>${scope}</td><td>${cityTrend?pct(city.recent_city_population_growth_pct,2):'—'}</td><td>${cityTrend?`${city.applied_relative_growth_pp>=0?'+':''}${fmt(city.applied_relative_growth_pp,2)}pp`:'0.00pp'}</td><td>${fmt(b2030.demand_capacity_index,1)}</td><td>${fmt(b2040.demand_capacity_index,1)}</td><td class="scenario-opt">${fmt(o2050.demand_capacity_index,1)}</td><td class="scenario-base">${fmt(b2050.demand_capacity_index,1)}</td><td class="scenario-stress">${fmt(s2050.demand_capacity_index,1)}</td><td>${fmt(b2050.fixed_stock_burden_index,1)}</td></tr>`;
  }).join('');
  const coverage=payload.coverage||{},sources=(payload.sources||[]).map(source=>`<a href="${source.url}" target="_blank" rel="noopener">${source.name}</a>（${source.data_status}）`).join('；');
  $('demographicMethod').innerHTML=`<p><b>覆盖：</b>${coverage.tracked_cities||0}城；本市趋势可算 ${coverage.city_trend_cities||0} 城（${(coverage.city_trend_names||[]).join('、')||'无'}），全国回退 ${coverage.national_fallback_cities||0} 城（${(coverage.national_fallback_names||[]).join('、')||'无'}）。</p><p><b>公式：</b>${payload.method}</p><p><b>来源：</b>${sources}</p>`+(payload.caveats||[]).map(note=>`<p>• ${note}</p>`).join('');
  renderCityCapacityChart();
}
function renderCityCapacityChart(){
  if(!demographicPayload)return;
  const mode=$('capacityCityMode')?.value||'all',year=Number($('capacityYear')?.value||2050),scenarioKey=$('capacityScenario')?.value||'base',scenarioLabel={optimistic:'乐观',base:'基准',stress:'压力'}[scenarioKey],axisMode=$('capacityAxisMode')?.value||'zoom';
  let cities=demographicPayload.cities||[];
  if(mode==='selected')cities=cities.filter(row=>selected.has(row.city));
  else if(mode==='city_trend')cities=cities.filter(row=>row.coverage_status==='city_trend');
  else if(mode==='fallback')cities=cities.filter(row=>row.coverage_status==='national_fallback');
  destroy('cityCapacity');
  $('cityCapacityTitle').textContent=`${year}年十五城${scenarioLabel}家庭形成容量`;
  if(!cities.length){$('cityCapacityTitle').textContent+=` · 当前筛选无城市`;return}
  const values=cities.map(row=>demographicPoint(row,scenarioKey,year)?.demand_capacity_index??null),finite=values.filter(Number.isFinite),zoomMin=Math.max(0,Math.floor((Math.min(...finite)-3)/5)*5),zoomMax=Math.ceil((Math.max(...finite)+3)/5)*5;
  charts.cityCapacity=new Chart($('cityCapacityChart'),{type:'bar',data:{labels:cities.map(row=>row.city),datasets:[{label:`${year}${scenarioLabel}容量（2025=100）`,data:values,backgroundColor:cities.map(row=>row.coverage_status==='city_trend'?'#27d3b2':'#f5a623')}]},options:{responsive:true,maintainAspectRatio:false,interaction:{mode:'index',intersect:false},scales:{x:{ticks:{color:'#8fa4bd',maxRotation:45,minRotation:0},grid:{display:false}},y:{beginAtZero:axisMode==='zero',min:axisMode==='zero'?0:zoomMin,max:zoomMax,ticks:{color:'#8fa4bd'},grid:{color:'#14263a'},title:{display:true,text:'潜在家庭形成容量指数',color:'#8fa4bd'}}},plugins:{legend:{display:false},tooltip:{callbacks:{afterLabel:context=>cities[context.dataIndex].coverage_status==='city_trend'?'使用本市常住人口趋势':'本市连续值不足，使用全国路径'}}}}});
}
function renderBacktest(backtest){
  if(!backtest||backtest.status!=='ok'){$('backtestKpis').innerHTML=`<div class="muted">${backtest?.status==='not_applicable'?'不适用':'历史不足'}</div>`;$('backtestNote').textContent=backtest?.reason||'';return}
  $('backtestKpis').innerHTML=`<div class="kpi">中位绝对误差<b>${pct(backtest.median_absolute_error_pp)}</b><small>百分点</small></div><div class="kpi">区间覆盖<b>${pct(backtest.envelope_coverage_pct,0)}</b><small>${backtest.n_obs}个历史起点</small></div><div class="kpi">方向命中<b>${pct(backtest.direction_hit_pct,0)}</b><small>${backtest.horizon_months}个月规则</small></div>`;
  const latest=backtest.latest;
  $('backtestNote').textContent=`最近一次可验证：${latest.as_of} 起，基准 ${pct(latest.base_change)}，实际至 ${latest.target_period} 为 ${pct(latest.actual_change)}。${backtest.method} 该回测只验证纯价格动能规则，未把后来发布的年度结构数据回填到历史时点。`;
}
function renderSimulation(sim){
  if(!sim||sim.status!=='ok'){$('simulationTitle').textContent='月度敏感性模拟';$('simulationSummary').innerHTML=`<div class="muted">${sim?.status==='not_applicable'?'不适用':'历史不足'}</div>`;$('simulationNote').textContent=sim?.reason||'';return}
  const listing=activeKind()==='listing',end=sim.points.at(-1)||{};
  $('simulationTitle').textContent=listing?'模拟区间期末挂牌价':'模拟区间期末变化';
  $('simulationSummary').innerHTML=['p10','p50','p90'].map(key=>`<div class="kpi">${key.toUpperCase()}<b>${listing?`${fmt(end[`${key}_price`],0)} 元/㎡`:pct(sim.end_vs_now[key])}</b><small>${listing?`较当前 ${pct(sim.end_vs_now[key])}`:'较当前'}</small></div>`).join('');
  $('simulationNote').textContent='P10/P50/P90 围绕纯价格动能基准重抽样；不含结构修正，也不是发生概率或置信区间。';
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
    $('anchorTitle').textContent='估值锚：房价指数 / 工资指数';
    $('anchorNote').textContent='该城市缺少至少3个可对齐的工资与房价年度点，保持缺失。';
    return;
  }
  $('anchorTitle').textContent='估值锚：房价指数 / 工资指数';
  $('anchorNote').textContent=`${anchor.note} 最新 ${anchor.latest.period}，较峰值 ${pct(anchor.latest_vs_peak)}。`;
  charts.anchor=new Chart($('anchorChart'),{type:'line',data:{labels:anchor.points.map(x=>x.period),datasets:[{label:'房价/工资指数',data:anchor.points.map(x=>x.ratio),borderColor:'#a78bfa',pointRadius:2}]},options:{responsive:true,maintainAspectRatio:false,scales:{x:{ticks:{color:'#8fa4bd'},grid:{color:'#14263a'}},y:{ticks:{color:'#8fa4bd'},grid:{color:'#14263a'}}},plugins:{legend:{display:false}}}});
}
function downloadCsv(){
  if(!comparePayload)return;
  const specs=momentumSpecs(),historyHeaders=specs.map(([,label])=>`${label}折算月速(%)`);
  const lines=[['城市','模型','结构修正强度(%)','本市结构驱动数','全国回退驱动数','最新期','当前挂牌价(元/㎡)','当前较峰值(%)',...historyHeaders,'乐观期末挂牌价(元/㎡)','乐观期末较当前(%)','基准期末挂牌价(元/㎡)','基准期末较当前(%)','压力期末挂牌价(元/㎡)','压力期末较当前(%)']];
  for(const row of comparePayload.rows){const by=Object.fromEntries(scenarioItems(row).map(x=>[x.key,x])),coverage=row.driver_coverage||{};lines.push([row.city,modelLabel(),useStructural()?structuralWeight()*100:0,coverage.city_specific_used??'',coverage.national_fallback_used??'',row.sample_end||'',row.current_price??'',row.current_vs_peak??'',...specs.map(([key])=>row.momentum?.[key]??''),scenarioEndPrice(by.optimistic,row.current_price)??'',by.optimistic?.end_vs_now??'',scenarioEndPrice(by.base,row.current_price)??'',by.base?.end_vs_now??'',scenarioEndPrice(by.stress,row.current_price)??'',by.stress?.end_vs_now??''])}
  const horizonFile=$('horizon').value==='2030'?'to-2030':`${$('horizon').value}m`;
  const csvCell=value=>{const text=String(value??'');return /[",\n]/.test(text)?`"${text.replaceAll('"','""')}"`:text};
  const blob=new Blob(['\ufeff'+lines.map(row=>row.map(csvCell).join(',')).join('\n')],{type:'text/csv;charset=utf-8'}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=`housing-scenario-${sourceMode()}-${activeKind()}-${horizonFile}.csv`;a.click();URL.revokeObjectURL(url);
}
function syncSourceUi(){
  const listing=isListingSource(),yearly=isYearlySource();
  document.querySelectorAll('[data-source-mode]').forEach(button=>
    button.classList.toggle('active',button.dataset.sourceMode===sourceMode()));
  ['rateOptimistic','rateBase','rateStress'].forEach(id=>$(id).value='');
  $('kind').disabled=listing;
  $('historyBadge').className=`badge ${listing?'listing':'official'}`;
  $('historyBadge').textContent=yearly?'历史 listing_annual_reference · 未来 scenario':listing?'历史 listing_reference · 未来 scenario':'历史 official · 未来 scenario';
  $('sourceNotice').innerHTML=yearly?'<b>年度挂牌层固定列出 15 个关注城市。</b> 历史仅画真实年度榜单/年末快照；缺失城市会明确显示，不拆成月度、不补造。':listing?'<b>月度挂牌层固定列出 15 个关注城市。</b> 只对孤立单月缺口采用前值法并标记；没有可信原始记录的城市保持 missing。':'<b>这里展示情景，不是价格预测。</b> 历史为统计局 70 城同质可比指数；常州、苏州不在官方 70 城名单中，请切换到安居客口径查看。模拟分位不代表真实概率。';
  $('compareValueMode').disabled=!listing;
  $('compareValueMode').value=listing?'price':'change';
  $('indexMode').querySelector('[value="raw"]').textContent=listing?'挂牌价（元/㎡）':'定基指数';
  $('indexMode').value=listing?'raw':'peak';
  $('historyWindow').value=listing?'0':'120';
  $('detailScopeNote').textContent=yearly?'真实年度回撤、结构驱动三档路径与首付杠杆；低频样本不运行月度模拟/回测':'历史回撤、结构驱动三档路径、5,000次纯动能敏感性模拟、首付杠杆与机械回测';
  momentumSpecs().forEach(([,label],index)=>$(`momentumHead${index+1}`).textContent=label);
  $('axisMode').value='auto';
  $('axisMin').disabled=true;$('axisMax').disabled=true;
}
async function loadCatalog(){
  try{
    syncSourceUi();showError('compareError','');setLoading(true);
    const response=await fetch('/api/housing-scenario/cities?'+new URLSearchParams({source:sourceMode()})),payload=await response.json();if(!response.ok)throw Error(payload.error||`HTTP ${response.status}`);
    catalog=payload.cities||[];selected=new Set(defaultCities().filter(city=>catalog.some(x=>x.city===city)).slice(0,12));renderCityChips();syncFocus(requestedFocus);requestedFocus=null;renderSelectionHint();updateUrlState();
    const coverage=payload.available_city_count==null?`${payload.city_count} 城`:`可用 ${payload.available_city_count}/${payload.tracked_city_count||payload.city_count} 城`;
    $('freshness').textContent=`${payload.source_label||sourceLabel()} · ${coverage} · 最新 ${payload.latest_period||'—'}`;
    if(isListingSource()){
      const missing=(payload.missing_cities||[]).join('、')||'无';
      const grain=isYearlySource()?'年度真实点不拆月，低频样本不做月度模拟/回测。':'仅孤立单月缺口可标记前值插补，连续缺失不补。';
      $('sourceNotice').innerHTML=`<b>15 城目录当前可用 ${payload.available_city_count||0} 城。</b> 缺失：${missing}。${grain}`;
    }
    await loadComparison();
  }catch(error){showError('compareError','来源目录加载失败：'+error.message)}finally{setLoading(false)}
}
async function init(){
  const source=INITIAL_PARAMS.get('source');
  if(['official','anjuke','anjuke_yearly'].includes(source)){
    $('dataSource').value=source;
    if(!INITIAL_PARAMS.get('city'))requestedFocus=source==='anjuke_yearly'?'上海':source==='official'?'北京':'常州';
  }
  const horizon=INITIAL_PARAMS.get('horizon');
  if([...$('horizon').options].some(option=>option.value===horizon))$('horizon').value=horizon;
  const kind=INITIAL_PARAMS.get('kind');
  if(kind==='new'||kind==='second')$('kind').value=kind;
  const model=INITIAL_PARAMS.get('model');
  if(model==='structural'||model==='momentum')$('forecastMode').value=model;
  const rawWeight=INITIAL_PARAMS.get('structural_weight'),weight=Number(rawWeight);
  if(rawWeight!==null&&rawWeight!==''&&Number.isFinite(weight)&&weight>=0&&weight<=100)$('structuralWeight').value=String(weight);
  for(const [param,id] of [['formation_optimistic','formationOptimistic'],['formation_base','formationBase'],['formation_stress','formationStress']]){
    const raw=INITIAL_PARAMS.get(param),value=Number(raw);
    if(raw!==null&&raw!==''&&Number.isFinite(value)&&value>=-50&&value<=50)$(id).value=String(value);
  }
  await loadCatalog();
}
document.querySelectorAll('[data-group]').forEach(button=>button.onclick=()=>applyGroup(button.dataset.group));
document.querySelectorAll('[data-source-mode]').forEach(button=>button.onclick=()=>selectSource(button.dataset.sourceMode));
$('citySearch').oninput=renderCityChips;$('compareRun').onclick=loadComparison;$('downloadCsv').onclick=downloadCsv;
$('focusCity').onchange=()=>{updateUrlState();loadDetail()};$('detailRun').onclick=loadDetail;$('kind').onchange=()=>{updateUrlState();loadComparison()};$('horizon').onchange=()=>{updateUrlState();loadComparison()};$('dataSource').onchange=()=>selectSource(sourceMode());
$('compareValueMode').onchange=()=>comparePayload&&renderComparison();
$('forecastMode').onchange=()=>{updateUrlState();if(comparePayload)renderComparison();if(detailPayload)renderDetail()};
$('structuralWeight').onchange=()=>{const value=Math.max(0,Math.min(100,Number($('structuralWeight').value)||0));$('structuralWeight').value=String(value);updateUrlState();loadComparison()};
$('demographicRun').onclick=()=>{if(validateFormationInputs()){updateUrlState();loadComparison()}};
['capacityYear','capacityScenario','capacityCityMode','capacityAxisMode'].forEach(id=>$(id).onchange=renderCityCapacityChart);
$('historyWindow').onchange=()=>detailPayload&&renderDetail();$('indexMode').onchange=()=>detailPayload&&renderDetail();
$('axisMode').onchange=()=>{const enabled=$('axisMode').value==='custom';if($('axisMode').value==='70110')$('indexMode').value='peak';$('axisMin').disabled=!enabled;$('axisMax').disabled=!enabled;if(detailPayload)renderDetail()};
['axisMin','axisMax'].forEach(id=>$(id).onchange=()=>detailPayload&&renderDetail());$('downPayment').onchange=loadDetail;
$('resetRates').onclick=()=>{['rateOptimistic','rateBase','rateStress'].forEach(id=>$(id).value='');loadDetail()};
init();
