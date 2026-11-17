// Admin panel: one generic editable table per entity, plus chip scanning and zone ranking.
const app = $('#app');
const cache = {};            // lists used to fill <select> options
let current = 'chips';

async function load(table) { cache[table] = await api('GET', '/api/admin/' + table); return cache[table]; }
const opts = (table, labelKey = 'name', blank) =>
  (blank ? [{ value: '', label: blank }] : []).concat((cache[table] || []).map(r => ({ value: r.id, label: r[labelKey] })));

function toast(el, text, bad) { el.textContent = text; el.style.color = bad ? 'var(--occ)' : 'var(--free)'; }

// ---- generic CRUD table -------------------------------------------------------------------------
// cfg: { table, pk, cols:[{key,label,type:'text'|'number'|'select'|'check'|'readonly', options(), cls}], blank, intro, toolbar }
function crud(cfg) {
  const status = h('div', { class: 'err', role: 'status' });
  const body = h('tbody');
  const pk = cfg.pk || 'id';

  const input = (col, row) => {
    const val = row ? row[col.key] : (col.default ?? '');
    if (col.type === 'select') {
      const sel = h('select', { 'aria-label': col.label }, col.options().map(o => h('option', { value: o.value }, o.label)));
      sel.value = val ?? ''; return sel;
    }
    if (col.type === 'check') return h('input', { type: 'checkbox', 'aria-label': col.label, checked: !!val, style: 'width:auto' });
    if (col.type === 'readonly') return h('span', { class: 'hint' }, row ? (col.fmt ? col.fmt(val) : String(val ?? '')) : '');
    return h('input', { type: col.type === 'number' ? 'number' : 'text', step: 'any', 'aria-label': col.label, value: val ?? '' });
  };
  const read = (col, el) => col.type === 'check' ? el.checked : (el.value === '' ? null : el.value);
  const collect = (cols, els) => Object.fromEntries(cols.filter(c => c.type !== 'readonly').map((c, i) => [c.key, read(c, els[i])]));

  const editable = cfg.cols.filter(c => c.type !== 'readonly');
  const rowEl = (row) => {
    const els = [];
    const tds = cfg.cols.map(c => {
      const el = input(c, row); if (c.type !== 'readonly') els.push(el);
      return h('td', { class: c.type === 'number' ? 'num' : '' }, el);
    });
    const save = h('button', { onclick: async () => {
      try { const r = await api('PUT', `/api/admin/${cfg.table}/${row[pk]}`, collect(cfg.cols, els)); toast(status, r.warning || 'Saved', !!r.warning); await refresh(); }
      catch (e) { toast(status, e.message, true); }
    } }, 'Save');
    const del = h('button', { class: 'danger', onclick: async () => {
      if (!window.confirm(`Delete this ${cfg.title.toLowerCase()} entry?`)) return;
      try { await api('DELETE', `/api/admin/${cfg.table}/${row[pk]}`); await refresh(); }
      catch (e) { toast(status, e.message, true); }
    } }, 'Delete');
    return h('tr', {}, tds, h('td', {}, h('div', { class: 'row' }, save, del)));
  };

  const addEls = [];
  const addRow = h('tr', {}, cfg.cols.map(c => {
    const el = input(c, null); if (c.type !== 'readonly') addEls.push(el);
    return h('td', { class: c.type === 'number' ? 'num' : '' }, el);
  }), h('td', {}, h('button', { class: 'primary', onclick: async () => {
    try {
      const r = await api('POST', '/api/admin/' + cfg.table, collect(cfg.cols, addEls));
      toast(status, r.warning || 'Added', !!r.warning); addEls.forEach(el => { if (el.type === 'checkbox') el.checked = !!el.dataset.def; else if (el.tagName !== 'SELECT') el.value = ''; });
      await refresh();
    } catch (e) { toast(status, e.message, true); }
  } }, 'Add')));
  addEls.forEach((el, i) => { if (editable[i].type === 'check') el.checked = !!editable[i].default; });

  async function refresh() {
    const rows = await load(cfg.table);
    // option lists of dependent selects may have changed (e.g. new department)
    body.replaceChildren(...rows.map(rowEl), addRow);
    if (cfg.after) await cfg.after(rows);
  }
  const root = h('div', { class: 'card', style: 'display:grid;gap:12px' },
    h('h2', {}, cfg.title), cfg.intro && h('p', { class: 'hint', style: 'margin:0' }, cfg.intro), cfg.toolbar && cfg.toolbar(addEls),
    h('div', { class: 'scroll' }, h('table', {}, h('thead', {}, h('tr', {}, cfg.cols.map(c => h('th', {}, c.label)), h('th'))), body)),
    status);
  return { root, refresh, extra: h('div') };
}

