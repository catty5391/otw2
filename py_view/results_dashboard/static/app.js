const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const COLORS = { reference: '#33d6d0', equivalent: '#ff9d5c', perry: '#8a78ff', steel: '#667989' };
const SERIES_LABELS = {
  segmented_reference: '分段参考',
  equivalent: '等效材料',
  equivalent_calibrated: '标定等效',
  equivalent_perry: 'Perry 试算',
  perfect_steel_corot_truss: '理想钢杆'
};

let overviewData = null;
let forceMeta = null;
let forcePayload = null;
let selectedMapMember = null;
let mapScreenSegments = [];

async function api(path) {
  const response = await fetch(path);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || `请求失败：${response.status}`);
  return data;
}

function fmt(value, digits = 2) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return 'unknown';
  return Number(value).toLocaleString('zh-CN', { maximumFractionDigits: digits, minimumFractionDigits: digits });
}

function escapeHtml(value) { return String(value ?? 'unknown').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }

const QUALITY_LABELS = { completed:'计算完成', nonconverged:'数值停止', failed:'未通过', validated:'范围内已验证', unvalidated:'未验证', unknown:'未知', legacy_unknown:'旧记录未审核', in_range:'已审核域内', out_of_range:'越界', not_evaluated:'物理极限未评估' };
function qualityText(quality) { return `计算：${QUALITY_LABELS[quality.execution_status] || quality.execution_status} · 验证：${QUALITY_LABELS[quality.validation_status] || quality.validation_status} · 范围：${QUALITY_LABELS[quality.domain_status] || quality.domain_status} · 极限：${QUALITY_LABELS[quality.limit_state_status] || quality.limit_state_status}`; }

function seriesColor(name) {
  if (name === 'segmented_reference') return COLORS.reference;
  if (name === 'equivalent' || name === 'equivalent_calibrated') return COLORS.equivalent;
  if (name === 'equivalent_perry') return COLORS.perry;
  return COLORS.steel;
}

function setupCanvas(canvas) {
  const rect = canvas.getBoundingClientRect();
  const ratio = Math.min(window.devicePixelRatio || 1, 2);
  canvas.width = Math.max(1, Math.round(rect.width * ratio));
  canvas.height = Math.max(1, Math.round(rect.height * ratio));
  const ctx = canvas.getContext('2d');
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  return { ctx, width: rect.width, height: rect.height, ratio };
}

