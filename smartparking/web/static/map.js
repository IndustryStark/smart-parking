// Draws the lot as SVG from a /api/state snapshot.
// opts: { highlightSpotId, onSpotClick(spot) }
function drawMap(svg, snap, opts = {}) {
  const U = 84;                                   // pixels per grid unit
  const spots = snap.spots;
  if (!spots.length) { svg.replaceChildren(); return; }
  const ex = snap.entrance_pos.x, ey = snap.entrance_pos.y;
  const xs = spots.map(p => p.x).concat(ex), ys = spots.map(p => p.y).concat(ey);
  const minx = Math.min(...xs), miny = Math.min(...ys);
  const W = (Math.max(...xs) - minx + 2) * U, H = (Math.max(...ys) - miny + 2) * U;
  const X = x => (x - minx + 1) * U, Y = y => (y - miny + 1) * U;
  svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
  svg.classList.toggle('clickable', !!opts.onSpotClick);

  const kids = [];
  // zone outlines: bounding box of each zone's spots
  const zones = {};
  for (const p of spots) (zones[p.zone] = zones[p.zone] || []).push(p);
  for (const [name, ps] of Object.entries(zones)) {
    const x0 = Math.min(...ps.map(p => X(p.x))) - 44, x1 = Math.max(...ps.map(p => X(p.x))) + 44;
    const y0 = Math.min(...ps.map(p => Y(p.y))) - 52, y1 = Math.max(...ps.map(p => Y(p.y))) + 44;
    kids.push(s('rect', { class: 'zone', x: x0, y: y0, width: x1 - x0, height: y1 - y0, rx: 12 }));
    kids.push(s('text', { class: 'zlabel', x: x0 + 10, y: y0 + 20 }, `Zone ${name}`));
  }
  // entrance gate
  kids.push(s('line', { class: 'gate', x1: X(ex), y1: Y(ey) - 34, x2: X(ex), y2: Y(ey) + 34 }));
  kids.push(s('text', { class: 'glabel', x: X(ex) - 6, y: Y(ey) + 56, 'text-anchor': 'middle' }, 'ENTRANCE'));

  for (const p of spots) {
    const cx = X(p.x), cy = Y(p.y), mis = p.state === 'OCCUPIED' && p.misparked;
    const cls = ['spot', p.state.toLowerCase(), mis ? 'mis' : '', opts.highlightSpotId === p.id ? 'hl' : '']
      .filter(Boolean).join(' ');
    let line2 = p.state === 'FREE' ? 'free' : (p.employee || (mis ? 'unknown car' : '')) ;
    if (p.state === 'RESERVED') line2 = 'for ' + (p.employee || '?');
    const tip = `${p.name} (zone ${p.zone}): ${p.state}` + (p.employee ? ` - ${p.employee}${p.department ? ' / ' + p.department : ''}` : '') +
      (mis ? ' - NOT IN ASSIGNED SPOT' : '');
    const g = s('g', { class: 'spot-g', onclick: opts.onSpotClick ? () => opts.onSpotClick(p) : null },
      s('title', {}, tip),
      s('rect', { class: cls, x: cx - 34, y: cy - 40, width: 68, height: 80, rx: 8 }),
      s('text', { class: 'sname', x: cx, y: cy - 20, 'text-anchor': 'middle' }, p.name));
    if (p.state !== 'FREE') {
      g.append(s('rect', { class: p.state === 'OCCUPIED' ? 'car' : 'carres', x: cx - 16, y: cy - 8, width: 32, height: 24, rx: 7,
                           opacity: p.state === 'OCCUPIED' ? 1 : .45 }));
    }
    g.append(s('text', { class: 'sub', x: cx, y: cy + 34, 'text-anchor': 'middle' },
      (line2 || '').slice(0, 11)));
    kids.push(g);
  }
  svg.replaceChildren(...kids);
}
