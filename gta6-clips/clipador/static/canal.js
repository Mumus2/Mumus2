/* Painel do canal — gráficos em SVG puro, sem bibliotecas externas.
   Todo texto vindo da API entra via textContent (nunca innerHTML). */
(() => {
  'use strict';

  // ---------- utilidades ----------
  const $ = (id) => document.getElementById(id);
  const store = {
    get(k, d) { try { const v = localStorage.getItem('canal:' + k); return v === null ? d : JSON.parse(v); } catch { return d; } },
    set(k, v) { try { localStorage.setItem('canal:' + k, JSON.stringify(v)); } catch { /* sem storage */ } },
  };
  const state = {
    dias: store.get('dias', 28), metrica: store.get('metrica', 'views'), aba: 'top',
    sort: { key: 'views', dir: -1 }, tabelas: {}, data: null, polling: null,
  };
  const NF = new Intl.NumberFormat('pt-BR');
  const NF1 = new Intl.NumberFormat('pt-BR', { maximumFractionDigits: 1 });
  const CF = new Intl.NumberFormat('pt-BR', { notation: 'compact', maximumFractionDigits: 1 });
  const num = (n) => (n == null ? '—' : NF.format(n));
  const compact = (n) => (n == null ? '—' : Math.abs(n) < 10000 ? NF1.format(n) : CF.format(n));
  const axisNum = (v, top) => (Math.abs(top) >= 10000 ? CF.format(v) : NF1.format(v));
  const money = (n) => {
    if (n == null) return '—';
    const cur = (state.data && state.data.currency) || 'BRL';
    try { return new Intl.NumberFormat('pt-BR', { style: 'currency', currency: cur }).format(n); } catch { return NF1.format(n); }
  };
  const pct = (n) => (n == null ? '—' : NF1.format(n) + '%');
  const hours = (n) => (n == null ? '—' : compact(n) + ' h');
  const mmss = (s) => (s == null ? '—' : `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, '0')}`);
  const safeUrl = (u) => (typeof u === 'string' && /^https:\/\//.test(u) ? u : '');
  const dayLabel = (d, long) => {
    const [y, m, dd] = String(d).split('-');
    return long ? `${dd}/${m}/${y}` : `${dd}/${m}`;
  };
  const dateBR = (isoStr) => {
    if (!isoStr) return '—';
    const d = new Date(isoStr);
    return isNaN(d) ? '—' : d.toLocaleDateString('pt-BR');
  };
  let regionNames = null;
  try { regionNames = new Intl.DisplayNames(['pt-BR'], { type: 'region' }); } catch { /* navegador antigo */ }
  const country = (c) => { try { return (regionNames && c && regionNames.of(c)) || c || '—'; } catch { return c; } };

  function h(tag, attrs = {}, ...kids) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v == null || v === false) continue;
      if (k === 'class') el.className = v;
      else if (k === 'text') el.textContent = v;
      else if (k === 'style' && typeof v === 'object') Object.assign(el.style, v);
      else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
      else el.setAttribute(k, v === true ? '' : v);
    }
    for (const kid of kids.flat()) if (kid != null) el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
    return el;
  }
  const SVGNS = 'http://www.w3.org/2000/svg';
  function s(tag, attrs = {}) {
    const el = document.createElementNS(SVGNS, tag);
    for (const [k, v] of Object.entries(attrs)) if (v != null) el.setAttribute(k, v);
    return el;
  }

  // ---------- traduções e cores fixas por entidade (cor segue a entidade, nunca o ranking) ----------
  const TRAFEGO = {
    SHORTS: 'Feed do Shorts', YT_SEARCH: 'Pesquisa do YouTube', SUBSCRIBER: 'Inscrições e notificações',
    BROWSE: 'Página inicial e navegação', RELATED_VIDEO: 'Vídeos sugeridos', EXT_URL: 'Sites e apps externos',
    NO_LINK_OTHER: 'Direto ou desconhecido', PLAYLIST: 'Playlists', NOTIFICATION: 'Notificações',
    YT_CHANNEL: 'Página do canal', YT_OTHER_PAGE: 'Outras páginas do YouTube', END_SCREEN: 'Telas finais',
    HASHTAGS: 'Hashtags', SOUND_PAGE: 'Páginas de áudio', ADVERTISING: 'Publicidade', NO_LINK_EMBEDDED: 'Players incorporados',
    ANNOTATION: 'Cards', CAMPAIGN_CARD: 'Cards de campanha', LIVE_REDIRECT: 'Redirecionamento de live',
    PRODUCT_PAGE: 'Páginas de produto', SHORTS_CONTENT_LINKS: 'Links em Shorts', VIDEO_REMIXES: 'Remixes',
  };
  const DISPOSITIVOS = [['MOBILE', 'Celular'], ['DESKTOP', 'Computador'], ['TV', 'TV'], ['TABLET', 'Tablet'], ['GAME_CONSOLE', 'Console']];
  const FORMATOS = [['shorts', 'Shorts'], ['videoOnDemand', 'Vídeos longos'], ['liveStream', 'Lives'], ['story', 'Stories']];
  const GENEROS = ['Masculino', 'Feminino', 'Outro'];
  const SERIES = ['--series-1', '--series-2', '--series-3', '--series-4', '--series-5'];
  const cssVar = (name) => getComputedStyle($('canal')).getPropertyValue(name).trim();

  // ---------- tooltip (valor primeiro, rótulo depois) ----------
  const tip = $('tooltip');
  function showTip(x, y, value, label, color, extra) {
    tip.textContent = '';
    const top = h('div', { class: 'tv' });
    if (color) top.append(h('span', { class: 'key', style: { background: color } }));
    top.append(value);
    tip.append(top, h('div', { class: 'tl', text: label }));
    if (extra) tip.append(h('div', { class: 'tx', text: extra }));
    tip.hidden = false;
    const r = tip.getBoundingClientRect();
    let left = x + 14, topY = y + 14;
    if (left + r.width > innerWidth - 8) left = x - r.width - 14;
    if (topY + r.height > innerHeight - 8) topY = y - r.height - 14;
    tip.style.left = Math.max(8, left) + 'px';
    tip.style.top = Math.max(8, topY) + 'px';
  }
  const hideTip = () => { tip.hidden = true; };
  function hoverable(el, getTip) {
    el.tabIndex = 0;
    const show = (x, y) => { const t = getTip(); showTip(x, y, t[0], t[1], t[2], t[3]); };
    el.addEventListener('pointermove', (e) => show(e.clientX, e.clientY));
    el.addEventListener('pointerleave', hideTip);
    el.addEventListener('focus', () => { const r = el.getBoundingClientRect(); show(r.left + r.width / 2, r.top); });
    el.addEventListener('blur', hideTip);
  }

  // ---------- escala "redonda" ----------
  function niceNum(x) {
    if (x <= 0) return 1;
    const e = Math.floor(Math.log10(x)), f = x / 10 ** e;
    return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10) * 10 ** e;
  }
  function niceTicks(lo, hi, count = 5) {
    const step = niceNum((hi - lo) / (count - 1));
    const a = Math.floor(lo / step) * step, b = Math.ceil(hi / step) * step;
    const out = [];
    for (let v = a; v <= b + step / 2; v += step) out.push(Math.round(v * 1e6) / 1e6);
    return out;
  }

  // ---------- gráfico de linha (1 série: título nomeia, sem legenda) ----------
  function lineChart(el, pts, fmt, axisFmt, color, emptyMsg) {
    el.textContent = '';
    if (!pts.length) { el.append(h('div', { class: 'empty', text: emptyMsg })); return; }
    const W = Math.max(el.clientWidth, 280), H = 300, m = { l: 58, r: 22, t: 22, b: 30 };
    const iw = W - m.l - m.r, ih = H - m.t - m.b, n = pts.length;
    const ys = pts.map((p) => p.y);
    let lo = Math.min(0, ...ys), hi = Math.max(0, ...ys);
    if (hi === lo) hi = lo + 1;
    const ticks = niceTicks(lo, hi, 5);
    lo = ticks[0]; hi = ticks[ticks.length - 1];
    const x = (i) => m.l + (n === 1 ? iw / 2 : (i * iw) / (n - 1));
    const y = (v) => m.t + ih - ((v - lo) / (hi - lo)) * ih;
    const svg = s('svg', { width: W, height: H, viewBox: `0 0 ${W} ${H}`, role: 'img' });
    svg.setAttribute('aria-label', `${$('serie-titulo').textContent}: último valor ${fmt(ys[n - 1])}`);
    for (const t of ticks) {
      svg.append(s('line', { x1: m.l, x2: W - m.r, y1: y(t), y2: y(t), stroke: t === 0 ? cssVar('--axis') : cssVar('--grid'), 'stroke-width': 1 }));
      const lab = s('text', { x: m.l - 8, y: y(t) + 4, 'text-anchor': 'end', class: 'axis-text' });
      lab.textContent = axisFmt(t, hi);
      svg.append(lab);
    }
    const step = Math.max(1, Math.ceil(n / Math.max(2, Math.floor(iw / 80))));
    for (let i = 0; i < n; i += step) {
      const lab = s('text', { x: x(i), y: H - 8, 'text-anchor': i === 0 ? 'start' : 'middle', class: 'axis-text' });
      lab.textContent = dayLabel(pts[i].x);
      svg.append(lab);
    }
    const base = y(Math.max(lo, 0));
    const line = pts.map((p, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(p.y).toFixed(1)}`).join('');
    svg.append(s('path', { d: `${line}L${x(n - 1).toFixed(1)},${base}L${x(0).toFixed(1)},${base}Z`, fill: color, 'fill-opacity': 0.1 }));
    svg.append(s('path', { d: line, fill: 'none', stroke: color, 'stroke-width': 2, 'stroke-linejoin': 'round', 'stroke-linecap': 'round' }));
    // ponto final + valor (rótulo seletivo: só o último)
    const lx = x(n - 1), ly = y(ys[n - 1]);
    svg.append(s('circle', { cx: lx, cy: ly, r: 4, fill: color, stroke: cssVar('--surface-1'), 'stroke-width': 2 }));
    const endLab = s('text', { x: lx - 8, y: ly - 10, 'text-anchor': 'end', class: 'end-label' });
    endLab.textContent = fmt(ys[n - 1]);
    svg.append(endLab);
    // camada de hover: mira vertical que encaixa no dia mais próximo
    const cross = s('line', { y1: m.t, y2: m.t + ih, stroke: cssVar('--text-muted'), 'stroke-width': 1, visibility: 'hidden' });
    const dot = s('circle', { r: 5, fill: color, stroke: cssVar('--surface-1'), 'stroke-width': 2, visibility: 'hidden' });
    const hit = s('rect', { x: m.l - 10, y: 0, width: iw + 20, height: H, fill: 'transparent' });
    svg.append(cross, dot, hit);
    let idx = n - 1;
    const label = $('serie-titulo').textContent.replace(' por dia', '');
    function focusIdx(i, cx, cy) {
      idx = Math.max(0, Math.min(n - 1, i));
      const px = x(idx), py = y(ys[idx]);
      cross.setAttribute('x1', px); cross.setAttribute('x2', px); cross.setAttribute('visibility', 'visible');
      dot.setAttribute('cx', px); dot.setAttribute('cy', py); dot.setAttribute('visibility', 'visible');
      const r = svg.getBoundingClientRect();
      showTip(cx ?? r.left + px, cy ?? r.top + py, fmt(ys[idx]), `${label} · ${dayLabel(pts[idx].x, true)}`, color);
    }
    function clear() { cross.setAttribute('visibility', 'hidden'); dot.setAttribute('visibility', 'hidden'); hideTip(); }
    hit.addEventListener('pointermove', (e) => {
      const r = svg.getBoundingClientRect();
      focusIdx(Math.round(((e.clientX - r.left - m.l) / iw) * (n - 1)), e.clientX, e.clientY);
    });
    hit.addEventListener('pointerleave', clear);
    el.tabIndex = 0;
    el.onkeydown = (e) => {
      if (e.key === 'ArrowLeft') { focusIdx(idx - 1); e.preventDefault(); }
      if (e.key === 'ArrowRight') { focusIdx(idx + 1); e.preventDefault(); }
    };
    el.onfocus = () => focusIdx(idx);
    el.onblur = clear;
    el.append(svg);
  }

  function sparkline(series) {
    const W = 160, H = 30, svg = s('svg', { viewBox: `0 0 ${W} ${H}`, preserveAspectRatio: 'none', 'aria-hidden': 'true' });
    if (series.length < 2) return svg;
    const lo = Math.min(...series), hi = Math.max(...series), span = hi - lo || 1;
    const px = (i) => 4 + (i * (W - 8)) / (series.length - 1), py = (v) => H - 5 - ((v - lo) / span) * (H - 10);
    svg.append(s('path', { d: series.map((v, i) => `${i ? 'L' : 'M'}${px(i)},${py(v)}`).join(''), fill: 'none',
      stroke: cssVar('--deemph'), 'stroke-width': 1.5, 'vector-effect': 'non-scaling-stroke', 'stroke-linejoin': 'round' }));
    const last = series.length - 1;
    svg.append(s('circle', { cx: px(last), cy: py(series[last]), r: 3, fill: cssVar('--series-1') }));
    return svg;
  }
  function bucket(values, maxPts = 30) {
    if (values.length <= maxPts) return values;
    const size = Math.ceil(values.length / maxPts), out = [];
    for (let i = 0; i < values.length; i += size) out.push(values.slice(i, i + size).reduce((a, b) => a + b, 0));
    return out;
  }

  // ---------- barras horizontais ranqueadas (uma cor só) ----------
  function bars(el, rows, fmt, emptyMsg, limit = 8) {
    el.textContent = '';
    if (!rows.length) { el.append(h('div', { class: 'empty', text: emptyMsg })); return; }
    let list = rows.slice(0, limit);
    if (rows.length > limit) {
      const rest = rows.slice(limit);
      list.push({ label: 'Outros', value: rest.reduce((a, r) => a + r.value, 0), extra: `${rest.length} itens somados` });
    }
    const max = Math.max(...list.map((r) => r.value)) || 1;
    const wrap = h('div', { class: 'bars' });
    for (const r of list) {
      const bar = h('div', { class: 'bar', style: { width: `calc((100% - 70px) * ${Math.max(r.value, 0) / max})` } });
      const row = h('div', { class: 'row' }, h('div', { class: 'name', text: r.label, title: r.label }),
        h('div', { class: 'track' }, bar, h('span', { class: 'val', text: fmt(r.value) })));
      hoverable(row, () => [fmt(r.value), r.label, cssVar('--series-1'), r.extra]);
      wrap.append(row);
    }
    el.append(wrap);
  }

  // ---------- barra segmentada alta (≤ 6 partes) ----------
  function segbar(el, parts, fmt, emptyMsg) {
    el.textContent = '';
    const total = parts.reduce((a, p) => a + p.value, 0);
    if (!parts.length || !total) { el.append(h('div', { class: 'empty', text: emptyMsg })); return; }
    const bar = h('div', { class: 'segbar', role: 'img',
      'aria-label': parts.map((p) => `${p.label} ${NF1.format((p.value / total) * 100)}%`).join(', ') });
    const legend = h('div', { class: 'legend' });
    for (const p of parts) {
      if (p.value <= 0) continue;
      const share = (p.value / total) * 100;
      const txt = h('span', { text: `${NF1.format(share)}%` });
      const blk = h('div', { class: 'blk', style: { flex: `${p.value} 1 0`, background: p.color } }, txt);
      hoverable(blk, () => [fmt(p.value), p.label, p.color, `${NF1.format(share)}% do total`]);
      bar.append(blk);
      legend.append(h('span', {}, h('i', { style: { background: p.color } }), p.label, h('span', { class: 'fig', text: fmt(p.value) })));
    }
    el.append(bar, legend);
    requestAnimationFrame(() => { // rótulo só dentro do bloco se couber com folga
      for (const blk of bar.children) {
        const span = blk.firstChild;
        if (span && span.offsetWidth + 14 > blk.clientWidth) span.style.visibility = 'hidden';
      }
    });
  }
  function colored(rows, order) { // cor fixa pela entidade
    return rows.map((r) => {
      const i = order.indexOf(r.key);
      return { ...r, color: i >= 0 && i < SERIES.length ? cssVar(SERIES[i]) : cssVar('--deemph') };
    });
  }

  // ---------- tabelas (visão acessível de cada gráfico) ----------
  function table(cols, rows) {
    const t = h('table', { class: 'data table-view' });
    t.append(h('thead', {}, h('tr', {}, cols.map((c) => h('th', { class: c.num ? 'num' : null, text: c.label })))));
    const body = h('tbody');
    for (const r of rows) body.append(h('tr', {}, cols.map((c) => h('td', { class: c.num ? 'num' : null, text: c.fmt ? c.fmt(r[c.key]) : r[c.key] }))));
    t.append(body);
    return t;
  }
  function withTable(key, el, drawChart, cols, rows) {
    const btn = document.querySelector(`[data-tabela="${key}"]`);
    if (state.tabelas[key]) {
      el.textContent = '';
      el.append(rows.length ? table(cols, rows) : h('div', { class: 'empty', text: 'Sem dados no período.' }));
      if (btn) btn.textContent = 'Ver gráfico';
    } else {
      drawChart();
      if (btn) btn.textContent = 'Ver tabela';
    }
  }

  // ---------- métricas do gráfico principal ----------
  const METRICAS = {
    views: { titulo: 'Visualizações por dia', fmt: compact, axis: axisNum },
    hours: { titulo: 'Horas assistidas por dia', fmt: hours, axis: axisNum },
    subs_total: { titulo: 'Inscritos (total) por dia', fmt: num, axis: axisNum },
    revenue: { titulo: 'Receita estimada por dia', fmt: money, axis: (v) => money(v).replace(/,00$/, '') },
  };

  function deltaEl(cur, prev, fmtAbs) {
    if (prev == null || cur == null) return h('div', { class: 'delta flat', text: ' ' });
    const diff = cur - prev;
    if (!prev) return h('div', { class: 'delta flat' }, `${diff >= 0 ? '+' : ''}${fmtAbs(diff)} `, h('span', { class: 'vs', text: 'vs. período anterior' }));
    const p = (diff / Math.abs(prev)) * 100, up = diff > 0, flat = Math.abs(p) < 0.5;
    return h('div', { class: `delta ${flat ? 'flat' : up ? 'up' : 'down'}` },
      `${flat ? '■' : up ? '▲' : '▼'} ${up ? '+' : ''}${NF1.format(p)}% `, h('span', { class: 'vs', text: 'vs. período anterior' }));
  }

  // ---------- render ----------
  function render(d) {
    state.data = d;
    document.querySelectorAll('#periodos button').forEach((b) => b.setAttribute('aria-pressed', String(+b.dataset.dias === d.days)));
    document.querySelectorAll('#metricas button').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.m === state.metrica)));
    document.querySelectorAll('#abas-videos button').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.aba === state.aba)));
    const coletando = (d.busy || []).includes('channel');
    $('btn-coletar').disabled = coletando;
    $('btn-coletar').textContent = coletando ? 'Coletando dados do YouTube…' : '↻ Atualizar dados do YouTube';
    renderRobot(d.bot || {});
    if (!d.ready) { renderEmpty(); return; }
    $('vazio').hidden = true;
    $('conteudo').hidden = false;
    renderProfile(d);
    renderWarnings(d.errors || {});
    renderKpis(d);
    renderSeries(d);
    renderYpp(d);
    renderBreakdowns(d);
    renderVideos();
    const t = d.fetched_at ? new Date(d.fetched_at) : null;
    $('status-coleta').textContent = t ? `Dados de ${t.toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' })} · a página se atualiza sozinha` : '';
  }

  function renderEmpty() {
    $('conteudo').hidden = false;
    for (const c of document.querySelectorAll('#conteudo > :not(#card-robo)')) c.hidden = true;
    const v = $('vazio');
    v.hidden = false;
    v.textContent = '';
    v.append(h('h2', { text: 'Ainda não há dados do canal' }),
      h('p', { class: 'muted', text: 'O painel se preenche sozinho assim que o robô consegue ler o seu canal. Para isso:' }),
      h('ol', {},
        h('li', {}, 'Crie o canal e configure as credenciais do YouTube (README).'),
        h('li', {}, 'Autorize o canal: ', h('code', { text: 'python -m clipador youtube-auth' })),
        h('li', {}, 'Deixe o robô rodando (', h('code', { text: 'python -m clipador run' }), ') ou clique em “Atualizar dados do YouTube”.')));
    $('ch-title').textContent = 'Canal ainda não conectado';
  }

  function renderProfile(d) {
    for (const c of document.querySelectorAll('#conteudo > *')) c.hidden = false;
    const c = d.channel || {};
    const banner = safeUrl(c.banner);
    const fallback = 'linear-gradient(120deg, #3b0a4f, #a1135e 60%, #ff9a3c)';
    $('banner').style.backgroundImage = banner ? `url("${encodeURI(banner)}"), ${fallback}` : fallback;
    const av = safeUrl(c.avatar), img = $('avatar');
    img.onerror = () => { img.removeAttribute('src'); img.onerror = null; };
    if (av && img.getAttribute('src') !== av) img.src = av; else if (!av) img.removeAttribute('src');
    $('ch-title').textContent = c.title || 'Seu canal';
    const link = $('ch-link');
    link.textContent = c.handle || 'abrir no YouTube';
    link.href = c.handle ? `https://www.youtube.com/${encodeURIComponent(c.handle)}` : `https://www.youtube.com/channel/${encodeURIComponent(c.id || '')}`;
    $('ch-meta').textContent = [c.published_at ? `criado em ${dateBR(c.published_at)}` : '', c.country ? country(c.country) : '',
      `${num(c.videos)} vídeos`, `${compact(c.views)} views no total`].filter(Boolean).join(' · ');
    $('ch-desc').textContent = c.description || '';
    $('hero-subs').textContent = c.subscribers_hidden ? 'oculto' : num(c.subscribers);
    const net = d.kpis.subs_net;
    const hd = $('hero-delta');
    hd.className = `delta ${net > 0 ? 'up' : net < 0 ? 'down' : 'flat'}`;
    hd.textContent = `${net > 0 ? '▲ +' : net < 0 ? '▼ ' : ''}${num(net)} em ${periodoTxt(d.days)}`;

    const chips = $('chips');
    chips.textContent = '';
    chips.append(monChip(d.monetization || {}));
    const ageMin = d.fetched_at ? Math.round((Date.now() - new Date(d.fetched_at)) / 60000) : null;
    if (ageMin != null) {
      const stale = ageMin > 180;
      chips.append(h('span', { class: `chip ${stale ? 'warn' : 'good'}` }, h('span', { class: 'ic', text: stale ? '!' : '●' }),
        ageMin < 1 ? 'Atualizado agora' : `Atualizado há ${ageMin < 60 ? ageMin + ' min' : Math.round(ageMin / 60) + ' h'}`));
    }
    if (c.long_uploads && c.long_uploads !== 'allowed') {
      chips.append(h('span', { class: 'chip warn' }, h('span', { class: 'ic', text: '!' }), 'Verifique o telefone para vídeos > 15 min'));
    }
  }
  const periodoTxt = (n) => (n === 365 ? '12 meses' : `${n} dias`);

  function monChip(mon) {
    const map = {
      active: ['good', '✓', 'Monetização ativa'],
      inactive: ['warn', '!', 'Monetização ainda não ativa'],
      no_permission: ['bad', '✕', 'Sem permissão para ler a receita'],
      unavailable: ['warn', '!', 'Receita indisponível'],
    };
    const [cls, ic, txt] = map[mon.status] || map.unavailable;
    return h('span', { class: `chip ${cls}` }, h('span', { class: 'ic', text: ic }), txt);
  }

  function renderWarnings(errors) {
    const box = $('avisos');
    const items = Object.entries(errors);
    box.hidden = !items.length;
    box.textContent = '';
    if (!items.length) return;
    const uniq = new Map();
    for (const [k, v] of items) uniq.set(v, (uniq.get(v) || []).concat(k.replace(/_\d+$/, '')));
    box.append(h('b', { text: `⚠ ${items.length} ${items.length === 1 ? 'relatório não pôde' : 'relatórios não puderam'} ser lidos` }),
      ' — o resto do painel está normal.',
      h('ul', {}, [...uniq].map(([msg, names]) => h('li', {}, h('span', { text: [...new Set(names)].join(', ') + ': ' }), msg))));
  }

  function renderKpis(d) {
    const k = d.kpis, ser = d.series, active = (d.monetization || {}).status === 'active';
    const tiles = [
      ['Visualizações', compact(k.views), k.views, k.views_prev, compact, ser.map((r) => r.views)],
      ['Horas assistidas', hours(k.hours), k.hours, k.hours_prev, hours, ser.map((r) => r.hours)],
      ['Inscritos (saldo)', `${k.subs_net > 0 ? '+' : ''}${num(k.subs_net)}`, k.subs_net, k.subs_net_prev, num, ser.map((r) => r.subs_net)],
      ['Receita estimada', active ? money(k.revenue) : null, k.revenue, k.revenue_prev, money, ser.map((r) => r.revenue)],
      ['RPM (por mil views)', active && k.rpm != null ? money(k.rpm) : null, null, null, money, null],
      ['Duração média', mmss(k.avg_view_s), null, null, null, null],
      ['Curtidas', compact(k.likes), null, null, null, ser.map((r) => r.likes)],
    ];
    const box = $('kpis');
    box.textContent = '';
    for (const [label, value, cur, prev, fmt, spark] of tiles) {
      const tile = h('div', { class: 'kpi' }, h('div', { class: 'label', text: label }));
      if (value == null) tile.append(h('div', { class: 'value na', text: 'Monetização ainda não ativa' }));
      else tile.append(h('div', { class: 'value', text: value }));
      if (fmt && value != null) tile.append(deltaEl(cur, prev, fmt));
      if (spark && value != null) tile.append(sparkline(bucket(spark)));
      box.append(tile);
    }
  }

  function renderSeries(d) {
    const mdef = METRICAS[state.metrica] || METRICAS.views;
    $('serie-titulo').textContent = mdef.titulo;
    const pts = d.series.map((r) => ({ x: r.day, y: r[state.metrica] ?? 0 }));
    const semReceita = state.metrica === 'revenue' && (d.monetization || {}).status !== 'active';
    withTable('serie', $('serie'),
      () => lineChart($('serie'), semReceita ? [] : pts, mdef.fmt, mdef.axis, cssVar('--series-1'),
        semReceita ? 'Sem receita para mostrar: a monetização ainda não está ativa.' : 'Sem dados do Analytics neste período ainda.'),
      [{ key: 'x', label: 'Dia', fmt: (v) => dayLabel(v, true) }, { key: 'y', label: mdef.titulo.replace(' por dia', ''), num: true, fmt: mdef.fmt }],
      pts.slice().reverse());
  }

  function renderYpp(d) {
    const y = d.ypp || {};
    const meters = [
      { name: 'Inscritos', v: y.subscribers || 0, goal: 1000, tier: 500, fmt: num },
      { name: 'Horas de exibição em vídeos longos (12 meses)', v: y.long_hours_12m || 0, goal: 4000, tier: 3000, fmt: (n) => NF.format(Math.round(n)) },
      { name: 'Visualizações de Shorts (90 dias)', v: y.shorts_views_90d || 0, goal: 10e6, tier: 3e6, fmt: compact },
    ];
    const box = $('ypp');
    box.textContent = '';
    const list = h('div', { class: 'meters' });
    for (const m of meters) {
      const done = m.v >= m.goal, frac = Math.min(1, m.v / m.goal);
      const top = h('div', { class: 'top' }, h('span', { text: m.name }),
        done ? h('span', { class: 'ok', text: '✓ Concluído' })
          : h('span', { class: 'fig', text: `${m.fmt(m.v)} de ${m.fmt(m.goal)} · ${NF1.format(frac * 100)}%` }));
      const rail = h('div', { class: 'rail', role: 'meter', 'aria-valuemin': 0, 'aria-valuemax': m.goal, 'aria-valuenow': m.v, 'aria-label': m.name },
        h('div', { class: 'fill', style: { width: `${frac * 100}%` } }),
        h('div', { class: 'tick', style: { left: `${(m.tier / m.goal) * 100}%` } }));
      const tl = h('div', { class: 'ticklabel' }, h('span', { style: { left: `${(m.tier / m.goal) * 100}%` }, text: `nível 1: ${m.fmt(m.tier)}` }));
      list.append(h('div', { class: `meter ${done ? 'done' : ''}` }, top, rail, tl));
    }
    box.append(list);
    $('ypp-nota').textContent = 'Precisa de inscritos + (horas de vídeos longos OU views de Shorts). Nível 1 libera clube de membros e Super Thanks.'
      + (y.approximate ? ' Valores aproximados — o número oficial está no YouTube Studio.' : '');
    const mc = $('mon-chip');
    mc.textContent = '';
    mc.append(monChip(d.monetization || {}));
    const rk = $('receita-kpis');
    rk.textContent = '';
    if ((d.monetization || {}).status === 'active') {
      for (const [l, v] of [['Receita no período', money(d.kpis.revenue)], ['RPM', money(d.kpis.rpm)],
        ['CPM', money(d.kpis.cpm)], ['Receita em 12 meses', money(d.monetization.revenue_365)]]) {
        rk.append(h('div', { class: 'mini' }, h('div', { class: 'label', text: l }), h('div', { class: 'value', text: v })));
      }
    }
  }

  function renderBreakdowns(d) {
    const st = d.streamers.map((r) => ({ label: r.name, value: r.views, extra: `${r.videos} vídeos · média de ${compact(r.avg_views)} views` }));
    withTable('streamers', $('streamers'), () => bars($('streamers'), st, compact, 'Nenhum corte publicado ainda.', 12),
      [{ key: 'name', label: 'Streamer' }, { key: 'videos', label: 'Vídeos', num: true, fmt: num },
        { key: 'views', label: 'Views', num: true, fmt: num }, { key: 'avg_views', label: 'Média', num: true, fmt: num }], d.streamers);

    const tr = d.traffic.map((r) => ({ label: TRAFEGO[r.name] || r.name, value: r.views }));
    withTable('trafego', $('trafego'), () => bars($('trafego'), tr, compact, 'Sem dados no período.'),
      [{ key: 'label', label: 'Origem' }, { key: 'value', label: 'Views', num: true, fmt: num }], tr);

    const pa = d.countries.map((r) => ({ label: country(r.name), value: r.views }));
    withTable('paises', $('paises'), () => bars($('paises'), pa, compact, 'Sem dados no período.'),
      [{ key: 'label', label: 'País' }, { key: 'value', label: 'Views', num: true, fmt: num }], pa);

    const ages = d.ages.map((r) => ({ label: r.name + ' anos', value: r.pct }));
    withTable('idades', $('idades'), () => bars($('idades'), ages, pct, 'O YouTube só mostra o público quando há views suficientes.', 7),
      [{ key: 'label', label: 'Idade' }, { key: 'value', label: '% do público', num: true, fmt: pct }], ages);
    segbar($('generos'), colored(d.genders.map((r) => ({ key: r.name, label: r.name, value: r.pct })), GENEROS), pct,
      'Sem dados de gênero ainda.');

    const devOrder = DISPOSITIVOS.map((x) => x[0]);
    const devName = Object.fromEntries(DISPOSITIVOS);
    segbar($('dispositivos'), colored(d.devices.map((r) => ({ key: r.name, label: devName[r.name] || 'Outros', value: r.views })), devOrder),
      compact, 'Sem dados no período.');
    const fmtOrder = FORMATOS.map((x) => x[0]);
    const fmtName = Object.fromEntries(FORMATOS);
    const ct = d.content_type.map((r) => ({ key: r.name, label: fmtName[r.name] || r.name, value: r.views, hours: r.hours }));
    segbar($('formato'), colored(ct, fmtOrder), compact, 'Sem dados no período.');
    if (ct.length) {
      $('formato').append(h('p', { class: 'muted small', text: ct.map((r) => `${r.label}: ${hours(r.hours)} assistidas`).join(' · ') }));
    }
  }

  // ---------- tabela de vídeos (ordenável, com busca) ----------
  function renderVideos() {
    const d = state.data;
    const q = $('busca').value.trim().toLowerCase(), f = $('filtro-formato').value;
    const top = state.aba === 'top';
    const cols = top
      ? [['title', 'Vídeo'], ['streamer', 'Streamer'], ['views', 'Views', 1], ['hours', 'Horas', 1], ['avg_pct', '% assistido', 1], ['subs', 'Inscritos', 1]]
      : [['title', 'Vídeo'], ['streamer', 'Streamer'], ['published_at', 'Publicado', 1], ['views', 'Views', 1], ['likes', 'Curtidas', 1], ['comments', 'Comentários', 1]];
    if (!cols.some((c) => c[0] === state.sort.key)) state.sort = { key: 'views', dir: -1 };
    let rows = (top ? d.top_videos : d.videos).filter((r) =>
      (!q || (r.title || '').toLowerCase().includes(q) || (r.streamer || '').toLowerCase().includes(q))
      && (!f || (f === 'short' ? r.is_short === true : r.is_short === false)));
    const { key, dir } = state.sort;
    rows = rows.slice().sort((a, b) => (a[key] > b[key] ? 1 : a[key] < b[key] ? -1 : 0) * dir);
    const t = $('tabela-videos');
    t.textContent = '';
    const headRow = h('tr', {}, h('th', { text: '' }));
    for (const [k, label, isNum] of cols) {
      const th = h('th', { class: isNum ? 'num' : null, 'data-sort': k, tabindex: 0, 'aria-sort': key === k ? (dir > 0 ? 'ascending' : 'descending') : 'none' }, label);
      if (key === k) th.append(h('span', { class: 'arrow', text: dir > 0 ? '▲' : '▼' }));
      const act = () => { state.sort = { key: k, dir: key === k ? -dir : -1 }; renderVideos(); };
      th.addEventListener('click', act);
      th.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); act(); } });
      headRow.append(th);
    }
    t.append(h('thead', {}, headRow));
    const body = h('tbody');
    if (!rows.length) body.append(h('tr', {}, h('td', { colspan: cols.length + 1, class: 'empty', text: 'Nenhum vídeo encontrado.' })));
    for (const r of rows.slice(0, 100)) {
      const thumb = safeUrl(r.thumbnail);
      const titleCell = h('td', { class: 't' }, h('a', { href: `https://youtu.be/${encodeURIComponent(r.id || '')}`, target: '_blank', rel: 'noopener', text: r.title || r.id }));
      if (r.is_short != null) titleCell.append(h('span', { class: 'tag', text: r.is_short ? 'Short' : 'Longo' }));
      const tr = h('tr', {}, h('td', {}, thumb ? h('img', { class: 'thumb', src: thumb, alt: '', loading: 'lazy', onerror: (e) => e.target.replaceWith(h('div', { class: 'thumb' })) }) : h('div', { class: 'thumb' })), titleCell);
      for (const [k, , isNum] of cols.slice(1)) {
        let v = r[k];
        if (k === 'published_at') v = dateBR(v);
        else if (k === 'hours') v = hours(v);
        else if (k === 'avg_pct') v = pct(v);
        else if (k === 'streamer') v = v || '—';
        else if (isNum) v = num(v);
        tr.append(h('td', { class: isNum ? 'num' : null, text: v }));
      }
      body.append(tr);
    }
    t.append(body);
  }

  function renderRobot(b) {
    const box = $('robo');
    box.textContent = '';
    for (const [l, v] of [['Ao vivo em GTA 6 agora', `${num(b.live)} de ${num(b.tracked)}`], ['Clipes prontos', num(b.ready)],
      ['Publicados hoje', num(b.posted_today)], ['Momentos no chat hoje', num(b.moments_today)],
      ['Cota da API usada', `${compact(b.quota_used)} de ${compact(b.quota_total)}`], ['Uploads restantes hoje', num(b.uploads_left)],
      ['Modo de postagem', b.mode === 'realtime' ? 'Tempo real' : 'Agendado']]) {
      box.append(h('div', { class: 'mini' }, h('div', { class: 'label', text: l }), h('div', { class: 'value', text: v })));
    }
  }

  // ---------- dados ----------
  async function load() {
    $('conteudo').classList.add('loading');
    try {
      const r = await fetch(`/api/canal?dias=${state.dias}`, { headers: { accept: 'application/json' }, credentials: 'same-origin' });
      if (!r.ok) throw new Error('HTTP ' + r.status);
      render(await r.json());
    } catch (e) {
      const box = $('avisos');
      box.hidden = false;
      box.textContent = '';
      box.append(h('b', { text: '⚠ Sem resposta do robô' }), ` (${e.message}). Mostrando os últimos dados carregados; tentando de novo em 1 minuto.`);
    } finally {
      $('conteudo').classList.remove('loading');
    }
  }

  async function collectNow() {
    $('btn-coletar').disabled = true;
    try {
      await fetch('/acao/channel', { method: 'POST', headers: { accept: 'application/json' }, credentials: 'same-origin' });
    } catch { /* o load abaixo mostra o erro */ }
    let tries = 0;
    clearInterval(state.polling);
    state.polling = setInterval(async () => {
      await load();
      if (++tries > 40 || !(state.data && (state.data.busy || []).includes('channel'))) clearInterval(state.polling);
    }, 3000);
  }

  // ---------- eventos ----------
  $('periodos').addEventListener('click', (e) => {
    const b = e.target.closest('button'); if (!b) return;
    state.dias = +b.dataset.dias; store.set('dias', state.dias); load();
  });
  $('metricas').addEventListener('click', (e) => {
    const b = e.target.closest('button'); if (!b || !state.data) return;
    state.metrica = b.dataset.m; store.set('metrica', state.metrica); render(state.data);
  });
  $('abas-videos').addEventListener('click', (e) => {
    const b = e.target.closest('button'); if (!b || !state.data) return;
    state.aba = b.dataset.aba; render(state.data);
  });
  document.addEventListener('click', (e) => {
    const b = e.target.closest('[data-tabela]'); if (!b || !state.data) return;
    state.tabelas[b.dataset.tabela] = !state.tabelas[b.dataset.tabela]; render(state.data);
  });
  $('busca').addEventListener('input', () => state.data && state.data.ready && renderVideos());
  $('filtro-formato').addEventListener('change', () => state.data && state.data.ready && renderVideos());
  $('btn-coletar').addEventListener('click', collectNow);
  let resizeT;
  addEventListener('resize', () => { clearTimeout(resizeT); resizeT = setTimeout(() => state.data && state.data.ready && renderSeries(state.data), 150); });

  load();
  setInterval(load, 60000);
})();
