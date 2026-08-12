'use strict';

const CITY_COLORS={
  北京:'#5795ff',上海:'#ff6680',广州:'#f5a623',深圳:'#19d3ae',厦门:'#a77bfa',
  南京:'#27c3d9',合肥:'#ff884d',常州:'#ef70bb',苏州:'#9acb58',无锡:'#92a9ff',
  武汉:'#00b8d9',长沙:'#ffd166',成都:'#ef476f',杭州:'#06d6a0',福州:'#c77dff'
};
const GROUPS={
  全部:[],一线:['北京','上海','广州','深圳'],
  长三角:['上海','南京','常州','苏州','无锡','杭州'],
  珠三角:['广州','深圳'],中部:['武汉','长沙','合肥'],
  海西:['厦门','福州'],西南:['成都']
};
let payload=null,METRICS=[],BOARDS=[],currentBoard='growth',selectedCities=new Set(),
  selectedMetrics=new Set(),selectedMetricsByBoard={},charts={},axisState={};
const $=id=>document.getElementById(id),fmt=(v,d=2)=>v==null?'—':Number(v).toLocaleString(undefined,{maximumFractionDigits:d});
const esc=v=>String(v??'').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));

function destroy(name){if(charts[name]){charts[name].destroy();delete charts[name]}}
function periodKey(period,end=false){if(!period)return '';return period.length===4?`${period}-${end?'12':'01'}`:period}
function inRange(row){const a=periodKey($('start').value),b=periodKey($('end').value,true),p=periodKey(row?.period,true);return row&&(!a||p>=a)&&(!b||p<=b)}
function metricByKey(key){return METRICS.find(x=>x.key===key)}
function cityMeta(name){return payload.cities.find(x=>x.city===name)}
function substituteArea(meta,includeCities=false){
  if(meta?.municipality)return '其他地区';
  return `${meta?.province||''}省${includeCities?'或其他城市':''}`;
}
function rawRows(metric,applyRange=true){
  let rows=[];
  if(metric.source==='official')rows=payload.official_housing.filter(r=>r.indicator_code===metric.code);
  if(metric.source==='listing')rows=payload.listing_housing;
  if(metric.source==='gdp')rows=payload.gdp_rows.filter(r=>r.indicator_code===metric.code);
  if(metric.source==='fiscal')rows=payload.fiscal_rows.filter(r=>r.indicator_code===metric.code);
  if(metric.source==='indicator')rows=(payload.indicator_rows||[]).filter(r=>r.indicator_code===metric.code);
  if(metric.source==='derived')rows=(payload.derived_rows||[]).filter(r=>r.indicator_code===metric.code);
  return rows.filter(r=>selectedCities.has(r.city)&&typeof r[metric.field]==='number'&&(!applyRange||inRange(r)));
}
function metricSeries(metric,applyRange=true){
  // 一城一条线:省级数据已不进入本模块,不存在跨城合并的背景线
  const rows=rawRows(metric,applyRange),groups=new Map();
  for(const row of rows){
    if(!groups.has(row.city))groups.set(row.city,[]);
    groups.get(row.city).push(row);
  }
  return [...groups.entries()].map(([city,cityRows])=>{
    const byPeriod=new Map();
    for(const row of cityRows)if(!byPeriod.has(row.period))byPeriod.set(row.period,row[metric.field]);
    return {key:`city:${city}`,label:city,color:CITY_COLORS[city],byPeriod};
  });
}
function allPeriods(series){return [...new Set(series.flatMap(s=>[...s.byPeriod.keys()]))].sort()}
function axisConfig(metric,series,visiblePeriods){
  const state=axisState[metric.key]||(axisState[metric.key]={mode:'visible',min:'',max:''});
  let min,max;
  if(state.mode==='custom'){min=Number(state.min);max=Number(state.max);if(!Number.isFinite(min))min=undefined;if(!Number.isFinite(max))max=undefined}
  if(state.mode==='global'){
    const global=metricSeries(metric,false),vals=global.flatMap(s=>[...s.byPeriod.values()]).filter(Number.isFinite);
    if(vals.length){min=Math.min(...vals);max=Math.max(...vals)}
  }
  return {min,max,state,indexed:state.mode==='indexed'&&!metric.rate};
}
function chartDataset(metric,series,periods,indexed){
  return series.map((s,i)=>{
    let data=periods.map(p=>s.byPeriod.get(p)??null);
    if(indexed){const base=data.find(v=>typeof v==='number'&&v!==0);data=data.map(v=>v==null||!base?null:Number((v/base*100).toFixed(2)))}
    const palette=Object.keys(CITY_COLORS);
    return {label:s.label,data,borderColor:s.color||CITY_COLORS[palette[i%palette.length]],backgroundColor:'transparent',borderWidth:2,pointRadius:periods.length>40?0:2,spanGaps:false,tension:.08};
  });
}
function makeChart(name,canvas,metric,series,periods,axis){
  destroy(name);const unit=axis.indexed?'指数':metric.unit;
  charts[name]=new Chart(canvas,{type:'line',data:{labels:periods,datasets:chartDataset(metric,series,periods,axis.indexed)},options:{responsive:true,maintainAspectRatio:false,interaction:{mode:'index',intersect:false},scales:{x:{ticks:{color:'#8fa4bd',maxTicksLimit:10},grid:{color:'#14263a'}},y:{min:axis.min,max:axis.max,ticks:{color:'#8fa4bd',callback:v=>fmt(v,axis.indexed?1:(metric.rate?1:0))+(metric.rate?'%':'')},grid:{color:'#14263a'}}},plugins:{legend:{position:'bottom',labels:{color:'#cbd8e6',boxWidth:18,usePointStyle:true}},tooltip:{callbacks:{label:c=>`${c.dataset.label}: ${fmt(c.parsed.y,2)} ${unit}`}}}}});
}
function axisControls(metric,state){
  const indexed=metric.rate?'':`<option value="indexed" ${state.mode==='indexed'?'selected':''}>首期=100</option>`;
  const custom=state.mode==='custom'?`<label>下限<input data-axis-min="${metric.key}" type="number" step="any" value="${state.min}"></label><label>上限<input data-axis-max="${metric.key}" type="number" step="any" value="${state.max}"></label>`:'';
  return `<div class="axis"><label>Y轴<select data-axis-mode="${metric.key}"><option value="visible" ${state.mode==='visible'?'selected':''}>可见区间自动</option><option value="global" ${state.mode==='global'?'selected':''}>全历史固定</option>${indexed}<option value="custom" ${state.mode==='custom'?'selected':''}>自定义</option></select></label>${custom}</div>`;
}
function renderComparisonCharts(){
  Object.keys(charts).filter(k=>k.startsWith('compare:')).forEach(destroy);
  const host=$('comparisonCharts'),metrics=METRICS.filter(m=>selectedMetrics.has(m.key));host.innerHTML='';
  for(const metric of metrics){
    const series=metricSeries(metric,true),periods=allPeriods(series),axis=axisConfig(metric,series,periods);
    const card=document.createElement('div');card.className='card chart-card';
    const missing=[...selectedCities].filter(c=>!series.some(s=>s.label===c));
    const scope=metric.key.startsWith('development_zone_')?' · 开发区口径':'';
    card.innerHTML=`<div class="chart-head"><div><div class="chart-title">${metric.label}</div><div class="chart-sub">${periods[0]||'—'} 至 ${periods.at(-1)||'—'} · ${series.length} 城${missing.length?` · ${missing.join('、')}暂无该口径数据`:''}${axis.indexed?' · 可见首期=100':''}${scope}</div></div>${axisControls(metric,axis.state)}</div>${periods.length?`<div class="chart"><canvas id="chart-${metric.key}"></canvas></div>`:`<div class="empty">所选城市在该期间暂无该口径数据（不以省级数据代替）</div>`}`;
    host.appendChild(card);if(periods.length)makeChart(`compare:${metric.key}`,$(`chart-${metric.key}`),metric,series,periods,axis);
  }
  if(!metrics.length)host.innerHTML='<div class="card wide empty">请至少选择一个指标</div>';
  host.querySelectorAll('[data-axis-mode]').forEach(el=>el.onchange=()=>{axisState[el.dataset.axisMode].mode=el.value;renderComparisonCharts()});
  host.querySelectorAll('[data-axis-min]').forEach(el=>el.onchange=()=>{axisState[el.dataset.axisMin].min=el.value;renderComparisonCharts()});
  host.querySelectorAll('[data-axis-max]').forEach(el=>el.onchange=()=>{axisState[el.dataset.axisMax].max=el.value;renderComparisonCharts()});
}
function latestForCity(metric,city){
  let rows=[];
  if(metric.source==='official')rows=payload.official_housing.filter(r=>r.city===city&&r.indicator_code===metric.code);
  if(metric.source==='listing')rows=payload.listing_housing.filter(r=>r.city===city);
  if(metric.source==='gdp')rows=payload.gdp_rows.filter(r=>r.city===city&&r.indicator_code===metric.code);
  if(metric.source==='fiscal')rows=payload.fiscal_rows.filter(r=>r.city===city&&r.indicator_code===metric.code);
  if(metric.source==='indicator')rows=(payload.indicator_rows||[]).filter(r=>r.city===city&&r.indicator_code===metric.code);
  if(metric.source==='derived')rows=(payload.derived_rows||[]).filter(r=>r.city===city&&r.indicator_code===metric.code);
  rows=rows.filter(r=>inRange(r)&&typeof r[metric.field]==='number');return rows.sort((a,b)=>a.period.localeCompare(b.period)).at(-1)||null;
}
// 每格单独判定口径:全市 / 市本级 都是这座城市的数,但口径大小不同,不可混比
function cellScope(metric,row,city){
  if(metric.source==='listing')
    return{cls:'ref',tag:'挂牌参考',note:'非官方',title:'安居客商业二手挂牌价参考；数据仅保存在本机独立库'};
  if(!['gdp','fiscal','indicator','derived'].includes(metric.source))return{cls:'',tag:'',note:'',title:''};
  if(metric.source==='derived')
    return{cls:'drv',tag:'派生',note:'公式可审计',title:row.formula||'由同城同年官方值计算'};
  if(row.geographic_scope==='city_development_zones')
    return{cls:'lvl',tag:'开发区',note:'开发区口径',title:`${city}开发区口径，不代表全市全部企业`};
  if(row.data_status==='official_mirror')
    return{cls:'mir',tag:'镜像',note:'镜像',
           title:`${city}官方原站在本机网络不可达，此值取自第三方镜像转存的该市统计局公报原件；已与可直连城市逐条对照验证`};
  if(row.data_status==='official_revised')
    return{cls:'rev',tag:'统计局修订',note:'在线修订序列',
           title:`${city}国家统计局主要城市年度数据；在线序列可能包含历史修订`};
  if(row.scope_label==='市本级补充'||row.scope_label==='市本级')
    return{cls:'lvl',tag:'市本级',note:'市本级',title:`${city}市本级口径，小于全市口径，与其他城市的全市值不可直接比较`};
  return{cls:'',tag:'',note:'',title:`${city}${row.scope_label||'城市口径'}`};
}
function renderMatrix(){
  const metrics=METRICS.filter(m=>selectedMetrics.has(m.key));
  $('matrixHead').innerHTML=`<tr><th>城市</th>${metrics.map(m=>`<th>${m.label}</th>`).join('')}<th>覆盖概况</th></tr>`;
  $('matrixBody').innerHTML=[...selectedCities].map(city=>{const meta=cityMeta(city);
    const cells=metrics.map(m=>{const r=latestForCity(m,city);
      if(!r)return `<td class="gap" title="${city}该指标的对应口径数据未入库；不以${substituteArea(cityMeta(city))}值代替">待入库</td>`;
      const s=cellScope(m,r,city);
      return `<td class="${s.cls}" title="${s.title}">${s.tag?`<i class="ctag">${s.tag}</i>`:''}${fmt(r[m.field],m.rate?2:0)} ${m.unit}<small>${r.period}${s.note?` · ${s.note}`:''}</small></td>`}).join('');
    return `<tr><td>${city}</td>${cells}<td><small>GDP ${meta.coverage.gdp_records} · 财政 ${meta.coverage.fiscal_records} · 一般指标 ${meta.coverage.indicator_records||0}</small></td></tr>`}).join('')
    ||`<tr><td colspan="${metrics.length+2}">请至少选择一个城市</td></tr>`;
}
function availableCityCount(metric){
  let rows=[];
  if(metric.source==='official')rows=payload.official_housing.filter(r=>r.indicator_code===metric.code);
  if(metric.source==='listing')rows=payload.listing_housing;
  if(metric.source==='gdp')rows=payload.gdp_rows.filter(r=>r.indicator_code===metric.code);
  if(metric.source==='fiscal')rows=payload.fiscal_rows.filter(r=>r.indicator_code===metric.code);
  if(metric.source==='indicator')rows=(payload.indicator_rows||[]).filter(r=>r.indicator_code===metric.code);
  if(metric.source==='derived')rows=(payload.derived_rows||[]).filter(r=>r.indicator_code===metric.code);
  return new Set(rows.filter(r=>typeof r[metric.field]==='number').map(r=>r.city)).size;
}
function boardByKey(key=currentBoard){return BOARDS.find(board=>board.key===key)||BOARDS[0]}
function boardMetrics(){const board=boardByKey();return METRICS.filter(metric=>board.metrics.includes(metric.key))}
function renderBoardTabs(){
  $('boardTabs').innerHTML=BOARDS.map(board=>`<button data-board="${board.key}" class="${board.key===currentBoard?'active':''}">${board.label}</button>`).join('');
  document.querySelectorAll('[data-board]').forEach(el=>el.onclick=()=>{
    selectedMetricsByBoard[currentBoard]=new Set(selectedMetrics);
    currentBoard=el.dataset.board;
    const board=boardByKey();
    selectedMetrics=new Set(selectedMetricsByBoard[currentBoard]||board.defaults);
    switchTab('compare');renderBoardTabs();renderCompare();
  });
}
function renderPickers(){
  $('cityQuick').innerHTML=Object.entries(GROUPS).map(([name,cities])=>`<button data-city-group="${name}">${name}</button>`).join('')+'<button data-city-group="清空">清空</button>';
  const bMetrics=boardMetrics(),board=boardByKey();
  const coveredCities=city=>bMetrics.some(metric=>(payload.metric_coverage[metric.key]?.city_names||[]).includes(city));
  $('cityChips').innerHTML=payload.cities.map(c=>{const active=selectedCities.has(c.city),has=coveredCities(c.city);return `<button class="chip ${active?'active':''} ${has?'':'missing'}" style="--chip-color:${CITY_COLORS[c.city]}" data-city="${c.city}">${c.city}</button>`}).join('');
  $('metricQuick').innerHTML='<button data-metric-group="推荐">本板块推荐</button><button data-metric-group="全选">本板块全选</button><button data-metric-group="清空">清空</button>';
  $('metricChips').innerHTML=bMetrics.map(m=>{const coverage=payload.metric_coverage[m.key]||{};return `<button class="chip ${selectedMetrics.has(m.key)?'active':''} ${(coverage.cities||0)?'':'missing'}" data-metric="${m.key}">${m.label} <small>${coverage.cities||0}/${payload.cities.length} 城 · ${coverage.start||'—'}–${coverage.end||'—'}</small></button>`}).join('');
  document.querySelectorAll('[data-city]').forEach(el=>el.onclick=()=>{selectedCities.has(el.dataset.city)?selectedCities.delete(el.dataset.city):selectedCities.add(el.dataset.city);renderCompare()});
  document.querySelectorAll('[data-city-group]').forEach(el=>el.onclick=()=>{const key=el.dataset.cityGroup;if(key==='清空')selectedCities.clear();else selectedCities=new Set(key==='全部'?payload.cities.map(c=>c.city):GROUPS[key]);renderCompare()});
  document.querySelectorAll('[data-metric]').forEach(el=>el.onclick=()=>{selectedMetrics.has(el.dataset.metric)?selectedMetrics.delete(el.dataset.metric):selectedMetrics.add(el.dataset.metric);selectedMetricsByBoard[currentBoard]=new Set(selectedMetrics);renderCompare()});
  document.querySelectorAll('[data-metric-group]').forEach(el=>el.onclick=()=>{const key=el.dataset.metricGroup;if(key==='清空')selectedMetrics.clear();else if(key==='全选')selectedMetrics=new Set(board.metrics);else selectedMetrics=new Set(board.defaults);selectedMetricsByBoard[currentBoard]=new Set(selectedMetrics);renderCompare()});
}
function renderCompare(){
  const board=boardByKey();$('boardTitle').textContent=board.label;$('boardDescription').textContent=board.description;$('matrixTitle').textContent=`${board.label}：所选城市最新值矩阵`;
  renderPickers();
  const metrics=METRICS.filter(metric=>selectedMetrics.has(metric.key));
  const missingPairs=[...selectedCities].reduce((sum,city)=>sum+metrics.filter(metric=>!(payload.metric_coverage[metric.key]?.city_names||[]).includes(city)).length,0);
  const citiesWithData=[...selectedCities].filter(city=>metrics.some(metric=>(payload.metric_coverage[metric.key]?.city_names||[]).includes(city)));
  const devScope=metrics.some(metric=>metric.key.startsWith('development_zone_'));
  $('compareNotice').textContent=`只使用城市自身口径，缺失不以省级数据代替、不补零、不插值。${devScope?' 当前选择含开发区高新技术指标，不能解释为全市总量。':''}`;
  $('compareCounts').innerHTML=`<div>已选城市<b>${selectedCities.size}</b></div><div>已选指标<b>${selectedMetrics.size}</b></div><div>至少一项有值<b>${citiesWithData.length}</b></div><div>城市×指标缺口<b>${missingPairs}</b></div>`;
  const v=payload.vintage_note;
  $('vintageNotice').classList.toggle('hidden',!v);
  if(v)$('vintageNotice').innerHTML=`<b>口径版本提示：</b>${v.text}`;
  renderComparisonCharts();renderMatrix();
}
function line(name,canvas,labels,datasets,unit=''){destroy(name);charts[name]=new Chart(canvas,{type:'line',data:{labels,datasets},options:{responsive:true,maintainAspectRatio:false,interaction:{mode:'index',intersect:false},scales:{x:{ticks:{color:'#8fa4bd',maxTicksLimit:10},grid:{color:'#14263a'}},y:{ticks:{color:'#8fa4bd',callback:v=>fmt(v,unit==='%'?1:0)+(unit==='%'?'%':'')},grid:{color:'#14263a'}}},plugins:{legend:{position:'bottom',labels:{color:'#cbd8e6'}}}}})}
function detailCity(){return cityMeta($('city').value)||payload.cities[0]}
function detailRows(source,code){let rows=source.filter(r=>r.city===detailCity().city&&(!code||r.indicator_code===code));return rows.filter(inRange)}
function kpi(label,metric){const row=latestForCity(metric,detailCity().city);return `<div class="kpi">${label}<b>${row?`${fmt(row[metric.field],metric.rate?2:0)} ${metric.unit}`:'—'}</b><small>${row?.period||'暂无直接数据'} · ${row?.scope_label||''}</small></div>`}
function renderDetail(){
  const c=detailCity();$('detailCityTitle').textContent=`${c.city} · 单城详情`;$('detailCityDescription').textContent=`当前城市：${c.city}；下方数据只取该城市自身记录，缺失年份保持空档，不以${substituteArea(c,true)}代替。`;$('scopeBadge').className='badge '+(c.fiscal_scope==='missing'?'gap':'city');$('scopeBadge').textContent=c.fiscal_scope_label;$('scopeNotice').textContent=c.fiscal_scope==='missing'?`${c.city}房价为城市口径；${c.city}市级财政与 GDP 官方值尚未入库，此处保持空缺，不用${substituteArea(c)}数据代替。`:`${c.city}的财政与 GDP 为该市自身口径${c.municipality?'（直辖市，省级行政区即本市）':''}。`;
  const keys=['official_second_yoy','listing_price','listing_yoy','nominal_gdp','general_budget_revenue','general_budget_expenditure','gov_fund_revenue','land_transfer_revenue','debt_outstanding'];$('kpis').innerHTML=keys.map(k=>kpi(metricByKey(k).label,metricByKey(k))).join('');
  const o=detailRows(payload.official_housing),l=detailRows(payload.listing_housing),periods=[...new Set(o.map(r=>r.period).concat(l.map(r=>r.period)))].sort(),map=(rows,code,field='value')=>new Map(rows.filter(r=>!code||r.indicator_code===code).map(r=>[r.period,r[field]]));const n=map(o,'new_home_yoy_pct'),s=map(o,'second_home_yoy_pct'),ly=map(l,null,'yoy_pct');line('detail:housing',$('detailHousing'),periods,[{label:'新房同比',data:periods.map(p=>n.get(p)??null),borderColor:'#f5a623',pointRadius:0},{label:'二手同比',data:periods.map(p=>s.get(p)??null),borderColor:'#5795ff',pointRadius:0},{label:'挂牌同比',data:periods.map(p=>ly.get(p)??null),borderColor:'#27d3b2',pointRadius:0}],'%');
  const lp=l.map(r=>r.period),lm=map(l,null,'avg_price');line('detail:listing',$('detailListing'),lp,[{label:'挂牌均价',data:lp.map(p=>lm.get(p)??null),borderColor:'#27d3b2',pointRadius:0}],'元/㎡');
  const f=detailRows(payload.fiscal_rows),fy=[...new Set(f.map(r=>r.period))].sort(),rev=map(f,'general_budget_revenue'),exp=map(f,'general_budget_expenditure');$('detailFiscalTitle').textContent=`${c.fiscal_scope_label}：一般预算收支`;line('detail:fiscal',$('detailFiscal'),fy,[{label:'收入',data:fy.map(p=>rev.get(p)??null),borderColor:'#27d3b2',pointRadius:2},{label:'支出',data:fy.map(p=>exp.get(p)??null),borderColor:'#f5a623',pointRadius:2}],'亿元');
  const g=detailRows(payload.gdp_rows,'nominal_gdp'),gp=g.map(r=>r.period),gm=map(g,'nominal_gdp');$('detailGdpTitle').textContent=c.gdp_scope_label;line('detail:gdp',$('detailGdp'),gp,[{label:'名义 GDP',data:gp.map(p=>gm.get(p)??null),borderColor:'#5795ff',pointRadius:2}],'亿元');renderFiscalTable();renderFiscalMetricChart();
}
function fiscalTableCityMeta(){return cityMeta($('fiscalTableCity')?.value)||detailCity()}
function fiscalTableYears(){
  const start=Number($('fiscalTableStart')?.value),end=Number($('fiscalTableEnd')?.value);
  if(!Number.isInteger(start)||!Number.isInteger(end)||start>end)return [];
  return Array.from({length:end-start+1},(_,i)=>String(start+i));
}
function fiscalTableRows(){
  const city=fiscalTableCityMeta().city,code=$('fiscalMetric')?.value,years=new Set(fiscalTableYears());
  return payload.fiscal_rows.filter(r=>r.city===city&&r.indicator_code===code&&years.has(r.period));
}
function normalizeFiscalTableRange(changed){
  const start=$('fiscalTableStart'),end=$('fiscalTableEnd');
  if(start.value>end.value){if(changed==='start')end.value=start.value;else start.value=end.value}
  renderFiscalTable();renderFiscalMetricChart();
}
function renderFiscalMetricChart(){
  const c=fiscalTableCityMeta(),code=$('fiscalMetric').value,metric=metricByKey(code),rows=fiscalTableRows().sort((a,b)=>a.period.localeCompare(b.period));
  const title=metric?.label||payload.indicator_labels[code]||code||'财政指标',periods=fiscalTableYears(),values=new Map(rows.map(r=>[r.period,r.value]));
  $('detailFiscalMetricTitle').textContent=`${c.city} · ${title}动态表`;
  $('detailFiscalMetricSub').textContent=`${periods[0]||'—'} 至 ${periods.at(-1)||'—'}；只显示${c.city}自身口径，缺年断线。`;
  if(!periods.length){destroy('detail:fiscalMetric');$('detailFiscalMetricNote').textContent='请选择有效的开始和结束年份。';return}
  const unit=rows[0]?.unit||metric?.unit||'亿元';
  line('detail:fiscalMetric',$('detailFiscalMetricChart'),periods,[{label:title,data:periods.map(p=>values.get(p)??null),borderColor:'#5795ff',backgroundColor:'transparent',borderWidth:2,pointRadius:periods.length>20?1.5:3,spanGaps:false}],unit);
  const missing=periods.filter(p=>!values.has(p)),latest=rows.at(-1),source=latest?.source_url?` 最新可用点来源：<a href="${esc(latest.source_url)}" target="_blank" rel="noopener">${esc(latest.source_name||'官方原文')}</a>。`:'';
  $('detailFiscalMetricNote').innerHTML=`单位：${esc(unit)}；所选期间实际入库 ${rows.length}/${periods.length} 个年度点。${missing.length?`缺失年份：${missing.join('、')}，图中为空，不代表零值。`:'所选期间逐年有值。'}${source}`;
}
function renderFiscalTable(){
  const c=fiscalTableCityMeta(),code=$('fiscalMetric').value,title=metricByKey(code)?.label||payload.indicator_labels[code]||code,rows=fiscalTableRows(),byYear=new Map(rows.map(r=>[r.period,r]));
  $('fiscalTable').innerHTML=fiscalTableYears().slice().reverse().map(year=>{const r=byYear.get(year);if(!r)return `<tr class="gap"><td>${esc(c.city)}</td><td>${year}</td><td>${esc(title)}</td><td>—</td><td>—</td><td>missing</td><td>未找到可核验官方原文</td><td>保持缺失，不以省级、市本级或估算值替代</td></tr>`;return `<tr><td>${esc(c.city)}</td><td>${esc(r.period)}</td><td>${esc(title)}</td><td>${fmt(r.value,4)} ${esc(r.unit)}</td><td>${esc(r.scope_label)}</td><td>${esc(r.data_status)}</td><td>${r.source_url?`<a href="${esc(r.source_url)}" target="_blank" rel="noopener">${esc(r.source_name||'官方原文')}</a>`:'—'}</td><td title="${esc(r.parser_notes||r.source_title||'')}">${esc(r.parser_notes||r.source_title||'—')}</td></tr>`}).join('')||'<tr><td colspan="8">请选择有效期间</td></tr>';
}
function csvValue(value){return `"${String(value??'').replace(/"/g,'""')}"`}
function downloadFiscalTableCsv(){
  const c=fiscalTableCityMeta(),code=$('fiscalMetric').value,title=metricByKey(code)?.label||payload.indicator_labels[code]||code,rows=fiscalTableRows(),byYear=new Map(rows.map(r=>[r.period,r]));
  const header=['城市','年份','指标代码','指标','数值','单位','地区口径','状态','来源','来源URL','说明'];
  const body=fiscalTableYears().map(year=>{const r=byYear.get(year);return [c.city,year,code,title,r?.value??'',r?.unit??'',r?.scope_label??'',r?.data_status??'missing',r?.source_name??'',r?.source_url??'',r?.parser_notes||r?.source_title||'保持缺失，不以省级、市本级或估算值替代']});
  const csv='\ufeff'+[header,...body].map(row=>row.map(csvValue).join(',')).join('\r\n'),blob=new Blob([csv],{type:'text/csv;charset=utf-8'}),url=URL.createObjectURL(blob),a=document.createElement('a');
  a.href=url;a.download=`city_fiscal_${c.city}_${code}_${$('fiscalTableStart').value}_${$('fiscalTableEnd').value}.csv`;document.body.appendChild(a);a.click();a.remove();URL.revokeObjectURL(url);
}
function renderCoverage(){
  const c=payload.coverage;
  $('coverageCards').innerHTML=`<div>目标城市<b>${c.cities}</b></div><div>官方房价城市<b>${c.official_housing_cities}</b></div><div>挂牌历史城市<b>${c.listing_cities}</b></div><div>有一般指标<b>${c.city_indicator_cities}</b></div><div>有市级财政<b>${c.direct_city_fiscal_cities}</b></div><div>有城市 GDP<b>${c.city_gdp_cities}</b></div>`;
  $('coverageTable').innerHTML=payload.cities.map(x=>`<tr><td>${x.city}</td><td>${x.coverage.official_housing_records}</td><td>${x.coverage.listing_records}</td><td>${x.coverage.indicator_records||0}</td><td><span class="badge ${x.fiscal_scope==='missing'?'gap':'city'}">${x.fiscal_scope_label}</span></td><td>${x.coverage.fiscal_records}</td><td>${x.coverage.gdp_records}</td></tr>`).join('');
  const rows=[];
  for(const board of BOARDS)for(const key of board.metrics){const metric=metricByKey(key),cov=payload.metric_coverage[key]||{};if(!metric)continue;rows.push(`<tr><td>${board.label}</td><td>${metric.label}</td><td>${cov.cities||0}/${payload.cities.length}</td><td>${cov.start||'—'}–${cov.end||'—'}</td><td>${cov.records||0}</td></tr>`)}
  $('metricCoverageTable').innerHTML=rows.join('');
  $('caveats').innerHTML=payload.caveats.map(x=>`<p>• ${x}</p>`).join('');renderConflicts();
}
function renderConflicts(){
  const rows=payload.source_conflicts||[],labels=payload.indicator_labels||{};
  $('conflictNote').textContent=rows.length
    ?`${rows.length} 条：城市已发布值与国家统计局在线序列不一致（相对差异 >0.5%）。此处仅记录，不改变上方取值。`
    :'当前没有超过 0.5% 的跨来源分歧。';
  $('conflictTable').innerHTML=rows.map(r=>{
    const pct=(r.relative_diff*100).toFixed(2);
    return `<tr><td>${r.region_name}</td><td>${labels[r.indicator_code]||r.indicator_code}</td><td>${r.period}</td>`+
      `<td>${fmt(r.kept_value,2)}</td><td><small>${r.kept_source_name||'—'}</small></td>`+
      `<td>${fmt(r.candidate_value,2)}</td><td>${r.relative_diff>0?'+':''}${pct}%</td>`+
      `<td>${r.candidate_source_url?`<a href="${r.candidate_source_url}" target="_blank" rel="noopener">统计局</a>`:'—'}</td></tr>`;
  }).join('')||'<tr><td colspan="8">无</td></tr>';
}
function switchTab(tab){document.querySelectorAll('[data-tab]').forEach(x=>x.classList.toggle('active',x.dataset.tab===tab));['compare','detail','scenario','listed','coverage'].forEach(x=>$(x).classList.toggle('hidden',x!==tab));if(tab==='detail')renderDetail();if(tab==='coverage')renderCoverage();if(tab==='scenario'&&!scPayload)initScenario();if(tab==='listed'&&!lcPayload)initListed()}
function init(){
  METRICS=payload.metric_catalog||[];BOARDS=payload.boards||[];currentBoard=BOARDS[0]?.key||'growth';
  selectedMetricsByBoard=Object.fromEntries(BOARDS.map(board=>[board.key,new Set(board.defaults)]));
  selectedMetrics=new Set(boardByKey()?.defaults||[]);selectedCities=new Set(payload.cities.map(c=>c.city));
  $('city').innerHTML=payload.cities.map(c=>`<option>${c.city}</option>`).join('');
  $('fiscalTableCity').innerHTML=payload.cities.map(c=>`<option>${c.city}</option>`).join('');$('fiscalTableCity').value=$('city').value;
  const allRows=[payload.official_housing,payload.listing_housing,payload.fiscal_rows,payload.gdp_rows,payload.indicator_rows||[],payload.derived_rows||[]].flat();
  const periods=[...new Set(allRows.map(r=>r.period).filter(Boolean))].sort();
  $('start').innerHTML=periods.map(p=>`<option>${p}</option>`).join('');$('end').innerHTML=periods.map(p=>`<option>${p}</option>`).join('');$('start').value=periods.includes('2010')?'2010':(periods[0]||'');$('end').value=periods.at(-1)||'';
  const fiscalCodes=[...new Set(payload.fiscal_rows.map(r=>r.indicator_code))].sort((a,b)=>(payload.indicator_labels[a]||a).localeCompare(payload.indicator_labels[b]||b,'zh-CN'));$('fiscalMetric').innerHTML=fiscalCodes.map(code=>`<option value="${code}">${payload.indicator_labels[code]||code}</option>`).join('');if(fiscalCodes.includes('gov_fund_revenue'))$('fiscalMetric').value='gov_fund_revenue';
  const observedFiscalYears=payload.fiscal_rows.map(r=>r.period).filter(p=>/^\d{4}$/.test(p)).map(Number),fiscalYears=observedFiscalYears.length?Array.from({length:Math.max(...observedFiscalYears)-Math.min(...observedFiscalYears)+1},(_,i)=>String(Math.min(...observedFiscalYears)+i)):[];
  $('fiscalTableStart').innerHTML=fiscalYears.map(y=>`<option>${y}</option>`).join('');$('fiscalTableEnd').innerHTML=fiscalYears.map(y=>`<option>${y}</option>`).join('');$('fiscalTableStart').value=fiscalYears.includes('2017')?'2017':(fiscalYears[0]||'');$('fiscalTableEnd').value=fiscalYears.at(-1)||'';
  const rerenderRange=()=>{renderCompare();if(!$('detail').classList.contains('hidden'))renderDetail()};
  renderBoardTabs();renderCompare();renderCoverage();$('start').onchange=rerenderRange;$('end').onchange=rerenderRange;$('city').onchange=()=>{$('fiscalTableCity').value=$('city').value;renderDetail()};$('fiscalTableCity').onchange=()=>{renderFiscalTable();renderFiscalMetricChart()};$('fiscalMetric').onchange=()=>{renderFiscalTable();renderFiscalMetricChart()};$('fiscalTableStart').onchange=()=>normalizeFiscalTableRange('start');$('fiscalTableEnd').onchange=()=>normalizeFiscalTableRange('end');$('fiscalTableCsv').onclick=downloadFiscalTableCsv;document.querySelectorAll('[data-tab]').forEach(x=>x.onclick=()=>switchTab(x.dataset.tab));
}
fetch('/api/city-economy/data').then(r=>{if(!r.ok)throw Error(`HTTP ${r.status}`);return r.json()}).then(p=>{payload=p;init()}).catch(e=>{document.querySelector('main').insertAdjacentHTML('beforeend',`<div class="notice">加载失败：${e.message}</div>`)});

