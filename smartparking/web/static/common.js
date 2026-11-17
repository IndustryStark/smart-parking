// Small helpers shared by all pages. User data is only ever inserted as text nodes (no innerHTML).
const $ = (sel, root = document) => root.querySelector(sel);

function h(tag, attrs, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k === 'class') e.className = v;
    else if (k.startsWith('on')) e.addEventListener(k.slice(2), v);
    else if (k === 'value') e.value = v ?? '';
    else if (v === true) e.setAttribute(k, '');
    else if (v !== false && v != null) e.setAttribute(k, v);
  }
  for (const c of kids.flat()) {
    if (c == null || c === false) continue;
    e.append(c.nodeType ? c : document.createTextNode(c));
  }
  return e;
}

function s(tag, attrs, ...kids) {
  const e = document.createElementNS('http://www.w3.org/2000/svg', tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k.startsWith('on')) e.addEventListener(k.slice(2), v);
    else if (v != null) e.setAttribute(k, v);
  }
  for (const c of kids.flat()) if (c != null) e.append(c.nodeType ? c : document.createTextNode(c));
  return e;
}

async function api(method, url, body) {
  const res = await fetch(url, {
    method,
    headers: body !== undefined ? { 'Content-Type': 'application/json' } : {},
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  let data = null;
  try { data = await res.json(); } catch (e) { /* empty body */ }
  if (!res.ok) {
    const err = new Error((data && data.error) || res.statusText);
    err.status = res.status;
    throw err;
  }
  return data;
}

// Live updates over Server-Sent Events, with polling as a fallback.
function liveState(cb) {
  let timer = null;
  const poll = () => api('GET', '/api/state').then(cb).catch(() => {});
  poll();
  if (!window.EventSource) { timer = setInterval(poll, 2000); return; }
  const es = new EventSource('/api/stream');
  es.onmessage = (e) => { if (timer) { clearInterval(timer); timer = null; } cb(JSON.parse(e.data)); };
  es.onerror = () => { if (!timer) timer = setInterval(poll, 2000); };
}

function fmtTime(ts) {
  return ts ? new Date(ts * 1000).toLocaleString([], { dateStyle: 'short', timeStyle: 'medium' }) : '';
}
