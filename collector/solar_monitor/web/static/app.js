/* solar-monitor UI — vanilla JS, no build step. SolarAssistant-like layout. */
'use strict';

const TOKEN = new URLSearchParams(location.search).get('token') || '';
function api(p) {
  let url = p;
  // per-site endpoints get ?site= when a non-default site is selected
  if (currentSite && META.site && currentSite !== META.site &&
      /^\/api\/v1\/(state|stream|history|energy|settings|connection|battery|rules|reload_settings|meta)/.test(p)) {
    url += (url.includes('?') ? '&' : '?') + 'site=' + encodeURIComponent(currentSite);
  }
  if (TOKEN) url += (url.includes('?') ? '&' : '?') + 'token=' + encodeURIComponent(TOKEN);
  return url;
}

let META = { metrics: {}, info: {}, settings: {} };
let currentSite = localStorage.getItem('solar.site') || new URLSearchParams(location.search).get('site') || '';
let STATE = {};
let view = 'overview';
let energyRange = localStorage.getItem('solar.energyRange') || '7d';

const $ = (id) => document.getElementById(id);

/* ---------------------------------------------------------------- helpers */
const UNIT_KEYS = { W: 'unit.W', kWh: 'unit.kWh', V: 'unit.V', A: 'unit.A', '%': 'unit.pct',
  C: 'unit.C', Hz: 'unit.Hz', VA: 'unit.VA', min: 'unit.min' };
const unit = (u) => (u ? t(UNIT_KEYS[u] || u) : '');

function fmt(v, digits) {
  if (v === null || v === undefined || v === '') return '—';
  if (typeof v === 'boolean') return v ? 'да' : 'нет';
  if (typeof v !== 'number') return String(v);
  if (digits === undefined) {
    const a = Math.abs(v);
    digits = a >= 100 ? 0 : a >= 10 ? 1 : 2;
  }
  return v.toLocaleString('ru-RU', { maximumFractionDigits: digits });
}
const power = (w) => (w === null || w === undefined ? '—'
  : Math.abs(w) >= 1000 ? fmt(w / 1000, 2) + ' ' + t('unit.kW')
    : fmt(w, 0) + ' ' + t('unit.W'));
const esc = (s) => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;')
  .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
const has = (k) => STATE[k] !== undefined && STATE[k] !== null;
const hasPv2 = () => STATE.has_mppt2 === 1 ||
  (STATE.pv_voltage_2 || 0) > 20 || (STATE.pv_power_2 || 0) > 50;

