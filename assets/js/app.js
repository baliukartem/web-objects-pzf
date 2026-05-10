/* ====================================================================
   ПЗФ Вінниччини — головний модуль
   ==================================================================== */

const CAT_COLORS = {
  "Національний природний парк":              "#1b6f3a",
  "Регіональний ландшафтний парк":            "#3a8a4f",
  "Заказник":                                  "#bfa66b",
  "Пам'ятка природи":                          "#c25450",
  "Парк-пам'ятка садово-паркового мистецтва":  "#7a4ec2",
  "Заповідне урочище":                         "#3a6cba",
  "Дендрологічний парк":                       "#27a39d",
  "Ботанічний сад":                            "#df8b22",
  "Зоологічний парк":                          "#a64a82",
  "_unknown":                                  "#7c8a82",
};

const catColor = (c) => CAT_COLORS[c] || CAT_COLORS._unknown;

const escapeHtml = (s) =>
  String(s || '').replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[c]));

/* ============ App state ============ */
const state = {
  q: '', rayon: '', otg: '', cat: '', type: '', sig: '',
  selected: null,
  PZF: null, RAYONS: null, OTGS: null, OVERRIDES: {},
};

/* ============ Data loading ============ */
async function loadData() {
  const [pzf, rayons, otgs, overrides] = await Promise.all([
    fetch('assets/data/pzf.json').then(r => r.json()),
    fetch('assets/data/rayons.geojson').then(r => r.json()),
    fetch('assets/data/otgs.geojson').then(r => r.json()),
    fetch('assets/data/coordinates_override.json').then(r => r.json()).catch(() => ({}))
  ]);
  state.PZF = pzf;
  state.RAYONS = rayons;
  state.OTGS = otgs;
  state.OVERRIDES = overrides.objects || {};

  // Apply manual coordinate overrides
  const overrideCount = Object.keys(state.OVERRIDES).length;
  let applied = 0;
  pzf.records.forEach(r => {
    const key = r.id || `${r.significance}_${r.category}_${r.num}`;
    const ov = state.OVERRIDES[key] || state.OVERRIDES[r.name];
    if (ov && Array.isArray(ov) && ov.length === 2) {
      r.lat = ov[0]; r.lon = ov[1];
      r.coord_source = 'manual';
      applied++;
    }
  });
  if (overrideCount) {
    console.log(`Coordinate overrides: applied ${applied} of ${overrideCount}`);
  }
}

/* ============ UI: Filters ============ */
function fillSelect(el, options, placeholder) {
  el.innerHTML = `<option value="">${placeholder}</option>` +
    options.map(o => `<option value="${escapeHtml(o.value)}">${escapeHtml(o.label)}${o.count != null ? ` (${o.count})` : ''}</option>`).join('');
}

function rebuildOTGOptions() {
  const fSel = document.getElementById('f-otg');
  const cur = fSel.value;
  const list = state.OTGS.features
    .filter(f => !state.rayon || String(f.properties.ADMIN_2) === state.rayon)
    .map(f => ({ value: String(f.properties.id), label: f.properties.ADMIN_3 }))
    .sort((a, b) => a.label.localeCompare(b.label, 'uk'));
  fillSelect(fSel, list, 'Усі громади');
  if (list.some(o => o.value === cur)) fSel.value = cur; else state.otg = '';
}

function buildFilters() {
  const rayonOpts = state.PZF.rayons
    .map(r => ({ value: r.name, label: r.name }))
    .sort((a, b) => a.label.localeCompare(b.label, 'uk'));
  fillSelect(document.getElementById('f-rayon'), rayonOpts, 'Усі райони');
  rebuildOTGOptions();

  const catCounts = {};
  state.PZF.records.forEach(r => {
    const c = r.category || '(невизначено)';
    catCounts[c] = (catCounts[c] || 0) + 1;
  });
  const catOpts = Object.entries(catCounts)
    .map(([k, v]) => ({ value: k, label: k, count: v }))
    .sort((a, b) => b.count - a.count);
  fillSelect(document.getElementById('f-cat'), catOpts, 'Усі категорії');

  const typeCounts = {};
  state.PZF.records.forEach(r => {
    const t = r.type_normalized || '(невказано)';
    typeCounts[t] = (typeCounts[t] || 0) + 1;
  });
  const typeOpts = Object.entries(typeCounts)
    .map(([k, v]) => ({ value: k, label: k, count: v }))
    .sort((a, b) => b.count - a.count);
  fillSelect(document.getElementById('f-type'), typeOpts, 'Усі типи');
}

