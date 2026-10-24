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
  $('#heroMembers').textContent = t.physical_members.toLocaleString('zh-CN');
  $('#commonDrift').textContent = `±${fmt(t.common_drift_percent,1)}%`;
  $('#axialCorrelation').textContent = fmt(t.axial_correlation,5);
  $('#speedup').textContent = t.runtime_comparison_valid ? `${fmt(t.speedup,2)}×` : '待评估';
  $('#commonCoverage').textContent = `${t.common_target_count}/${t.requested_targets ?? 'unknown'} 目标`;
  $('.engine').textContent = data.project.analysis_engine;
  $('#servicePort').textContent = `PORT ${window.location.port || 'default'}`;
  $('#dbSize').textContent = `${fmt(data.project.database_size_mb,0)} MB`;
  $('#memberMetrics').innerHTML = `
    <article class="metric-card"><span>参考峰值</span><strong>${fmt(m.peak_force_kn,1)}</strong><small> kN</small></article>
    <article class="metric-card"><span>曲线 NRMSE</span><strong>${fmt(m.nrmse_percent,2)}</strong><small> %</small></article>
    <article class="metric-card"><span>该算例峰前卸载</span><strong>${m.pre_yield_unloading_passed === true ? '通过' : m.pre_yield_unloading_passed === false ? '未通过' : 'unknown'}</strong><small> 不代表空间循环验证</small></article>
    <article class="metric-card"><span>参考网格</span><strong>${m.reference_divisions}</strong><small> 分段</small></article>`;
  $('#memberErrorText').textContent = `${fmt(m.nrmse_percent,2)}%`;
  $('#memberRange').textContent = `${m.screening.count ?? 'unknown'} 根 · λ ${fmt(m.screening.minimum_slenderness,0)}–${fmt(m.screening.maximum_slenderness,0)}`;
  $('#validationLengths').textContent = m.actual_validation.map(v=>`${fmt(v.length_m,2)} m`).join(' / ');
  $('#towerShearError').textContent = `${fmt(t.base_shear_error_percent,3)}%`;
  $('#towerAxialError').textContent = `${fmt(t.axial_nrmse_percent,3)}%`;
  $('#paperCount').textContent = `${data.project.paper_count} 篇 PDF`;
  $('#unloadingState').textContent = m.pre_yield_unloading_passed === true ? '该历史算例通过' : '未通过或unknown';
  $('#lastUpdated').textContent = `RESULT SNAPSHOT · ${data.project.result_updated ? new Date(data.project.result_updated*1000).toLocaleString('zh-CN') : 'unknown'}`;
  populateDiagnostics(data.diagnostics);
  populateFollowup(data.followup);
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
  const [pushover, cyclic] = await Promise.all([api('/api/pushover'), api('/api/cyclic')]);
  drawLineChart($('#pushoverChart'), pushover.series, {xLabel: pushover.x_label, yLabel: pushover.y_label});
  makeLegend($('#pushoverLegend'), Object.keys(pushover.series));
  attachChartTooltip($('#pushoverChart'), $('#pushoverTooltip'));
  drawLineChart($('#cyclicChart'), cyclic.series, {xLabel: cyclic.x_label, yLabel: cyclic.y_label});
  makeLegend($('#cyclicLegend'), Object.keys(cyclic.series));
  attachChartTooltip($('#cyclicChart'), $('#cyclicTooltip'));
  $('#targetTable').innerHTML = cyclic.targets.map((r,i)=>`<tr><td>目标 ${i+1} · ${r.displacement_mm>0?'+':''}${fmt(r.displacement_mm,1)} mm</td><td>${r.displacement_mm>0?'+':''}${fmt(r.displacement_mm,1)} mm</td><td>${fmt(r.equivalent_kn,2)} kN</td><td>${fmt(r.reference_kn,2)} kN</td><td>${r.error_percent>0?'+':''}${fmt(r.error_percent,3)}%</td></tr>`).join('');
}