function drawLineChart(canvas, data, options = {}) {
  canvas._plotData=data;canvas._plotOptions=options;
  const { ctx, width, height } = setupCanvas(canvas);
  const padding = options.compact ? { l: 42, r: 12, t: 12, b: 30 } : { l: 58, r: 22, t: 18, b: 43 };
  const all = Object.values(data).flat();
  if (!all.length) return;
  let xmin = Math.min(...all.map(p => p.x));
  let xmax = Math.max(...all.map(p => p.x));
  let ymin = Math.min(...all.map(p => p.y));
  let ymax = Math.max(...all.map(p => p.y));
  if (options.includeZero !== false) { xmin = Math.min(0, xmin); ymin = Math.min(0, ymin); ymax = Math.max(0, ymax); }
  const xd = xmax - xmin || 1, yd = ymax - ymin || 1;
  xmin -= xd * .035; xmax += xd * .035; ymin -= yd * .08; ymax += yd * .08;
  const sx = x => padding.l + (x - xmin) / (xmax - xmin) * (width - padding.l - padding.r);
  const sy = y => height - padding.b - (y - ymin) / (ymax - ymin) * (height - padding.t - padding.b);

  ctx.clearRect(0, 0, width, height);
  ctx.lineWidth = 1; ctx.font = options.compact ? '8px ui-monospace' : '9px ui-monospace'; ctx.fillStyle = '#587080';
  for (let i = 0; i <= 5; i++) {
    const y = padding.t + i * (height - padding.t - padding.b) / 5;
    const val = ymax - i * (ymax - ymin) / 5;
    ctx.strokeStyle = 'rgba(157,188,211,.11)'; ctx.beginPath(); ctx.moveTo(padding.l, y); ctx.lineTo(width - padding.r, y); ctx.stroke();
    ctx.textAlign = 'right'; ctx.fillText(fmt(val, Math.abs(val) < 10 ? 2 : 0), padding.l - 8, y + 3);
  }
  for (let i = 0; i <= 5; i++) {
    const x = padding.l + i * (width - padding.l - padding.r) / 5;
    const val = xmin + i * (xmax - xmin) / 5;
    ctx.strokeStyle = 'rgba(157,188,211,.07)'; ctx.beginPath(); ctx.moveTo(x, padding.t); ctx.lineTo(x, height - padding.b); ctx.stroke();
    ctx.textAlign = 'center'; ctx.fillText(fmt(val, Math.abs(val) < 10 ? 2 : 0), x, height - padding.b + 16);
  }
  if (xmin <= 0 && xmax >= 0) { ctx.strokeStyle = 'rgba(237,245,247,.22)'; ctx.beginPath(); ctx.moveTo(sx(0), padding.t); ctx.lineTo(sx(0), height-padding.b); ctx.stroke(); }
  if (ymin <= 0 && ymax >= 0) { ctx.strokeStyle = 'rgba(237,245,247,.22)'; ctx.beginPath(); ctx.moveTo(padding.l, sy(0)); ctx.lineTo(width-padding.r, sy(0)); ctx.stroke(); }
  for (const [name, points] of Object.entries(data)) {
    ctx.beginPath();
    points.forEach((point, index) => { const x=sx(point.x), y=sy(point.y); index ? ctx.lineTo(x,y) : ctx.moveTo(x,y); });
    ctx.strokeStyle = seriesColor(name); ctx.globalAlpha = name === 'perfect_steel_corot_truss' ? .45 : .95; ctx.lineWidth = name === 'segmented_reference' ? 2.2 : 1.7; ctx.stroke(); ctx.globalAlpha = 1;
  }
  if (!options.compact) {
    ctx.fillStyle = '#718a9b'; ctx.font = '9px system-ui'; ctx.textAlign = 'center';
    if (options.xLabel) ctx.fillText(options.xLabel, (padding.l + width-padding.r)/2, height-5);
    if (options.yLabel) { ctx.save(); ctx.translate(13, (padding.t+height-padding.b)/2); ctx.rotate(-Math.PI/2); ctx.fillText(options.yLabel, 0, 0); ctx.restore(); }
  }
  canvas._chart = { data, sx, sy, xmin, xmax, ymin, ymax, padding };
}

function attachChartTooltip(canvas, tooltip) {
  canvas.addEventListener('mousemove', event => {
    const chart = canvas._chart; if (!chart) return;
    const rect = canvas.getBoundingClientRect(); const mx = event.clientX - rect.left; const my = event.clientY - rect.top;
    let closest = null;
    for (const [name, points] of Object.entries(chart.data)) {
      const step = Math.max(1, Math.floor(points.length / 350));
      for (let i=0; i<points.length; i+=step) {
        const p=points[i], d=Math.hypot(chart.sx(p.x)-mx, chart.sy(p.y)-my);
        if (!closest || d<closest.d) closest={name,p,d};
      }
    }
    if (closest && closest.d < 28) {
      tooltip.style.display='block'; tooltip.style.left=`${Math.min(rect.width-145,mx+13)}px`; tooltip.style.top=`${Math.max(8,my-55)}px`;
      tooltip.innerHTML=`<b style="color:${seriesColor(closest.name)}">${SERIES_LABELS[closest.name]||closest.name}</b><br>x ${fmt(closest.p.x,2)}<br>y ${fmt(closest.p.y,2)}`;
    } else tooltip.style.display='none';
  });
  canvas.addEventListener('mouseleave', () => tooltip.style.display='none');
}

function makeLegend(target, names) {
  target.innerHTML = names.map(name => `<span><i style="background:${seriesColor(name)}"></i>${SERIES_LABELS[name]||name}</span>`).join('');
}