function buildLegend() {
  const wrap = document.getElementById('legend-rows');
  const cats = Array.from(new Set(state.PZF.records.map(r => r.category).filter(Boolean))).sort();
  wrap.innerHTML = cats.map(c =>
    `<div class="row"><span class="sw" style="background:${catColor(c)}"></span><span>${escapeHtml(c)}</span></div>`
  ).join('');
}

/* ============ Map setup ============ */
let map, rayonLayer, otgLayer, markersGroup, clusterGroup, plainMarkersLayer;

function buildMap() {
  map = L.map('map', { zoomControl: true, attributionControl: true })
        .setView([49.0, 28.5], 8);

  L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', {
    attribution: '© OpenStreetMap, © CartoDB',
    subdomains: 'abcd', maxZoom: 19
  }).addTo(map);

  /* Rayons */
  rayonLayer = L.geoJSON(state.RAYONS, {
    style: { color: '#2f6b3d', weight: 1.6, opacity: 0.8, fillColor: '#2f6b3d', fillOpacity: 0.04 },
    onEachFeature: (f, layer) => {
      const p = f.properties;
      layer.bindTooltip(p.admin_ua, { sticky: true });
      layer.on('mouseover', () => layer.setStyle({ fillOpacity: 0.15 }));
      layer.on('mouseout',  () => layer.setStyle({ fillOpacity: 0.04 }));
      layer.on('click', () => {
        document.getElementById('f-rayon').value = p.admin_ua;
        state.rayon = p.admin_ua;
        rebuildOTGOptions();
        applyFilters();
      });
    }
  }).addTo(map);

  /* OTGs */
  otgLayer = L.geoJSON(state.OTGS, {
    style: { color: '#4a8b58', weight: 1, opacity: 0.7, dashArray: '3 3', fillColor: '#4a8b58', fillOpacity: 0.03 },
    onEachFeature: (f, layer) => {
      const p = f.properties;
      layer.bindTooltip(`${p.ADMIN_3}<br><small>${p.TYPE || ''}</small>`, { sticky: true });
      layer.on('mouseover', () => layer.setStyle({ fillOpacity: 0.15 }));
      layer.on('mouseout',  () => layer.setStyle({ fillOpacity: 0.03 }));
      layer.on('click', () => {
        document.getElementById('f-rayon').value = p.ADMIN_2;
        state.rayon = p.ADMIN_2;
        rebuildOTGOptions();
        document.getElementById('f-otg').value = String(p.id);
        state.otg = String(p.id);
        applyFilters();
      });
    }
  });

  map.fitBounds(rayonLayer.getBounds(), { padding: [20, 20] });

  /* Marker layers */
  clusterGroup = L.markerClusterGroup({
    showCoverageOnHover: false,
    zoomToBoundsOnClick: true,
    spiderfyOnMaxZoom: false,
    maxClusterRadius: 45,
    chunkedLoading: true,
    spiderfyDistanceMultiplier: 1.5,
    iconCreateFunction: cluster => {
      const n = cluster.getChildCount();
      const size = n < 10 ? 32 : n < 50 ? 38 : 44;
      return L.divIcon({
        html: `<div style="width:${size}px;height:${size}px;border-radius:50%;background:rgba(47,107,61,0.85);border:3px solid #fff;color:#fff;display:grid;place-items:center;font-weight:700;font-size:13px;box-shadow:0 2px 8px rgba(0,0,0,0.25)">${n}</div>`,
        className: 'pzf-cluster',
        iconSize: [size, size],
      });
    },
  });
  plainMarkersLayer = L.layerGroup();
  markersGroup = clusterGroup;
  map.addLayer(markersGroup);
}

function buildMarkers(records) {
  clusterGroup.clearLayers();
  plainMarkersLayer.clearLayers();
  records.forEach(r => {
    if (r.lat == null || r.lon == null) return;
    const color = catColor(r.category);
    const icon = L.divIcon({
      className: '',
      html: `<div class="pzf-marker" style="background:${color}"></div>`,
      iconSize: [14, 14], iconAnchor: [7, 7],
    });
    const m = L.marker([r.lat, r.lon], { icon, title: r.name });
    m.on('click', () => selectRecord(r));
    m.bindTooltip(r.name, { direction: 'top', offset: [0, -6] });
    clusterGroup.addLayer(m);
    plainMarkersLayer.addLayer(L.marker([r.lat, r.lon], { icon, title: r.name })
      .on('click', () => selectRecord(r))
      .bindTooltip(r.name, { direction: 'top', offset: [0, -6] }));
  });
}