function drawHeroTower() {
  const canvas=$('#heroTower'), {ctx,width,height}=setupCanvas(canvas); ctx.clearRect(0,0,width,height);
  const cx=width*.53, top=height*.12, bottom=height*.9;
  const levels=[0,.13,.28,.43,.58,.72,.85,1];
  const half=t=>width*(.06 + t*.22);
  ctx.strokeStyle='rgba(51,214,208,.7)'; ctx.lineWidth=1.15; ctx.shadowColor='rgba(51,214,208,.25)'; ctx.shadowBlur=8;
  const pt=(side,t)=>[cx+side*half(t), top+t*(bottom-top)];
  for (const side of [-1,1]) { ctx.beginPath(); levels.forEach((t,i)=>{const p=pt(side,t); i?ctx.lineTo(...p):ctx.moveTo(...p)}); ctx.stroke(); }
  levels.forEach((t,i)=>{ const l=pt(-1,t),r=pt(1,t); ctx.beginPath();ctx.moveTo(...l);ctx.lineTo(...r);ctx.stroke(); if(i){const prev=levels[i-1],lp=pt(-1,prev),rp=pt(1,prev);ctx.globalAlpha=.65;ctx.beginPath();ctx.moveTo(...lp);ctx.lineTo(...r);ctx.moveTo(...rp);ctx.lineTo(...l);ctx.stroke();ctx.globalAlpha=1;} });
  for (const t of [.05,.19,.35]) { const y=top+t*(bottom-top), span=width*(.18-t*.12); ctx.beginPath();ctx.moveTo(cx-span,y);ctx.lineTo(cx+span,y);ctx.stroke(); }
  ctx.shadowBlur=0; ctx.fillStyle='#33d6d0'; ctx.beginPath();ctx.arc(cx,top,3,0,Math.PI*2);ctx.fill();
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
  const item=(r,type)=>`<div class="resource-item"><span class="file-icon">${type}</span><div><b title="${r.name}">${r.name}</b><small>${r.type||`${fmt(r.size_mb,1)} MB`}</small></div><a href="/download?key=${encodeURIComponent(r.key)}" title="下载">↓</a></div>`;
  $('#reportList').innerHTML=data.reports.map(r=>item(r,'MD')).join('');$('#paperList').innerHTML=data.papers.map(r=>item(r,'PDF')).join('');
}