const ICONS = {
  solar: '<circle cx="12" cy="12" r="4" fill="currentColor" stroke="none"/><path d="M12 2v2.4M12 19.6V22M2 12h2.4M19.6 12H22M4.9 4.9l1.7 1.7M17.4 17.4l1.7 1.7M19.1 4.9l-1.7 1.7M6.6 17.4l-1.7 1.7"/>',
  battery: '<rect x="2" y="7" width="17" height="10" rx="2"/><path d="M21 10.5v3"/>',
  grid: '<path d="M12 3l5 18M12 3L7 21M5 21h14M7 14h10M8 9h8"/>',
  load: '<path d="M3 11l9-7 9 7"/><path d="M6 10v10h12V10"/>',
  inverter: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M13 8l-3 5h3l-2 4"/>',
  bolt: '<path d="M13 2L4 14h6l-1 8 9-12h-6l1-8z"/>',
  temp: '<path d="M12 3a2 2 0 00-2 2v7a4 4 0 104 0V5a2 2 0 00-2-2z"/>',
  alert: '<path d="M12 3l9 17H3L12 3z"/><path d="M12 9v5M12 17h.01"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
};
const icon = (name) => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
  stroke-width="1.8" stroke-linecap="round">${ICONS[name] || ICONS.bolt}</svg>`;

/* ---------------------------------------------------------------- gauges */
const GAUGES = [
  { key: 'pv', label: 'flow.pv', cls: 'yellow', icon: 'solar' },
  { key: 'load', label: 'flow.load', cls: 'red', icon: 'load' },
  { key: 'batt', label: 'flow.battery', cls: 'green', icon: 'battery' },
  { key: 'grid', label: 'flow.grid', cls: 'blue', icon: 'grid' },
];

function buildGauges() {
  $('gauges').innerHTML = GAUGES.map((g) => `
    <div class="gauge">
      <svg viewBox="0 0 200 132">
        <path class="track" d="M28 104 A72 72 0 0 1 172 104"/>
        <path class="fill ${g.cls}" data-fill="${g.key}" d="M28 104 A72 72 0 0 1 172 104"/>
        <text class="g-value" data-value="${g.key}" x="100" y="88">—</text>
        <text class="g-unit" data-unit="${g.key}" x="100" y="106"></text>
        <text class="g-label" x="100" y="126">${t(g.label)}</text>
      </svg>
    </div>`).join('');
  document.querySelectorAll('[data-fill]').forEach((el) => {
    const len = el.getTotalLength();
    el.dataset.len = len;
    el.style.strokeDasharray = `0 ${len}`;
  });
}

function setGauge(key, pct, value, unitStr) {
  const fill = document.querySelector(`[data-fill="${key}"]`);
  const val = document.querySelector(`[data-value="${key}"]`);
  const un = document.querySelector(`[data-unit="${key}"]`);
  if (!fill) return;
  const len = Number(fill.dataset.len) || 240;
  const p = Math.max(0, Math.min(100, pct || 0));
  fill.style.strokeDasharray = `${(len * p) / 100} ${len}`;
  val.textContent = value;
  if (un) un.textContent = unitStr || '';
}

function renderGauges() {
  const rated = STATE.rated_power || 11000;
  const soc = STATE.battery_state_of_charge;
  setGauge('pv', (100 * (STATE.pv_power || 0)) / rated, fmt((STATE.pv_power || 0) / 1000, 2), t('unit.kW'));
  setGauge('load', (100 * (STATE.load_power || 0)) / rated, fmt((STATE.load_power || 0) / 1000, 2), t('unit.kW'));
  setGauge('grid', (100 * Math.abs(STATE.grid_power || 0)) / rated, fmt(Math.abs(STATE.grid_power || 0) / 1000, 2), t('unit.kW'));
  setGauge('batt', soc || 0, fmt(soc, 0), '%');
}

/* ---------------------------------------------------------------- statuses */
function status(name, label, value, unitStr, tone) {
  return `<div class="status">
    <div class="ico">${icon(name)}</div>
    <div>
      <div class="label">${esc(label)}</div>
      <div class="value ${tone || ''}">${value}${unitStr ? `<small>${esc(unitStr)}</small>` : ''}</div>
    </div>
  </div>`;
}

function metricStatus(key, iconName, label) {
  const m = META.metrics[key] || META.info[key] || {};
  const v = STATE[key];
  const shown = m.unit === 'W' ? power(v) : fmt(v, m.unit === 'kWh' ? 2 : undefined);
  return status(iconName, label || m.name || key, shown, m.unit === 'W' ? '' : unit(m.unit));
}

/* ---------------------------------------------------------------- overview */
function pickInverterIcon() {
  // тип берём из QPIRI: output_mode (single/parallel), machine_type (grid tie/off grid/hybrid)
  const mode = String(STATE.output_mode || '').toLowerCase();
  const machine = String(STATE.machine_type || '').toLowerCase();
  const power = STATE.rated_power ? `${Math.round(STATE.rated_power / 1000)} ${t('unit.kW')}` : '';
  if (mode.includes('parallel')) return ['#ico-inverter-parallel', t('inv.parallel'), power];
  if (machine.includes('hybrid')) return ['#ico-inverter-hybrid', t('inv.hybrid'), power];
  if (machine.includes('grid tie')) return ['#ico-inverter-hybrid', t('inv.gridtie'), power];
  return ['#ico-inverter-offgrid', t('inv.offgrid'), power];
}

const q = (key) => Array.from(document.querySelectorAll(`[data-k="${key}"]`));
const qb = (part) => Array.from(document.querySelectorAll(`[data-bat="${part}"]`));
function setKey(key, value, attr) {
  q(key).forEach((el) => {
    if (attr) el.setAttribute(attr, value);
    else el.textContent = value;
  });
}

function renderBatteryIcon() {
  // заливка АКБ по уровню заряда: 38 — внутренняя высота, 9 — верх заливки
  const socRaw = STATE.battery_state_of_charge;
  const soc = socRaw === undefined || socRaw === null ? null : Math.max(0, Math.min(100, Number(socRaw)));
  const bodies = qb('body');
  const fills = qb('fill');
  const pcts = qb('pct');
  if (!bodies.length || !fills.length || !pcts.length) return;
  const color = soc === null ? 'var(--border-strong)'
    : soc >= 60 ? '#3e9e00' : soc >= 30 ? '#e3a60d' : '#f9584b';
  const inner = 38;
  const h = soc === null ? 0 : Math.round((inner * soc) / 100);
  bodies.forEach((b) => b.setAttribute('stroke', color));
  fills.forEach((f) => {
    f.setAttribute('fill', color);
    f.setAttribute('height', String(h));
    f.setAttribute('y', String(9 + inner - h));
  });
  pcts.forEach((p) => {
    p.textContent = soc === null ? '—' : String(Math.round(soc));
    p.setAttribute('fill', soc !== null && soc >= 45 ? '#ffffff' : 'var(--heading)');
  });
}

function renderFlow() {
  const pv = STATE.pv_power || 0, load = STATE.load_power || 0;
  const grid = STATE.grid_power || 0, batt = STATE.battery_power || 0;

  setKey('v-pv', power(pv));
  setKey('v-grid', power(grid));
  setKey('v-load', power(load));
  setKey('v-batt', power(Math.abs(batt)));
  const amps = Math.abs(Number(STATE.battery_current) || 0);
  const battState = batt < -20 ? t('batt.discharge') : batt > 20 ? t('batt.charge') : t('batt.idle');
  setKey('v-batt-cap', batt === 0 && !amps ? '—'
    : `${battState} · ${fmt(amps, 1)} ${t('unit.A')}`);
  renderBatteryIcon();
  // в узле инвертора — режим работы (SOC живёт в узле АКБ и в gauge)
  setKey('v-inv', STATE.device_mode || '—');
  q('v-inv').forEach((el) => { el.style.fontSize = '15px'; });

  const wire = (name, on, cls) => {
    document.querySelectorAll(`[data-wire="${name}"]`).forEach((el) => {
      el.classList.toggle('on', !!on);
      ['pv', 'grid', 'batt', 'load'].forEach((c) => el.classList.remove(c + '-on'));
      if (on) el.classList.add(cls + '-on');
    });
  };
  wire('pv', pv > 20, 'pv');
  wire('load', load > 20, 'load');
  wire('grid', Math.abs(grid) > 20, 'grid');
  wire('batt', Math.abs(batt) > 20, 'batt');
  // разряд = поток ИЗ АКБ в инвертор: анимация в обратную сторону
  document.querySelectorAll('[data-wire="batt"]').forEach((el) => {
    el.classList.toggle('reverse', batt < -20);
  });

  // иконка и подпись инвертора — по типу, который сообщает сам инвертор (QPIRI)
  const [iconHref, invType, invPower] = pickInverterIcon();
  q('ico-inv').forEach((el) => {
    if (el.getAttribute('href') !== iconHref) el.setAttribute('href', iconHref);
  });
  const shortCaption = window.matchMedia('(max-width: 700px)').matches;
  setKey('c-inv', (shortCaption ? [invType, invPower] : [t('flow.inverter'), invType, invPower])
    .filter(Boolean).join(' · '));

  // два входа PV у инвертора -> две панели на схеме
  const dual = hasPv2();
  q('pv-single').forEach((el) => { el.style.display = dual ? 'none' : ''; });
  q('pv-dual').forEach((el) => { el.style.display = dual ? '' : 'none'; });
  setKey('l-pv', dual ? t('flow.pv_dual') : t('flow.pv'));

}

function renderOverview() {
  const ovAlert = $('overview-alert');
  const data = bmsAlertHtml();
  if (ovAlert) {
    if (data) { ovAlert.style.display = ''; ovAlert.className = 'card ' + data.tone; ovAlert.innerHTML = data.html; }
    else { ovAlert.style.display = 'none'; ovAlert.innerHTML = ''; }
  }
  renderHeaderAlert();
  renderGauges();
  renderFlow();

  $('today-statuses').innerHTML = [
    ['pv_energy_today', 'solar', t('energy.pv')],
    ['load_energy_today', 'load', t('energy.load')],
    ['grid_energy_today', 'grid', t('energy.grid')],
    ['battery_charge_today', 'battery', t('energy.charge')],
    ['battery_discharge_today', 'battery', t('energy.discharge')],
  ].map(([key, ico, label]) => `<div class="energy-row">
      <div class="ico">${icon(ico)}</div>
      <div class="lbl">${esc(label)}</div>
      <div class="val">${fmt(STATE[key], 2)}<small>${t('unit.kWh')}</small></div>
    </div>`).join('')
    + (has('pv_forecast_today') ? `<div class="energy-row">
        <div class="ico">${icon('solar')}</div>
        <div class="lbl">${t('energy.forecast')}</div>
        <div class="val">${fmt(STATE.pv_forecast_today, 2)}<small>${t('unit.kWh')}</small></div>
      </div>` : '');

  // --- массивы PV: показываем только если инвертор их реально отдаёт ---
  const card = $('card-pv-arrays');
  if (hasPv2()) {
    card.style.display = '';
    $('pv-array-statuses').innerHTML = [
      status('solar', `PV1 · ${t('ov.gauges')}`, power(STATE.pv_power_1), ''),
      status('solar', 'PV1 · напряжение', fmt(STATE.pv_voltage_1, 1), 'В'),
      status('solar', 'PV1 · ток', fmt(STATE.pv_current_1, 1), 'А'),
      status('solar', 'PV2 · мощность', power(STATE.pv_power_2), ''),
      status('solar', 'PV2 · напряжение', fmt(STATE.pv_voltage_2, 1), 'В'),
      status('solar', 'PV2 · ток', fmt(STATE.pv_current_2, 1), 'А'),
    ].join('');
  } else {
    card.style.display = 'none';
  }

  const soc = STATE.battery_state_of_charge;
  const warn = has('warnings') && STATE.warnings !== 'none' ? STATE.warnings : null;
  $('live-statuses').innerHTML = [
    status('inverter', t('state.mode'), esc(STATE.device_mode || '—'), ''),
    status('battery', t('state.battery'), fmt(STATE.battery_voltage, 2), 'В', soc < 30 ? 'yellow' : 'green'),
    status('battery', t('state.soc'), fmt(soc, 0), '%', soc < 30 ? 'yellow' : 'green'),
    status('bolt', t('state.batt_power'), power(Math.abs(STATE.battery_power || 0)),
      (STATE.battery_power || 0) > 0 ? t('batt.charge') : t('batt.discharge')),
    status('temp', t('state.temp'), fmt(STATE.temperature, 0), '°C'),
    warn ? status('alert', t('state.warnings'), esc(warn), '', 'red')
         : status('alert', t('state.warnings'), t('state.none'), '', 'green'),
  ].join('');
}

/* ---------------------------------------------------------------- tables */
function rows(keys, meta) {
  return keys.filter((k) => has(k)).map((k) => {
    const m = (meta && meta[k]) || META.metrics[k] || META.info[k] || { name: k, unit: '' };
    const v = STATE[k];
    const shown = m.unit === 'W' ? fmt(v, 0) : fmt(v);
    let tone = '';
    if (k === 'battery_state_of_charge') tone = v < 30 ? 'yellow' : 'green';
    if (k === 'mains_ok') tone = v ? 'green' : 'red';
    return `<tr><td class="k">${esc(m.name)}${tone ? `<span class="pill-label ${tone}">${v ? 'есть' : 'нет'}</span>` : ''}</td>
      <td class="v">${shown}</td><td class="u">${esc(unit(m.unit))}</td></tr>`;
  }).join('');
}

function renderInverter() {
  $('tbl-inverter').innerHTML = rows([
    'device_mode', 'pv_power', 'pv_power_1', 'pv_power_2',
    'pv_voltage_1', 'pv_current_1', 'pv_voltage_2', 'pv_current_2',
    'ac_output_voltage', 'ac_output_frequency', 'load_power', 'load_apparent_power',
    'load_percentage', 'bus_voltage', 'temperature', 'warnings',
  ]);
  $('tbl-inverter-info').innerHTML = rows([
    'rated_power', 'rated_battery_voltage', 'rated_grid_voltage', 'rated_ac_output_voltage',
    'rated_ac_output_frequency', 'rated_ac_output_current', 'battery_type',
    'input_voltage_range', 'machine_type', 'max_charging_time', 'max_discharge_current',
    'serial_number',
  ], META.info);
}

let BMS_CATALOG = null;
let SETTINGS_CACHE = null;

async function loadBmsConfig() {
  const host = $('bms-config');
  if (!BMS_CATALOG) {
    try {
      const d = await (await fetch(api('/api/v1/battery/config'))).json();
      BMS_CATALOG = d;
    } catch (e) { return; }
  }
  const sel = $('bms-brand');
  const cfg = BMS_CATALOG.config || {};
  const groups = {};
  (BMS_CATALOG.catalog || []).forEach((item) => {
    (groups[item.group] = groups[item.group] || []).push(item);
  });
  sel.innerHTML = Object.entries(groups).map(([group, items]) =>
    `<optgroup label="${esc(group)}">` + items.map((i) =>
      `<option value="${esc(i.id)}" ${i.supported ? '' : 'disabled'}
        ${i.id === cfg.brand ? 'selected' : ''}>${esc(i.brand)}${i.supported ? '' : ' — пока нет протокола'}</option>`
    ).join('') + '</optgroup>').join('');
  if (cfg.port) $('bms-port').value = cfg.port;
  if (cfg.baud !== undefined) $('bms-baud').value = cfg.baud;
  if (cfg.unit_id !== undefined) $('bms-unit').value = cfg.unit_id;
  if (cfg.capacity_ah) $('bms-capacity').value = cfg.capacity_ah;
  if (cfg.interface) $('bms-can').value = cfg.interface;
  host.style.display = host.style.display === 'none' ? '' : 'none';
}

async function applyBms(sourceOverride) {
  const msg = $('bms-msg');
  msg.className = 'msg'; msg.textContent = 'подключаю…';
  const body = sourceOverride || {
    brand: $('bms-brand').value,
    port: $('bms-port').value,
    baud: Number($('bms-baud').value) || 9600,
    unit_id: Number($('bms-unit').value) || 1,
    capacity_ah: Number($('bms-capacity').value) || null,
    interface: $('bms-can').value || 'can0',
  };
  try {
    const r = await fetch(api('/api/v1/battery/config'), {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const d = await r.json();
    if (!r.ok) {
      msg.className = 'msg err'; msg.textContent = '✗ ' + (d.error || r.status);
      return;
    }
    msg.className = 'msg ok';
    msg.textContent = '✓ источник: ' + (d.driver || d.source);
    BMS_CATALOG = null;
    setTimeout(() => { loadBattery(); }, 1500);
  } catch (e) {
    msg.className = 'msg err'; msg.textContent = '✗ ' + e;
  }
}

let protocolTimer = null;

async function renderProtocolWatch() {
  let d;
  try { d = await (await fetch(api('/api/v1/battery/protocol'))).json(); }
  catch (e) { return; }
  const row = $('protocol-watch-row');
  const msg = $('protocol-watch');
  const state = d.state;
  if (!state) { row.style.display = 'none'; return; }
  row.style.display = '';
  if (state === 'checking') {
    msg.className = 'msg';
    msg.textContent = `Проверяю связь с АКБ по протоколу «${d.current}» (обычно 20–30 с): осталось ${d.seconds_left} с`
      + (d.bms_connected === 1 ? ' · BMS на связи' : ' · BMS не отвечает');
    if (!protocolTimer) protocolTimer = setInterval(renderProtocolWatch, 2500);
  } else {
    if (protocolTimer) { clearInterval(protocolTimer); protocolTimer = null; }
    msg.className = 'msg ' + (state === 'confirmed' ? 'ok' : 'err');
    msg.textContent = state === 'confirmed'
      ? `✓ протокол «${d.current}» подтверждён, BMS на связи`
      : `↩️ протокол возвращён на «${d.previous}» (${d.reason === 'timeout' ? 'нет связи с АКБ' : 'вручную'})`;
    row.querySelector('#protocol-confirm').style.display = state === 'checking' ? '' : 'none';
    row.querySelector('#protocol-cancel').style.display = state === 'checking' ? '' : 'none';
  }
}

let CODES = null;
let CONN = null;

// Какие кнопки показывать для кода (см. мануал: 60/69/70/71 — BMS, 62 — связь)
const CODE_ACTIONS = {
  60: ['user', 'agm', 'reload'],
  69: ['user', 'agm', 'reload'],
  70: ['reload'],
  71: ['user', 'agm', 'reload'],
  62: ['bmssettings', 'reload'],
};
const ACTION_LABEL = {
  user: 'User (PBT02)',
  agm: 'AGM (PBT00)',
  reload: 'Перечитать',
  bmssettings: 'Настройки BMS',
};

async function setBatteryType(label) {
  const msg = $('codes-msg') || $('inv-bms-msg');
  const res = await fetch(api('/api/v1/settings'), {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ key: 'battery_type', value: label, verified: true }),
  });
  const data = await res.json();
  if (msg) {
    msg.className = 'msg ' + (data.ok ? 'ok' : 'err');
    msg.textContent = (data.ok ? '✓ ' : '✗ ') + data.message;
  }
  if (data.ok) {
    SETTINGS_CACHE = null;
    setTimeout(() => { loadBattery(); loadBmsEvents(); }, 1500);
  }
  return data;
}

async function runCodeAction(kind) {
  const msg = $('codes-msg');
  if (kind === 'bmssettings') {
    location.hash = '#/battery';
    setTimeout(() => { const b = $('bms-config-toggle'); if (b) b.click(); }, 300);
    return;
  }
  if (kind === 'reload') {
    msg.className = 'msg'; msg.textContent = 'читаю настройки…';
    const r = await fetch(api('/api/v1/reload_settings'), { method: 'POST' });
    const d = await r.json();
    msg.className = 'msg ' + (d.ok ? 'ok' : 'err');
    msg.textContent = (d.ok ? '✓ ' : '✗ ') + d.message;
    return;
  }
  const label = kind === 'user' ? 'User' : 'AGM';
  if (!window.confirm(`Переключить протокол BMS на «${label}»?\n\n`
    + 'User/AGM отключает управление по BMS: инвертор будет заряжать без её лимитов и защит.')) return;
  await setBatteryType(label);
}

function codeActionsCell(codeStr) {
  const code = Number(codeStr);
  const kinds = CODE_ACTIONS[code];
  if (!kinds) return '<td class="k">—</td>';
  return '<td class="k">' + kinds.map((k) =>
    `<button class="pill" data-code-action="${k}" style="font-size:.8em;padding:3px 8px">${ACTION_LABEL[k]}</button>`
  ).join(' ') + '</td>';
}

async function loadCodes() {
  if (!CODES) {
    try { CODES = await (await fetch(api('/api/v1/codes'))).json(); }
    catch (e) { return; }
  }
  const filter = ($('codes-filter').value || '').trim().toLowerCase();
  const match = (row) => !filter || String(row.code).includes(filter)
    || (row.event || '').toLowerCase().includes(filter)
    || (row.action || '').toLowerCase().includes(filter);
  const render = (rows) => rows.filter(match).map((r) => `<tr>
      <td class="v">${r.code}</td>
      <td>${esc(r.event)}</td>
      <td class="k" style="font-size:.86em">${esc(r.action || '')}</td>
      ${codeActionsCell(r.code)}</tr>`).join('');
  let shown = 0;
  for (const [group, key] of [['bms', 'codes-bms'], ['faults', 'codes-faults'],
                              ['warnings', 'codes-warnings'], ['parallel', 'codes-parallel']]) {
    const rows = CODES[group] || [];
    shown += rows.filter(match).length;
    const host = $(key);
    if (host) host.innerHTML = render(rows) || '<tr><td colspan="4" class="empty">нет совпадений</td></tr>';
  }
  $('codes-count').textContent = t('codes.count', { n: shown });
  document.querySelectorAll('[data-code-action]').forEach((btn) => {
    btn.addEventListener('click', () => runCodeAction(btn.dataset.codeAction));
  });
  $('codes-note').textContent = CODES.note || '';
}

async function loadConnection() {
  let d;
  try {
    const r = await fetch(api('/api/v1/connection'));
    d = await r.json();
    if (!r.ok || !d.modes) throw new Error(d.error || ('HTTP ' + r.status));
  } catch (e) {
    const msg = $('conn-msg');
    if (msg) { msg.className = 'msg err'; msg.textContent = '✗ не удалось получить настройки подключения: ' + e; }
    const sel = $('conn-mode');
    if (sel && !sel.options.length) sel.innerHTML = '<option>— недоступно —</option>';
    return;
  }
  CONN = d;
  const cfg = d.config || {};

  // статус
  const st = d.stats || {};
  $('conn-status').innerHTML = [
    status('inverter', t('conn.transport'), esc(d.transport || d.current || '—'), ''),
    status('bolt', t('conn.source'), d.source === 'sa-mqtt' ? t('conn.import') : t('conn.direct'), ''),
    status('clock', t('conn.link'), st.online ? t('conn.yes') : t('conn.no'), '', st.online ? 'green' : 'red'),
    status('bolt', t('conn.exchange'), `rx ${st.rx ?? '—'} / tx ${st.tx ?? '—'}`, ''),
  ].join('');

  // список режимов
  const modes = d.modes || {};
  $('conn-mode').innerHTML = Object.entries(modes).map(([k, v]) =>
    `<option value="${k}" ${k === cfg.mode ? 'selected' : ''}>${esc(t(`conn.mode.${k}`))}</option>`).join('');

  // найденные устройства
  const ports = d.ports || {};
  $('conn-ports').innerHTML = (ports.serial || []).map((p) => `<option value="${esc(p)}">`).join('');
  $('conn-hid').innerHTML = (ports.hid || []).map((p) => `<option value="${esc(p)}">`).join('');

  // значения
  $('conn-tcp-host').value = cfg.tcp_host || '';
  $('conn-tcp-port').value = cfg.tcp_port || 9999;
  $('conn-serial-port').value = cfg.serial_port || '';
  $('conn-serial-baud').value = cfg.serial_baud || 2400;
  $('conn-hid-device').value = cfg.hid_device || '';
  $('conn-topic').value = cfg.trans_topic || 'inverter/';

  const notice = $('conn-notice');
  const importing = d.switchable === false;
  if (importing) {
    notice.style.display = '';
    notice.innerHTML = 'Сейчас данные импортируются из <b>SolarAssistant</b> (sa-mqtt). '
      + 'Нажатие «Применить» переключит этот сайт на <b>прямое подключение</b> и перезапустит '
      + 'его коллектор. Важно: USB-порт инвертора занят SolarAssistant, а коллектор этого сайта '
      + 'работает на VDS (USB там нет) — поэтому «прямое» подключение возможно только по сети '
      + '(TCP: ser2net на Orange Pi) либо после переноса коллектора на сам Orange Pi.';
  } else {
    notice.style.display = 'none';
  }
  syncConnFields();
}

function syncConnFields() {
  const mode = $('conn-mode').value;
  const show = (id, on) => { const el = $(id); if (el) el.style.display = on ? '' : 'none'; };
  show('conn-f-tcp-host', mode === 'tcp');
  show('conn-f-tcp-port', mode === 'tcp');
  show('conn-f-serial-port', mode === 'serial');
  show('conn-f-serial-baud', mode === 'serial');
  show('conn-f-hid', mode === 'hid');
  show('conn-f-topic', mode === 'mqtt');
  const hint = t(`conn.hint.${mode}`);
  $('conn-hint').textContent = hint;
}

function connFormBody() {
  return {
    mode: $('conn-mode').value,
    tcp_host: $('conn-tcp-host').value.trim(),
    tcp_port: Number($('conn-tcp-port').value) || 9999,
    serial_port: $('conn-serial-port').value.trim(),
    serial_baud: Number($('conn-serial-baud').value) || 2400,
    hid_device: $('conn-hid-device').value.trim(),
    trans_topic: $('conn-topic').value.trim(),
  };
}

async function probeConnection() {
  const msg = $('conn-msg');
  msg.className = 'msg'; msg.textContent = t('conn.checking');
  const r = await fetch(api('/api/v1/connection/probe'), {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(connFormBody()),
  });
  const d = await r.json();
  if (d.ok) {
    msg.className = 'msg ok';
    msg.textContent = `✓ ${d.target}: АКБ ${d.battery_voltage} В, сеть ${d.grid_voltage} В, `
      + `нагрузка ${d.load_power} Вт${d.serial_number ? ', S/N ' + d.serial_number : ''} · ${d.latency_ms} мс`;
  } else {
    msg.className = 'msg err';
    msg.textContent = '✗ ' + (d.error || 'нет ответа');
  }
}

async function applyConnection() {
  const msg = $('conn-msg');
  const importing = CONN && CONN.switchable === false;
  const question = importing
    ? 'Перевести этот сайт с импорта SolarAssistant на прямое подключение?\n\n'
      + 'Коллектор будет перезапущен. SolarAssistant при этом продолжит работать и, возможно, '
      + 'уже занимает порт инвертора — тогда прямое подключение не установится.'
    : 'Переключить подключение к инвертору?\n\n'
      + 'Опрос прервётся на пару секунд, данные продолжат идти с нового источника.';
  if (!window.confirm(question)) return;
  msg.className = 'msg'; msg.textContent = t('conn.applying');
  const r = await fetch(api('/api/v1/connection'), {
    method: 'PUT', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(connFormBody()),
  });
  const d = await r.json();
  msg.className = 'msg ' + (r.ok ? 'ok' : 'err');
  if (r.ok && d.restarting) {
    msg.textContent = t('conn.restarting');
    setTimeout(pollAfterRestart, 4000);
    return;
  }
  msg.textContent = r.ok ? '✓ подключено: ' + d.transport : '✗ ' + (d.error || r.status);
  if (r.ok) setTimeout(() => { loadConnection(); loadBmsConfig(); }, 1500);
}

async function pollAfterRestart(tries = 0) {
  const msg = $('conn-msg');
  try {
    const r = await fetch(api('/api/v1/connection'));
    if (r.ok) {
      msg.className = 'msg ok';
      msg.textContent = t('conn.restarted');
      loadConnection();
      return;
    }
  } catch (e) { /* ещё не поднялся */ }
  if (tries < 15) {
    if (msg) msg.textContent = t('conn.restart_wait', { n: tries + 1 });
    setTimeout(() => pollAfterRestart(tries + 1), 3000);
  } else if (msg) {
    msg.className = 'msg err';
    msg.textContent = t('conn.restart_fail');
  }
}

async function loadBmsEvents() {
  let d;
  try { d = await (await fetch(api('/api/v1/battery/events?limit=30&hours=24'))).json(); }
  catch (e) { return; }
  const s = d.summary || { codes: [] };
  const sum = $('bms-summary');
  if (s.codes && s.codes.length) {
    sum.innerHTML = 'за сутки: ' + s.codes.map((c) =>
      `<b>код ${c.code}</b> — ${c.count}× / ${c.minutes} мин`).join(' · ');
    sum.className = '';
  } else {
    sum.textContent = 'за сутки ограничений от BMS не было';
    sum.className = 'muted';
  }
  const rows = (d.events || []).map((e) => {
    const dur = e.previous_duration_s !== undefined && e.previous !== undefined && e.previous !== 0
      ? `${Math.round(e.previous_duration_s / 60 * 10) / 10} мин` : '—';
    return `<tr>
      <td class="k">${esc(e.time)}</td>
      <td class="v">${e.code}</td>
      <td>${esc(e.title || (e.code === 0 ? 'норма' : ''))}${e.note ? ` <span class="pill-label">${esc(e.note)}</span>` : ''}</td>
      <td class="u">${dur}</td></tr>`;
  }).join('');
  $('bms-events').innerHTML = rows;
  $('bms-events-empty').style.display = rows ? 'none' : '';
}

const BMS_CODE_TEXT = {
  60: ['не разрешает заряд и разряд', 'инвертор остановил заряд и разряд АКБ'],
  69: ['не разрешает заряд', 'инвертор прекратил заряд АКБ'],
  70: ['требует заряжать', 'инвертор заряжает АКБ по требованию BMS'],
  71: ['не разрешает разряд', 'инвертор прекратил разряд АКБ'],
};

function bmsAlertHtml() {
  const code = Number(STATE.bms_code || 0);
  const linkDown = STATE.inverter_bms_connected === 0 && STATE.inverter_bms_status;
  if (code) {
    const [title, effect] = BMS_CODE_TEXT[code] || ['ограничил режим', ''];
    return { tone: 'bad', html: `<div class="body" style="padding:12px 14px">
      <b>⚠️ Код ${code} на дисплее инвертора — BMS ${esc(title)}</b>
      <div class="muted" style="font-size:.9em;margin-top:4px">
        ${esc(effect.charAt(0).toUpperCase() + effect.slice(1))}: это защита батареи
        (полный пакет, напряжение ячейки, температура), а не ошибка протокола.
        Обычно снимается само. Принудительно — режим <b>User</b> или <b>AGM</b>.
      </div></div>`, short: `код ${code}` };
  }
  if (linkDown) {
    return { tone: '', html: `<div class="body" style="padding:12px 14px">
      <b>🔌 Связи с BMS нет — на дисплее может быть код 62.</b>
      <div class="muted" style="font-size:.9em;margin-top:4px">
        По мануалу: buzzer через 3 мин, через 10 мин инвертор прекращает заряд и разряд АКБ.
        Проверьте протокол (подключение занимает 20–30 с) или выберите User/AGM.
      </div></div>`, short: 'нет связи BMS' };
  }
  return null;
}

function renderHeaderAlert() {
  const badge = $('header-alert');
  if (!badge) return;
  const alert = bmsAlertHtml();
  badge.style.display = alert ? '' : 'none';
  if (alert) {
    badge.className = 'alert-badge' + (alert.tone === 'bad' ? '' : ' ok');
    badge.textContent = '⚠ ' + alert.short;
    badge.title = 'Нажмите, чтобы открыть АКБ';
    badge.onclick = () => { location.hash = '#/battery'; };
  }
}

async function renderInverterBms() {
  const state = $('inv-bms-status');
  const host = $('inv-bms-statuses');
  const cur = STATE.battery_type;
  const link = STATE.inverter_bms_status;

  if (!SETTINGS_CACHE) {
    try { SETTINGS_CACHE = await (await fetch(api('/api/v1/settings'))).json(); } catch (e) { SETTINGS_CACHE = []; }
  }
  const spec = (SETTINGS_CACHE || []).find((x) => x.key === 'battery_type');
  const sel = $('inv-bms-type');
  if (spec && !sel.dataset.filled) {
    sel.innerHTML = spec.options.map((o) =>
      `<option value="${esc(o.label)}" ${o.label === cur ? 'selected' : ''}>${esc(o.label)}</option>`).join('');
    sel.dataset.filled = '1';
  }
  if (spec) sel.value = cur || spec.value;

  const alert = $('bms-alert');
  const alertData = bmsAlertHtml();
  if (alertData) {
    alert.style.display = '';
    alert.className = 'card ' + alertData.tone;
    alert.innerHTML = alertData.html;
  } else {
    alert.style.display = 'none';
    alert.innerHTML = '';
  }

  state.innerHTML = `Текущий протокол: <b>${esc(cur || '—')}</b>`
    + (link ? ` · BMS: <b>${esc(link)}</b>` : ' · BMS-данных нет (команда QBMS не поддерживается)');

  const blocks = [];
  if (STATE.inverter_bms_soc !== undefined) blocks.push(status('battery', 'SOC от BMS', fmt(STATE.inverter_bms_soc, 0), '%', STATE.inverter_bms_soc < 30 ? 'yellow' : 'green'));
  if (STATE.inverter_bms_bulk_voltage !== undefined) blocks.push(status('bolt', 'Bulk от BMS', fmt(STATE.inverter_bms_bulk_voltage, 1), 'В'));
  if (STATE.inverter_bms_float_voltage !== undefined) blocks.push(status('bolt', 'Float от BMS', fmt(STATE.inverter_bms_float_voltage, 1), 'В'));
  if (STATE.inverter_bms_cutoff_voltage !== undefined) blocks.push(status('bolt', 'Cut-off от BMS', fmt(STATE.inverter_bms_cutoff_voltage, 1), 'В'));
  if (STATE.inverter_bms_max_charge_current !== undefined) blocks.push(status('bolt', 'Макс. заряд (BMS)', fmt(STATE.inverter_bms_max_charge_current, 0), 'А'));
  if (STATE.inverter_bms_max_discharge_current !== undefined) blocks.push(status('bolt', 'Макс. разряд (BMS)', fmt(STATE.inverter_bms_max_discharge_current, 0), 'А'));
  if (STATE.inverter_bms_stop_charge !== undefined) {
    blocks.push(status('battery', 'Запрет заряда', STATE.inverter_bms_stop_charge ? 'да' : 'нет', '', STATE.inverter_bms_stop_charge ? 'red' : 'green'));
    blocks.push(status('battery', 'Запрет разряда', STATE.inverter_bms_stop_discharge ? 'да' : 'нет', '', STATE.inverter_bms_stop_discharge ? 'red' : 'green'));
  }
  host.innerHTML = blocks.join('');
  renderProtocolWatch();
  loadBmsEvents();
}

async function loadBattery() {
  const host = $('bms-statuses');
  const info = $('battery-source');
  let d;
  try {
    d = await (await fetch(api('/api/v1/battery'))).json();
  } catch (e) {
    host.innerHTML = '';
    info.textContent = 'Источник данных АКБ: недоступен';
    return;
  }
  const names = { inverter: 'значения инвертора', emulated: 'эмуляция (кулонометрия)',
    jbd: 'JBD / Overkill / QUCC', pylontech: 'Pylontech / Pytes / Dyness',
    modbus: 'Modbus RTU', vedirect: 'Victron VE.Direct (шунт)', can: 'CAN bus' };
  const src = names[d.source] || d.source;
  if (!d.enabled) {
    info.innerHTML = `Источник данных АКБ: <b>${esc(src)}</b> — используются значения инвертора.`
      + `<br><span class="muted">Доступно в конфигурации: ${Object.entries(d.available || {})
        .map(([k, v]) => `${k}`).join(', ')} (переменная BATTERY_SOURCE).</span>`;
    host.innerHTML = '';
    return;
  }
  info.innerHTML = `Источник данных АКБ: <b>${esc(src)}</b> · ${esc(d.driver || '')}`
    + (d.age_s !== null && d.age_s !== undefined ? ` · обновлено ${d.age_s} с назад` : '')
    + (d.errors ? ` · <span style="color:#f9584b">ошибок: ${d.errors}</span>` : '');
  const r = d.reading || {};
  const blocks = [];
  if (r.bms_soc !== undefined) blocks.push(status('battery', 'SOC (BMS)', fmt(r.bms_soc, 1), '%', r.bms_soc < 30 ? 'yellow' : 'green'));
  if (r.bms_soh !== undefined) blocks.push(status('battery', 'SOH', fmt(r.bms_soh, 0), '%'));
  if (r.bms_voltage !== undefined) blocks.push(status('bolt', 'Напряжение (BMS)', fmt(r.bms_voltage, 2), 'В'));
  if (r.bms_current !== undefined) blocks.push(status('bolt', 'Ток (BMS)', fmt(r.bms_current, 1), 'А'));
  if (r.bms_temperature !== undefined) blocks.push(status('temp', 'Температура (BMS)', fmt(r.bms_temperature, 1), '°C'));
  if (r.bms_remaining_ah !== undefined) blocks.push(status('battery', 'Осталось', fmt(r.bms_remaining_ah, 1), 'А·ч'));
  if (r.bms_capacity_ah !== undefined) blocks.push(status('battery', 'Ёмкость', fmt(r.bms_capacity_ah, 0), 'А·ч'));
  if (r.bms_cycles !== undefined) blocks.push(status('clock', 'Циклов', fmt(r.bms_cycles, 0), ''));
  if (r.bms_cell_min !== undefined) {
    blocks.push(status('bolt', 'Ячейка min / max', `${fmt(r.bms_cell_min, 3)} / ${fmt(r.bms_cell_max, 3)}`, 'В'));
  }
  host.innerHTML = blocks.join('') || '<p class="empty">BMS не отдаёт данные</p>';
  renderInverterBms();
}

function renderBattery() {
  const soc = STATE.battery_state_of_charge;
  $('batt-statuses').innerHTML = [
    status('battery', t('state.soc'), fmt(soc, 0), '%', soc < 30 ? 'yellow' : 'green'),
    status('battery', 'Напряжение', fmt(STATE.battery_voltage), 'В'),
    status('bolt', 'Ток', fmt(STATE.battery_current), 'А'),
    status('bolt', 'Мощность', power(Math.abs(STATE.battery_power || 0)), ''),
    metricStatus('battery_charge_today', 'battery'),
    metricStatus('battery_discharge_today', 'battery'),
  ].join('');
  $('tbl-battery').innerHTML = rows([
    'battery_float_charge_voltage', 'battery_absorption_charge_voltage',
    'back_to_battery_voltage', 'to_grid_battery_voltage', 'shutdown_battery_voltage',
    'max_charge_current', 'max_grid_charge_current', 'rated_battery_voltage',
  ]);
}

function renderGrid() {
  $('grid-statuses').innerHTML = [
    status('grid', 'Сеть', STATE.mains_ok ? 'есть' : 'нет', '', STATE.mains_ok ? 'green' : 'red'),
    status('bolt', 'Напряжение', fmt(STATE.grid_voltage), 'В'),
    status('bolt', 'Частота', fmt(STATE.grid_frequency, 1), 'Гц'),
    status('bolt', 'Мощность', power(STATE.grid_power || 0), ''),
    metricStatus('grid_energy_today', 'grid'),
  ].join('');
  $('tbl-grid').innerHTML = rows([
    'grid_voltage', 'grid_frequency', 'grid_power', 'mains_ok',
    'ac_output_voltage', 'ac_output_frequency', 'load_power', 'load_percentage',
  ]);
}

/* ---------------------------------------------------------------- energy */
async function loadEnergy() {
  const note = $('energy-note');
  note.style.display = 'none';
  try {
    const r = await fetch(api(`/api/v1/energy?from=-${energyRange}`));
    if (!r.ok) {
      const e = await r.json();
      note.textContent = 'Энергия недоступна: ' + (e.error || r.status);
      note.style.display = 'block';
      $('energy-statuses').innerHTML = '';
      return;
    }
    const d = await r.json();
    $('energy-statuses').innerHTML = [
      status('solar', 'Выработано PV', fmt(d.pv, 2), 'кВт·ч'),
      status('load', 'Потреблено', fmt(d.load, 2), 'кВт·ч'),
      status('grid', 'Из сети', fmt(d.grid, 2), 'кВт·ч'),
    ].join('');
  } catch (e) {
    note.textContent = 'Ошибка: ' + e;
    note.style.display = 'block';
  }
}

/* ---------------------------------------------------------------- charts */
const RANGES = {
  '1h': { from: '-1h', gb: '10s' }, '6h': { from: '-6h', gb: '1m' },
  '24h': { from: '-24h', gb: '2m' }, '7d': { from: '-7d', gb: '15m' },
  '30d': { from: '-30d', gb: '1h' },
};
const C = {
  pv: '#f1852b', pv2: '#f5b942', load: '#f9584b', grid: '#0048ff',
  batt: '#3e9e00', volt: '#6588e8', curr: '#ff8a65', temp: '#f9584b', bus: '#8e7cff',
};
// Состав страницы: первый график — обзор (с кнопками серий), далее по метрикам.
const CHARTS = [
  { id: 'overview', title: 'ch.overview', unit: 'W', wide: true, height: 260,
    series: [{ m: 'pv_power', label: t('flow.pv'), color: C.pv },
             { m: 'load_power', label: t('flow.load'), color: C.load },
             { m: 'grid_power', label: t('flow.grid'), color: C.grid }] },
  { id: 'pv_power', title: 'ch.pv_power', unit: 'W',
    series: [{ m: 'pv_power', label: t('ch.total'), color: C.pv },
             { m: 'pv_power_1', label: 'MPPT 1', color: C.pv2 },
             { m: 'pv_power_2', label: 'MPPT 2', color: C.bus }] },
  { id: 'load_power', title: 'ch.load_power', unit: 'W',
    series: [{ m: 'load_power', label: 'нагрузка', color: C.load }] },
  { id: 'grid_power', title: 'ch.grid_power', unit: 'W',
    series: [{ m: 'grid_power', label: 'сеть', color: C.grid }] },
  { id: 'battery_power', title: 'ch.batt_power', unit: 'W',
    series: [{ m: 'battery_power', label: 'АКБ', color: C.batt }] },
  { id: 'battery_soc', title: 'ch.soc', unit: '%',
    series: [{ m: 'battery_state_of_charge', label: 'SOC', color: C.batt }] },
  { id: 'battery_voltage', title: 'ch.batt_voltage', unit: 'V',
    series: [{ m: 'battery_voltage', label: 'напряжение', color: C.volt }] },
  { id: 'battery_current', title: 'ch.batt_current', unit: 'A',
    series: [{ m: 'battery_current', label: 'ток', color: C.curr }] },
  { id: 'pv_voltage', title: 'ch.pv_voltage', unit: 'V',
    series: [{ m: 'pv_voltage_1', label: 'MPPT 1', color: C.pv },
             { m: 'pv_voltage_2', label: 'MPPT 2', color: C.bus }] },
  { id: 'pv_current', title: 'ch.pv_current', unit: 'A',
    series: [{ m: 'pv_current_1', label: 'MPPT 1', color: C.pv },
             { m: 'pv_current_2', label: 'MPPT 2', color: C.bus }] },
  { id: 'grid_voltage', title: 'ch.grid_voltage', unit: 'V',
    series: [{ m: 'grid_voltage', label: 'сеть', color: C.grid }] },
  { id: 'grid_frequency', title: 'ch.grid_freq', unit: 'Hz',
    series: [{ m: 'grid_frequency', label: 'частота', color: C.grid }] },
  { id: 'temperature', title: 'ch.temp', unit: '°C',
    series: [{ m: 'temperature', label: 'температура', color: C.temp }] },
  { id: 'ac_output_voltage', title: 'ch.ac_out', unit: 'V',
    series: [{ m: 'ac_output_voltage', label: 'выход', color: C.volt }] },
  { id: 'bus_voltage', title: 'ch.bus', unit: 'V',
    series: [{ m: 'bus_voltage', label: 'bus', color: C.bus }] },
];

const chartCache = new Map();     // `${metric}|${range}` -> points
const chartInstances = new Map(); // id -> uPlot
const hiddenSeries = new Set();   // ключи "chartId:metric"
let chartsRange = localStorage.getItem('solar.chartRange') || '7d';
let chartsBuilt = false;
let chartsToken = 0;          // защита от гонки: две отрисовки одновременно ломали uPlot

function themeChartColors() {
  const css = getComputedStyle(document.documentElement);
  return {
    grid: css.getPropertyValue('--chart-grid').trim() || '#f0f0f0',
    axis: css.getPropertyValue('--chart-axis').trim() || '#8c8c8c',
    text: css.getPropertyValue('--heading').trim() || '#29334a',
  };
}

let forecastCache = null;

async function fetchForecast() {
  if (forecastCache) return forecastCache;
  try {
    const d = await (await fetch(api('/api/v1/forecast'))).json();
    const now = Date.now() / 1000;
    forecastCache = (d.enabled && d.points)
      ? d.points.filter((p) => p[0] >= now - 3600 && p[0] <= now + 24 * 3600)
          .map((p) => [new Date(p[0] * 1000).toISOString(), p[1]])
      : [];
  } catch (e) { forecastCache = []; }
  return forecastCache;
}

async function seriesPoints(spec) {
  if (spec.m === '__forecast') return fetchForecast();
  return fetchMetric(spec.m);
}

function chartSpecs(ch) {
  // на «Обзоре» добавляем пунктиром прогноз PV (данные forecast.solar из Influx/сервиса)
  if (ch.id !== 'overview') return ch.series;
  return ch.series.concat([{ m: '__forecast', label: t('ch.forecast'), color: '#29d',
                             dash: [6, 5], forecast: true }]);
}

function download(name, blob) {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = name;
  document.body.appendChild(a);
  a.click();
  setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
}

function exportPng(id) {
  const u = chartInstances.get(id);
  if (!u) return;
  const src = u.ctx.canvas;
  const css = getComputedStyle(document.documentElement);
  const bg = css.getPropertyValue('--card').trim() || '#fff';
  const out = document.createElement('canvas');
  out.width = src.width; out.height = src.height;
  const ctx = out.getContext('2d');
  ctx.fillStyle = bg;
  ctx.fillRect(0, 0, out.width, out.height);
  ctx.drawImage(src, 0, 0);
  out.toBlob((blob) => download(`${id}.png`, blob), 'image/png');
}

function exportCsv(id) {
  const u = chartInstances.get(id);
  if (!u) return;
  const names = u.series.slice(1).map((s) => s.label || 'value');
  const rows = ['time,' + names.join(',')];
  const xs = u.data[0] || [];
  for (let i = 0; i < xs.length; i++) {
    const t = new Date(xs[i] * 1000).toISOString();
    const vals = names.map((_, j) => {
      const v = u.data[j + 1] ? u.data[j + 1][i] : null;
      return v === null || v === undefined ? '' : v;
    });
    rows.push([t].concat(vals).join(','));
  }
  download(`${id}.csv`, new Blob([rows.join('\n')], { type: 'text/csv' }));
}

async function fetchMetric(metric) {
  const key = `${metric}|${chartsRange}`;
  if (chartCache.has(key)) return chartCache.get(key);
  const cfg = RANGES[chartsRange];
  try {
    const r = await fetch(api(`/api/v1/history?topic=inverter_1/${metric}`
      + `&from=${cfg.from}&group_by=${cfg.gb}&agg=mean`));
    if (!r.ok) return [];
    const d = await r.json();
    const points = d.points || [];
    chartCache.set(key, points);
    return points;
  } catch (e) { return []; }
}

/** Выравниваем несколько метрик по общей оси времени. */
function alignSeries(seriesData) {
  const maps = seriesData.map((points) => {
    const m = new Map();
    points.forEach((p) => m.set(Math.floor(new Date(p[0]).getTime() / 1000), p[1]));
    return m;
  });
  const xs = Array.from(new Set(maps.flatMap((m) => Array.from(m.keys())))).sort((a, b) => a - b);
  const cols = maps.map((m) => xs.map((t) => (m.has(t) ? m.get(t) : null)));
  return { xs, cols };
}

function buildChartsShell() {
  const root = $('charts-root');
  root.innerHTML = CHARTS.map((ch) => `
    <div class="card ${ch.wide ? 'wide' : ''}" data-card="${ch.id}">
      <h3>${esc(t(ch.title))}
        <span class="chart-tools">
          <button data-png="${ch.id}" title="Скачать картинку">PNG</button>
          <button data-csv="${ch.id}" title="Скачать данные">CSV</button>
        </span>
      </h3>
      <div class="body">
        <div class="chart-host" id="chart-${ch.id}"></div>
        ${ch.series.length > 1 ? `<div class="chart-toggles" id="toggles-${ch.id}"></div>` : ''}
      </div>
    </div>`).join('');
  chartsBuilt = true;
}

async function renderChart(ch, token) {
  const host = $(`chart-${ch.id}`);
  if (!host) return;
  if (token !== undefined && token !== chartsToken) return;

  const specs = chartSpecs(ch);
  const data = await Promise.all(specs.map((s) => seriesPoints(s)));
  if (token !== undefined && token !== chartsToken) return;

  const visible = specs.map((s) => !hiddenSeries.has(`${ch.id}:${s.m}`));
  const usable = specs.map((s, i) => (data[i] || []).length > 0);
  const { xs, cols } = alignSeries(specs.map((s, i) => data[i] || []));
  const colors = themeChartColors();

  let plot = chartInstances.get(ch.id);
  if (!xs.length) {                       // данных нет вовсе
    if (plot) { plot.destroy(); chartInstances.delete(ch.id); }
    host.innerHTML = `<p class="empty" style="padding:26px 0">${t('ch.no_data')}</p>`;
  } else if (!plot) {
    host.innerHTML = '';
    plot = new uPlot({
      width: host.clientWidth || 500,
      height: ch.height || 180,
      scales: { x: { time: true }, y: { digits: 1 } },
      axes: [
        { stroke: colors.axis, grid: { stroke: colors.grid }, ticks: { stroke: colors.grid } },
        { stroke: colors.axis, grid: { stroke: colors.grid }, ticks: { stroke: colors.grid },
          size: 52, label: ch.unit, labelSize: 18, labelFont: '11px Exo' },
      ],
      series: [{ label: 'время' }].concat(specs.map((s, i) => ({
        label: s.label, stroke: s.color, width: 1.8, spanGaps: false,
        fill: i === 0 && !s.dash ? hexA(s.color, 0.12) : undefined,
        dash: s.dash || undefined,
        show: visible[i] && usable[i],
      }))),
      legend: { show: false },
      cursor: { drag: { x: true, y: false }, points: { size: 6 } },
      hooks: {
        setSelect: [(u) => {
          const { left, width } = u.select;
          if (width < 5) return;
          syncZoom(ch.id, u.posToVal(left, 'x'), u.posToVal(left + width, 'x'));
        }],
      },
    }, [xs, ...cols], host);
    chartInstances.set(ch.id, plot);
  } else {
    // график уже есть: обновляем данные и видимость серий (без пересоздания)
    plot.setData([xs, ...cols]);
    specs.forEach((s, i) => {
      try { plot.setSeries(i + 1, { show: visible[i] && usable[i] }); } catch (e) { /* ignore */ }
    });
  }

  const toggles = $(`toggles-${ch.id}`);
  if (toggles) {
    toggles.innerHTML = specs.map((s, i) => {
      const off = !visible[i] || !usable[i];
      return `<button class="pill ${off ? 'off' : ''}" data-toggle="${ch.id}:${s.m}"
        ${usable[i] ? '' : `disabled title="${t('ch.no_data_period')}"`}>
        <span class="dotc" style="background:${s.color}"></span>${esc(s.label)}</button>`;
    }).join('');
    toggles.querySelectorAll('[data-toggle]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const key = btn.dataset.toggle;
        if (hiddenSeries.has(key)) hiddenSeries.delete(key); else hiddenSeries.add(key);
        const target = CHARTS.find((c) => c.id === btn.dataset.toggle.split(':')[0]);
        if (target) renderChart(target, chartsToken);
      });
    });
  }
}

function hexA(hex, a) {
  const n = parseInt(hex.replace('#', ''), 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
}

function syncZoom(sourceId, from, to) {
  chartInstances.forEach((u, id) => {
    if (id === sourceId) return;
    try { u.setScale('x', { min: from, max: to }); } catch (e) { /* ignore */ }
  });
}

async function loadCharts() {
  const token = ++chartsToken;
  if (!chartsBuilt) {
    buildChartsShell();
    $('charts-root').addEventListener('click', (ev) => {
      const png = ev.target.closest('[data-png]');
      const csv = ev.target.closest('[data-csv]');
      if (png) exportPng(png.dataset.png);
      if (csv) exportCsv(csv.dataset.csv);
    });
  }
  chartCache.clear();
  await Promise.all(CHARTS.map((ch) => renderChart(ch, token)));
  if (token === chartsToken) relayoutCharts();
}

function relayoutCharts() {
  chartInstances.forEach((u, id) => {
    const host = $(`chart-${id}`);
    if (host && host.clientWidth) {
      const ch = CHARTS.find((c) => c.id === id);
      u.setSize({ width: host.clientWidth, height: (ch && ch.height) || 180 });
    }
  });
}

/* ---------------------------------------------------------------- settings */
let AUTH_INFO = null;

async function renderAuthAlert() {
  const host = $('auth-alert');
  if (!host) return;
  if (!AUTH_INFO) {
    try { AUTH_INFO = await (await fetch(api('/api/v1/auth'))).json(); } catch (e) { return; }
  }
  if (!AUTH_INFO.default_password) { host.style.display = 'none'; host.innerHTML = ''; return; }
  const d = AUTH_INFO.default_credentials || { user: 'admin', password: 'admin' };
  host.style.display = '';
  host.className = 'card';
  host.innerHTML = `<div class="body" style="padding:12px 14px">
    <b>🔑 ${esc(t('auth.default_title'))}</b>
    <div class="muted" style="font-size:.9em;margin-top:4px">
      ${esc(t('auth.default_text'))} <code>${esc(d.user)} / ${esc(d.password)}</code>.
      <a href="#/settings" style="margin-left:6px">${esc(t('auth.default_link'))}</a>
    </div></div>`;
}

async function loadAuth() {
  const info = $('auth-info');
  if (!info) return;
  try {
    const d = await (await fetch(api('/api/v1/auth'))).json();
    const src = { env: t('auth.src_env'), file: t('auth.src_file'), off: t('auth.src_off') }[d.source] || d.source;
    info.textContent = d.enabled
      ? `${t('auth.user')}: ${d.user} · ${src}` + (d.updated ? ` · ${new Date(d.updated * 1000).toLocaleString()}` : '')
      : t('auth.disabled');
  } catch (e) { info.textContent = t('auth.unavailable'); }
}

async function savePassword() {
  const msg = $('auth-msg');
  const cur = $('auth-current').value;
  const nw = $('auth-new').value;
  const rep = $('auth-repeat').value;
  msg.className = 'msg';
  if (nw !== rep) { msg.className = 'msg err'; msg.textContent = t('auth.mismatch'); return; }
  if ((nw || '').length < 6) { msg.className = 'msg err'; msg.textContent = t('auth.too_short'); return; }
  msg.textContent = t('set.writing');
  const r = await fetch(api('/api/v1/auth/password'), {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ current_password: cur, new_password: nw }),
  });
  const d = await r.json();
  msg.className = 'msg ' + (r.ok ? 'ok' : 'err');
  msg.textContent = r.ok ? '✓ ' + d.message : '✗ ' + (d.error || r.status);
  if (r.ok) {
    $('auth-current').value = $('auth-new').value = $('auth-repeat').value = '';
    loadAuth();
  }
}

async function loadSettings() {
  const grid = $('settings-grid');
  const r = await fetch(api('/api/v1/settings'));
  if (!r.ok) { grid.innerHTML = '<p class="empty">Не удалось получить настройки</p>'; return; }
  const items = await r.json();
  grid.innerHTML = items.map((s) => {
    const id = 'set-' + s.key;
    if (s.kind === 'select') {
      const opts = s.options.map((o) =>
        `<option value="${esc(o.label)}" ${String(o.label) === String(s.value) ? 'selected' : ''}>${esc(o.label)}</option>`).join('');
      return `<div class="setting">
        <div class="name">${esc(s.name)}</div>
        <div class="cur">сейчас: <b>${esc(s.value ?? '—')}</b></div>
        <div class="row2"><select id="${id}">${opts}</select>
          <button class="primary" data-key="${esc(s.key)}">Сохранить</button></div>
        <div class="msg" id="msg-${esc(s.key)}"></div></div>`;
    }
    return `<div class="setting">
      <div class="name">${esc(s.name)}</div>
      <div class="cur">сейчас: <b>${fmt(s.value)}</b> ${esc(unit(s.unit))}</div>
      <div class="row2">
        <input type="number" id="${id}" value="${s.value ?? ''}" min="${s.min}" max="${s.max}" step="${s.step}">
        <button class="primary" data-key="${esc(s.key)}">Сохранить</button></div>
      <div class="msg" id="msg-${esc(s.key)}"></div></div>`;
  }).join('');

  grid.querySelectorAll('button[data-key]').forEach((btn) => {
    btn.addEventListener('click', () => saveSetting(btn.dataset.key, btn));
  });
}

async function saveSetting(key, btn) {
  const el = $('set-' + key);
  const msg = $('msg-' + key);
  btn.disabled = true;
  msg.className = 'msg';
  msg.textContent = 'запись…';
  try {
    const r = await fetch(api('/api/v1/settings'), {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ key, value: el ? el.value : null, verified: true }),
    });
    const res = await r.json();
    msg.className = 'msg ' + (res.ok ? 'ok' : 'err');
    msg.textContent = (res.ok ? '✓ ' : '✗ ') + res.message +
      (res.readback !== undefined && res.readback !== null ? ` (прочитано: ${res.readback})` : '');
    if (res.ok) setTimeout(loadSettings, 1400);
  } catch (e) {
    msg.className = 'msg err';
    msg.textContent = '✗ ' + e;
  } finally {
    btn.disabled = false;
  }
}

/* ---------------------------------------------------------------- automation */
const OP_LABEL = { '<': 'меньше', '<=': 'не больше', '>': 'больше', '>=': 'не меньше',
  '==': 'равно', '!=': 'не равно' };
const ACT_LABEL = { notify: 'уведомить', set: 'записать настройку', mqtt: 'опубликовать в MQTT' };

async function loadAutomation() {
  const [data, settings, meta] = await Promise.all([
    fetch(api('/api/v1/rules')).then((r) => r.json()).catch(() => ({ rules: [] })),
    fetch(api('/api/v1/settings')).then((r) => r.json()).catch(() => []),
    META,
  ]);
  $('automation-channels').textContent = data.channels && data.channels.length
    ? 'каналы: ' + data.channels.join(', ') + ` · не чаще ${data.notify_interval_s} с`
    : 'каналы уведомлений не настроены (TELEGRAM_BOT_TOKEN / WEBHOOK_URL)';

  renderRules(data.rules || []);
  renderRuleForm(meta, settings);
}

function ruleText(r) {
  const c = r.when;
  return `${c.metric} ${OP_LABEL[c.op] || c.op} ${c.value}` +
    (c.for_s ? ` в течение ${c.for_s} с` : '');
}

function renderRules(list) {
  const host = $('rules-list');
  if (!list.length) {
    host.innerHTML = '<p class="empty">Правил пока нет — добавь первое ниже.</p>';
    return;
  }
  host.innerHTML = list.map((r) => `
    <div class="rule ${r.enabled ? '' : 'off'}">
      <div class="info">
        <div class="name">${esc(r.name)}</div>
        <div class="cond">когда <b>${esc(ruleText(r))}</b>${r.cooldown_s ? ` · не чаще ${r.cooldown_s} с` : ''}</div>
        <div class="acts">${r.then.map((a) => `<code>${esc(ACT_LABEL[a.type] || a.type)}</code> ` +
          esc(a.type === 'set' ? `${a.key} = ${a.value}` : a.type === 'mqtt' ? `${a.topic}: ${a.payload || ''}` : a.text)).join(' · ')}</div>
      </div>
      <button class="pill toggle" data-toggle="${r.id}">${r.enabled ? 'выкл' : 'вкл'}</button>
      <button class="pill" data-del="${r.id}">удалить</button>
    </div>`).join('');

  host.querySelectorAll('[data-toggle]').forEach((b) => b.addEventListener('click', async () => {
    const r = list.find((x) => x.id === b.dataset.toggle);
    await fetch(api(`/api/v1/rules/${r.id}/toggle`), {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled: !r.enabled }),
    });
    loadAutomation();
  }));
  host.querySelectorAll('[data-del]').forEach((b) => b.addEventListener('click', async () => {
    await fetch(api(`/api/v1/rules/${b.dataset.del}`), { method: 'DELETE' });
    loadAutomation();
  }));
}

function renderRuleForm(meta, settings) {
  const metrics = Object.entries(meta.metrics || {})
    .filter(([, v]) => v.unit).map(([k, v]) => `<option value="${k}">${esc(v.name)}</option>`).join('');
  const setKeys = (settings || []).map((s) => `<option value="${esc(s.key)}">${esc(s.name)}</option>`).join('');

  $('rule-form').innerHTML = `
    <div class="form-grid">
      <div><label>Название</label><input id="r-name" placeholder="АКБ разряжена"></div>
      <div><label>Метрика</label><select id="r-metric">${metrics}</select></div>
      <div><label>Условие</label><select id="r-op">${Object.keys(OP_LABEL)
        .map((o) => `<option value="${o}">${OP_LABEL[o]}</option>`).join('')}</select></div>
      <div><label>Значение</label><input id="r-value" type="number" step="any" value="25"></div>
      <div><label>Держать, с</label><input id="r-for" type="number" value="60" min="0"></div>
      <div><label>Не чаще, с</label><input id="r-cooldown" type="number" value="600" min="0"></div>
      <div><label>Действие</label><select id="r-action">
        <option value="notify">уведомить</option>
        <option value="set">записать настройку</option>
        <option value="mqtt">опубликовать в MQTT</option>
      </select></div>
      <div id="r-wa"><label>Текст</label><input id="r-text" placeholder="АКБ {battery_state_of_charge}%"></div>
      <div id="r-wb" style="display:none"><label>Настройка</label><select id="r-key">${setKeys}</select></div>
      <div id="r-wc" style="display:none"><label>Значение настройки</label><input id="r-setvalue"></div>
      <div id="r-wd" style="display:none"><label>Топик</label><input id="r-topic" placeholder="home/alerts/x"></div>
      <div id="r-we" style="display:none"><label>Payload</label><input id="r-payload"></div>
    </div>
    <div class="form-actions">
      <button class="primary" id="r-add">Добавить правило</button>
      <button class="pill" id="r-example">Вставить пример</button>
      <span class="msg" id="r-msg"></span>
    </div>`;

  const sync = () => {
    const t = $('r-action').value;
    $('r-wa').style.display = t === 'notify' ? '' : 'none';
    $('r-wb').style.display = t === 'set' ? '' : 'none';
    $('r-wc').style.display = t === 'set' ? '' : 'none';
    $('r-wd').style.display = t === 'mqtt' ? '' : 'none';
    $('r-we').style.display = t === 'mqtt' ? '' : 'none';
  };
  $('r-action').addEventListener('change', sync);
  sync();

  $('r-example').addEventListener('click', async () => {
    const ex = await (await fetch(api('/api/v1/rules/examples'))).json();
    const e = ex[0];
    $('r-name').value = e.name;
    $('r-metric').value = e.when.metric;
    $('r-op').value = e.when.op;
    $('r-value').value = e.when.value;
    $('r-for').value = e.when.for_s;
    $('r-cooldown').value = e.cooldown_s;
    $('r-action').value = e.then[0].type;
    sync();
    $('r-text').value = e.then[0].text || '';
  });

  $('r-add').addEventListener('click', async () => {
    const type = $('r-action').value;
    const action = type === 'notify'
      ? { type, text: $('r-text').value || 'правило сработало' }
      : type === 'set' ? { type, key: $('r-key').value, value: $('r-setvalue').value, verified: true }
      : { type, topic: $('r-topic').value, payload: $('r-payload').value };
    const body = {
      name: $('r-name').value || `${$('r-metric').value} ${$('r-op').value} ${$('r-value').value}`,
      when: { metric: $('r-metric').value, op: $('r-op').value,
              value: Number($('r-value').value), for_s: Number($('r-for').value) },
      then: [action],
      cooldown_s: Number($('r-cooldown').value),
    };
    const r = await fetch(api('/api/v1/rules'), {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    });
    const msg = $('r-msg');
    if (r.ok) {
      msg.className = 'msg ok'; msg.textContent = '✓ правило добавлено';
      loadAutomation();
    } else {
      const e = await r.json();
      msg.className = 'msg err'; msg.textContent = '✗ ' + (e.error || r.status);
    }
  });
}

/* ---------------------------------------------------------------- routing */
const CONFIG_VIEWS = ['inverter', 'battery', 'connection', 'automation', 'codes', 'settings'];

function show(v) {
  view = v;
  const inConfig = CONFIG_VIEWS.includes(v);
  document.querySelectorAll('.view').forEach((s) => s.classList.toggle('active', s.id === 'view-' + v));
  document.querySelectorAll('#tabs .menu-item').forEach((a) => {
    a.classList.toggle('active', a.dataset.view === (inConfig ? 'config' : v));
  });
  const sub = $('submenu');
  if (sub) {
    sub.style.display = inConfig ? '' : 'none';
    sub.querySelectorAll('a').forEach((a) => a.classList.toggle('active', a.dataset.view === v));
  }
  if (v === 'energy') loadEnergy();
  if (v === 'battery') loadBattery();
  if (v === 'battery') loadBmsConfig();
  if (v === 'charts') loadCharts();
  if (v === 'settings') { loadSettings(); loadAuth(); }
  if (v === 'automation') loadAutomation();
  if (v === 'codes') loadCodes();
  if (v === 'connection') loadConnection();
}

function route() {
  const v = (location.hash.replace('#/', '') || 'overview').split('?')[0];
  show($('view-' + v) ? v : 'overview');
}

/* ---------------------------------------------------------------- state */
function render() {
  $('dot').classList.toggle('on', !!STATE.last_update);
  $('mode').textContent = STATE.device_mode || '—';
  const age = STATE.last_update ? Math.max(0, Math.round(Date.now() / 1000 - STATE.last_update)) : null;
  $('age').textContent = age === null ? '' : age + ' с';

  renderOverview();
  if (!AUTH_INFO || !AUTH_INFO.default_password) renderAuthAlert();
  if (view === 'inverter') renderInverter();
  if (view === 'battery') renderBattery();
  if (view === 'grid') renderGrid();
}

let stream = null;
function startStream() {
  const es = new EventSource(api('/api/v1/stream'));
  stream = es;
  es.addEventListener('state', (e) => {
    try { STATE = JSON.parse(e.data); render(); } catch (err) { /* ignore */ }
  });
  es.onerror = () => { es.close(); setTimeout(startStream, 3000); };
}

const THEME_KEY = 'solar.theme';

function currentTheme() {
  return localStorage.getItem(THEME_KEY) || document.documentElement.dataset.theme || 'light';
}

function applyTheme(theme, redraw = true) {
  document.documentElement.dataset.theme = theme;
  localStorage.setItem(THEME_KEY, theme);
  const btn = $('theme-toggle');
  if (btn) btn.textContent = theme === 'dark' ? '☀️' : '🌙';
  if (redraw && currentView === 'charts') loadCharts();
}

function toggleTheme() {
  applyTheme(currentTheme() === 'dark' ? 'light' : 'dark');
}

function diagLoop() {
  const out = document.getElementById('diag');
  if (!out) return;
  let widest = '', maxw = 0;
  document.querySelectorAll('body *').forEach((el) => {
    const r = el.getBoundingClientRect();
    if (r.width > maxw) { maxw = r.width; widest = el.tagName + (el.getAttribute('class') ? '.' + String(el.getAttribute('class')).split(' ')[0] : ''); }
  });
  const flow = document.querySelector('.flow-mobile');
  out.textContent = `scroll=${document.documentElement.scrollWidth}/${document.documentElement.clientWidth}`
    + ` wide=${widest}:${Math.round(maxw)} flow=${flow ? Math.round(flow.getBoundingClientRect().width) : '-'}`;
}


// при смене языка перерисовываем динамические подписи
function onLanguageChanged() {
  applyI18n();
  render();
  if (view === 'charts') { CODES = null; loadCharts(); }
  if (view === 'settings') loadSettings();
  if (view === 'connection') loadConnection();
  if (view === 'codes') { CODES = null; loadCodes(); }
  if (view === 'automation') loadAutomation();
  if (view === 'battery') { loadBattery(); renderBattery(); }
  if (view === 'energy') loadEnergy();
}

async function boot() {
  applyI18n();
  const langSel = $('lang-select');
  if (langSel) {
    langSel.value = localStorage.getItem('solar.lang') || 'auto';
    langSel.addEventListener('change', () => {
      if (langSel.value === 'auto') {
        localStorage.removeItem('solar.lang');
        const auto = (navigator.language || 'en').slice(0, 2);
        location.reload();
      } else {
        setLang(langSel.value);
      }
    });
  }
  // ?theme=dark|light — удобно для киоска и скриншотов
  const qTheme = new URLSearchParams(location.search).get('theme');
  if (qTheme) document.body.classList.add('no-transition');   // для киоска/скриншотов
  applyTheme(qTheme || currentTheme(), false);
  $('theme-toggle').addEventListener('click', toggleTheme);
  buildGauges();
  try {
    META = await (await fetch(api('/api/v1/meta'))).json();
    const list = META.sites && META.sites.length ? META.sites : [META.site];
    if (!currentSite) currentSite = META.site;
    if (list.length > 1) {
      const sel = $('site-select');
      sel.innerHTML = list.map((s0) => `<option value="${esc(s0)}" ${s0 === currentSite ? 'selected' : ''}>${esc(s0)}</option>`).join('');
      sel.style.display = '';
      sel.addEventListener('change', () => {
        currentSite = sel.value;
        localStorage.setItem('solar.site', currentSite);
        try { stream.close(); } catch (e) { /* ignore */ }
        startStream();
        fetch(api('/api/v1/state')).then((r) => r.json()).then((d) => { STATE = d; render(); });
        // данные страниц принадлежат выбранному сайту — перезагружаем их
        if (view === 'charts') loadCharts();
        if (view === 'energy') loadEnergy();
        if (view === 'settings') loadSettings();
        if (view === 'connection') loadConnection();
        if (view === 'battery') { loadBattery(); loadBmsConfig(); }
        if (view === 'automation') loadAutomation();
        if (view === 'codes') { CODES = null; loadCodes(); }
        fetch(api('/api/v1/meta')).then((r) => r.json()).then((m) => {
          const sameSite = currentSite === META.site;
          $('site').textContent = (sameSite ? '' : currentSite + ' · ')
            + (m.device || currentSite) + ' · ' + (m.transport || '');
          $('footer-transport').textContent = m.transport || '';
        }).catch(() => {
          $('site').textContent = currentSite + ' · …';
        });
      });
    }
    $('site').textContent = (currentSite && currentSite !== META.site ? currentSite + ' · ' : '')
      + (META.device || META.site || '') + ' · ' + (META.transport || '');
    $('footer-transport').textContent = META.transport || '';
    document.title = (META.device || 'solar-monitor') + ' — solar-monitor';
  } catch (e) { /* keep defaults */ }

  try { STATE = await (await fetch(api('/api/v1/state'))).json(); } catch (e) { STATE = {}; }
  render();
  startStream();

  document.querySelectorAll('[data-range]').forEach((x) => {
    x.classList.toggle('active', x.dataset.range === chartsRange);
  });
  document.querySelectorAll('[data-energy]').forEach((x) => {
    x.classList.toggle('active', x.dataset.energy === energyRange);
  });
  window.addEventListener('hashchange', route);
  route();

  document.querySelectorAll('[data-range]').forEach((el) => el.addEventListener('click', () => {
    chartsRange = el.dataset.range;
    localStorage.setItem('solar.chartRange', chartsRange);
    document.querySelectorAll('[data-range]').forEach((x) => x.classList.toggle('active', x === el));
    loadCharts();
  }));
  document.querySelectorAll('[data-energy]').forEach((el) => el.addEventListener('click', () => {
    energyRange = el.dataset.energy;
    localStorage.setItem('solar.energyRange', energyRange);
    document.querySelectorAll('[data-energy]').forEach((x) => x.classList.toggle('active', x === el));
    loadEnergy();
  }));
  $('energy-reload').addEventListener('click', loadEnergy);
  $('codes-filter').addEventListener('input', loadCodes);
  $('conn-mode').addEventListener('change', syncConnFields);
  $('conn-probe').addEventListener('click', probeConnection);
  $('conn-apply').addEventListener('click', applyConnection);
  $('bms-config-toggle').addEventListener('click', loadBmsConfig);
  $('bms-apply').addEventListener('click', () => applyBms());
  $('bms-inverter').addEventListener('click', () => applyBms({ source: 'inverter', brand: '' }));
  $('inv-bms-save').addEventListener('click', async () => {
    const msg = $('inv-bms-msg');
    const target = $('inv-bms-type').value;
    const cur = STATE.battery_type || '—';
    if (target !== cur && !window.confirm(
      `Сменить протокол BMS инвертора: «${cur}» → «${target}»?\n\n`
      + 'Инвертор подключает батарею за 20–30 с; пока связи нет — он не заряжает АКБ. '
      + 'Если за 45 с связь не появится, протокол автоматически вернётся на прежний.')) {
      return;
    }
    msg.className = 'msg'; msg.textContent = 'запись…';
    const r = await fetch(api('/api/v1/settings'), {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ key: 'battery_type', value: $('inv-bms-type').value, verified: true }),
    });
    const res = await r.json();
    msg.className = 'msg ' + (res.ok ? 'ok' : 'err');
    msg.textContent = (res.ok ? '✓ ' : '✗ ') + res.message;
    if (res.ok) {
      SETTINGS_CACHE = null;
      setTimeout(() => { loadBattery(); renderProtocolWatch(); }, 1200);
    }
  });
  $('inv-bms-user').addEventListener('click', async () => {
    if (!window.confirm('Переключить протокол BMS на «User»?\n\n'
      + 'User/AGM отключает управление по BMS: инвертор будет заряжать без её лимитов и защит.')) return;
    await setBatteryType('User');
  });
  $('inv-bms-agm').addEventListener('click', async () => {
    if (!window.confirm('Переключить протокол BMS на «AGM»?\n\n'
      + 'User/AGM отключает управление по BMS: инвертор будет заряжать без её лимитов и защит.')) return;
    await setBatteryType('AGM');
  });
  $('protocol-confirm').addEventListener('click', async () => {
    await fetch(api('/api/v1/battery/protocol/confirm'), { method: 'POST' });
    renderProtocolWatch();
  });
  $('protocol-cancel').addEventListener('click', async () => {
    await fetch(api('/api/v1/battery/protocol/cancel'), { method: 'POST' });
    renderProtocolWatch();
  });
  $('notify-test').addEventListener('click', async () => {
    const msg = $('automation-msg');
    msg.className = 'msg'; msg.textContent = 'отправляю…';
    const r = await fetch(api('/api/v1/notify/test'), { method: 'POST' });
    const res = await r.json();
    const okCh = Object.values(res).filter((v) => v === 'sent').length;
    msg.className = 'msg ' + (okCh ? 'ok' : 'err');
    msg.textContent = okCh ? `✓ отправлено (${Object.keys(res).join(', ')})`
      : '✗ нет каналов: ' + JSON.stringify(res);
  });
  $('auth-save').addEventListener('click', savePassword);
  $('reload-settings').addEventListener('click', async () => {
    const msg = $('reload-msg');
    msg.className = 'msg'; msg.textContent = 'читаю…';
    const r = await fetch(api('/api/v1/reload_settings'), { method: 'POST' });
    const res = await r.json();
    msg.className = 'msg ' + (res.ok ? 'ok' : 'err');
    msg.textContent = (res.ok ? '✓ ' : '✗ ') + res.message;
    if (res.ok) loadSettings();
  });
  if (new URLSearchParams(location.search).has('debug')) {
    const bar = document.createElement('div');
    bar.id = 'diag';
    bar.style.cssText = 'position:fixed;left:0;top:0;z-index:999;background:#ff0;color:#000;'
      + 'font:12px monospace;padding:4px;white-space:pre-wrap;max-width:100%';
    document.body.appendChild(bar);
    diagLoop();
    setInterval(diagLoop, 300);
  }
  window.addEventListener('resize', relayoutCharts);
  setInterval(() => { if (STATE.last_update) render(); }, 1000);
}

boot();