/* ============ Filtering ============ */
function applyFilters() {
  state.q = document.getElementById('q').value.trim().toLowerCase();
  state.rayon = document.getElementById('f-rayon').value;
  state.otg = document.getElementById('f-otg').value;
  state.cat = document.getElementById('f-cat').value;
  state.type = document.getElementById('f-type').value;

  const filtered = state.PZF.records.filter(r => {
    if (state.sig && r.significance !== state.sig) return false;
    if (state.rayon && r.rayon_name !== state.rayon) return false;
    if (state.otg && String(r.otg_id) !== state.otg) return false;
    if (state.cat && r.category !== state.cat) return false;
    if (state.type && r.type_normalized !== state.type) return false;
    if (state.q) {
      const hay = `${r.name || ''} ${r.location || ''} ${r.org || ''} ${r.type || ''}`.toLowerCase();
      if (!hay.includes(state.q)) return false;
    }
    return true;
  });

  buildMarkers(filtered);
  renderList(filtered);
  updateBar(filtered);
  return filtered;
}

function updateBar(filtered) {
  document.getElementById('result-count').textContent = filtered.length.toLocaleString('uk-UA');
  document.getElementById('result-total').textContent = state.PZF.records.length.toLocaleString('uk-UA');
  const totalArea = filtered.reduce((s, r) => s + (r.area || 0), 0);
  document.getElementById('result-area').textContent = totalArea.toLocaleString('uk-UA', { maximumFractionDigits: 1 });
}

function renderList(records) {
  const list = document.getElementById('list');
  if (records.length === 0) {
    list.innerHTML = `<div style="padding:40px 20px;text-align:center;color:var(--muted);font-size:13px">Не знайдено обʼєктів за заданими фільтрами</div>`;
    return;
  }
  const cap = 200;
  const shown = records.slice(0, cap);
  list.innerHTML = shown.map(r => `
    <div class="item" data-key="${r.num}_${r.significance}_${escapeHtml(r.category || '')}">
      <div class="name">${escapeHtml(r.name)}</div>
      <div class="meta">
        <span class="dot" style="background:${catColor(r.category)}"></span>
        <span>${escapeHtml(r.category || '—')}</span>
        ${r.type ? `<span>· ${escapeHtml(r.type)}</span>` : ''}
        ${r.area != null ? `<span>· ${r.area.toLocaleString('uk-UA')} га</span>` : ''}
      </div>
      <div class="meta">
        <span style="opacity:.8">${escapeHtml(r.rayon_name || 'район невідомий')}</span>
        ${r.otg_name ? `<span>· ${escapeHtml(r.otg_name)}</span>` : ''}
      </div>
    </div>
  `).join('') + (records.length > cap ? `<div style="padding:10px 14px;color:var(--muted);font-size:12px;text-align:center">Показано перші ${cap} з ${records.length}. Уточніть фільтри.</div>` : '');

  list.querySelectorAll('.item').forEach((el, i) => {
    el.addEventListener('click', () => {
      selectRecord(shown[i]);
      if (shown[i].lat && shown[i].lon) {
        map.setView([shown[i].lat, shown[i].lon], Math.max(map.getZoom(), 11));
      }
    });
  });
}

function selectRecord(r) {
  state.selected = r;
  document.querySelectorAll('.item').forEach(el => el.classList.remove('active'));
  document.getElementById('d-cat').textContent = r.category || 'Категорія невказана';
  document.getElementById('d-name').textContent = r.name;

  const sigPill = r.significance
    ? (r.significance === 'загальнодержавне'
        ? '<span class="pill gold">Загальнодержавне</span>'
        : '<span class="pill">Місцеве</span>')
    : '—';

  const sourcePill = {
    'manual':            '<span class="pill" style="background:#dff5e1;color:#1b6f3a">точна (вручну)</span>',
    'osm':               '<span class="pill" style="background:#dff5e1;color:#1b6f3a">з OSM</span>',
    'otg-distributed':   '<span class="pill gray">в межах ОТГ</span>',
    'rayon-distributed': '<span class="pill gray">в межах району</span>',
  }[r.coord_source] || '<span class="pill gray">невідомо</span>';

  const fields = [
    ['Тип', r.type],
    ['Площа', r.area != null ? `${r.area.toLocaleString('uk-UA')} га` : '—'],
    ['Значення', sigPill],
    ['Район', r.rayon_name || '—'],
    ['Громада', r.otg_name || '—'],
    ['Координати', `${r.lat?.toFixed(4) || '—'}, ${r.lon?.toFixed(4) || '—'} ${sourcePill}`],
    ['Розташування', r.location || '—'],
    ['Землекористувач', r.org || '—'],
    ['Підстава', r.decree || '—'],
  ];
  document.getElementById('d-body').innerHTML = fields.map(([k, v]) =>
    `<div class="field-row"><div class="k">${k}</div><div class="v">${v || '—'}</div></div>`
  ).join('');
  document.getElementById('detail').classList.add('open');
}