async function loadTianMaQu() {
  try {
    const data = await api('/api/tian-ma-qu');
    if (data.b1_diagnostics) {
      const b = data.b1_diagnostics;
      $('#tmqB1Status').textContent = `${b.initial_state_matches}/${b.initial_state_comparisons} 个历史风速工况重力初态与同网格模态一致。40→80段静态位移已较稳定；160阶对部分挂点位移仍有明显截断误差。查看逐风向、逐位置的通过与未通过项目。`;
      $('#tmqB1Panel').classList.remove('hidden');
    }
    if (data.modal_analysis) {
      const m = data.modal_analysis, c = m.cases[m.primary_case], matched = m.tower_matches[m.primary_case];
      $('#tmqModalStatus').textContent = `导线最低频率 ${fmt(c.modes[0].frequency_Hz,5)} Hz；塔身扭转 / X侧摆 / Y侧摆 ${matched.map(v=>fmt(v.frequency_Hz,4)).join(' / ')} Hz。采用80段/档结果，并保留20、40段对照；横向耦合参与分配仍有网格敏感性。`;
      $('#tmqModalImage').src = '/tmq/modal_results/frequency_comparison.svg';
      $('#tmqModalPanel').classList.remove('hidden');
    }
    if (data.wind_speed) {
      const w = data.wind_speed, valid = w.cases.filter(c => c.evidence_valid).length;
      $('#tmqSpeedStatus').textContent = `${w.workflow_status === 'complete' ? '本批计算结束' : '复核进行中'} · ${w.coarse_case_count} 个初始工况，已收录 ${w.cases.length} 次计算（含扩展和复核）· ${valid} 次记录与平衡检查通过 · 首次压屈、曲线最大荷载和数值停止点分别列出。`;
      $('#tmqSpeedImage').src = '/tmq/wind_speed_results/wind_response.svg';
      $('#tmqSpeedPanel').classList.remove('hidden');
    }
    if (data.directional_wind) {
      const w = data.directional_wind, completed = w.cases.filter(c => c.passed).length;
      $('#tmqWindStatus').textContent = `${completed}/${w.case_count} 个工况通过 · 0°/30°/45°/90° · 单塔与一塔四档分别计算 · 每例独立重力和材料历史。状态：${w.passed ? '加载与小幅接入验收通过' : '尚有未通过工况'}；不等于工程气动力标定通过。`;
      $('#tmqWindImage').src = '/tmq/directional_results_v2/small_cycles.svg';
      $('#tmqWindPanel').classList.remove('hidden');
    }
    if (data.weakness) {
      const w = data.weakness, p = w.primary_max_isdr_y, g = w.geometric_max_isdr_y;
      $('#tmqWeaknessStatus').textContent = `首批压屈位于 33 m 塔身水平杆（825、828、917、920）。修正位移角最大：节点转角法 ${p.z_lower}–${p.z_upper} m，${fmt(100*p.isdr_y_abs_max,4)}%；几何拟合法 ${g.z_lower}–${g.z_upper} m，${fmt(100*g.geometric_isdr_y_abs_max,4)}%。新增记录重跑 ${w.run.accepted_steps} 步，与原响应${w.replay_check.passed ? '逐步一致' : '尚未核对一致'}。`;
      $('#tmqWeaknessImage').src = '/tmq/weakness_results/weakness_locations.svg';
      $('#tmqWeaknessPanel').classList.remove('hidden');
    }
    if (data.full_tower) {
      const t = data.full_tower.run, extended = data.full_tower.extended_run;
      $('#tmqTowerStatus').textContent = `${t.elements} 根杆件 · ${t.completed_targets}/${t.targets_drift.length} 个目标 · ${t.accepted_steps} 个接受步 · 状态 ${t.status} · 曾压屈 ${t.max_buckled_members || 0} 根 · 曾进入拉向强化 ${t.max_tensile_yield_members || 0} 根。` + (extended ? ` 更大幅值试算：${extended.status}，实际停止漂移 ${(100*extended.last_point.drift_ratio).toFixed(4)}%，原因 ${extended.stop_reason}。` : '');
      $('#tmqTowerImage').src = '/tmq/tower_results/full_tower_hysteresis.svg';
      $('#tmqTowerPanel').classList.remove('hidden');
    }
    if (!data.available) { $('#tmqStatus').textContent = data.reason; return; }
    const s = data.summary, cases = s.cases;
    const native = cases.map(c => c.opensees).filter(Boolean);
    const completed = native.reduce((total, c) => total + (c.completed_steps || 0), 0);
    const requested = native.reduce((total, c) => total + (c.requested_steps || 0), 0);
    const allChecked = cases.length > 0 && cases.every(c => c.checks?.passed === true && c.opensees?.passed === true);
    const metrics = [
      ['管试件参数组', String(cases.length), 'P102 两组参数行 + P89'],
      ['OpenSees 总步数', native.length ? `${fmt(completed,0)} / ${fmt(requested,0)}` : '未运行', '各工况完成度见下表'],
      ['数值与适配检查', allChecked ? '全部通过' : '未全部通过', '不等于原试验标定通过'],
      ['力学验证身份', '文献原型', '尚未完成原试验定量标定']
    ];
    $('#tmqMetrics').innerHTML = metrics.map(([title,value,note]) => `<article class="metric-card"><span>${escapeHtml(title)}</span><strong>${escapeHtml(value)}</strong><small>${escapeHtml(note)}</small></article>`).join('');
    const ids = new Set(['p102_row_a','p102_row_b','p89_pf']);
    const magnitude = value => typeof value === 'number' ? fmt(Math.abs(value),2) : 'unknown';
    $('#tmqCases').innerHTML = cases.map(c => {
      const id = c.case?.key, n = c.opensees;
      const links = ids.has(id) ? `<a href="/tmq/results/${id}/history.csv" download>材料 CSV</a><a href="/tmq/results/${id}/events.json" download>折点</a>${n ? `<a href="/tmq/results/${id}/opensees_history.csv" download>OpenSees CSV</a>` : ''}` : '不可用';
      const coverage = n ? `${n.completed_steps} / ${n.requested_steps}${n.complete === true ? ' · 完成' : ' · 未完成'}` : '未运行';
      const check = c.checks?.passed === true && n?.passed === true ? '通过（非试验标定）' : '未全部通过';
      return `<tr><td>${escapeHtml(c.case?.label)}</td><td>${escapeHtml(coverage)}</td><td>${magnitude(c.first_buckling_kN)}</td><td>${magnitude(c.subsequent_buckling_kN)}</td><td>${fmt(c.peak_tension_kN,2)}</td><td>${escapeHtml(check)}</td><td>${links}</td></tr>`;
    }).join('');
    $('#tmqStatus').textContent = `结果生成：${s.created_utc || '未知'} · ${s.complete === true ? '当前批次计算及数值检查完成' : '当前批次未全部完成'} · 独立单杆，不是全塔结果。`;
    $('#tmqHysteresis').src = '/tmq/results/full_hysteresis.svg';
    $('#tmqContent').classList.remove('hidden');
  } catch (error) {
    $('#tmqStatus').textContent = `Tian–Ma–Qu 结果读取失败：${error.message}`;
    $('#tmqContent').classList.add('hidden');
  }
}