function populateOverview(data) {
  overviewData = data; const m=data.member, t=data.tower;
  const setText=(selector,value)=>{const node=$(selector);if(node)node.textContent=value;};
  setText('#commonCoverage',`${t.common_target_count}/${t.requested_targets ?? 'unknown'} 目标`);
  if ($('#memberMetrics')) $('#memberMetrics').innerHTML = `
    <article class="metric-card"><span>参考峰值</span><strong>${fmt(m.peak_force_kn,1)}</strong><small> kN</small></article>
    <article class="metric-card"><span>曲线 NRMSE</span><strong>${fmt(m.nrmse_percent,2)}</strong><small> %</small></article>
    <article class="metric-card"><span>该算例峰前卸载</span><strong>${m.pre_yield_unloading_passed === true ? '通过' : m.pre_yield_unloading_passed === false ? '未通过' : 'unknown'}</strong><small> 不代表空间循环验证</small></article>
    <article class="metric-card"><span>参考网格</span><strong>${m.reference_divisions}</strong><small> 分段</small></article>`;
  setText('#memberErrorText',`${fmt(m.nrmse_percent,2)}%`);
  setText('#memberRange',`${m.screening.count ?? 'unknown'} 根 · λ ${fmt(m.screening.minimum_slenderness,0)}–${fmt(m.screening.maximum_slenderness,0)}`);
  setText('#validationLengths',m.actual_validation.map(v=>`${fmt(v.length_m,2)} m`).join(' / '));
  setText('#towerShearError',`${fmt(t.base_shear_error_percent,3)}%`);
  setText('#towerAxialError',`${fmt(t.axial_nrmse_percent,3)}%`);
  setText('#unloadingState',m.pre_yield_unloading_passed === true ? '该历史算例通过' : '未通过或unknown');
}

function populateDiagnostics(data) {
  $('#diagnosticCases').innerHTML = data.cases.map(item => {
    if (!item.available) return `<article class="quality-case"><h4>${escapeHtml(item.label)}</h4><p>缺少结果文件</p></article>`;
    const q = item.quality, summary = item.summary;
    const bounds = item.domain_checks.map(row => `#${row.member} 压应变 ${fmt(row.maximum_compression_strain * 100,3)}% / 骨架终点 ${fmt(row.calibrated_compression_limit * 100,3)}%`).join('<br>');
    const first = Object.values(q.first_out_of_domain_by_member || {}).map(event => `#${escapeHtml(event.member_id)} 首次越界 step ${event.accepted_step} / stage ${escapeHtml(event.stage_id)}`).join('<br>');
    return `<article class="quality-case ${q.validation_status === 'failed' || q.domain_status === 'out_of_range' ? 'quality-warning' : ''}"><h4>${escapeHtml(item.label)}</h4><strong>${summary.completed_targets}/${summary.requested_targets} 目标 · ${summary.steps} 步</strong><p>${escapeHtml(qualityText(q))}</p><p>${bounds}${first ? '<br>' + first : ''}</p><small>${escapeHtml(q.quality_flags.join(' / ') || '未取得独立验证')}<br>引擎 ${escapeHtml(item.engine_version)} · 统计准入 ${q.eligible_for_fragility ? '通过' : '拒绝'}</small></article>`;
  }).join('');
}

function populateFollowup(data) {
  $('#followupRuns').innerHTML = data.runs.length ? data.runs.map(run => {
    const q = run.quality, counts = q.detail_counts || {}, first = q.first_out_of_domain_event;
    const firstText = first ? `首次越界：#${first.member_id} · step ${first.accepted_step} · stage ${first.stage_id ?? 'unknown'} · ${first.quantity}=${fmt(first.value,6)}` : '首次越界：无已登记事件';
    return `<article class="followup-run"><b>${escapeHtml(run.id)}</b><p>${escapeHtml(qualityText(q))}</p><small>用途：${escapeHtml(q.purpose)} · 覆盖 ${q.coverage.completed}/${q.coverage.requested ?? 'unknown'} ${escapeHtml(q.coverage.unit)} · 统计准入 ${q.eligible_for_fragility ? '通过' : '拒绝'}</small><p>${escapeHtml(q.quality_flags.join(' / ') || '无已登记质量标记')}</p><small>${escapeHtml(firstText)}<br>域对象 ${counts.member_domains ?? 'unknown'} · 已观测域 ${counts.observed_domains ?? 'unknown'} · 域事件 ${counts.domain_events ?? 'unknown'} · 发生首越界的杆件 ${counts.first_out_of_domain_members ?? 'unknown'}<br>此处为摘要；完整权威证据：${escapeHtml(run.manifest)}</small></article>`;
  }).join('') : '尚无带清单的新试验。';
}