/* ============ Stats modal ============ */
function openStats() {
  const recs = state.PZF.records;
  const totalArea = recs.reduce((s, r) => s + (r.area || 0), 0);

  const catRows = {};
  recs.forEach(r => {
    const c = r.category || '(невизначено)';
    if (!catRows[c]) catRows[c] = { count: 0, area: 0 };
    catRows[c].count++;
    catRows[c].area += r.area || 0;
  });
  const cats = Object.entries(catRows).sort((a, b) => b[1].count - a[1].count);
  const maxCount = Math.max(...cats.map(c => c[1].count));

  const rayonRows = {};
  recs.forEach(r => {
    const c = r.rayon_name || '(не вказано)';
    if (!rayonRows[c]) rayonRows[c] = { count: 0, area: 0 };
    rayonRows[c].count++;
    rayonRows[c].area += r.area || 0;
  });
  const rayons = Object.entries(rayonRows).sort((a, b) => b[1].area - a[1].area);
  const maxRArea = Math.max(...rayons.map(r => r[1].area));

  const typeRows = {};
  recs.forEach(r => {
    const c = r.type_normalized || '(невказано)';
    if (!typeRows[c]) typeRows[c] = { count: 0, area: 0 };
    typeRows[c].count++;
    typeRows[c].area += r.area || 0;
  });
  const types = Object.entries(typeRows).sort((a, b) => b[1].count - a[1].count).slice(0, 10);
  const maxTCount = Math.max(...types.map(r => r[1].count));

  // Додаткові аналітичні секції
  // 1. Розподіл за значенням
  const sigRows = {};
  recs.forEach(r => {
    const s = r.significance || '(невказано)';
    if (!sigRows[s]) sigRows[s] = { count: 0, area: 0 };
    sigRows[s].count++;
    sigRows[s].area += r.area || 0;
  });
  const sigs = Object.entries(sigRows).sort((a, b) => b[1].count - a[1].count);
  // 2. Розподіл за джерелом координат
  const srcRows = {};
  recs.forEach(r => {
    const s = r.coord_source || '(невказано)';
    if (!srcRows[s]) srcRows[s] = { count: 0 };
    srcRows[s].count++;
  });
  const srcs = Object.entries(srcRows).sort((a, b) => b[1].count - a[1].count);
  // 3. ТОП-10 землекористувачів
  const orgRows = {};
  recs.forEach(r => {
    const o = r.org || '(невказано)';
    if (!orgRows[o]) orgRows[o] = 0;
    orgRows[o]++;
  });
  const orgs = Object.entries(orgRows).sort((a, b) => b[1] - a[1]).slice(0, 10);

  const html = `
    <div class="stat-grid">
      <div class="stat-card"><div class="n">${recs.length}</div><div class="l">Опрацьовано</div></div>
      <div class="stat-card"><div class="n">${state.PZF.totals_official?.objects || recs.length}</div><div class="l">за офіц. переліком</div></div>
      <div class="stat-card"><div class="n">${(totalArea / 1000).toFixed(1)} тис.</div><div class="l">га (опрац.)</div></div>
      <div class="stat-card"><div class="n">${((state.PZF.totals_official?.area_ha || totalArea) / 1000).toFixed(1)} тис.</div><div class="l">га (офіц.)</div></div>
    </div>
    <p style="margin:0 0 14px;color:var(--muted);font-size:12.5px">
      Дані синхронізовано з офіційним переліком територій та обʼєктів ПЗФ Вінницької області
      станом на 01.01.2025. Кожен обʼєкт привʼязаний до нової адміністративно-територіальної структури —
      <b>6 районів</b> та <b>63 територіальні громади</b>.
      Площа фактична за офіційними даними — <b>${(state.PZF.totals_official?.effective_area_ha || 0).toLocaleString('uk-UA')} га</b>
      (різниця з сумарною — через перекриття обʼєктів різних категорій).
    </p>

    <div class="chart-section">
      <h3>Розподіл за категоріями</h3>
      ${cats.map(([k, v]) => `
        <div class="bar-row">
          <div class="lbl">${escapeHtml(k)}</div>
          <div class="bar"><div class="fill" style="width:${(v.count / maxCount * 100).toFixed(1)}%;background:${catColor(k)}"></div></div>
          <div class="v">${v.count}</div>
        </div>`).join('')}
    </div>

    <div class="chart-section">
      <h3>Площа ПЗФ за районами (га)</h3>
      ${rayons.map(([k, v]) => `
        <div class="bar-row">
          <div class="lbl">${escapeHtml(k)}</div>
          <div class="bar"><div class="fill" style="width:${(v.area / maxRArea * 100).toFixed(1)}%"></div></div>
          <div class="v">${v.area.toLocaleString('uk-UA', { maximumFractionDigits: 0 })}</div>
        </div>`).join('')}
    </div>

    <div class="chart-section">
      <h3>ТОП-10 типів обʼєктів</h3>
      ${types.map(([k, v]) => `
        <div class="bar-row">
          <div class="lbl">${escapeHtml(k)}</div>
          <div class="bar"><div class="fill" style="width:${(v.count / maxTCount * 100).toFixed(1)}%"></div></div>
          <div class="v">${v.count}</div>
        </div>`).join('')}
    </div>

    <div class="chart-section">
      <h3>Розподіл за значенням</h3>
      ${sigs.map(([k, v]) => `
        <div class="bar-row">
          <div class="lbl">${escapeHtml(k)}</div>
          <div class="bar"><div class="fill" style="width:${(v.count / recs.length * 100).toFixed(1)}%"></div></div>
          <div class="v">${v.count}</div>
        </div>`).join('')}
    </div>

    <div class="chart-section">
      <h3>Джерело координат</h3>
      ${srcs.map(([k, v]) => `
        <div class="bar-row">
          <div class="lbl">${escapeHtml(k)}</div>
          <div class="bar"><div class="fill" style="width:${(v.count / recs.length * 100).toFixed(1)}%"></div></div>
          <div class="v">${v.count}</div>
        </div>`).join('')}
    </div>

    <div class="chart-section">
      <h3>ТОП-10 землекористувачів</h3>
      ${orgs.map(([k, v]) => `
        <div class="bar-row">
          <div class="lbl">${escapeHtml(k)}</div>
          <div class="bar"><div class="fill" style="width:${(v / orgs[0][1] * 100).toFixed(1)}%"></div></div>
          <div class="v">${v}</div>
        </div>`).join('')}
    </div>
  `;
  document.getElementById('modal-body').innerHTML = html;
  document.getElementById('modal-bg').classList.add('open');
}