// ── 房价情景推演 ───────────────────────────────────────────────────────────
const SC_FIELDS={optimistic:'scOpt',base:'scBase',stress:'scStress'};
const SC_COLOR={optimistic:'#27d3b2',base:'#f5a623',stress:'#ff6b7d'};
let scPayload=null;
function scQuery(){
  const q=new URLSearchParams({city:$('scCity').value,horizon:$('scHorizon').value,
    down_payment:(Number($('scDown').value)/100)||0.35});
  const meta=cityMeta($('scCity').value); if(meta)q.set('city_code',meta.city_code);
  for(const[k,id]of Object.entries(SC_FIELDS)){const v=$(id).value.trim();if(v!=='')q.set(k,v)}
  return q.toString();
}
function loadScenario(){
  fetch('/api/housing-scenario/data?'+scQuery()).then(r=>{if(!r.ok)throw Error('HTTP '+r.status);return r.json()})
    .then(p=>{scPayload=p;renderScenario()})
    .catch(e=>{$('scMomentum').textContent='加载失败：'+e.message});
}
function renderScenario(){
  const kind=$('scKind').value,s=scPayload.series[kind];
  ['scenario:main','scenario:anchor'].forEach(destroy);
  if(!s||s.status!=='ok'){$('scKpis').innerHTML='';$('scMomentum').textContent='该城该口径历史不足，无法推演。';
    $('scEquity').innerHTML='<tr><td colspan="6">—</td></tr>';return}
  const byKey=Object.fromEntries(s.scenarios.filter(x=>!x.status).map(x=>[x.key,x]));
  $('scKpis').innerHTML=`
    <div class="kpi">较峰值<b>${s.current_vs_peak.toFixed(1)}%</b><small>峰值 ${s.peak.period} · 最新 ${s.current.period}</small></div>
    <div class="kpi">乐观 ${scPayload.horizon_months} 月后<b>${byKey.optimistic?byKey.optimistic.end_vs_peak.toFixed(1)+'%':'—'}</b><small>较峰值 · 相对今天 ${byKey.optimistic?byKey.optimistic.end_vs_now.toFixed(1)+'%':'—'}</small></div>
    <div class="kpi">基准<b>${byKey.base?byKey.base.end_vs_peak.toFixed(1)+'%':'—'}</b><small>相对今天 ${byKey.base?byKey.base.end_vs_now.toFixed(1)+'%':'—'}</small></div>
    <div class="kpi">压力<b>${byKey.stress?byKey.stress.end_vs_peak.toFixed(1)+'%':'—'}</b><small>相对今天 ${byKey.stress?byKey.stress.end_vs_now.toFixed(1)+'%':'—'}</small></div>`;
  const m=s.momentum;
  $('scMomentum').textContent=`观测动能：近6月 ${m['6m']??'—'}%/月 · 近12月 ${m['12m']??'—'}%/月 · 近24月 ${m['24m']??'—'}%/月 · 近36月 ${m['36m']??'—'}%/月`;
  for(const[k,id]of Object.entries(SC_FIELDS)){const sc=byKey[k];
    $(id).placeholder=sc&&sc.derived_monthly_rate!=null?sc.derived_monthly_rate.toFixed(3):'—';
    $(id).classList.toggle('overridden',!!(sc&&sc.overridden))}
  // 图：历史 + 三条情景，横轴取历史后段以免压扁
  const hist=s.points.slice(-72),labels=hist.map(p=>p.period)
    .concat((byKey.base?byKey.base.path:[]).map(p=>p.period));
  const pad=new Array(hist.length-1).fill(null);
  const ds=[{label:'实际（统计局定基指数）',data:hist.map(p=>p.index).concat(new Array(labels.length-hist.length).fill(null)),
             borderColor:'#5795ff',pointRadius:0,borderWidth:2,spanGaps:false}];
  for(const k of ['optimistic','base','stress']){const sc=byKey[k];if(!sc)continue;
    ds.push({label:sc.label,data:pad.concat([hist.at(-1).index],sc.path.map(p=>p.index)),
             borderColor:SC_COLOR[k],borderDash:[6,3],pointRadius:0,borderWidth:1.8,spanGaps:false})}
  const sim=s.simulation;
  if(sim&&sim.status==='ok'){
    const simPad=new Array(hist.length-1).fill(null),tail=hist.at(-1).index;
    ds.push({label:'P90（模拟上沿）',data:simPad.concat([tail],sim.points.map(p=>p.p90)),
             borderColor:'rgba(167,139,250,.55)',backgroundColor:'rgba(167,139,250,.12)',
             pointRadius:0,borderWidth:1,fill:'+2',spanGaps:false});
    ds.push({label:'P50（模拟中位）',data:simPad.concat([tail],sim.points.map(p=>p.p50)),
             borderColor:'#a78bfa',pointRadius:0,borderWidth:1.4,borderDash:[2,2],spanGaps:false});
    ds.push({label:'P10（模拟下沿）',data:simPad.concat([tail],sim.points.map(p=>p.p10)),
             borderColor:'rgba(167,139,250,.55)',pointRadius:0,borderWidth:1,spanGaps:false});
  }
  ds.push({label:`峰值 ${s.peak.period}`,data:labels.map(()=>s.peak.index),borderColor:'#6b7c93',borderDash:[3,3],pointRadius:0,borderWidth:1});
  charts['scenario:main']=new Chart($('scChart'),{type:'line',data:{labels,datasets:ds},
    options:{responsive:true,maintainAspectRatio:false,interaction:{mode:'index',intersect:false},
      scales:{x:{ticks:{color:'#8fa4bd',maxTicksLimit:12},grid:{color:'#14263a'}},
              y:{ticks:{color:'#8fa4bd'},grid:{color:'#14263a'},title:{display:true,text:'定基指数',color:'#8fa4bd'}}},
      plugins:{legend:{position:'bottom',labels:{color:'#cbd8e6',boxWidth:16,usePointStyle:true}}}}});
  const dp=(s.equity.down_payment*100).toFixed(0);
  $('scEquityNote').textContent=`首付 ${dp}%。自有资金变动＝房价变动 ÷ 首付比，是价格变动对权益的杠杆放大；未计已还本金与利息支出，因此不等于家庭净值变动。低于 -100% 表示价格跌幅已超过首付，账面上房产价值低于剩余贷款。`;
  $('scEquity').innerHTML=s.equity.rows.map(r=>{
    const g=k=>r.by_scenario[k]?`${r.by_scenario[k].equity_change.toFixed(0)}%`:'—';
    return `<tr><td>${r.purchase_period}</td><td>${r.price_change_to_now.toFixed(1)}%</td>`+
      `<td>${r.equity_change_to_now.toFixed(0)}%</td><td>${g('optimistic')}</td><td>${g('base')}</td><td>${g('stress')}</td></tr>`}).join('')
    ||'<tr><td colspan="6">无可用买入时点</td></tr>';
  renderBacktest(s);
  const a=scPayload.valuation_anchor;
  if(a){$('scAnchorNote').textContent=`${a.note} 峰值 ${a.peak.period}（${a.peak.ratio}），最新 ${a.latest.period}（${a.latest.ratio}），较峰值 ${a.latest_vs_peak}%。工资序列止于 ${a.wage_end}。`;
    charts['scenario:anchor']=new Chart($('scAnchorChart'),{type:'line',
      data:{labels:a.points.map(p=>p.period),datasets:[{label:'房价/工资比',data:a.points.map(p=>p.ratio),borderColor:'#a78bfa',pointRadius:2}]},
      options:{responsive:true,maintainAspectRatio:false,scales:{x:{ticks:{color:'#8fa4bd'},grid:{color:'#14263a'}},y:{ticks:{color:'#8fa4bd'},grid:{color:'#14263a'}}},plugins:{legend:{display:false}}}});
  } else {$('scAnchorNote').textContent='该城缺在岗职工平均工资序列，估值锚无法计算。'}
  $('scCaveats').innerHTML=scPayload.caveats.map(x=>`<p>• ${x}</p>`).join('');
}
function initScenario(){
  const cities=payload.cities.map(c=>c.city);
  $('scCity').innerHTML=cities.map(c=>`<option>${c}</option>`).join('');
  $('scCity').value=cities.includes('厦门')?'厦门':cities[0];
  $('scRun').onclick=loadScenario;
  $('scReset').onclick=()=>{Object.values(SC_FIELDS).forEach(id=>{$(id).value='';$(id).classList.remove('overridden')});
    $('scHorizon').value=24;$('scDown').value=35;loadScenario()};
  ['scCity','scHorizon','scDown'].forEach(id=>$(id).onchange=loadScenario);
  $('scKind').onchange=()=>{if(scPayload)renderScenario()};
  loadScenario();
}