function setupInteractions() {
  const observer=new IntersectionObserver(entries=>entries.forEach(e=>e.target.classList.toggle('visible',e.isIntersecting)),{threshold:.08});$$('.reveal').forEach(el=>observer.observe(el));
  const navObserver=new IntersectionObserver(entries=>entries.forEach(e=>{if(e.isIntersecting){$$('.nav-link').forEach(a=>a.classList.toggle('active',a.getAttribute('href')===`#${e.target.id}`));}}),{rootMargin:'-20% 0px -65%'});['overview','tianmaqu','member','cyclic','forces','resources'].forEach(id=>navObserver.observe(document.getElementById(id)));
  $('#menuButton').addEventListener('click',()=>$('.sidebar').classList.toggle('open'));$$('.nav-link').forEach(a=>a.addEventListener('click',()=>$('.sidebar').classList.remove('open')));
  $('#forceMode').addEventListener('change',()=>{$('#snapshotControls').classList.toggle('hidden',$('#forceMode').value!=='snapshot');$('#envelopeControls').classList.toggle('hidden',$('#forceMode').value!=='envelope');});
  $('#forceTime').addEventListener('input',()=>$('#forceTimeOutput').textContent=$('#forceTime').value);
  $('#diagnosticLoad').addEventListener('click',loadDiagnostic);
  $('#diagnosticCase').addEventListener('change',loadDiagnostic);
  $('#diagnosticMember').addEventListener('change',loadDiagnostic);
  $('#forceModel').addEventListener('change',async()=>{forceMeta=null;await loadForceMeta();await loadForceData();});$('#forceLoad').addEventListener('click',loadForceData);$('#forceProjection').addEventListener('change',drawForceMap);
  const map=$('#forceMap'),tip=$('#mapTooltip');map.addEventListener('mousemove',e=>{const hit=findMapMember(e);if(!hit){tip.style.display='none';return;}const m=hit.member,rect=map.getBoundingClientRect();tip.style.display='block';tip.style.left=`${Math.min(rect.width-165,hit.x+12)}px`;tip.style.top=`${Math.max(8,hit.y-62)}px`;tip.innerHTML=`<b>杆件 #${m.element}</b><br>${m.section}<br>${fmt(forceUnitValue(m.value),3)} ${componentMeta().unit}`;});map.addEventListener('mouseleave',()=>tip.style.display='none');map.addEventListener('click',e=>{const hit=findMapMember(e);if(hit)selectMember(hit.member).catch(console.error);});
  let resizeTimer;window.addEventListener('resize',()=>{clearTimeout(resizeTimer);resizeTimer=setTimeout(()=>{drawHeroTower();if(forcePayload)drawForceMap();loadCharts().catch(console.error);if(selectedMapMember)selectMember(selectedMapMember).catch(console.error);},180);});
}

async function boot() {
  setupInteractions(); drawHeroTower();
  try { const overview=await api('/api/overview');populateOverview(overview); } catch(error) { console.error(error); $('#diagnosticCases').textContent=error.message; }
  await Promise.allSettled([loadCharts(),loadResources(),loadDiagnostic(),loadTianMaQu()]);
  await loadForceData();
}
boot();