/* ============ Wire up events ============ */
function wireEvents() {
  document.getElementById('t-rayon').addEventListener('change', e => {
    if (e.target.checked) rayonLayer.addTo(map); else map.removeLayer(rayonLayer);
  });
  document.getElementById('t-otg').addEventListener('change', e => {
    if (e.target.checked) otgLayer.addTo(map); else map.removeLayer(otgLayer);
  });
  document.getElementById('t-pzf').addEventListener('change', e => {
    if (e.target.checked) markersGroup.addTo(map); else map.removeLayer(markersGroup);
  });
  document.getElementById('t-cluster').addEventListener('change', e => {
    map.removeLayer(markersGroup);
    markersGroup = e.target.checked ? clusterGroup : plainMarkersLayer;
    if (document.getElementById('t-pzf').checked) markersGroup.addTo(map);
    applyFilters();
  });

  document.getElementById('d-close').addEventListener('click', () => {
    document.getElementById('detail').classList.remove('open');
  });

  document.getElementById('reset').addEventListener('click', () => {
    document.getElementById('q').value = '';
    document.getElementById('f-rayon').value = '';
    document.getElementById('f-otg').value = '';
    document.getElementById('f-cat').value = '';
    document.getElementById('f-type').value = '';
    state.sig = '';
    document.querySelectorAll('#sig-badges .badge').forEach(b =>
      b.classList.toggle('active', b.dataset.sig === ''));
    rebuildOTGOptions();
    applyFilters();
    map.fitBounds(rayonLayer.getBounds(), { padding: [20, 20] });
  });

  ['q', 'f-rayon', 'f-otg', 'f-cat', 'f-type'].forEach(id => {
    document.getElementById(id).addEventListener('input', () => {
      if (id === 'f-rayon') {
        state.rayon = document.getElementById(id).value;
        rebuildOTGOptions();
      }
      applyFilters();
    });
  });

  document.querySelectorAll('#sig-badges .badge').forEach(b => {
    b.addEventListener('click', () => {
      document.querySelectorAll('#sig-badges .badge').forEach(x => x.classList.remove('active'));
      b.classList.add('active');
      state.sig = b.dataset.sig;
      applyFilters();
    });
  });

  document.getElementById('stats-open').addEventListener('click', openStats);
  document.getElementById('modal-close').addEventListener('click', () =>
    document.getElementById('modal-bg').classList.remove('open'));
  document.getElementById('modal-bg').addEventListener('click', e => {
    if (e.target.id === 'modal-bg') document.getElementById('modal-bg').classList.remove('open');
  });
}