function renderBacktest(s){
  const bt=s.backtest,sim=s.simulation,band=$('scBacktest');
  if(!bt||bt.status!=='ok'){band.textContent='历史样本不足，无法回测本方法。';
    $('scBtNote').textContent='';$('scBtTable').innerHTML='<tr><td colspan="3">—</td></tr>';return}
  // 模拟带宽 vs 回测已证实误差:带宽明显更窄时必须当面说破，否则读者会高估精度
  const simWidth=sim&&sim.status==='ok'?Math.abs(sim.end_vs_now.p90-sim.end_vs_now.p10):null;
  const warn=simWidth!=null&&simWidth<bt.median_absolute_error_pp
    ?`　⚠ 模拟区间宽度 ${simWidth.toFixed(1)} 个百分点，<b>比回测已证实的中位误差还窄</b>，说明它只刻画了月度噪声、没有涵盖政策与信贷层面的转折。`:'';
  band.innerHTML=`<b>先看这条：本方法在历史上有多准。</b>以 ${bt.sample_start}–${bt.sample_end} 的 ${bt.n_obs} 个起点回测，`+
    `基准档 ${bt.horizon_months} 个月预测的中位绝对误差 <b>${bt.median_absolute_error_pp} 个百分点</b>，`+
    `实际值落在三档区间内的比例仅 <b>${bt.envelope_coverage_pct}%</b>，方向判对 ${bt.direction_hit_pct}%。`+
    `上方三档数字请据此打折理解。${warn}`;
  $('scBtNote').textContent=bt.method;
  const rows=[
    ['样本',`${bt.n_obs} 个起点`,`${bt.sample_start} 至 ${bt.sample_end}，每 ${bt.evaluation_step_months} 个月取一个`],
    ['基准档中位绝对误差',`${bt.median_absolute_error_pp} pp`,`${bt.horizon_months} 个月后的累计变动，预测与实际之差`],
    ['三档区间覆盖率',`${bt.envelope_coverage_pct}%`,'实际值落在乐观与压力之间的比例；越低说明区间越不够宽'],
    ['方向判对率',`${bt.direction_hit_pct}%`,'涨跌方向是否判对；50% 相当于抛硬币'],
  ];
  if(simWidth!=null)rows.push(['模拟区间宽度',`${simWidth.toFixed(1)} pp`,'P90 与 P10 之差，与上面的中位绝对误差对照看']);
  if(bt.latest)rows.push(['最近一次评估',`${bt.latest.as_of} → ${bt.latest.target_period}`,
    `预测 ${bt.latest.base_change}%，实际 ${bt.latest.actual_change}%，误差 ${bt.latest.base_error} pp`]);
  $('scBtTable').innerHTML=rows.map(r=>`<tr><td>${r[0]}</td><td>${r[1]}</td><td><small>${r[2]}</small></td></tr>`).join('');
}