async function loadDiagnostic() {
  const caseId = $('#diagnosticCase').value, member = $('#diagnosticMember').value;
  $('#diagnosticMemberInfo').textContent = '读取历史已提交状态…';
  try {
    const [curve, history] = await Promise.all([api(`/api/diagnostics/curve?case=${encodeURIComponent(caseId)}`), api(`/api/diagnostics/member?case=${encodeURIComponent(caseId)}&member=${member}`)]);
    drawLineChart($('#diagnosticCurveChart'), {equivalent:curve.series}, {xLabel:curve.x_label,yLabel:curve.y_label});
    drawLineChart($('#diagnosticMemberChart'), {equivalent:history.points.map(p=>({x:p.step,y:p.force_kn}))}, {xLabel:'已提交步',yLabel:'关键杆轴力 / kN'});
    drawLineChart($('#diagnosticStrainChart'), {equivalent:history.points.map(p=>({x:p.step,y:p.strain * 100}))}, {xLabel:'已提交步',yLabel:'等效应变 / %'});
    const meta = history.metadata || {};
    $('#diagnosticMemberInfo').textContent = `原杆 #${member} · ${meta.section_name || 'unknown'} · ${meta.length ? fmt(meta.length,3) + ' m' : 'unknown'} · 端点 ${JSON.stringify(meta.node_i_coord)} → ${JSON.stringify(meta.node_j_coord)} · 轴向切线 dN/dε 单位N，除以杆长后才是N/m。`;
    const points = history.same_stage_reference_checkpoints;
    $('#diagnosticReference').textContent = points.length ? points.map(p=>`−0.6%目标：等效 ${fmt(p.equivalent_force_N/1000,3)} kN，四段参考首段 ${fmt(p.reference_first_segment_force_N/1000,3)} kN，压力量值差 ${fmt(p.compression_magnitude_difference_percent,2)}%。`).join(' ') + ' 其余阶段未提供参考全历程，未插值生成。' : '当前案例没有同阶段参考检查点。Elastic消融仅用于查因；诊断表只含轴向通道，没有节点位移历史动画。';
  } catch(error) { $('#diagnosticMemberInfo').textContent = error.message; }
}

async function loadCharts() {
  if ($('#pushoverChart')) {
    const data=await api('/api/pushover');
    drawLineChart($('#pushoverChart'),data.series,{xLabel:data.x_label,yLabel:data.y_label});
    makeLegend($('#pushoverLegend'),Object.keys(data.series));
    attachChartTooltip($('#pushoverChart'),$('#pushoverTooltip'));
  }
  if ($('#cyclicChart')) {
    const data=await api('/api/cyclic');
    drawLineChart($('#cyclicChart'),data.series,{xLabel:data.x_label,yLabel:data.y_label});
    makeLegend($('#cyclicLegend'),Object.keys(data.series));
    attachChartTooltip($('#cyclicChart'),$('#cyclicTooltip'));
    $('#targetTable').innerHTML=data.targets.map((r,i)=>`<tr><td>目标 ${i+1} · ${r.displacement_mm>0?'+':''}${fmt(r.displacement_mm,1)} mm</td><td>${fmt(r.displacement_mm,1)} mm</td><td>${fmt(r.equivalent_kn,2)} kN</td><td>${fmt(r.reference_kn,2)} kN</td><td>${fmt(r.error_percent,3)}%</td></tr>`).join('');
  }
}

function componentMeta() { return forceMeta.components[$('#forceComponent').value]; }
function forceUnitValue(value) { return value * componentMeta().scale; }
function signedColor(value, scale, envelope=false) {
  const t=Math.min(1,Math.abs(value)/(scale||1));
  if(envelope) return `rgb(${Math.round(183+72*t)},${Math.round(200-112*t)},${Math.round(207-70*t)})`;
  const zero=[183,200,207], end=value<0?[60,143,255]:[255,80,107];
  return `rgb(${zero.map((v,i)=>Math.round(v+(end[i]-v)*t)).join(',')})`;
}

