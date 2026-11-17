// Live map page and entrance screen.
function entranceActive(snap) {
  const e = snap.entrance;
  return e && e.ts && (snap.ts - e.ts) < snap.entrance_ttl;
}

function ledMeaning(color, blink) {
  if (color === 'blue') return blink ? 'help requested' : 'hold your chip to the reader';
  if (color === 'green') return 'go';
  if (color === 'red') return blink ? 'chip refused' : 'lot full';
  return 'off';
}

// On-screen copy of the entrance LED (what the Pi's LED is showing right now).
function renderSignals(snap) {
  const f = snap.feedback || {};
  const led = $('#led');
  if (led) led.className = 'led ' + (f.led || 'off') + (f.blink ? ' blink' : '');
  const label = $('#led-label');
  if (label) label.textContent = ledMeaning(f.led, f.blink);
}

function initIndex() {
  const svg = $('#map');
  liveState(snap => {
    renderSignals(snap);
    $('#n-free').textContent = snap.counts.free;
    $('#n-res').textContent = snap.counts.reserved;
    $('#n-occ').textContent = snap.counts.occupied;
    drawMap(svg, snap, {
      highlightSpotId: entranceActive(snap) && snap.entrance.ok ? snap.entrance.spot_id : null,
      onSpotClick: window.MOCK ? (p => api('POST', '/api/sim/spot', { spot_id: p.id, occupied: p.state !== 'OCCUPIED' })) : null,
    });
    const e = snap.entrance, active = entranceActive(snap);
    const box = $('#entrance-msg');
    box.textContent = active ? e.message : 'Please scan your chip.';
    box.className = 'msg' + (active ? (e.ok === true ? ' ok' : e.ok === false ? ' bad' : '') : '');
    const rows = snap.spots.filter(p => p.state !== 'FREE').map(p => h('tr', {},
      h('td', {}, p.name), h('td', {}, p.employee || 'unknown car'), h('td', {}, p.department || ''),
      h('td', {}, h('span', { class: 'pill ' + (p.state === 'OCCUPIED' && p.misparked ? 'mis' : p.state.toLowerCase()) },
        p.state === 'OCCUPIED' && p.misparked ? 'wrong spot' : p.state.toLowerCase()))));
    $('#who tbody').replaceChildren(...(rows.length ? rows : [h('tr', {}, h('td', { colspan: 4, class: 'hint' }, 'No cars in the lot.'))]));
  });

  if (window.MOCK) {
    $('#sim-repeat').onclick = () => api('POST', '/api/sim/repeat', {});
    $('#sim-help').onclick = () => api('POST', '/api/sim/help', {});
    api('GET', '/api/sim/chips').then(chips => {
      $('#sim-chips').replaceChildren(...chips.map(c =>
        h('button', { onclick: () => api('POST', '/api/sim/scan', { uid: c.uid }) }, c.employee || ('Spare ' + c.uid))));
    });
  }
}

// Entrance kiosk: only what the driver needs. The spot, big. Everything else is one short line.
function initEntrance() {
  const box = $('#big');
  let idleTimer;
  const idle = () => { box.className = 'kiosk idle'; box.replaceChildren(h('div', { class: 'line' }, 'Hold your chip to the reader')); };
  liveState(snap => {
    const e = snap.entrance;
    clearTimeout(idleTimer);
    if (!entranceActive(snap)) return idle();
    if (e.ok) {
      box.className = 'kiosk go';
      box.replaceChildren(h('div', { class: 'label' }, 'Your spot'), h('div', { class: 'spot' }, e.spot),
        h('div', { class: 'line' }, `Zone ${e.zone}`));
    } else {
      box.className = 'kiosk ' + (e.ok === false ? 'bad' : 'idle');
      box.replaceChildren(h('div', { class: 'line' }, e.message));
    }
    idleTimer = setTimeout(idle, Math.max(0, (snap.entrance_ttl - (snap.ts - e.ts))) * 1000 + 300);
  });
}

document.addEventListener('DOMContentLoaded', () => {
  const page = document.body.dataset.page;
  if (page === 'index') initIndex();
  if (page === 'entrance') initEntrance();
});