// ── 上市公司 ───────────────────────────────────────────────────────────────
let lcPayload=null;
function loadListed(){
  const scope=$('lcScope').value;
  const cities=payload.cities.map(c=>c.city).join(',');
  fetch(`/api/listed-company/data?city_scope=${scope}&cities=${encodeURIComponent(cities)}`)
    .then(r=>{if(!r.ok)throw Error('HTTP '+r.status);return r.json()})
    .then(p=>{lcPayload=p;renderListed()})
    .catch(e=>{$('lcMeta').textContent='加载失败：'+e.message});
}
function renderListed(){
  const key=$('lcSort').value;
  const rows=[...lcPayload.cities].sort((a,b)=>{
    const g=x=>key==='company_count'?x.company_count
      :key==='securitisation_rate'?(x.derived.securitisation_rate??-1)
      :(x.totals_yi[key]??-1);
    return g(b)-g(a);
  });
  const covered=rows.filter(r=>r.totals_yi.market_cap!=null).length;
  const totalCompanies=rows.reduce((s,r)=>s+r.company_count,0);
  const annualRevenueCovered=rows.reduce((s,r)=>s+(r.coverage.revenue||0),0);
  $('lcMeta').textContent=`${rows.length} 城 · ${totalCompanies} 家公司 · ${covered} 城有市值数据 · `+
    `完整年度营收覆盖 ${annualRevenueCovered}/${totalCompanies} 家 · 归属口径 ${lcPayload.city_scope==='office_city'?'办公地':'注册地'}`;
  const cell=(r,k)=>{
    const v=r.totals_yi[k];if(v==null)return '<td class="gap">待入库</td>';
    const st=(r.data_statuses[k]||[]);
    const period=r.report_periods&&r.report_periods[k];
    const periodText=period?(period.start===period.end?period.end:`${period.start}–${period.end}`):'';
    const tag=st.includes('third_party')&&!st.includes('official')
      ?'<i class="ctag" style="border-color:#6b5a2b;color:#e0c168">三方</i>':'';
    return `<td>${tag}${fmt(v,0)}<small>${r.coverage[k]||0}/${r.company_count} 家有值${periodText?' · '+periodText:''}</small></td>`;
  };
  $('lcTable').innerHTML=rows.map(r=>`<tr><td>${r.city}</td><td>${r.company_count}</td>`+
    ['market_cap','revenue','net_profit','net_assets','total_assets','total_liabilities'].map(k=>cell(r,k)).join('')+
    `<td>${r.derived.securitisation_rate!=null?r.derived.securitisation_rate.toFixed(1)+'%':'—'}`+
    `<small>${r.gdp_yi?'GDP '+fmt(r.gdp_yi,0)+' ('+r.gdp_period+')':'无 GDP'}</small></td>`+
    `<td>${r.derived.listed_revenue_to_gdp!=null?r.derived.listed_revenue_to_gdp.toFixed(1)+'%':'—'}</td></tr>`).join('')
    ||'<tr><td colspan="10">暂无数据，请先运行采集</td></tr>';
  renderListedCharts(rows);
  renderListedHistory();
  renderListedDrill();
  renderScopeComparison();
  $('lcIndustry').innerHTML=rows.map(r=>`<tr><td>${r.city}</td><td>${
    (r.top_industries||[]).map(([n,c])=>`${n} <b>${c}</b>`).join('　')||'—'}</td></tr>`).join('');
  $('lcCaveats').innerHTML=lcPayload.caveats.map(x=>`<p>• ${x}</p>`).join('');
}

