'use strict';

const CITY_COLORS={北京:'#5795ff',上海:'#ff6680',广州:'#f5a623',深圳:'#19d3ae',厦门:'#a77bfa',南京:'#27c3d9',合肥:'#ff884d',常州:'#ef70bb',苏州:'#9acb58',无锡:'#92a9ff'};
const METRICS=[
  {key:'official_second_yoy',label:'官方二手房同比',group:'房价',source:'official',code:'second_home_yoy_pct',field:'value',unit:'%',rate:true},
  {key:'official_new_yoy',label:'官方新房同比',group:'房价',source:'official',code:'new_home_yoy_pct',field:'value',unit:'%',rate:true},
  {key:'listing_price',label:'挂牌均价',group:'房价',source:'listing',field:'avg_price',unit:'元/㎡'},
  {key:'listing_yoy',label:'挂牌同比',group:'房价',source:'listing',field:'yoy_pct',unit:'%',rate:true},
  {key:'nominal_gdp',label:'地区 GDP',group:'经济',source:'gdp',code:'nominal_gdp',field:'value',unit:'亿元'},
  {key:'primary_industry_value',label:'第一产业增加值',group:'经济',source:'gdp',code:'primary_industry_value',field:'value',unit:'亿元'},
  {key:'secondary_industry_value',label:'第二产业增加值',group:'经济',source:'gdp',code:'secondary_industry_value',field:'value',unit:'亿元'},
  {key:'tertiary_industry_value',label:'第三产业增加值',group:'经济',source:'gdp',code:'tertiary_industry_value',field:'value',unit:'亿元'},
  {key:'general_budget_revenue',label:'一般预算收入',group:'财政',source:'fiscal',code:'general_budget_revenue',field:'value',unit:'亿元'},
  {key:'general_budget_expenditure',label:'一般预算支出',group:'财政',source:'fiscal',code:'general_budget_expenditure',field:'value',unit:'亿元'},
  {key:'gov_fund_revenue',label:'政府性基金收入',group:'财政',source:'fiscal',code:'gov_fund_revenue',field:'value',unit:'亿元'},
  {key:'gov_fund_expenditure',label:'政府性基金支出',group:'财政',source:'fiscal',code:'gov_fund_expenditure',field:'value',unit:'亿元'},
  {key:'land_transfer_revenue',label:'卖地收入',group:'土地',source:'fiscal',code:'land_transfer_revenue',field:'value',unit:'亿元'},
  {key:'debt_outstanding',label:'地方债余额',group:'债务',source:'fiscal',code:'debt_outstanding',field:'value',unit:'亿元'},
  {key:'tax_revenue',label:'税收收入',group:'财政',source:'fiscal',code:'tax_revenue',field:'value',unit:'亿元'},
  {key:'residential_avg_price',label:'住宅新房均价（官方）',group:'房价',source:'indicator',code:'residential_avg_price',field:'value',unit:'元/㎡'},
  {key:'commercial_housing_sold_area',label:'商品房销售面积',group:'房价',source:'indicator',code:'commercial_housing_sold_area',field:'value',unit:'万㎡'},
  {key:'real_estate_investment',label:'房地产开发投资',group:'房价',source:'indicator',code:'real_estate_investment',field:'value',unit:'亿元'},
  {key:'land_purchased_area',label:'房企购置土地面积',group:'土地',source:'indicator',code:'land_purchased_area',field:'value',unit:'万㎡'},
  {key:'retail_sales',label:'社会消费品零售总额',group:'经济',source:'indicator',code:'retail_sales',field:'value',unit:'亿元'},
  {key:'trade_total',label:'货物进出口总额',group:'经济',source:'indicator',code:'trade_total',field:'value',unit:'百万美元'},
  {key:'household_deposits',label:'住户存款余额',group:'经济',source:'indicator',code:'household_deposits',field:'value',unit:'亿元'},
  {key:'registered_population',label:'年末户籍人口',group:'经济',source:'indicator',code:'registered_population',field:'value',unit:'万人'},
  {key:'avg_wage',label:'在岗职工平均工资',group:'经济',source:'indicator',code:'avg_wage',field:'value',unit:'元'},
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
  if(metric.source==='indicator')rows=(payload.indicator_rows||[]).filter(r=>r.indicator_code===metric.code);
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
    return {label:s.label,data,borderColor:s.color||CITY_COLORS[Object.keys(CITY_COLORS)[i%10]],backgroundColor:'transparent',borderWidth:2,pointRadius:periods.length>40?0:2,spanGaps:false,tension:.08};
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
    card.innerHTML=`<div class="chart-head"><div><div class="chart-title">${metric.label}</div><div class="chart-sub">${periods[0]||'—'} 至 ${periods.at(-1)||'—'} · ${series.length} 城${missing.length?` · ${missing.join('、')}暂无城市级官方值`:''}${axis.indexed?' · 可见首期=100':''}</div></div>${axisControls(metric,axis.state)}</div>${periods.length?`<div class="chart"><canvas id="chart-${metric.key}"></canvas></div>`:`<div class="empty">所选城市在该期间暂无城市级官方值（不以省级数据代替）</div>`}`;
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
  rows=rows.filter(r=>inRange(r)&&typeof r[metric.field]==='number');return rows.sort((a,b)=>a.period.localeCompare(b.period)).at(-1)||null;
}
// 每格单独判定口径:全市 / 市本级 都是这座城市的数,但口径大小不同,不可混比
function cellScope(metric,row,city){
  if(!['gdp','fiscal','indicator'].includes(metric.source))return{cls:'',tag:'',note:'',title:''};
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
  $('matrixHead').innerHTML=`<tr><th>城市</th>${metrics.map(m=>`<th>${m.label}</th>`).join('')}<th>财政/GDP 数据来自谁</th></tr>`;
  $('matrixBody').innerHTML=[...selectedCities].map(city=>{const meta=cityMeta(city);
    const cells=metrics.map(m=>{const r=latestForCity(m,city);
      if(!r)return `<td class="gap" title="${city}该指标的城市级官方值未入库；不以${cityMeta(city).province}省值代替">待入库</td>`;
      const s=cellScope(m,r,city);
      return `<td class="${s.cls}" title="${s.title}">${s.tag?`<i class="ctag">${s.tag}</i>`:''}${fmt(r[m.field],m.rate?2:0)} ${m.unit}<small>${r.period}${s.note?` · ${s.note}`:''}</small></td>`}).join('');
    return `<tr><td>${city}</td>${cells}<td><span class="badge ${meta.fiscal_scope==='missing'?'gap':'city'}">${meta.fiscal_scope_label}</span></td></tr>`}).join('')
    ||`<tr><td colspan="${metrics.length+2}">请至少选择一个城市</td></tr>`;
}
function availableCityCount(metric){
  let rows=[];
  if(metric.source==='official')rows=payload.official_housing.filter(r=>r.indicator_code===metric.code);
  if(metric.source==='listing')rows=payload.listing_housing;
  if(metric.source==='gdp')rows=payload.gdp_rows.filter(r=>r.indicator_code===metric.code);
  if(metric.source==='fiscal')rows=payload.fiscal_rows.filter(r=>r.indicator_code===metric.code);
  if(metric.source==='indicator')rows=(payload.indicator_rows||[]).filter(r=>r.indicator_code===metric.code);
  return new Set(rows.filter(r=>typeof r[metric.field]==='number').map(r=>r.city)).size;
}
function renderPickers(){
  $('cityQuick').innerHTML=Object.entries(GROUPS).map(([name,cities])=>`<button data-city-group="${name}">${name}</button>`).join('')+'<button data-city-group="清空">清空</button>';
  $('cityChips').innerHTML=payload.cities.map(c=>{const active=selectedCities.has(c.city),has=c.coverage.official_housing_records||c.coverage.listing_records;return `<button class="chip ${active?'active':''} ${has?'':'missing'}" style="--chip-color:${CITY_COLORS[c.city]}" data-city="${c.city}">${c.city}</button>`}).join('');
  $('metricQuick').innerHTML='<button data-metric-group="全景">推荐全景</button><button data-metric-group="房价">只看房价</button><button data-metric-group="财政土地">财政土地</button><button data-metric-group="清空">清空</button>';
  $('metricChips').innerHTML=METRICS.map(m=>`<button class="chip ${selectedMetrics.has(m.key)?'active':''}" data-metric="${m.key}">${m.label} <small>${availableCityCount(m)}/10 城</small></button>`).join('');
  document.querySelectorAll('[data-city]').forEach(el=>el.onclick=()=>{selectedCities.has(el.dataset.city)?selectedCities.delete(el.dataset.city):selectedCities.add(el.dataset.city);renderCompare()});
  document.querySelectorAll('[data-city-group]').forEach(el=>el.onclick=()=>{const key=el.dataset.cityGroup;if(key==='清空')selectedCities.clear();else selectedCities=new Set(key==='全部'?payload.cities.map(c=>c.city):GROUPS[key]);renderCompare()});
  document.querySelectorAll('[data-metric]').forEach(el=>el.onclick=()=>{selectedMetrics.has(el.dataset.metric)?selectedMetrics.delete(el.dataset.metric):selectedMetrics.add(el.dataset.metric);renderCompare()});
  document.querySelectorAll('[data-metric-group]').forEach(el=>el.onclick=()=>{const key=el.dataset.metricGroup;if(key==='清空')selectedMetrics.clear();else if(key==='房价')selectedMetrics=new Set(METRICS.filter(m=>m.group==='房价').map(m=>m.key));else if(key==='财政土地')selectedMetrics=new Set(METRICS.filter(m=>['财政','土地','债务'].includes(m.group)).map(m=>m.key));else selectedMetrics=new Set(DEFAULT_METRICS);renderCompare()});
}
function renderCompare(){
  renderPickers();const pending=[...selectedCities].filter(c=>cityMeta(c).fiscal_scope==='missing');
  $('compareNotice').textContent=pending.length?`本模块只画城市自己的官方值。${pending.join('、')}的市级财政/GDP 尚未入库，相关图与格子显示为缺口，不用所属省数据顶替（省域经济请看财政收支与债务页）。`:'所选城市的房价、GDP 与财政均为城市口径。';
  $('compareCounts').innerHTML=`<div>已选城市<b>${selectedCities.size}</b></div><div>已选指标<b>${selectedMetrics.size}</b></div><div>有城市房价<b>${[...selectedCities].filter(c=>cityMeta(c).coverage.official_housing_records).length}</b></div><div>市级财政待入库<b>${pending.length}</b></div>`;
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
  const c=detailCity();$('scopeBadge').className='badge '+(c.fiscal_scope==='missing'?'gap':'city');$('scopeBadge').textContent=c.fiscal_scope_label;$('scopeNotice').textContent=c.fiscal_scope==='missing'?`${c.city}房价为城市口径；${c.city}市级财政与 GDP 官方值尚未入库，此处保持空缺，不用${c.province}省数据代替。`:`${c.city}的财政与 GDP 为该市自身口径${c.municipality?'（直辖市，省级行政区即本市）':''}。`;
  const keys=['official_second_yoy','listing_price','listing_yoy','nominal_gdp','general_budget_revenue','general_budget_expenditure','gov_fund_revenue','land_transfer_revenue','debt_outstanding'];$('kpis').innerHTML=keys.map(k=>kpi(metricByKey(k).label,metricByKey(k))).join('');
  const o=detailRows(payload.official_housing),l=detailRows(payload.listing_housing),periods=[...new Set(o.map(r=>r.period).concat(l.map(r=>r.period)))].sort(),map=(rows,code,field='value')=>new Map(rows.filter(r=>!code||r.indicator_code===code).map(r=>[r.period,r[field]]));const n=map(o,'new_home_yoy_pct'),s=map(o,'second_home_yoy_pct'),ly=map(l,null,'yoy_pct');line('detail:housing',$('detailHousing'),periods,[{label:'新房同比',data:periods.map(p=>n.get(p)??null),borderColor:'#f5a623',pointRadius:0},{label:'二手同比',data:periods.map(p=>s.get(p)??null),borderColor:'#5795ff',pointRadius:0},{label:'挂牌同比',data:periods.map(p=>ly.get(p)??null),borderColor:'#27d3b2',pointRadius:0}],'%');
  const lp=l.map(r=>r.period),lm=map(l,null,'avg_price');line('detail:listing',$('detailListing'),lp,[{label:'挂牌均价',data:lp.map(p=>lm.get(p)??null),borderColor:'#27d3b2',pointRadius:0}],'元/㎡');
  const f=detailRows(payload.fiscal_rows),fy=[...new Set(f.map(r=>r.period))].sort(),rev=map(f,'general_budget_revenue'),exp=map(f,'general_budget_expenditure');$('detailFiscalTitle').textContent=`${c.fiscal_scope_label}：一般预算收支`;line('detail:fiscal',$('detailFiscal'),fy,[{label:'收入',data:fy.map(p=>rev.get(p)??null),borderColor:'#27d3b2',pointRadius:2},{label:'支出',data:fy.map(p=>exp.get(p)??null),borderColor:'#f5a623',pointRadius:2}],'亿元');
  const g=detailRows(payload.gdp_rows,'nominal_gdp'),gp=g.map(r=>r.period),gm=map(g,'nominal_gdp');$('detailGdpTitle').textContent=c.gdp_scope_label;line('detail:gdp',$('detailGdp'),gp,[{label:'名义 GDP',data:gp.map(p=>gm.get(p)??null),borderColor:'#5795ff',pointRadius:2}],'亿元');renderFiscalTable();
}
function renderFiscalTable(){const c=detailCity(),code=$('fiscalMetric').value,rows=detailRows(payload.fiscal_rows,code).sort((a,b)=>b.period.localeCompare(a.period));$('fiscalTable').innerHTML=rows.map(r=>`<tr><td>${r.period}</td><td>${fmt(r.value,2)} ${r.unit}</td><td>${r.scope_label}</td><td>${r.data_status}</td><td>${r.source_url?`<a href="${r.source_url}" target="_blank" rel="noopener">原文</a>`:'—'}</td></tr>`).join('')||'<tr><td colspan="5">暂无该口径直接数据</td></tr>'}
function renderCoverage(){const c=payload.coverage;$('coverageCards').innerHTML=`<div>目标城市<b>${c.cities}</b></div><div>官方房价城市<b>${c.official_housing_cities}</b></div><div>挂牌历史城市<b>${c.listing_cities}</b></div><div>有市级财政<b>${c.direct_city_fiscal_cities}</b></div><div>有城市 GDP<b>${c.city_gdp_cities}</b></div>`;$('coverageTable').innerHTML=payload.cities.map(x=>`<tr><td>${x.city}</td><td>${x.coverage.official_housing_records}</td><td>${x.coverage.listing_records}</td><td><span class="badge ${x.fiscal_scope==='missing'?'gap':'city'}">${x.fiscal_scope_label}</span></td><td>${x.coverage.fiscal_records}</td><td>${x.coverage.gdp_records}</td></tr>`).join('');$('caveats').innerHTML=payload.caveats.map(x=>`<p>• ${x}</p>`).join('');renderConflicts()}
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
  selectedCities=new Set(payload.cities.map(c=>c.city));$('city').innerHTML=payload.cities.map(c=>`<option>${c.city}</option>`).join('');const periods=[...new Set(payload.official_housing.concat(payload.listing_housing,payload.fiscal_rows,payload.gdp_rows).map(r=>r.period))].sort();$('start').innerHTML=periods.map(p=>`<option>${p}</option>`).join('');$('end').innerHTML=periods.map(p=>`<option>${p}</option>`).join('');$('start').value=periods[0]||'';$('end').value=periods.at(-1)||'';const fiscalCodes=[...new Set(payload.fiscal_rows.map(r=>r.indicator_code))];$('fiscalMetric').innerHTML=fiscalCodes.map(code=>`<option value="${code}">${payload.indicator_labels[code]||code}</option>`).join('');$('fiscalMetric').value='general_budget_revenue';
  const rerenderRange=()=>{renderCompare();if(!$('detail').classList.contains('hidden'))renderDetail()};
  renderCompare();renderCoverage();$('start').onchange=rerenderRange;$('end').onchange=rerenderRange;$('city').onchange=renderDetail;$('fiscalMetric').onchange=renderFiscalTable;document.querySelectorAll('[data-tab]').forEach(x=>x.onclick=()=>switchTab(x.dataset.tab));
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
  destroy('listed:rate');
  const key=$('lcSort').value;
  const rows=[...lcPayload.cities].sort((a,b)=>{
    const g=x=>key==='company_count'?x.company_count
      :key==='securitisation_rate'?(x.derived.securitisation_rate??-1)
      :(x.totals_yi[key]??-1);
    return g(b)-g(a);
  });
  const covered=rows.filter(r=>r.totals_yi.market_cap!=null).length;
  $('lcMeta').textContent=`${rows.length} 城 · ${rows.reduce((s,r)=>s+r.company_count,0)} 家公司 · ${covered} 城有市值数据 · 归属口径 ${lcPayload.city_scope==='office_city'?'办公地':'注册地'}`;
  const cell=(r,k)=>{
    const v=r.totals_yi[k];if(v==null)return '<td class="gap">待入库</td>';
    const st=(r.data_statuses[k]||[]);
    const tag=st.includes('third_party')&&!st.includes('official')
      ?'<i class="ctag" style="border-color:#6b5a2b;color:#e0c168">三方</i>':'';
    return `<td>${tag}${fmt(v,0)}<small>${r.coverage[k]||0}/${r.company_count} 家有值</small></td>`;
  };
  $('lcTable').innerHTML=rows.map(r=>`<tr><td>${r.city}</td><td>${r.company_count}</td>`+
    ['market_cap','revenue','net_profit','net_assets','total_assets','total_liabilities'].map(k=>cell(r,k)).join('')+
    `<td>${r.derived.securitisation_rate!=null?r.derived.securitisation_rate.toFixed(1)+'%':'—'}`+
    `<small>${r.gdp_yi?'GDP '+fmt(r.gdp_yi,0)+' ('+r.gdp_period+')':'无 GDP'}</small></td>`+
    `<td>${r.derived.listed_revenue_to_gdp!=null?r.derived.listed_revenue_to_gdp.toFixed(1)+'%':'—'}</td></tr>`).join('')
    ||'<tr><td colspan="10">暂无数据，请先运行采集</td></tr>';
  const withRate=rows.filter(r=>r.derived.securitisation_rate!=null);
  if(withRate.length){
    charts['listed:rate']=new Chart($('lcRateChart'),{type:'bar',
      data:{labels:withRate.map(r=>r.city),datasets:[
        {label:'证券化率 %',data:withRate.map(r=>r.derived.securitisation_rate),backgroundColor:'#5795ff'},
        {label:'上市公司营收/GDP %',data:withRate.map(r=>r.derived.listed_revenue_to_gdp??null),backgroundColor:'#f5a623'}]},
      options:{responsive:true,maintainAspectRatio:false,
        scales:{x:{ticks:{color:'#8fa4bd'},grid:{color:'#14263a'}},
                y:{ticks:{color:'#8fa4bd',callback:v=>v+'%'},grid:{color:'#14263a'}}},
        plugins:{legend:{position:'bottom',labels:{color:'#cbd8e6'}}}}});
  }
  $('lcIndustry').innerHTML=rows.map(r=>`<tr><td>${r.city}</td><td>${
    (r.top_industries||[]).map(([n,c])=>`${n} <b>${c}</b>`).join('　')||'—'}</td></tr>`).join('');
  $('lcCaveats').innerHTML=lcPayload.caveats.map(x=>`<p>• ${x}</p>`).join('');
}
function initListed(){
  $('lcScope').onchange=loadListed;
  $('lcSort').onchange=()=>{if(lcPayload)renderListed()};
  $('lcReload').onclick=loadListed;
  loadListed();
}