// ---- tabs -----------------------------------------------------------------------------------------
const tabs = {
  async chips() {
    await Promise.all([load('employees'), load('departments')]);
    const learn = h('span', { class: 'hint' });
    const view = crud({
      table: 'chips', pk: 'uid', title: 'Chips',
      intro: 'Register a new RFID chip: press "Scan new chip" and hold it at the entrance reader, or type its UID. Then assign it to an employee.',
      cols: [
        { key: 'uid', label: 'Chip UID', type: 'text' },
        { key: 'employee_id', label: 'Employee', type: 'select', options: () => opts('employees', 'name', '- unassigned -') },
        { key: 'active', label: 'Active', type: 'check', default: true },
        { key: 'created', label: 'Added', type: 'readonly', fmt: v => v ? fmtTime(v) : '-' },
      ],
      toolbar: (addEls) => h('div', { class: 'row' },
        h('button', { onclick: async () => {
          await api('POST', '/api/admin/learn', {}); learn.textContent = 'Hold the chip at the reader (15 s)...';
          for (let i = 0; i < 25; i++) {
            await new Promise(r => setTimeout(r, 700));
            const st = await api('GET', '/api/admin/learn');
            if (st.uid) { addEls[0].value = st.uid; learn.textContent = 'Captured ' + st.uid + '. Pick an employee and press Add.'; return; }
          }
          learn.textContent = 'No chip seen. Try again.';
        } }, 'Scan new chip'),
        h('button', { onclick: async () => {
          const st = await api('GET', '/api/admin/learn');
          if (st.last_unknown) { addEls[0].value = st.last_unknown; learn.textContent = 'Using last unknown scan ' + st.last_unknown; }
          else learn.textContent = 'No unknown chip has been scanned yet.';
        } }, 'Use last unknown scan'), learn),
    });
    // show the creation time readable
    const orig = view.refresh;
    view.refresh = async () => { await orig(); };
    return view;
  },

  async employees() {
    await Promise.all([load('departments'), load('spots')]);
    return crud({
      table: 'employees', title: 'Employees',
      intro: 'The department decides which parking zones an employee is sent to. A fixed spot overrides that when it is free.',
      cols: [
        { key: 'name', label: 'Name', type: 'text' },
        { key: 'department_id', label: 'Department', type: 'select', options: () => opts('departments') },
        { key: 'fixed_spot_id', label: 'Fixed spot (optional)', type: 'select', options: () => opts('spots', 'name', '- none -') },
      ],
    });
  },

  async departments() {
    await load('zones');
    const orderBox = h('div', { class: 'card', style: 'display:grid;gap:14px' });
    const view = crud({
      table: 'departments', title: 'Departments', intro: 'Add departments here, then rank the parking zones for each one below.',
      cols: [{ key: 'name', label: 'Department', type: 'text' }],
      after: async (rows) => { await load('zones'); renderOrder(rows); },
    });
    function renderOrder(rows) {
      const zname = Object.fromEntries(cache.zones.map(z => [z.id, z.name]));
      orderBox.replaceChildren(h('h2', {}, 'Closest zones per department'),
        h('p', { class: 'hint', style: 'margin:0' }, 'Top of the list = closest. Employees are sent to the first zone with a free spot.'),
        ...rows.map(d => {
          const order = d.zone_order.filter(id => zname[id]);
          cache.zones.forEach(z => { if (!order.includes(z.id)) order.push(z.id); });
          const note = h('span', { class: 'hint' });
          const list = h('ol', { class: 'order' });
          const paint = () => list.replaceChildren(...order.map((zid, i) => h('li', {},
            h('b', {}, i + 1 + '.'), h('span', {}, 'Zone ' + zname[zid]),
            h('button', { disabled: i === 0, 'aria-label': 'Move up', onclick: () => { [order[i - 1], order[i]] = [order[i], order[i - 1]]; paint(); } }, '↑'),
            h('button', { disabled: i === order.length - 1, 'aria-label': 'Move down', onclick: () => { [order[i + 1], order[i]] = [order[i], order[i + 1]]; paint(); } }, '↓'))));
          paint();
          return h('div', {}, h('h3', { style: 'margin:0 0 8px' }, d.name), list,
            h('div', { class: 'row', style: 'margin-top:8px' }, h('button', { class: 'primary', onclick: async () => {
              try { await api('PUT', `/api/admin/departments/${d.id}/zones`, { zones: order }); toast(note, 'Saved'); }
              catch (e) { toast(note, e.message, true); }
            } }, 'Save order'), note));
        }));
    }
    view.root.append(orderBox);
    return view;
  },

  async spots() {
    await load('zones');
    const zoneView = crud({
      table: 'zones', title: 'Zones (parking lots)', intro: 'A new zone is added to the end of every department\'s ranking; reorder it under Departments.',
      cols: [{ key: 'name', label: 'Zone', type: 'text' }],
      after: async () => { await load('zones'); },
    });
    const spotView = crud({
      table: 'spots', title: 'Spots and sensors',
      intro: 'x / y place the spot on the map (grid units). Distance to the entrance is calculated from them. Sensor pins use BCM numbering; for ultrasonic, "GPIO pin" is ECHO.',
      cols: [
        { key: 'name', label: 'Spot', type: 'text' },
        { key: 'zone_id', label: 'Zone', type: 'select', options: () => opts('zones') },
        { key: 'x', label: 'x', type: 'number', default: 0 },
        { key: 'y', label: 'y', type: 'number', default: 0 },
        { key: 'sensor_kind', label: 'Sensor', type: 'select', options: () => [{ value: 'ir', label: 'IR obstacle' }, { value: 'ultrasonic', label: 'Ultrasonic' }] },
        { key: 'gpio_pin', label: 'GPIO pin', type: 'number' },
        { key: 'trigger_pin', label: 'Trigger pin', type: 'number' },
        { key: 'state', label: 'State', type: 'readonly' },
      ],
    });
    const wrap = { root: h('div', { style: 'display:grid;gap:20px' }, zoneView.root, spotView.root),
      refresh: async () => { await zoneView.refresh(); await spotView.refresh(); } };
    return wrap;
  },

  async log() {
    const body = h('tbody');
    const root = h('div', { class: 'card' }, h('h2', {}, 'Event log'),
      h('div', { class: 'scroll' }, h('table', {}, h('thead', {}, h('tr', {}, ['Time', 'Event', 'Details', 'Employee', 'Spot'].map(t => h('th', {}, t)))), body)));
    const refresh = async () => {
      const rows = await api('GET', '/api/admin/events?limit=150');
      body.replaceChildren(...rows.map(r => h('tr', {}, h('td', {}, fmtTime(r.ts)), h('td', {}, r.kind), h('td', {}, r.message), h('td', {}, r.employee || ''), h('td', {}, r.spot || ''))));
    };
    const timer = setInterval(() => (current === 'log' && document.body.contains(root)) ? refresh() : clearInterval(timer), 4000);
    return { root, refresh };
  },
};
const TAB_LABELS = { chips: 'Chips', employees: 'Employees', departments: 'Departments', spots: 'Zones & spots', log: 'Log' };