// 十个城市直接在条末标值，比让读者在坐标轴与柱端之间来回估读更可靠。
const horizontalValueLabels={id:'horizontalValueLabels',afterDatasetsDraw(chart,args,opts){
  const formatter=opts&&opts.formatter?opts.formatter:(v=>String(v));
  const ctx=chart.ctx;ctx.save();ctx.font='10px system-ui';ctx.textBaseline='middle';
  chart.data.datasets.forEach((dataset,di)=>{
    const meta=chart.getDatasetMeta(di);if(meta.hidden)return;
    meta.data.forEach((bar,i)=>{const value=Number(dataset.data[i]);if(!Number.isFinite(value))return;
      const text=formatter(value,{chart,datasetIndex:di,index:i});const room=chart.chartArea.right-bar.x;
      ctx.fillStyle='#cbd8e6';ctx.textAlign=room>ctx.measureText(text).width+10?'left':'right';
      ctx.fillText(text,bar.x+(ctx.textAlign==='left'?6:-6),bar.y);
    });
  });ctx.restore();}};

function listedPeriodSpan(rows,key){
  const periods=rows.map(r=>r.report_periods&&r.report_periods[key]).filter(Boolean);
  if(!periods.length)return '暂无可用报告期';
  const starts=periods.map(p=>p.start).sort(),ends=periods.map(p=>p.end).sort();
  return starts[0]===ends[ends.length-1]?starts[0]:`${starts[0]}–${ends[ends.length-1]}`;
}

