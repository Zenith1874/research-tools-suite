'use strict';

const CITY_COLORS={北京:'#5795ff',上海:'#ff6680',广州:'#f5a623',深圳:'#19d3ae',厦门:'#a77bfa',南京:'#27c3d9',合肥:'#ff884d',常州:'#ef70bb',苏州:'#9acb58',无锡:'#92a9ff'};
const METRICS=[
  {key:'official_second_yoy',label:'官方二手房同比',group:'房价',source:'official',code:'second_home_yoy_pct',field:'value',unit:'%',rate:true},
  {key:'official_new_yoy',label:'官方新房同比',group:'房价',source:'official',code:'new_home_yoy_pct',field:'value',unit:'%',rate:true},
  {key:'listing_price',label:'挂牌均价',group:'房价',source:'listing',field:'avg_price',unit:'元/㎡'},
  {key:'listing_yoy',label:'挂牌同比',group:'房价',source:'listing',field:'yoy_pct',unit:'%',rate:true},
  {key:'nominal_gdp',label:'地区 GDP',group:'经济',source:'gdp',code:'nominal_gdp',field:'value',unit:'亿元'},
  {key:'general_budget_revenue',label:'一般预算收入',group:'财政',source:'fiscal',code:'general_budget_revenue',field:'value',unit:'亿元'},
  {key:'general_budget_expenditure',label:'一般预算支出',group:'财政',source:'fiscal',code:'general_budget_expenditure',field:'value',unit:'亿元'},
  {key:'gov_fund_revenue',label:'政府性基金收入',group:'财政',source:'fiscal',code:'gov_fund_revenue',field:'value',unit:'亿元'},
  {key:'gov_fund_expenditure',label:'政府性基金支出',group:'财政',source:'fiscal',code:'gov_fund_expenditure',field:'value',unit:'亿元'},
  {key:'land_transfer_revenue',label:'卖地收入',group:'土地',source:'fiscal',code:'land_transfer_revenue',field:'value',unit:'亿元'},
  {key:'debt_outstanding',label:'地方债余额',group:'债务',source:'fiscal',code:'debt_outstanding',field:'value',unit:'亿元'},
  {key:'tax_revenue',label:'税收收入',group:'财政',source:'fiscal',code:'tax_revenue',field:'value',unit:'亿元'},
];
const DEFAULT_METRICS=['official_second_yoy','listing_price','general_budget_revenue','general_budget_expenditure','gov_fund_revenue','gov_fund_expenditure','land_transfer_revenue','nominal_gdp'];
const GROUPS={全部:[],一线:['北京','上海','广州','深圳'],长三角:['上海','南京','常州','苏州','无锡'],珠三角:['广州','深圳']};
let payload=null,selectedCities=new Set(),selectedMetrics=new Set(DEFAULT_METRICS),charts={},axisState={};
const $=id=>document.getElementById(id),fmt=(v,d=2)=>v==null?'—':Number(v).toLocaleString(undefined,{maximumFractionDigits:d});