function drawForceMap() {
  if(!forcePayload) return;
  const canvas=$('#forceMap'), {ctx,width,height}=setupCanvas(canvas), projection=$('#forceProjection').value;
  const members=forcePayload.members, coords=members.flatMap(m=>[m.a,m.b]);
  const xi=projection==='xz'?0:1, yi=2;
  const minX=Math.min(...coords.map(p=>p[xi])),maxX=Math.max(...coords.map(p=>p[xi])),minY=Math.min(...coords.map(p=>p[yi])),maxY=Math.max(...coords.map(p=>p[yi]));
  const pad={l:42,r:42,t:34,b:48}, dx=maxX-minX||1,dy=maxY-minY||1;
  const scale=Math.min((width-pad.l-pad.r)/dx,(height-pad.t-pad.b)/dy), ox=(width-dx*scale)/2-minX*scale, oy=height-pad.b+minY*scale;
  const point=p=>[ox+p[xi]*scale,oy-p[yi]*scale];
  ctx.clearRect(0,0,width,height); mapScreenSegments=[];
  const colorScale=forcePayload.scale.p98||forcePayload.scale.maximum||1;
  const sorted=[...members].sort((a,b)=>Math.abs(a.value)-Math.abs(b.value));
  sorted.forEach(m=>{const a=point(m.a),b=point(m.b), selected=selectedMapMember&&selectedMapMember.element===m.element;ctx.beginPath();ctx.moveTo(...a);ctx.lineTo(...b);ctx.strokeStyle=selected?'#ffffff':signedColor(m.value,colorScale,forcePayload.mode==='envelope');ctx.globalAlpha=selected?1:.88;ctx.lineWidth=selected?3.5:Math.max(.7,Math.min(1.8,scale*.009));ctx.stroke();mapScreenSegments.push({a,b,member:m});});ctx.globalAlpha=1;
  ctx.fillStyle='#587080';ctx.font='9px ui-monospace';ctx.textAlign='right';ctx.fillText(`${maxY.toFixed(1)} m`,width-12,pad.t+3);ctx.fillText(`${minY.toFixed(1)} m`,width-12,height-pad.b);
  const unit=componentMeta().unit, limit=forceUnitValue(colorScale); $('#colorMin').textContent=forcePayload.mode==='envelope'?'0':`−${fmt(limit,1)} ${unit}`;$('#colorMax').textContent=`${fmt(limit,1)} ${unit}`;
  $('#forceMemberCount').textContent=`${members.length.toLocaleString('zh-CN')} 根物理杆件`;
  $('#forceViewLabel').textContent=forcePayload.mode==='snapshot'?`${SERIES_LABELS[forcePayload.model]} · STEP ${forcePayload.step}`:`${SERIES_LABELS[forcePayload.model]} · ${forcePayload.actual_start}—${forcePayload.actual_end}`;
}

function distanceToSegment(px,py,a,b){const dx=b[0]-a[0],dy=b[1]-a[1],l2=dx*dx+dy*dy;if(!l2)return Math.hypot(px-a[0],py-a[1]);const t=Math.max(0,Math.min(1,((px-a[0])*dx+(py-a[1])*dy)/l2));return Math.hypot(px-(a[0]+t*dx),py-(a[1]+t*dy));}
function findMapMember(event) { const rect=$('#forceMap').getBoundingClientRect(),x=event.clientX-rect.left,y=event.clientY-rect.top;let hit=null;for(const segment of mapScreenSegments){const d=distanceToSegment(x,y,segment.a,segment.b);if(!hit||d<hit.d)hit={...segment,d,x,y};}return hit&&hit.d<8?hit:null; }

async function selectMember(member) {
  selectedMapMember=member;drawForceMap();$('#inspectorEmpty').classList.add('hidden');$('#inspectorContent').classList.remove('hidden');
  $('#selectedMember').textContent=`物理杆件 #${member.element}`;$('#selectedSection').textContent=member.section;$('#selectedNodes').textContent=`${member.node_i} → ${member.node_j}`;$('#selectedValue').textContent=`${fmt(forceUnitValue(member.value),3)} ${componentMeta().unit}`;
  const params=new URLSearchParams({model:$('#forceModel').value,component:$('#forceComponent').value,element:member.element});
  const history=await api(`/api/internal-force/history?${params}`); const points=history.points.map(p=>({x:p.x,y:forceUnitValue(p.y)}));
  drawLineChart($('#memberHistoryChart'), {equivalent:points}, {compact:true});
}