function makeListedBar(name,canvasId,rows,valueOf,datasetLabel,color,formatValue,tickValue){
  destroy(name);
  const ranked=rows.map(r=>({row:r,value:Number(valueOf(r))}))
    .filter(x=>Number.isFinite(x.value)).sort((a,b)=>b.value-a.value);
  if(!ranked.length)return false;
  charts[name]=new Chart($(canvasId),{type:'bar',
    data:{labels:ranked.map(x=>x.row.city),datasets:[{label:datasetLabel,
      data:ranked.map(x=>x.value),backgroundColor:color,borderRadius:4,barPercentage:.72}]},
    options:{indexAxis:'y',responsive:true,maintainAspectRatio:false,
      layout:{padding:{right:74}},
      scales:{x:{beginAtZero:true,ticks:{color:'#8fa4bd',callback:tickValue||undefined},
                 grid:{color:'#14263a'},border:{color:'#28405b'}},
              y:{ticks:{color:'#cbd8e6'},grid:{display:false},border:{display:false}}},
      plugins:{legend:{display:false},horizontalValueLabels:{formatter:formatValue},
        tooltip:{callbacks:{label:c=>`${datasetLabel}：${formatValue(c.parsed.x)}`}}}},
    plugins:[horizontalValueLabels]});
  return true;
}