function destroy(name){if(charts[name]){charts[name].destroy();delete charts[name]}}
function periodKey(period,end=false){if(!period)return '';return period.length===4?`${period}-${end?'12':'01'}`:period}
function inRange(row){const a=periodKey($('start').value),b=periodKey($('end').value,true),p=periodKey(row?.period,true);return row&&(!a||p>=a)&&(!b||p<=b)}
function metricByKey(key){return METRICS.find(x=>x.key===key)}
function cityMeta(name){return payload.cities.find(x=>x.city===name)}
function rawRows(metric,applyRange=true){
  let rows=[];
  if(metric.source==='official')rows=payload.official_housing.filter(r=>r.indicator_code===metric.code);
  if(metric.source==='listing')rows=payload.listing_housing;
  if(metric.source==='gdp')rows=payload.gdp_rows.filter(r=>r.indicator_code===metric.code);
  if(metric.source==='fiscal')rows=payload.fiscal_rows.filter(r=>r.indicator_code===metric.code);
  return rows.filter(r=>selectedCities.has(r.city)&&typeof r[metric.field]==='number'&&(!applyRange||inRange(r)));
}
function metricSeries(metric,applyRange=true){
  const rows=rawRows(metric,applyRange),groups=new Map();
  for(const row of rows){
    const context=(metric.source==='gdp'||metric.source==='fiscal')&&row.geographic_scope==='province_context';
    const key=context?`province:${row.region_code}`:`city:${row.city}`;
    if(!groups.has(key))groups.set(key,{key,context,cities:new Set(),region:row.region_name,rows:[]});
    const group=groups.get(key);group.cities.add(row.city);group.rows.push(row);
  }
  return [...groups.values()].map(group=>{
    const cities=[...group.cities],label=group.context?`${group.region}省背景（${cities.join('/')}）`:cities[0];
    const byPeriod=new Map();
    for(const row of group.rows)if(!byPeriod.has(row.period))byPeriod.set(row.period,row[metric.field]);
    const color=group.context?CITY_COLORS[cities[0]]:CITY_COLORS[label];
    return {key:group.key,label,color,context:group.context,byPeriod};
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
    return {label:s.label,data,borderColor:s.color||CITY_COLORS[Object.keys(CITY_COLORS)[i%10]],backgroundColor:'transparent',borderWidth:s.context?1.7:2,pointRadius:periods.length>40?0:2,borderDash:s.context?[6,3]:[],spanGaps:false,tension:.08};
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
    const contextCount=series.filter(s=>s.context).length;
    card.innerHTML=`<div class="chart-head"><div><div class="chart-title">${metric.label}</div><div class="chart-sub">${periods[0]||'—'} 至 ${periods.at(-1)||'—'} · ${series.length} 条线${contextCount?` · ${contextCount} 条省级背景线已去重`:''}${axis.indexed?' · 可见首期=100':''}</div></div>${axisControls(metric,axis.state)}</div>${periods.length?`<div class="chart"><canvas id="chart-${metric.key}"></canvas></div>`:'<div class="empty">所选城市与期间暂无数据</div>'}`;
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
  rows=rows.filter(r=>inRange(r)&&typeof r[metric.field]==='number');return rows.sort((a,b)=>a.period.localeCompare(b.period)).at(-1)||null;
}
// 每格单独判定口径:省背景值绝不能看起来像城市值(广州/深圳同为广东、南京苏锡常同为江苏)
function cellScope(metric,row,city){
  if(!['gdp','fiscal'].includes(metric.source))return{cls:'',tag:'',note:'',title:''};
  if(row.geographic_scope==='province_context')
    return{cls:'prov',tag:`${row.region_name}省`,note:'省背景',
           title:`${row.region_name}省${metric.label}，${city}市本级数据未入库；不可解释为${city}的值`};
  if(row.scope_label==='市本级补充')
    return{cls:'lvl',tag:'市本级',note:'市本级',title:`${city}市本级口径，小于全市口径，与其他城市的全市值不可直接比较`};
  return{cls:'',tag:'',note:'',title:`${city}${row.scope_label||'城市口径'}`};
}
function renderMatrix(){
  const metrics=METRICS.filter(m=>selectedMetrics.has(m.key));
  $('matrixHead').innerHTML=`<tr><th>城市</th>${metrics.map(m=>`<th>${m.label}</th>`).join('')}<th>财政/GDP 数据来自谁</th></tr>`;
  $('matrixBody').innerHTML=[...selectedCities].map(city=>{const meta=cityMeta(city);
    const cells=metrics.map(m=>{const r=latestForCity(m,city);
      if(!r)return '<td>—</td>';
      const s=cellScope(m,r,city);
      return `<td class="${s.cls}" title="${s.title}">${s.tag?`<i class="ctag">${s.tag}</i>`:''}${fmt(r[m.field],m.rate?2:0)} ${m.unit}<small>${r.period}${s.note?` · ${s.note}`:''}</small></td>`}).join('');
    return `<tr><td>${city}</td>${cells}<td><span class="badge ${meta.fiscal_scope==='province_context'?'province':'city'}">${meta.fiscal_scope_label}</span></td></tr>`}).join('')
    ||`<tr><td colspan="${metrics.length+2}">请至少选择一个城市</td></tr>`;
}
function availableCityCount(metric){
  let rows=[];
  if(metric.source==='official')rows=payload.official_housing.filter(r=>r.indicator_code===metric.code);
  if(metric.source==='listing')rows=payload.listing_housing;
  if(metric.source==='gdp')rows=payload.gdp_rows.filter(r=>r.indicator_code===metric.code);
  if(metric.source==='fiscal')rows=payload.fiscal_rows.filter(r=>r.indicator_code===metric.code);
  return new Set(rows.filter(r=>typeof r[metric.field]==='number').map(r=>r.city)).size;
}
function renderPickers(){
  $('cityQuick').innerHTML=Object.entries(GROUPS).map(([name,cities])=>`<button data-city-group="${name}">${name}</button>`).join('')+'<button data-city-group="清空">清空</button>';
  $('cityChips').innerHTML=payload.cities.map(c=>{const active=selectedCities.has(c.city),has=c.coverage.official_housing_records||c.coverage.listing_records;return `<button class="chip ${active?'active':''} ${has?'':'missing'}" style="--chip-color:${CITY_COLORS[c.city]}" data-city="${c.city}">${c.city}</button>`}).join('');
  $('metricQuick').innerHTML='<button data-metric-group="全景">推荐全景</button><button data-metric-group="房价">只看房价</button><button data-metric-group="财政土地">财政土地</button><button data-metric-group="清空">清空</button>';
  $('metricChips').innerHTML=METRICS.map(m=>`<button class="chip ${selectedMetrics.has(m.key)?'active':''}" data-metric="${m.key}">${m.label} <small>${availableCityCount(m)}/10${['gdp','fiscal'].includes(m.source)?'·含省背景':''}</small></button>`).join('');
  document.querySelectorAll('[data-city]').forEach(el=>el.onclick=()=>{selectedCities.has(el.dataset.city)?selectedCities.delete(el.dataset.city):selectedCities.add(el.dataset.city);renderCompare()});
  document.querySelectorAll('[data-city-group]').forEach(el=>el.onclick=()=>{const key=el.dataset.cityGroup;if(key==='清空')selectedCities.clear();else selectedCities=new Set(key==='全部'?payload.cities.map(c=>c.city):GROUPS[key]);renderCompare()});
  document.querySelectorAll('[data-metric]').forEach(el=>el.onclick=()=>{selectedMetrics.has(el.dataset.metric)?selectedMetrics.delete(el.dataset.metric):selectedMetrics.add(el.dataset.metric);renderCompare()});
  document.querySelectorAll('[data-metric-group]').forEach(el=>el.onclick=()=>{const key=el.dataset.metricGroup;if(key==='清空')selectedMetrics.clear();else if(key==='房价')selectedMetrics=new Set(METRICS.filter(m=>m.group==='房价').map(m=>m.key));else if(key==='财政土地')selectedMetrics=new Set(METRICS.filter(m=>['财政','土地','债务'].includes(m.group)).map(m=>m.key));else selectedMetrics=new Set(DEFAULT_METRICS);renderCompare()});
}
function renderCompare(){
  renderPickers();const context=[...selectedCities].filter(c=>cityMeta(c).fiscal_scope==='province_context');
  $('compareNotice').textContent=context.length?`房价按所选城市逐城比较；财政和 GDP 中，${context.join('、')}当前是所属省背景。相同省份自动合并为一条虚线，避免重复冒充城市数据。`:'当前所选城市的财政与 GDP 均可按城市/直辖市全市口径比较。';
  $('compareCounts').innerHTML=`<div>已选城市<b>${selectedCities.size}</b></div><div>已选指标<b>${selectedMetrics.size}</b></div><div>城市房价口径<b>${[...selectedCities].filter(c=>cityMeta(c).coverage.official_housing_records).length}</b></div><div>省级背景城市<b>${context.length}</b></div>`;
  renderComparisonCharts();renderMatrix();
}
function line(name,canvas,labels,datasets,unit=''){destroy(name);charts[name]=new Chart(canvas,{type:'line',data:{labels,datasets},options:{responsive:true,maintainAspectRatio:false,interaction:{mode:'index',intersect:false},scales:{x:{ticks:{color:'#8fa4bd',maxTicksLimit:10},grid:{color:'#14263a'}},y:{ticks:{color:'#8fa4bd',callback:v=>fmt(v,unit==='%'?1:0)+(unit==='%'?'%':'')},grid:{color:'#14263a'}}},plugins:{legend:{position:'bottom',labels:{color:'#cbd8e6'}}}}})}
function detailCity(){return cityMeta($('city').value)||payload.cities[0]}
function detailRows(source,code){let rows=source.filter(r=>r.city===detailCity().city&&(!code||r.indicator_code===code));return rows.filter(inRange)}
function kpi(label,metric){const row=latestForCity(metric,detailCity().city);return `<div class="kpi">${label}<b>${row?`${fmt(row[metric.field],metric.rate?2:0)} ${metric.unit}`:'—'}</b><small>${row?.period||'暂无直接数据'} · ${row?.scope_label||''}</small></div>`}
function renderDetail(){
  const c=detailCity();$('scopeBadge').className='badge '+(c.fiscal_scope==='province_context'?'province':'city');$('scopeBadge').textContent=c.fiscal_scope_label;$('scopeNotice').textContent=c.fiscal_scope==='province_context'?`${c.city}房价为城市口径；财政与 GDP 当前仅展示${c.province}省背景，绝不解释为${c.city}市本级。`:`${c.city}为直辖市，现有省级行政区财政与 GDP 可作为全市口径使用。`;
  const keys=['official_second_yoy','listing_price','listing_yoy','nominal_gdp','general_budget_revenue','general_budget_expenditure','gov_fund_revenue','land_transfer_revenue','debt_outstanding'];$('kpis').innerHTML=keys.map(k=>kpi(metricByKey(k).label,metricByKey(k))).join('');
  const o=detailRows(payload.official_housing),l=detailRows(payload.listing_housing),periods=[...new Set(o.map(r=>r.period).concat(l.map(r=>r.period)))].sort(),map=(rows,code,field='value')=>new Map(rows.filter(r=>!code||r.indicator_code===code).map(r=>[r.period,r[field]]));const n=map(o,'new_home_yoy_pct'),s=map(o,'second_home_yoy_pct'),ly=map(l,null,'yoy_pct');line('detail:housing',$('detailHousing'),periods,[{label:'新房同比',data:periods.map(p=>n.get(p)??null),borderColor:'#f5a623',pointRadius:0},{label:'二手同比',data:periods.map(p=>s.get(p)??null),borderColor:'#5795ff',pointRadius:0},{label:'挂牌同比',data:periods.map(p=>ly.get(p)??null),borderColor:'#27d3b2',pointRadius:0}],'%');
  const lp=l.map(r=>r.period),lm=map(l,null,'avg_price');line('detail:listing',$('detailListing'),lp,[{label:'挂牌均价',data:lp.map(p=>lm.get(p)??null),borderColor:'#27d3b2',pointRadius:0}],'元/㎡');
  const f=detailRows(payload.fiscal_rows),fy=[...new Set(f.map(r=>r.period))].sort(),rev=map(f,'general_budget_revenue'),exp=map(f,'general_budget_expenditure');$('detailFiscalTitle').textContent=`${c.fiscal_scope_label}：一般预算收支`;line('detail:fiscal',$('detailFiscal'),fy,[{label:'收入',data:fy.map(p=>rev.get(p)??null),borderColor:'#27d3b2',pointRadius:2},{label:'支出',data:fy.map(p=>exp.get(p)??null),borderColor:'#f5a623',pointRadius:2}],'亿元');
  const g=detailRows(payload.gdp_rows,'nominal_gdp'),gp=g.map(r=>r.period),gm=map(g,'nominal_gdp');$('detailGdpTitle').textContent=c.gdp_scope_label;line('detail:gdp',$('detailGdp'),gp,[{label:'名义 GDP',data:gp.map(p=>gm.get(p)??null),borderColor:'#5795ff',pointRadius:2}],'亿元');renderFiscalTable();
}
function renderFiscalTable(){const c=detailCity(),code=$('fiscalMetric').value,rows=detailRows(payload.fiscal_rows,code).sort((a,b)=>b.period.localeCompare(a.period));$('fiscalTable').innerHTML=rows.map(r=>`<tr><td>${r.period}</td><td>${fmt(r.value,2)} ${r.unit}</td><td>${r.scope_label}</td><td>${r.data_status}</td><td>${r.source_url?`<a href="${r.source_url}" target="_blank" rel="noopener">原文</a>`:'—'}</td></tr>`).join('')||'<tr><td colspan="5">暂无该口径直接数据</td></tr>'}
function renderCoverage(){const c=payload.coverage;$('coverageCards').innerHTML=`<div>目标城市<b>${c.cities}</b></div><div>官方房价城市<b>${c.official_housing_cities}</b></div><div>挂牌历史城市<b>${c.listing_cities}</b></div><div>城市可用财政口径<b>${c.direct_city_fiscal_cities}</b></div><div>省级背景地区<b>${c.province_context_regions}</b></div>`;$('coverageTable').innerHTML=payload.cities.map(x=>`<tr><td>${x.city}</td><td>${x.coverage.official_housing_records}</td><td>${x.coverage.listing_records}</td><td><span class="badge ${x.fiscal_scope==='province_context'?'province':'city'}">${x.fiscal_scope_label}</span></td><td>${x.coverage.fiscal_records}</td><td>${x.coverage.gdp_records}</td></tr>`).join('');$('caveats').innerHTML=payload.caveats.map(x=>`<p>• ${x}</p>`).join('')}
function switchTab(tab){document.querySelectorAll('[data-tab]').forEach(x=>x.classList.toggle('active',x.dataset.tab===tab));['compare','detail','coverage'].forEach(x=>$(x).classList.toggle('hidden',x!==tab));if(tab==='detail')renderDetail();if(tab==='coverage')renderCoverage()}
function init(){
  selectedCities=new Set(payload.cities.map(c=>c.city));$('city').innerHTML=payload.cities.map(c=>`<option>${c.city}</option>`).join('');const periods=[...new Set(payload.official_housing.concat(payload.listing_housing,payload.fiscal_rows,payload.gdp_rows).map(r=>r.period))].sort();$('start').innerHTML=periods.map(p=>`<option>${p}</option>`).join('');$('end').innerHTML=periods.map(p=>`<option>${p}</option>`).join('');$('start').value=periods[0]||'';$('end').value=periods.at(-1)||'';const fiscalCodes=[...new Set(payload.fiscal_rows.map(r=>r.indicator_code))];$('fiscalMetric').innerHTML=fiscalCodes.map(code=>`<option value="${code}">${payload.indicator_labels[code]||code}</option>`).join('');$('fiscalMetric').value='general_budget_revenue';
  const rerenderRange=()=>{renderCompare();if(!$('detail').classList.contains('hidden'))renderDetail()};
  renderCompare();renderCoverage();$('start').onchange=rerenderRange;$('end').onchange=rerenderRange;$('city').onchange=renderDetail;$('fiscalMetric').onchange=renderFiscalTable;document.querySelectorAll('[data-tab]').forEach(x=>x.onclick=()=>switchTab(x.dataset.tab));
}
fetch('/api/city-economy/data').then(r=>{if(!r.ok)throw Error(`HTTP ${r.status}`);return r.json()}).then(p=>{payload=p;init()}).catch(e=>{document.querySelector('main').insertAdjacentHTML('beforeend',`<div class="notice">加载失败：${e.message}</div>`)});