async function showTab(name) {
  current = name;
  const holder = $('#tab-body');
  const view = await tabs[name]();
  holder.replaceChildren(view.root);
  await view.refresh();
  document.querySelectorAll('.tabs button').forEach(b => b.setAttribute('aria-selected', String(b.dataset.tab === name)));
}

function showApp() {
  $('#logout').hidden = false;
  app.replaceChildren(
    h('div', { class: 'tabs', role: 'tablist' }, Object.keys(TAB_LABELS).map(k =>
      h('button', { role: 'tab', 'data-tab': k, onclick: () => showTab(k) }, TAB_LABELS[k]))),
    h('div', { id: 'tab-body', style: 'display:grid;gap:20px' }));
  showTab(current);
}

function showLogin() {
  $('#logout').hidden = true;
  const err = h('div', { class: 'err', role: 'alert' });
  const pw = h('input', { type: 'password', id: 'pw', autocomplete: 'current-password', 'aria-label': 'Password' });
  const go = async (e) => {
    e && e.preventDefault();
    try { await api('POST', '/api/admin/login', { password: pw.value }); showApp(); }
    catch (ex) { err.textContent = ex.message; }
  };
  app.replaceChildren(h('form', { class: 'card login', onsubmit: go },
    h('h2', {}, 'Admin login'), pw, h('button', { class: 'primary', type: 'submit' }, 'Log in'), err));
  pw.focus();
}

$('#logout').addEventListener('click', async () => { await api('POST', '/api/admin/logout', {}); showLogin(); });
api('GET', '/api/admin/me').then(r => r.authenticated ? showApp() : showLogin());