function renderListedCharts(rows){
  ['listed:scale','listed:securitisation','listed:revenue-gdp','listed:sales-multiple']
    .forEach(destroy);
  const key=$('lcSort').value;
  const metrics={
    market_cap:{title:'城市上市公司总市值排名',label:'总市值',color:'#5795ff',
      value:r=>r.totals_yi.market_cap,format:v=>`${fmt(v,0)} 亿元`,period:'market_cap'},
    company_count:{title:'城市上市公司家数排名',label:'公司家数',color:'#27d3b2',
      value:r=>r.company_count,format:v=>`${fmt(v,0)} 家`,period:null},
    revenue:{title:'城市上市公司完整年度营收排名',label:'完整年度营收',color:'#f5a623',
      value:r=>r.totals_yi.revenue,format:v=>`${fmt(v,0)} 亿元`,period:'revenue'},
    securitisation_rate:{title:'城市市值证券化率排名',label:'证券化率',color:'#a77bfa',
      value:r=>r.derived.securitisation_rate,format:v=>`${fmt(v,1)}%`,period:'market_cap'},
  };
  const metric=metrics[key]||metrics.market_cap;
  $('lcScaleTitle').textContent=metric.title;
  const hasScale=makeListedBar('listed:scale','lcScaleChart',rows,metric.value,metric.label,
    metric.color,metric.format,key==='company_count'?(v=>fmt(v,0)):(v=>fmt(v,0)));
  const valueCount=rows.filter(r=>Number.isFinite(Number(metric.value(r)))).length;
  $('lcScaleSub').textContent=hasScale
    ?`${valueCount}/${rows.length} 城有值${metric.period?' · 数据期 '+listedPeriodSpan(rows,metric.period):''}`
    :'暂无符合当前口径的数据；完整年度财务回填完成后自动显示。';

  makeListedBar('listed:securitisation','lcSecuritisationChart',rows,
    r=>r.derived.securitisation_rate,'证券化率','#5795ff',v=>`${fmt(v,1)}%`,v=>`${fmt(v,0)}%`);
  makeListedBar('listed:revenue-gdp','lcRevenueGdpChart',rows,
    r=>r.derived.listed_revenue_to_gdp,'完整年度营收/GDP','#f5a623',v=>`${fmt(v,1)}%`,v=>`${fmt(v,0)}%`);

  const multipleRows=rows.filter(r=>Number(r.totals_yi.market_cap)>0&&Number(r.totals_yi.revenue)>0)
    .map(r=>({...r,sales_multiple:r.totals_yi.market_cap/r.totals_yi.revenue}));
  makeListedBar('listed:sales-multiple','lcSalesMultipleChart',multipleRows,
    r=>r.sales_multiple,'市销率','#27d3b2',v=>`${fmt(v,1)}×`,v=>`${fmt(v,0)}×`);
  if(multipleRows.length){
    const ranked=[...multipleRows].sort((a,b)=>b.sales_multiple-a.sales_multiple);
    $('lcMultipleNote').textContent=`本组最高为 ${ranked[0].city} ${ranked[0].sales_multiple.toFixed(1)}×，`+
      `最低为 ${ranked[ranked.length-1].city} ${ranked[ranked.length-1].sales_multiple.toFixed(1)}×。`+
      `该指标是城市上市主体的描述性总量比，不是可交易组合估值。`;
  }else $('lcMultipleNote').textContent='完整年度营收尚未回填，暂不计算市销率。';
}

function concentrationLevel(hhi){
  if(!Number.isFinite(Number(hhi)))return '暂无';
  if(hhi>=2500)return '高度集中';
  if(hhi>=1500)return '中度集中';
  return '相对分散';
}

