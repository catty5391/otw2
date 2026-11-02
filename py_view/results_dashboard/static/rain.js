/* Read-only presentation of independently generated rain-loading evidence. */
(() => {
  'use strict';
  const root = '/rain-loading/results/';
  const byId = id => document.getElementById(id);
  const list = value => Array.isArray(value) ? value : [];
  const string = value => {
    if (value == null) return '—';
    if (typeof value === 'number' && Number.isFinite(value)) {
      if (Number.isInteger(value)) return String(value);
      if (Math.abs(value) < 1e-4) return value.toExponential(5).replace(/\.?0+e/, 'e');
      return String(Number(value.toPrecision(6)));
    }
    return typeof value === 'object' ? JSON.stringify(value) : String(value);
  };
  const node = (tag, text, className) => {
    const element = document.createElement(tag);
    if (text !== undefined) element.textContent = string(text);
    if (className) element.className = className;
    return element;
  };
  const relativeArtifact = file => {
    const name = string(file).replace(/^results\//, '');
    return /^[A-Za-z0-9_-]+\.(?:png|svg|pdf|md|json|csv)$/.test(name) ? root + encodeURIComponent(name) : null;
  };
  const externalURL = value => {
    try {const url = new URL(value); return ['http:', 'https:'].includes(url.protocol) ? url.href : null;}
    catch {return null;}
  };
  function table(title, columns, rows, className = '') {
    const block = node('div', undefined, 'rain-table-block');
    if (title) block.append(node('h3', title));
    const scroll = node('div', undefined, 'rain-table-scroll');
    const tab = node('table', undefined, className);
    const head = node('thead'), header = node('tr'), body = node('tbody');
    for (const column of columns) {
      const cell = node('th', column.label ?? column.key);cell.scope = 'col';header.append(cell);
    }
    head.append(header);tab.append(head);
    for (const row of rows) {
      const tr = node('tr');
      for (const column of columns) {
        const td = node('td');
        const value = row[column.key];
        if (value instanceof Node) td.append(value);
        else td.textContent = column.key === 'component' ? ({tower:'塔身',conductor:'导线'}[value] || string(value)) : string(value);
        tr.append(td);
      }
      body.append(tr);
    }
    tab.append(body);scroll.append(tab);block.append(scroll);return block;
  }
  async function boot() {
    try {
      const response = await fetch(root + 'summary.json', {cache:'no-store'});
      if (!response.ok) throw new Error(`结果摘要尚不可用（HTTP ${response.status}）`);
      const data = await response.json();
      if (!data || typeof data !== 'object' || Array.isArray(data)) throw new Error('结果摘要格式不正确');
      if (data.title) byId('rainTitle').textContent = data.title;
      if (data.subtitle) byId('rainSubtitle').textContent = data.subtitle;
      const statuses = {complete:'本轮计算已完成',completed:'本轮计算已完成',partial:'部分计算完成',
        numerical_verified:'数值检查完成 · 物理验证待开展',pending:'研究进行中',failed:'存在未通过检查'};
      byId('rainStatus').textContent = statuses[data.status] || data.status || '已读取结果 · 请查看各项验证范围';
      byId('rainDate').textContent = data.generated_at || data.date || '';
      byId('rainScope').textContent = data.scope || '摘要未说明计算范围，请先核对完整报告。';
      for (const step of list(data.steps)) {
        const li = node('li');li.append(node('h3',step.title),node('p',step.detail));byId('rainSteps').append(li);
      }
      if (!list(data.steps).length) byId('rainSteps').append(node('li','本轮摘要尚未提供计算步骤，详见完整报告。'));
      for (const equation of list(data.equations)) {
        const block = node('div',undefined,'rain-equation');
        block.append(node('h3',equation.name),node('pre',equation.expression),node('p',equation.description));
        byId('rainEquations').append(block);byId('rainEquations').hidden = false;
      }
      for (const finding of list(data.findings)) byId('rainFindings').append(node('div',finding,'rain-finding'));
      let resultCount = 0;
      for (const item of list(data.tables)) {
        const columns = list(item.columns).filter(column => column && typeof column.key === 'string');
        const rows = list(item.rows).filter(row => row && typeof row === 'object');
        if (!columns.length || !rows.length) continue;
        byId('rainTables').append(table(item.title,columns,rows));resultCount++;
      }
      for (const item of list(data.figures)) {
        const url = relativeArtifact(item.file);
        if (!url || !/\.(?:png|svg)$/.test(url)) continue;
        const figure = node('figure',undefined,'rain-figure');
        figure.append(node('h3',item.title));
        const full = node('a');full.href = url;full.target = '_blank';full.rel = 'noopener';
        full.setAttribute('aria-label',`查看原图：${item.title || item.file}`);
        const img = node('img');img.src = url;img.alt = item.title || item.file;img.loading = 'lazy';img.decoding = 'async';
        img.addEventListener('error',()=>{
          img.hidden = true;
          full.append(node('p',`图文件读取失败：${item.file}。请核对计算产物。`,'rain-empty'));
          document.body.dataset.figureError = 'true';
        },{once:true});
        full.append(img);figure.append(full);
        const caption = node('figcaption',item.caption || '图示范围及参数见完整报告。');
        const original = node('a','查看原图 ↗');original.href = url;original.target = '_blank';original.rel = 'noopener';
        caption.append(original);figure.append(caption);byId('rainFigures').append(figure);resultCount++;
      }
      byId('rainPending').hidden = resultCount > 0;
      const checks = list(data.verification?.checks);
      if (checks.length) {
        const rows = checks.map(check=>({name:check.name,
          result:node('span',check.passed === true ? '通过' : check.passed === false ? '未通过' : '未判定',
            check.passed === true ? 'rain-check-pass' : check.passed === false ? 'rain-check-fail' : 'rain-check-unknown'),
          value:check.value,criterion:check.criterion}));
        byId('rainChecks').append(table('逐项数值检查',[
          {key:'name',label:'检查项目'},{key:'result',label:'结果'},{key:'value',label:'本轮结果 / 误差'},
          {key:'criterion',label:'验收条件与范围'}],rows,'check-table'));
      } else byId('rainChecks').append(node('p','摘要尚未提供逐项验证证据。','rain-empty'));
      const assumptions = list(data.assumptions);
      for (const item of assumptions) byId('rainAssumptions').append(node('li',item));
      if (!assumptions.length) byId('rainAssumptions').append(node('li','适用边界尚未在摘要中列明，应先阅读报告再使用结果。'));
      for (const source of list(data.sources)) {
        const url = externalURL(source.url);if (!url) continue;
        const card = node('div',undefined,'rain-source'), link = node('a',source.title);
        link.href = url;link.target = '_blank';link.rel = 'noopener';card.append(link);
        if (source.note) card.append(node('p',source.note));byId('rainSources').append(card);
      }
      const artifacts = [{title:'结果摘要 JSON',file:'summary.json'}, ...list(data.artifacts)];
      const seen = new Set();
      for (const item of artifacts) {
        const url = relativeArtifact(item.file);if (!url || seen.has(url)) continue;seen.add(url);
        const link = node('a',item.title || item.file);link.href = url;link.target = '_blank';link.rel = 'noopener';
        byId('rainDownloads').append(link);
      }
      if (data.literature_report_available === true) {
        const link = node('a','文献与公式调查');link.href = '/rain-loading/literature/README.md';link.target = '_blank';link.rel='noopener';byId('rainDownloads').append(link);
      }
      document.body.dataset.ready = 'true';
    } catch (error) {
      byId('rainStatus').textContent = '结果尚不可用';
      byId('rainPending').textContent = `${error.message}。概念说明可先阅读，数值结果需等待真实计算产物。`;
      byId('rainPending').hidden = false;document.body.dataset.ready = 'unavailable';
    }
  }
  boot();
})();