/* ============ Init ============ */
async function init() {
  try {
    await loadData();
    buildMap();
    buildFilters();
    buildLegend();
    wireEvents();
    document.getElementById('hs-objects').textContent = state.PZF.records.length;
    document.getElementById('hs-area').textContent =
      ((state.PZF.totals_official?.area_ha
        || state.PZF.records.reduce((s, r) => s + (r.area || 0), 0)) / 1000).toFixed(1) + ' тис.';
    applyFilters();
    document.getElementById('loading').classList.add('hidden');
  } catch (err) {
    console.error('Init failed', err);
    document.getElementById('loading').innerHTML = `
      <div style="text-align:center;color:var(--muted);font-size:14px;max-width:480px">
        <div style="color:#c25450;font-weight:600;margin-bottom:8px">Не вдалося завантажити дані</div>
        <div>${escapeHtml(err.message || String(err))}</div>
        <div style="margin-top:14px;font-size:12px">
          Скоріше за все, файл відкрито через <code>file://</code>. Запустіть локальний сервер:
          <pre style="background:#fff;padding:10px;border-radius:8px;text-align:left;margin-top:8px">python3 server.py
# або
python3 -m http.server 8000</pre>
          і відкрийте <a href="http://localhost:8000/">http://localhost:8000</a>
        </div>
      </div>`;
  }
}


// --- Mobile adaptive panel toggles ---
function setupMobilePanels() {
  const aside = document.querySelector('aside');
  const asideToggle = document.getElementById('aside-toggle');
  const layersToggle = document.getElementById('layers-toggle');
  const legendToggle = document.getElementById('legend-toggle');
  const overlayControls = document.getElementById('overlay-controls');
  const legend = document.getElementById('legend');

  function isMobile() {
    return window.innerWidth <= 700;
  }

  function updatePanelVisibility() {
    if (isMobile()) {
      asideToggle.style.display = 'block';
      layersToggle.style.display = 'block';
      legendToggle.style.display = 'block';
      aside.classList.remove('open');
      overlayControls.classList.remove('open');
      legend.classList.remove('open');
    } else {
      asideToggle.style.display = 'none';
      layersToggle.style.display = 'none';
      legendToggle.style.display = 'none';
      aside.classList.remove('open');
      overlayControls.classList.remove('open');
      legend.classList.remove('open');
    }
  }


  asideToggle.addEventListener('click', () => {
    const opened = aside.classList.toggle('open');
    asideToggle.classList.toggle('open', opened);
    overlayControls.classList.remove('open');
    legend.classList.remove('open');
    layersToggle.classList.remove('open');
    legendToggle.classList.remove('open');
  });
  layersToggle.addEventListener('click', () => {
    const opened = overlayControls.classList.toggle('open');
    layersToggle.classList.toggle('open', opened);
    aside.classList.remove('open');
    legend.classList.remove('open');
    asideToggle.classList.remove('open');
    legendToggle.classList.remove('open');
  });
  legendToggle.addEventListener('click', () => {
    const opened = legend.classList.toggle('open');
    legendToggle.classList.toggle('open', opened);
    aside.classList.remove('open');
    overlayControls.classList.remove('open');
    asideToggle.classList.remove('open');
    layersToggle.classList.remove('open');
  });

  // Закривати панелі при зміні розміру
  window.addEventListener('resize', updatePanelVisibility);
  updatePanelVisibility();
}

document.addEventListener('DOMContentLoaded', () => {
  init();
  setupMobilePanels();
});