function renderListedHistory(){
  destroy('listed:history');
  const metric=$('lcHistoryMetric').value||'revenue',sample=$('lcHistorySample').value||'balanced';
  const scaleSelect=$('lcHistoryScale');
  scaleSelect.disabled=metric!=='revenue';
  if(scaleSelect.disabled)scaleSelect.value='level';
  const indexed=metric==='revenue'&&scaleSelect.value==='indexed';
  const periods=[...new Set(lcPayload.cities.flatMap(r=>r.annual_history?.periods||[]))].sort();
  const field=metric==='revenue'?'revenue_yi':metric==='net_profit'?'net_profit_yi':'profit_margin_pct';
  const label=metric==='revenue'?'营业收入':metric==='net_profit'?'归母净利润':'利润率';
  const datasets=lcPayload.cities.map(row=>{
    const byPeriod=new Map((row.annual_history?.[sample]||[]).map(x=>[x.period,x[field]]));
    const raw=periods.map(p=>byPeriod.get(p)??null);
    const base=raw.find(v=>Number.isFinite(Number(v))&&Number(v)!==0);
    const data=indexed?raw.map(v=>v==null||base==null?null:Number((v/base*100).toFixed(2))):raw;
    return {label:row.city,data,borderColor:CITY_COLORS[row.city]||'#8fa4bd',backgroundColor:'transparent',
      borderWidth:2,pointRadius:3,pointHoverRadius:5,tension:.08,spanGaps:false};
  }).filter(ds=>ds.data.some(v=>v!=null));
  if(periods.length<2||!datasets.length){
    $('lcHistorySub').textContent='历史回填完成后自动显示；当前完整年度不足两期。';
    $('lcHistoryNote').textContent='暂无可比较的五年序列。';return;
  }
  const counts=lcPayload.cities.map(r=>r.annual_history?.balanced_company_count||0);
  $('lcHistorySub').textContent=`${periods[0]}–${periods[periods.length-1]} · `+
    `${sample==='balanced'?'平衡样本':'各年可得样本'} · ${indexed?'各城首年=100':'绝对值'}`;
  charts['listed:history']=new Chart($('lcHistoryChart'),{type:'line',data:{labels:periods,datasets},
    options:{responsive:true,maintainAspectRatio:false,interaction:{mode:'index',intersect:false},
      scales:{x:{ticks:{color:'#8fa4bd'},grid:{color:'#14263a'}},
              y:{ticks:{color:'#8fa4bd',callback:v=>indexed?fmt(v,0):metric==='profit_margin_pct'?`${fmt(v,1)}%`:fmt(v,0)},
                 grid:{color:'#14263a'},title:{display:true,color:'#8fa4bd',
                   text:indexed?'指数':metric==='profit_margin_pct'?'%':'亿元'}}},
      plugins:{legend:{position:'bottom',labels:{color:'#cbd8e6',boxWidth:13}},
        tooltip:{callbacks:{label:c=>`${c.dataset.label}：${indexed?fmt(c.parsed.y,1):
          metric==='profit_margin_pct'?fmt(c.parsed.y,2)+'%':fmt(c.parsed.y,1)+' 亿元'}`}}}}});
  $('lcHistoryNote').textContent=sample==='balanced'
    ?`平衡样本只保留五年营收和净利润均齐全的当前公司；各城市入样数 ${Math.min(...counts)}–${Math.max(...counts)} 家。`+
      `可点击图例隐藏大城市。该口径仍有存续者偏差，并按当前地址回溯归属。`
    :'各年可得样本保留当年所有已有值公司，覆盖变化和新上市会共同影响总量；适合看当年规模，不宜直接当作同一批公司增长率。';
}

function renderListedDrill(){
  const citySelect=$('lcDrillCity'),metricSelect=$('lcDrillMetric');
  const previous=citySelect.value;
  citySelect.innerHTML=lcPayload.cities.map(r=>`<option value="${r.city}">${r.city}</option>`).join('');
  citySelect.value=lcPayload.cities.some(r=>r.city===previous)?previous:
    (lcPayload.cities.some(r=>r.city==='北京')?'北京':lcPayload.cities[0]?.city||'');
  const row=lcPayload.cities.find(r=>r.city===citySelect.value);
  const metric=metricSelect.value||'market_cap';
  const summary=row&&row.concentration&&row.concentration[metric];
  destroy('listed:top-companies');
  if(!summary||!summary.top_companies.length){
    $('lcConcentrationKpis').innerHTML='<div class="kpi"><small>暂无可用公司明细</small></div>';
    $('lcConcentrationNote').textContent='该城市该指标暂无可用值。';return;
  }
  const kpis=[
    ['Top1 占比',`${fmt(summary.top1_share_pct,1)}%`,'最大一家占已覆盖公司合计'],
    ['Top5 占比',`${fmt(summary.top5_share_pct,1)}%`,'前五家占已覆盖公司合计'],
    ['HHI',fmt(summary.hhi,0),`${concentrationLevel(summary.hhi)}；份额平方和×10000`],
    ['覆盖率',`${fmt(summary.coverage_pct,1)}%`,`${summary.n_obs}/${summary.company_count} 家有值`],
  ];
  $('lcConcentrationKpis').innerHTML=kpis.map(k=>
    `<div class="kpi"><small>${k[0]}</small><b>${k[1]}</b><small>${k[2]}</small></div>`).join('');
  const top=summary.top_companies,label=metric==='market_cap'?'总市值':'完整年度营收';
  charts['listed:top-companies']=new Chart($('lcTopCompaniesChart'),{type:'bar',
    data:{labels:top.map(x=>x.name||x.code),datasets:[{label,data:top.map(x=>x.value_yi),
      companyMeta:top,backgroundColor:CITY_COLORS[row.city]||'#5795ff',borderRadius:4,barPercentage:.72}]},
    options:{indexAxis:'y',responsive:true,maintainAspectRatio:false,
      layout:{padding:{right:125}},
      scales:{x:{beginAtZero:true,ticks:{color:'#8fa4bd',callback:v=>fmt(v,0)},grid:{color:'#14263a'}},
              y:{ticks:{color:'#cbd8e6'},grid:{display:false}}},
      plugins:{legend:{display:false},horizontalValueLabels:{formatter:(v,ctx)=>
        `${fmt(v,0)}亿 · ${fmt(top[ctx.index].share_pct,1)}%`},
        tooltip:{callbacks:{title:items=>{const x=top[items[0].dataIndex];return `${x.name||'—'}（${x.code}）`},
          label:c=>`${label}：${fmt(c.parsed.x,1)} 亿元；贡献 ${fmt(top[c.dataIndex].share_pct,2)}%`,
          afterLabel:c=>`行业：${top[c.dataIndex].industry||'未分类'}；报告期：${top[c.dataIndex].period||'—'}`}}}},
    plugins:[horizontalValueLabels]});
  const leader=top[0];
  $('lcConcentrationNote').textContent=
    `${row.city}${label}的第一家公司是 ${leader.name}，占已覆盖合计 ${fmt(leader.share_pct,1)}%；`+
    `Top5 占 ${fmt(summary.top5_share_pct,1)}%，HHI ${fmt(summary.hhi,0)}（${concentrationLevel(summary.hhi)}）。`+
    `占比的分母只包括已有该指标的 ${summary.n_obs} 家公司。`;
}

function renderScopeComparison(){
  destroy('listed:scope-comparison');
  const rows=[...(lcPayload.scope_comparison||[])].sort((a,b)=>b.office_count-a.office_count);
  if(!rows.length){$('lcScopeComparisonNote').textContent='暂无两种地址口径的可比数据。';return}
  charts['listed:scope-comparison']=new Chart($('lcScopeComparisonChart'),{type:'bar',
    data:{labels:rows.map(r=>r.city),datasets:[
      {label:'办公地',data:rows.map(r=>r.office_count),backgroundColor:'#5795ff',borderRadius:3},
      {label:'注册地',data:rows.map(r=>r.register_count),backgroundColor:'#f5a623',borderRadius:3}]},
    options:{indexAxis:'y',responsive:true,maintainAspectRatio:false,layout:{padding:{right:36}},
      scales:{x:{beginAtZero:true,ticks:{color:'#8fa4bd',callback:v=>fmt(v,0)},grid:{color:'#14263a'}},
              y:{ticks:{color:'#cbd8e6'},grid:{display:false}}},
      plugins:{legend:{position:'bottom',labels:{color:'#cbd8e6',boxWidth:13}},
        horizontalValueLabels:{formatter:v=>fmt(v,0)},
        tooltip:{callbacks:{afterBody:items=>{const r=rows[items[0].dataIndex];
          return `办公地−注册地：${r.delta>=0?'+':''}${r.delta} 家`}}}}},plugins:[horizontalValueLabels]});
  const largest=[...rows].sort((a,b)=>Math.abs(b.delta)-Math.abs(a.delta))[0];
  $('lcScopeComparisonNote').textContent=
    `差异最大的是 ${largest.city}：办公地 ${largest.office_count} 家、注册地 ${largest.register_count} 家，`+
    `相差 ${largest.delta>=0?'+':''}${largest.delta} 家。差额还会受到两类地址解析成功率不同的影响，`+
    `不应解释为公司迁入或迁出数量。`;
}

function initListed(){
  $('lcScope').onchange=loadListed;
  $('lcSort').onchange=()=>{if(lcPayload)renderListed()};
  $('lcDrillCity').onchange=()=>{if(lcPayload)renderListedDrill()};
  $('lcDrillMetric').onchange=()=>{if(lcPayload)renderListedDrill()};
  $('lcHistoryMetric').onchange=()=>{if(lcPayload)renderListedHistory()};
  $('lcHistorySample').onchange=()=>{if(lcPayload)renderListedHistory()};
  $('lcHistoryScale').onchange=()=>{if(lcPayload)renderListedHistory()};
  $('lcReload').onclick=loadListed;
  loadListed();
}