async function loadForceMeta() {
  const model=$('#forceModel').value; forceMeta=await api(`/api/internal-force/meta?model=${model}`);const max=forceMeta.times.at(-1)?.time||0;
  $('#forceTime').max=max;$('#forceTime').value=Math.min(Number($('#forceTime').value),max);$('#forceTimeOutput').textContent=$('#forceTime').value;$('#forceStart').max=max;$('#forceEnd').max=max;$('#forceEnd').value=max;
}
async function loadForceData() {
  $('#forceLoading').classList.remove('hidden');
  try { if(!forceMeta||forceMeta.model!==$('#forceModel').value) await loadForceMeta();const common=new URLSearchParams({model:$('#forceModel').value,component:$('#forceComponent').value});if($('#forceMode').value==='snapshot'){common.set('time',$('#forceTime').value);forcePayload=await api(`/api/internal-force/snapshot?${common}`);}else{common.set('start',$('#forceStart').value);common.set('end',$('#forceEnd').value);forcePayload=await api(`/api/internal-force/envelope?${common}`);}selectedMapMember=null;$('#inspectorEmpty').classList.remove('hidden');$('#inspectorContent').classList.add('hidden');drawForceMap();} catch(error){$('#forceViewLabel').textContent=error.message;} finally{$('#forceLoading').classList.add('hidden');}
}

async function loadResources() {
  const data=await api('/api/resources');
  $('#paperCount').textContent=`${data.papers.length} 篇 PDF`;
  const item=(r,type)=>`<div class="resource-item"><span class="file-icon">${type}</span><div><b title="${escapeHtml(r.name)}">${escapeHtml(r.name)}</b><small>${r.type||`${fmt(r.size_mb,1)} MB`}</small></div><a href="/download?key=${encodeURIComponent(r.key)}" title="下载">↓</a></div>`;
  $('#reportList').innerHTML=data.reports.map(r=>item(r,'MD')).join('');$('#paperList').innerHTML=data.papers.map(r=>item(r,'PDF')).join('');
}

function setupInteractions() {
  if ($('#diagnosticLoad')) {
    for (const [selector,event] of [['#diagnosticLoad','click'],['#diagnosticCase','change'],['#diagnosticMember','change']]) $(selector).addEventListener(event,loadDiagnostic);
  }
  if ($('#forceMap')) {
    $('#forceMode').addEventListener('change',()=>{$('#snapshotControls').classList.toggle('hidden',$('#forceMode').value!=='snapshot');$('#envelopeControls').classList.toggle('hidden',$('#forceMode').value!=='envelope');});
    $('#forceTime').addEventListener('input',()=>$('#forceTimeOutput').textContent=$('#forceTime').value);
    $('#forceModel').addEventListener('change',async()=>{forceMeta=null;await loadForceData();});
    $('#forceLoad').addEventListener('click',loadForceData);$('#forceProjection').addEventListener('change',drawForceMap);
    const map=$('#forceMap'),tip=$('#mapTooltip');
    map.addEventListener('mousemove',e=>{const hit=findMapMember(e);if(!hit){tip.style.display='none';return;}const m=hit.member,rect=map.getBoundingClientRect();tip.style.display='block';tip.style.left=`${Math.min(rect.width-165,hit.x+12)}px`;tip.style.top=`${Math.max(8,hit.y-62)}px`;tip.innerHTML=`<b>杆件 #${m.element}</b><br>${escapeHtml(m.section)}<br>${fmt(forceUnitValue(m.value),3)} ${componentMeta().unit}`;});
    map.addEventListener('mouseleave',()=>tip.style.display='none');
    map.addEventListener('click',e=>{const hit=findMapMember(e);if(hit)selectMember(hit.member).catch(showPageError);});
  }
  let resizeTimer;
  window.addEventListener('resize',()=>{clearTimeout(resizeTimer);resizeTimer=setTimeout(()=>{
    if(forcePayload)drawForceMap();
    $$('canvas').forEach(canvas=>{if(canvas._plotData)drawLineChart(canvas,canvas._plotData,canvas._plotOptions);});
  },180);});
}

function showPageError(error) {
  const target=$('#pageError');target.hidden=false;target.textContent=`读取本模块数据失败：${error.message||error}`;
}

async function boot() {
  setupInteractions();
  const page=document.body.dataset.page, tasks=[];
  if (page==='member'||page==='cyclic') tasks.push(api('/api/overview').then(populateOverview),loadCharts());
  if (page==='resources') tasks.push(loadResources());
  if (page==='diagnostics') tasks.push(api('/api/diagnostics').then(populateDiagnostics),loadDiagnostic());
  if (page==='followup') tasks.push(api('/api/followup').then(populateFollowup));
  if (page==='forces') tasks.push(loadForceData());
  const results=await Promise.allSettled(tasks);
  results.filter(result=>result.status==='rejected').forEach(result=>showPageError(result.reason));
  document.body.dataset.ready=results.every(result=>result.status==='fulfilled')?'true':'error';
}
boot();
