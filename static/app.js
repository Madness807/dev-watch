let procData = [];
let dockerData = [];
let portsData = [];
let connData = [];
let projectsData = [];
let actionTarget = null;
let watchInterval = null;
const WATCH_SPEEDS = [3, 5, 10, 0]; // 0 = off
let watchSpeedIdx = 2; // default 10s
let viewMode = (localStorage.getItem('dw-view') === 'tables') ? 'tables' : 'cockpit';
let cockpitCollapsed = {};

// ── Section accordions ──
function toggleSection(id) {
  document.getElementById(id).classList.toggle('collapsed');
}

// ── Type filters ──
const activeTypes = { node: true, python: true, rust: true, go: true, deno: true, bun: true, java: true, php: true, ruby: true, c: true, native: true };

function toggleTypeFilter(type) {
  activeTypes[type] = !activeTypes[type];
  document.querySelector(`.filter-type[data-type="${type}"]`).classList.toggle('active', activeTypes[type]);
  renderAll();
}

// ── Icons ──
const ICONS = {
  node: '/icons/nodejs.svg',
  python: '/icons/python.svg',
  docker: '/icons/docker.svg',
  postgres: '/icons/postgresql.svg',
  redis: '/icons/redis.svg',
  mongo: '/icons/mongodb.svg',
  mysql: '/icons/mysql.svg',
  nginx: '/icons/nginx.svg',
  traefik: '/icons/traefik.svg',
  grafana: '/icons/grafana.svg',
  prometheus: '/icons/prometheus.svg',
  rabbitmq: '/icons/rabbitmq.svg',
  elasticsearch: '/icons/elasticsearch.svg',
  mariadb: '/icons/mariadb.svg',
  go: '/icons/go.svg',
  rust: '/icons/rust.svg',
  ruby: '/icons/ruby.svg',
  php: '/icons/php.svg',
  java: '/icons/java.svg',
  apache: '/icons/apache.svg',
  loki: '/icons/loki.svg',
  deno: '/icons/deno.svg',
  bun: '/icons/bun.svg',
};

function typeTag(type) {
  const icon = ICONS[type] ? `<img src="${ICONS[type]}" alt="${type}">` : '';
  return `<span class="type-tag ${type}">${icon}${type}</span>`;
}

function detectImageTech(image) {
  const img = image.toLowerCase();
  const patterns = [
    [/node|next|nuxt|vite|react|vue|angular/, 'node'],
    [/python|django|flask|fastapi|uvicorn|gunicorn/, 'python'],
    [/postgres|postgis/, 'postgres'],
    [/redis/, 'redis'],
    [/mongo/, 'mongo'],
    [/mysql/, 'mysql'],
    [/mariadb/, 'mariadb'],
    [/nginx/, 'nginx'],
    [/traefik/, 'traefik'],
    [/grafana/, 'grafana'],
    [/rabbitmq/, 'rabbitmq'],
    [/elasticsearch|elastic/, 'elasticsearch'],
    [/golang|go:/, 'go'],
    [/rust/, 'rust'],
    [/ruby|rails/, 'ruby'],
    [/php|laravel/, 'php'],
    [/java|spring|tomcat/, 'java'],
    [/apache|httpd/, 'apache'],
    [/prometheus/, 'prometheus'],
    [/loki/, 'loki'],
    [/deno/, 'deno'],
  ];
  for (const [re, tech] of patterns) {
    if (re.test(img)) return tech;
  }
  return null;
}

function imageVersion(image) {
  const parts = image.split(':');
  const tag = parts.length > 1 ? parts[parts.length - 1] : 'latest';
  const isLatest = tag === 'latest';
  return `<span class="version-tag ${isLatest ? 'latest' : 'pinned'}">${esc(tag)}</span>`;
}

function techIcon(name, image) {
  const tech = detectImageTech(name) || detectImageTech(image);
  const icon = (tech && ICONS[tech]) ? ICONS[tech] : ICONS.docker;
  return `<img src="${icon}" alt="${tech || 'docker'}" style="width:14px;height:14px;vertical-align:-2px;margin-right:4px;">`;
}

// ── Sort state ──
let procSort = { key: 'type', dir: 'asc' };

function sortProcs(key, e) {
  if (procSort.key === key) {
    procSort.dir = procSort.dir === 'asc' ? 'desc' : 'asc';
  } else {
    procSort.key = key;
    procSort.dir = key === 'project' ? 'asc' : 'desc';
  }
  document.querySelectorAll('#proc-table th.sortable').forEach(th => th.classList.remove('asc', 'desc'));
  e.target.closest('th').classList.add(procSort.dir);
  renderAll();
}

// ── Notifications ──
// Presence debounce: an item must be seen on N consecutive scans before "appeared"
// fires, and missed on N consecutive scans before "disappeared" fires. The scan is
// an instantaneous ps snapshot, so a short-lived command (one-off script, editor
// hook, CLI tool run from a project dir) shows up in exactly one scan — announcing
// it would flood the page with New process / Process terminated toast pairs.
const PRESENCE_SCANS = 2;

const procTracker = { seeded: false, items: {} };       // pid → {info, confirmed, seen, misses}
const containerTracker = { seeded: false, items: {} };  // id → {info, confirmed, seen, misses}
let prevHealth = {};                                     // id → health (unhealthy/recovered transitions)

// Diff `current` (key → info) against the tracker; returns debounced lifecycle events.
function trackPresence(tracker, current) {
  const appeared = [], disappeared = [];
  if (!tracker.seeded) {
    // First scan: adopt everything silently — nothing to compare against.
    tracker.seeded = true;
    Object.keys(current).forEach(k => {
      tracker.items[k] = { info: current[k], confirmed: true, seen: 1, misses: 0 };
    });
    return { appeared, disappeared };
  }
  Object.keys(current).forEach(k => {
    const it = tracker.items[k];
    if (!it) {
      tracker.items[k] = { info: current[k], confirmed: false, seen: 1, misses: 0 };
      return;
    }
    it.info = current[k];
    it.misses = 0;
    it.seen++;
    if (!it.confirmed && it.seen >= PRESENCE_SCANS) {
      it.confirmed = true;
      appeared.push(it.info);
    }
  });
  Object.keys(tracker.items).forEach(k => {
    if (current[k] !== undefined) return;
    const it = tracker.items[k];
    if (!it.confirmed) { delete tracker.items[k]; return; }  // never announced → drop silently
    it.misses++;
    if (it.misses >= PRESENCE_SCANS) {
      disappeared.push(it.info);
      delete tracker.items[k];
    }
  });
  return { appeared, disappeared };
}

function toastLine(label, value) {
  return `<div class="toast-line"><span class="toast-label">${esc(label)}</span><span class="toast-value">${esc(value)}</span></div>`;
}

function showToast(title, icon, lines, type) {
  const container = document.getElementById('toast-container');
  const toast = document.createElement('div');
  toast.className = 'toast ' + (type || '');
  toast.innerHTML = `<div class="toast-title">${icon} ${esc(title)}</div><div class="toast-body">${lines.join('')}</div>`;
  container.appendChild(toast);
  setTimeout(() => {
    toast.classList.add('fade-out');
    setTimeout(() => toast.remove(), 300);
  }, 6000);
}

// ── Sound notifications ──
let audioCtx = null;
function getAudioCtx() {
  if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  if (audioCtx.state === 'suspended') audioCtx.resume();
  return audioCtx;
}

function playTone(freq, duration, volume) {
  const ctx = getAudioCtx();
  const osc = ctx.createOscillator();
  const gain = ctx.createGain();
  osc.connect(gain);
  gain.connect(ctx.destination);
  osc.frequency.value = freq;
  osc.type = 'sine';
  gain.gain.value = volume || 0.08;
  gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + duration);
  osc.start();
  osc.stop(ctx.currentTime + duration);
}

function soundUp() { playTone(880, 0.15, 0.06); setTimeout(() => playTone(1100, 0.12, 0.05), 120); }
function soundDown() { playTone(440, 0.2, 0.07); setTimeout(() => playTone(330, 0.25, 0.06), 150); }

function notify(title, icon, lines, type) {
  showToast(title, icon, lines, type);
  if (type === 'danger') soundDown();
  else soundUp();
}

function checkNotifications(newProcs, newDocker) {
  const procsNow = {};
  newProcs.forEach(r => { procsNow[r.pid] = r; });
  const procDiff = trackPresence(procTracker, procsNow);

  procDiff.disappeared.forEach(p => {
    notify('Process terminated', '<svg width="14" height="14" viewBox="0 0 24 24" fill="none"><circle cx="12" cy="12" r="10" stroke="#f87171" stroke-width="2"/><path d="M8 8l8 8M16 8l-8 8" stroke="#f87171" stroke-width="2" stroke-linecap="round"/></svg>', [
      toastLine('Project', p.project),
      toastLine('PID', String(p.pid)),
      toastLine('Type', p.type),
      toastLine('Cmd', p.cmd),
    ], 'danger');
  });

  procDiff.appeared.forEach(r => {
    notify('New process', '<svg width="14" height="14" viewBox="0 0 24 24" fill="none"><circle cx="12" cy="12" r="10" stroke="#4ade80" stroke-width="2"/><path d="M8 12h8M12 8v8" stroke="#4ade80" stroke-width="2" stroke-linecap="round"/></svg>', [
      toastLine('Project', r.project),
      toastLine('PID', String(r.pid)),
      toastLine('Type', r.type),
      toastLine('Cmd', r.cmd),
    ], '');
  });

  const containersNow = {};
  newDocker.forEach(r => { containersNow[r.id] = r; });
  const dockerDiff = trackPresence(containerTracker, containersNow);

  dockerDiff.disappeared.forEach(c => {
    notify('Container stopped', '<svg width="14" height="14" viewBox="0 0 24 24" fill="none"><rect x="3" y="3" width="18" height="18" rx="3" stroke="#f87171" stroke-width="2"/><rect x="8" y="8" width="8" height="8" fill="#f87171"/></svg>', [
      toastLine('Name', c.name),
      toastLine('Image', c.image),
      toastLine('Project', c.project || 'standalone'),
    ], 'danger');
  });

  // container went unhealthy (skip on the very first scan — nothing to compare against)
  const hadContainers = Object.keys(prevHealth).length > 0;
  newDocker.forEach(r => {
    const prev = prevHealth[r.id];
    if (hadContainers && r.health === 'unhealthy' && prev !== 'unhealthy') {
      notify('Container unhealthy', '<svg width="14" height="14" viewBox="0 0 24 24" fill="none"><path d="M12 2L2 22h20L12 2z" stroke="#fbbf24" stroke-width="2" fill="none"/><path d="M12 10v4M12 17v1" stroke="#fbbf24" stroke-width="2" stroke-linecap="round"/></svg>', [
        toastLine('Name', r.name),
        toastLine('Image', r.image),
        toastLine('Project', r.project || 'standalone'),
      ], 'warn');
    }
  });

  // container recovered
  newDocker.forEach(r => {
    if (r.health === 'healthy' && prevHealth[r.id] === 'unhealthy') {
      notify('Container recovered', '<svg width="14" height="14" viewBox="0 0 24 24" fill="none"><circle cx="12" cy="12" r="10" stroke="#4ade80" stroke-width="2"/><path d="M8 12l3 3 5-6" stroke="#4ade80" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>', [
        toastLine('Name', r.name),
        toastLine('Image', r.image),
      ], '');
    }
  });

  prevHealth = {};
  newDocker.forEach(r => { prevHealth[r.id] = r.health; });
}

// ── Core ──
function apiBase() { return window.location.origin; }

function setStatus(msg, cls) {
  const el = document.getElementById('ep-status');
  el.textContent = msg;
  el.className = 'ep-status ' + cls;
}

function showError(msg) {
  const el = document.getElementById('error-banner');
  el.textContent = msg;
  el.classList.add('show');
  setTimeout(() => el.classList.remove('show'), 5000);
}

// Escape for HTML text AND attribute contexts (quotes included, so values
// interpolated into title="..." / data-*="..." cannot break out of the attribute).
function esc(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

// AbortSignal.timeout() fallback for older browsers.
function timeoutSignal(ms) {
  if (typeof AbortSignal !== 'undefined' && typeof AbortSignal.timeout === 'function') {
    return AbortSignal.timeout(ms);
  }
  const ctrl = new AbortController();
  setTimeout(() => ctrl.abort(), ms);
  return ctrl.signal;
}

// Copy to clipboard (Clipboard API on localhost is a secure context; textarea fallback otherwise).
function copyText(text) {
  if (navigator.clipboard && navigator.clipboard.writeText) {
    return navigator.clipboard.writeText(text);
  }
  const ta = document.createElement('textarea');
  ta.value = text;
  ta.style.position = 'fixed';
  ta.style.opacity = '0';
  document.body.appendChild(ta);
  ta.select();
  try { document.execCommand('copy'); } catch (e) {}
  ta.remove();
  return Promise.resolve();
}

// Small one-line toast for quick-action feedback.
function flashToast(title, detail, type) {
  showToast(title, '', detail ? [esc(detail)] : [], type || '');
}

// Monochrome copy glyph (inherits the button's color).
const COPY_ICON = '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" style="vertical-align:-1px;"><rect x="9" y="9" width="11" height="11" rx="2" stroke="currentColor" stroke-width="2"/><path d="M5 15V5a2 2 0 0 1 2-2h8" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>';

// Port tags: click to open http://localhost:<port>, plus a copy-URL button. Shared by both tables.
function portTags(ports) {
  if (!ports || !ports.length) return '<span class="no-port">&mdash;</span>';
  return ports.map(p =>
    `<span class="port-tag port-open" data-port="${p}" title="Open http://localhost:${p}">:${p}</span>` +
    `<button class="port-copy" data-port="${p}" title="Copy http://localhost:${p}">${COPY_ICON}</button>`
  ).join('');
}

async function fetchData() {
  try {
    setStatus('fetch...', 'idle');
    // System meters are fetched in both views.
    const sysReq = fetch(apiBase() + '/api/system', { signal: timeoutSignal(5000) }).catch(() => null);

    if (viewMode === 'cockpit') {
      const res = await fetch(apiBase() + '/api/projects', { signal: timeoutSignal(5000) });
      if (!res.ok) throw new Error('HTTP ' + res.status);
      projectsData = await res.json();
      // Derive flat arrays from the grouped payload (drives history, notifications, counts).
      procData = projectsData.flatMap(g => g.processes);
      dockerData = projectsData.flatMap(g => g.containers);
      portsData = projectsData.flatMap(g => g.ports);
      connData = [];
    } else {
      const [psRes, dockerRes, portsRes, connRes] = await Promise.all([
        fetch(apiBase() + '/api/ps', { signal: timeoutSignal(5000) }),
        fetch(apiBase() + '/api/docker', { signal: timeoutSignal(5000) }).catch(() => null),
        fetch(apiBase() + '/api/ports', { signal: timeoutSignal(5000) }).catch(() => null),
        fetch(apiBase() + '/api/connections', { signal: timeoutSignal(5000) }).catch(() => null),
      ]);
      if (!psRes.ok) throw new Error('HTTP ' + psRes.status);
      procData = await psRes.json();
      dockerData = dockerRes && dockerRes.ok ? await dockerRes.json() : [];
      portsData = portsRes && portsRes.ok ? await portsRes.json() : [];
      connData = connRes && connRes.ok ? await connRes.json() : [];
      projectsData = [];
    }

    updateProcHistory(procData);   // one sample per scan (not per filter keystroke)
    const sysRes = await sysReq;
    const sysData = sysRes && sysRes.ok ? await sysRes.json() : null;
    if (sysData) renderSystem(sysData);
    checkNotifications(procData, dockerData);
    setStatus('connected', 'ok');
    renderAll();
  } catch(e) {
    setStatus(e.message, 'err');
    showError('Unable to reach server');
  }
}

function getFilter() { return document.getElementById('filter').value.toLowerCase().trim(); }

function matchProc(r, f) {
  if (!activeTypes[r.type]) return false;
  if (!f) return true;
  return String(r.pid).includes(f) ||
    r.type.includes(f) ||
    r.project.toLowerCase().includes(f) ||
    r.cmd.toLowerCase().includes(f) ||
    r.dir.toLowerCase().includes(f) ||
    r.ports.some(p => String(p).includes(f));
}

function matchDocker(r, f) {
  if (!f) return true;
  return r.id.toLowerCase().includes(f) ||
    r.name.toLowerCase().includes(f) ||
    r.image.toLowerCase().includes(f) ||
    r.status.toLowerCase().includes(f) ||
    (r.ports || []).some(p => String(p.host).includes(f) || String(p.container).includes(f)) ||
    (r.internal_ports || []).some(p => String(p).includes(f));
}


function ts() { return new Date().toTimeString().slice(0, 8); }

function renderAll() {
  const f = getFilter();
  if (viewMode === 'cockpit') {
    renderCockpit(projectsData, f);
  } else {
    renderProcs(procData.filter(r => matchProc(r, f)));
    renderDocker(dockerData.filter(r => matchDocker(r, f)));
    renderPorts(portsData);
    renderConnections(connData);
  }

  document.getElementById('total-procs').textContent = procData.length;
  document.getElementById('total-docker').textContent = dockerData.length;
  document.getElementById('last-scan').textContent = 'Last scan: ' + ts();
}

function renderProcs(rows) {
  document.getElementById('proc-count').textContent = rows.length + ' found';
  const tbody = document.getElementById('proc-body');
  if (!rows.length) {
    tbody.innerHTML = '<tr><td colspan="10" class="empty">No processes detected</td></tr>';
    return;
  }

  // sort
  rows.sort((a, b) => {
    let va = a[procSort.key], vb = b[procSort.key];
    if (typeof va === 'string') { va = va.toLowerCase(); vb = vb.toLowerCase(); }
    if (va < vb) return procSort.dir === 'asc' ? -1 : 1;
    if (va > vb) return procSort.dir === 'asc' ? 1 : -1;
    return 0;
  });

  tbody.innerHTML = rows.map(r => `
    <tr>
      <td>${typeTag(r.type)}</td>
      <td class="pid">${r.pid}</td>
      <td class="metric">${sparkline((procHistory[r.pid]||{}).cpu, 100, r.cpu)}<span style="color:${meterColor(r.cpu)}">${r.cpu}%</span></td>
      <td class="metric" title="${r.mem_pct}% of RAM">${sparkline((procHistory[r.pid]||{}).mem, 100, r.mem_pct)}<span style="color:${meterColor(r.mem_pct)}">${r.mem_mb} MB</span></td>
      <td class="project">${esc(r.project)}</td>
      <td class="cmd" title="${esc(r.cmd)}">${esc(r.cmd)}</td>
      <td>${r.venv ? `<span class="venv-tag">${esc(r.venv)}</span>` : '<span class="venv-tag system">system</span>'}</td>
      <td>${portTags(r.ports)}</td>
      <td class="dir copyable" data-path="${esc(r.dir_full)}" title="${esc(r.dir)} — click to copy">${esc(r.dir)}</td>
      <td>
        <button class="opendir-btn" data-path="${esc(r.dir_full)}" title="Open folder (${esc(r.dir)})">dir</button>
        <button class="kill-btn" data-pid="${r.pid}" data-project="${esc(r.project)}">kill</button>
      </td>
    </tr>
  `).join('');
}

function dockerPorts(r) {
  const bound = (r.ports || []).map(p => `<span class="port-tag">${p.host}:${p.container}</span>`);
  const internal = (r.internal_ports || []).map(p => `<span class="port-tag internal">:${p}</span>`);
  const all = bound.concat(internal);
  return all.length ? all.join('') : '<span class="no-port">&mdash;</span>';
}

// ── System meters ──
// ── Trend history (client-side ring buffer; server stays stateless) ──
const HISTORY_LEN = 40;
let procHistory = {};                              // pid -> { cpu: [...], mem: [...] }
let sysHistory = { cpu: [], ram: [], disk: [], gpu: [] };

function pushCapped(arr, val) {
  arr.push(val);
  if (arr.length > HISTORY_LEN) arr.shift();
}

function updateProcHistory(rows) {
  const alive = new Set(rows.map(r => r.pid));
  Object.keys(procHistory).forEach(pid => { if (!alive.has(Number(pid))) delete procHistory[pid]; });
  rows.forEach(r => {
    const h = procHistory[r.pid] || (procHistory[r.pid] = { cpu: [], mem: [] });
    pushCapped(h.cpu, r.cpu);
    pushCapped(h.mem, r.mem_pct);
  });
}

// Tiny SVG trend line. refMax keeps a near-idle series flat at the bottom (no noise
// amplification); a value above refMax (e.g. multi-core CPU > 100%) extends the curve.
function sparkline(values, refMax, current) {
  if (!values || values.length < 2) return '';
  const W = 54, H = 14, n = values.length;
  const scale = Math.max(refMax, ...values) || 1;
  const stepX = W / (n - 1);
  const pts = values.map((v, i) =>
    `${(i * stepX).toFixed(1)},${(H - (v / scale) * H).toFixed(1)}`).join(' ');
  return `<svg class="spark" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">` +
    `<polyline points="${pts}" fill="none" stroke="${meterColor(current)}" stroke-width="1.2"/></svg>`;
}

function meterColor(pct) {
  if (pct > 85) return 'var(--red)';
  if (pct > 60) return 'var(--amber)';
  return 'var(--green)';
}

function updateMeter(id, pct, label) {
  const fill = document.getElementById(id + '-fill');
  const val = document.getElementById(id + '-val');
  if (fill) { fill.style.width = pct + '%'; fill.style.background = meterColor(pct); }
  if (val) { val.textContent = label; val.style.color = meterColor(pct); }
}

function updateSpark(id, history, pct) {
  const el = document.getElementById(id + '-spark');
  if (el) el.innerHTML = sparkline(history, 100, pct);
}

function renderSystem(sys) {
  updateMeter('cpu', sys.cpu, sys.cpu + '%');
  updateMeter('ram', sys.ram.pct, sys.ram.pct + '%');
  updateMeter('disk', sys.disk.pct, sys.disk.pct + '%');
  pushCapped(sysHistory.cpu, sys.cpu);
  pushCapped(sysHistory.ram, sys.ram.pct);
  pushCapped(sysHistory.disk, sys.disk.pct);
  updateSpark('cpu', sysHistory.cpu, sys.cpu);
  updateSpark('ram', sysHistory.ram, sys.ram.pct);
  updateSpark('disk', sysHistory.disk, sys.disk.pct);
  if (sys.gpu) {
    const gpuMeter = document.getElementById('gpu-meter');
    if (gpuMeter) gpuMeter.style.display = '';
    const vramPct = sys.gpu.vram_total > 0 ? Math.round(sys.gpu.vram_used / sys.gpu.vram_total * 100) : 0;
    updateMeter('gpu', vramPct, vramPct + '%');
    pushCapped(sysHistory.gpu, vramPct);
    updateSpark('gpu', sysHistory.gpu, vramPct);
  }
}

// ── Connections ──
function renderConnections(rows) {
  const f = getFilter();
  const filtered = rows.filter(r => {
    if (!f) return true;
    return r.process.toLowerCase().includes(f) ||
      r.local.includes(f) ||
      r.remote.includes(f) ||
      String(r.pid).includes(f);
  });
  document.getElementById('conn-count').textContent = filtered.length + ' connection(s)';
  const tbody = document.getElementById('conn-body');
  if (!filtered.length) {
    tbody.innerHTML = '<tr><td colspan="4" class="empty">No active connections</td></tr>';
    return;
  }
  tbody.innerHTML = filtered.map(r => `
    <tr>
      <td class="project">${esc(r.process)}</td>
      <td style="font-size:12px;color:var(--text-dim);">${esc(r.local)}</td>
      <td style="font-size:12px;color:var(--cyan);">${esc(r.remote)}</td>
      <td class="pid">${r.pid || ''}</td>
    </tr>
  `).join('');
}

// ── Docker accordion ──
const accordionState = {};

function getProjectHealth(containers) {
  const hasDown = containers.some(r => !r.status.toLowerCase().startsWith('up'));
  const hasUnhealthy = containers.some(r => r.health === 'unhealthy');
  if (hasDown) return 'red';
  if (hasUnhealthy) return 'orange';
  return 'green';
}

function isCollapsed(proj) {
  return accordionState[proj] !== true;
}

function toggleAccordion(proj) {
  accordionState[proj] = isCollapsed(proj) ? true : false;
  const header = document.querySelector(`[data-project="${CSS.escape(proj)}"]`);
  const rows = document.querySelectorAll(`[data-group="${CSS.escape(proj)}"]`);
  const chevron = header ? header.querySelector('.chevron') : null;
  if (isCollapsed(proj)) {
    rows.forEach(r => r.style.display = 'none');
    if (chevron) chevron.style.transform = 'rotate(-90deg)';
  } else {
    rows.forEach(r => r.style.display = '');
    if (chevron) chevron.style.transform = '';
  }
}

function renderDocker(rows) {
  document.getElementById('docker-count').textContent = rows.length + ' container(s)';
  const tbody = document.getElementById('docker-body');
  if (!rows.length) {
    tbody.innerHTML = '<tr><td colspan="7" class="empty">No Docker containers running</td></tr>';
    return;
  }

  const groups = {};
  const noProject = [];
  rows.forEach(r => {
    if (r.project) {
      if (!groups[r.project]) groups[r.project] = [];
      groups[r.project].push(r);
    } else {
      noProject.push(r);
    }
  });

  let html = '';

  function containerRow(r, group) {
    const collapsed = group && isCollapsed(group);
    return `
      <tr style="${collapsed ? 'display:none;' : ''}" ${group ? `data-group="${esc(group)}"` : ''}>
        <td style="text-align:center;">${techIcon(r.name, r.image)}</td>
        <td class="project">${esc(r.name)}</td>
        <td style="color:var(--purple);font-size:11px;">${esc(r.image)}</td>
        <td>${imageVersion(r.image)}</td>
        <td><span class="docker-status ${r.status.toLowerCase().startsWith('up') ? 'up' : 'other'}">${esc(r.status)}</span></td>
        <td>${dockerPorts(r)}</td>
        <td>
          <button class="restart-btn" data-id="${esc(r.id)}" data-name="${esc(r.name)}" data-action="restart">restart</button>
          <button class="stop-btn" data-id="${esc(r.id)}" data-name="${esc(r.name)}" data-action="stop">stop</button>
        </td>
      </tr>`;
  }

  Object.keys(groups).sort().forEach(proj => {
    const health = getProjectHealth(groups[proj]);
    const collapsed = isCollapsed(proj);
    html += `
      <tr class="project-row" data-project="${esc(proj)}">
        <td style="text-align:center;">
          <span class="chevron" style="font-size:10px;color:var(--text-dim);display:inline-block;transition:transform .2s;${collapsed ? 'transform:rotate(-90deg);' : ''}">&#9660;</span>
        </td>
        <td class="project" style="font-weight:700;">
          <span class="health-dot ${health}" style="display:inline-block;margin-right:6px;"></span>
          <img src="${ICONS.docker}" alt="docker" style="width:14px;height:14px;vertical-align:-2px;margin-right:4px;">
          ${esc(proj)}
        </td>
        <td></td>
        <td></td>
        <td></td>
        <td></td>
        <td style="color:var(--text-dim);font-size:12px;text-align:right;">${groups[proj].length} container(s)</td>
      </tr>`;
    groups[proj].forEach(r => { html += containerRow(r, proj); });
  });

  noProject.forEach(r => { html += containerRow(r, null); });
  tbody.innerHTML = html;
}

function renderPorts(rows) {
  const f = getFilter();
  const filtered = rows.filter(r => {
    if (!f) return true;
    return String(r.port).includes(f) ||
      r.process.toLowerCase().includes(f) ||
      r.cmd.toLowerCase().includes(f) ||
      String(r.pid).includes(f);
  });
  document.getElementById('port-count').textContent = filtered.length + ' port(s)';
  const tbody = document.getElementById('port-body');
  if (!filtered.length) {
    tbody.innerHTML = '<tr><td colspan="5" class="empty">No listening ports</td></tr>';
    return;
  }
  tbody.innerHTML = filtered.map(r => `
    <tr>
      <td>${portTags([r.port])}</td>
      <td class="project">${esc(r.process)}</td>
      <td class="pid">${r.pid || ''}</td>
      <td><span class="bind-tag ${r.bind}">${r.bind === 'all' ? '0.0.0.0' : '127.0.0.1'}</span></td>
      <td class="cmd" title="${esc(r.cmd)}">${esc(r.cmd)}</td>
    </tr>
  `).join('');
}

// ── Actions ──
function askKill(pid, project) {
  actionTarget = { kind: 'kill', pid, project };
  document.getElementById('modal-title').textContent = 'Kill process?';
  document.getElementById('kill-pid-display').textContent = pid;
  document.getElementById('kill-proj-display').textContent = project;
  document.getElementById('modal-detail').textContent = 'SIGTERM';
  document.getElementById('kill-modal').classList.add('show');
}

function askDockerStop(id, name) {
  actionTarget = { kind: 'docker-stop', id, name };
  document.getElementById('modal-title').textContent = 'Stop container?';
  document.getElementById('kill-pid-display').textContent = id.substring(0, 12);
  document.getElementById('kill-proj-display').textContent = name;
  document.getElementById('modal-detail').textContent = 'docker stop';
  document.getElementById('kill-modal').classList.add('show');
}

function askDockerRestart(id, name) {
  actionTarget = { kind: 'docker-restart', id, name };
  document.getElementById('modal-title').textContent = 'Restart container?';
  document.getElementById('kill-pid-display').textContent = id.substring(0, 12);
  document.getElementById('kill-proj-display').textContent = name;
  document.getElementById('modal-detail').textContent = 'docker restart';
  document.getElementById('kill-modal').classList.add('show');
}

function closeModal() { document.getElementById('kill-modal').classList.remove('show'); actionTarget = null; }

async function confirmAction() {
  if (!actionTarget) return;
  const target = actionTarget;
  closeModal();
  try {
    let res;
    if (target.kind === 'kill') {
      res = await fetch(apiBase() + '/api/kill', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pid: target.pid })
      });
    } else if (target.kind === 'docker-stop') {
      res = await fetch(apiBase() + '/api/docker/stop', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: target.id })
      });
    } else if (target.kind === 'docker-restart') {
      res = await fetch(apiBase() + '/api/docker/restart', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: target.id })
      });
    }
    const json = await res.json();
    if (!res.ok) { showError(json.error || 'Action failed'); return; }
    await fetchData();
  } catch(e) {
    showError('Action failed: ' + e.message);
  }
}

// ── Watch ──
function cycleWatch() {
  watchSpeedIdx = (watchSpeedIdx + 1) % WATCH_SPEEDS.length;
  applyWatch();
}

function applyWatch() {
  clearInterval(watchInterval);
  const speed = WATCH_SPEEDS[watchSpeedIdx];
  const btn = document.getElementById('watch-btn');
  const line = document.getElementById('status-line');
  if (speed > 0) {
    btn.textContent = 'Watch ' + speed + 's';
    btn.classList.add('active');
    line.classList.remove('off');
    watchInterval = setInterval(fetchData, speed * 1000);
  } else {
    btn.textContent = 'Watch off';
    btn.classList.remove('active');
    line.classList.add('off');
  }
}

// ── Quick actions ──
function openUrl(port) { window.open('http://localhost:' + port, '_blank', 'noopener'); }
function copyUrl(port) { const u = 'http://localhost:' + port; copyText(u).then(() => flashToast('Copied', u, '')); }
function copyPath(path) { copyText(path).then(() => flashToast('Copied', path, '')); }

async function openDir(path) {
  try {
    const res = await fetch(apiBase() + '/api/open', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path })
    });
    const json = await res.json().catch(() => ({}));
    if (res.ok) flashToast('Folder opened', path, '');
    else flashToast('Open failed', json.error || ('HTTP ' + res.status), 'warn');
  } catch (e) {
    flashToast('Open failed', e.message, 'danger');
  }
}

// ── Cockpit (grouped by project) ──
function applyViewClasses() {
  document.body.classList.toggle('mode-cockpit', viewMode === 'cockpit');
  document.body.classList.toggle('mode-tables', viewMode === 'tables');
  const c = document.getElementById('view-cockpit'), t = document.getElementById('view-tables');
  if (c) c.classList.toggle('active', viewMode === 'cockpit');
  if (t) t.classList.toggle('active', viewMode === 'tables');
}

function setView(mode) {
  viewMode = (mode === 'tables') ? 'tables' : 'cockpit';
  localStorage.setItem('dw-view', viewMode);
  applyViewClasses();
  fetchData();
}

function toggleCard(key) {
  cockpitCollapsed[key] = !cockpitCollapsed[key];
  renderAll();
}

function matchPortRow(r, f) {
  return String(r.port).includes(f) ||
    (r.process || '').toLowerCase().includes(f) ||
    (r.cmd || '').toLowerCase().includes(f);
}

function projectHostPorts(g) {
  const set = new Set();
  g.processes.forEach(p => (p.ports || []).forEach(x => set.add(x)));
  g.containers.forEach(c => (c.ports || []).forEach(x => set.add(x.host)));
  return [...set].sort((a, b) => a - b);
}

function filterProjectMembers(g, f) {
  if (!f || (g.name || '').toLowerCase().includes(f)) return g;
  const processes = g.processes.filter(r => matchProc(r, f));
  const containers = g.containers.filter(r => matchDocker(r, f));
  const ports = g.ports.filter(r => matchPortRow(r, f));
  if (!processes.length && !containers.length && !ports.length) return null;
  return { ...g, processes, containers, ports };
}

function cockpitProcRow(p) {
  const cpuSpark = sparkline((procHistory[p.pid] || {}).cpu, 100, p.cpu);
  return `<div class="proj-row">
    ${typeTag(p.type)}
    <span class="pid">${p.pid}</span>
    <span class="metric">${cpuSpark}<span style="color:${meterColor(p.cpu)}">${p.cpu}%</span></span>
    <span class="metric">${p.mem_mb} MB</span>
    <span class="cmd" title="${esc(p.cmd)}">${esc(p.cmd)}</span>
    <span class="spacer"></span>
    <button class="opendir-btn" data-path="${esc(p.dir_full)}" title="Open folder">dir</button>
    <button class="kill-btn" data-pid="${p.pid}" data-project="${esc(p.project)}">kill</button>
  </div>`;
}

function cockpitContainerRow(c) {
  const up = c.status.toLowerCase().startsWith('up');
  return `<div class="proj-row">
    ${techIcon(c.name, c.image)}
    <span class="cname">${esc(c.name)}${c.service ? ` <span class="project-badges">(${esc(c.service)})</span>` : ''}</span>
    <span class="docker-status ${up ? 'up' : 'other'}">${esc(c.status)}</span>
    ${dockerPorts(c)}
    <span class="spacer"></span>
    <button class="restart-btn" data-id="${esc(c.id)}" data-name="${esc(c.name)}" data-action="restart">restart</button>
    <button class="stop-btn" data-id="${esc(c.id)}" data-name="${esc(c.name)}" data-action="stop">stop</button>
  </div>`;
}

function cockpitPortRow(pt) {
  return `<div class="proj-row">
    ${portTags([pt.port])}
    <span class="project">${esc(pt.process || '')}</span>
    <span class="pid">${pt.pid || ''}</span>
    <span class="bind-tag ${pt.bind}">${pt.bind === 'all' ? '0.0.0.0' : '127.0.0.1'}</span>
  </div>`;
}

function renderProjectCard(g) {
  const collapsed = cockpitCollapsed[g.key];
  const ung = g.key === '__ungrouped__';
  const badges = [];
  if (g.processes.length) badges.push(g.processes.length + ' proc');
  if (g.containers.length) badges.push(g.containers.length + ' cont');

  const shownPids = new Set(g.processes.map(p => p.pid));
  const hostPorts = new Set(g.containers.flatMap(c => (c.ports || []).map(x => x.host)));
  const orphanPorts = g.ports.filter(pt => !shownPids.has(pt.pid) && !hostPorts.has(pt.port));

  let detail = g.processes.map(cockpitProcRow).join('') + g.containers.map(cockpitContainerRow).join('');
  if (orphanPorts.length) {
    detail += '<div class="proj-section-label">ports</div>' + orphanPorts.map(cockpitPortRow).join('');
  }

  return `<div class="project-card ${collapsed ? 'collapsed' : ''} ${ung ? 'ungrouped' : ''}">
    <div class="project-head" data-card="${esc(g.key)}">
      <span class="chevron">&#9660;</span>
      <span class="health-dot ${g.health}"></span>
      <span class="project-name">${esc(g.name)}</span>
      <span class="project-badges">${badges.join(' · ')}</span>
      ${g.processes.length ? `<span class="project-summary">CPU ${g.cpu}% · ${g.mem_mb} MB</span>` : ''}
      <span class="project-chips">${portTags(projectHostPorts(g))}</span>
    </div>
    <div class="project-detail">${detail || '<div class="empty">empty</div>'}</div>
  </div>`;
}

function renderCockpit(projects, f) {
  const body = document.getElementById('cockpit-body');
  const cards = projects.map(g => filterProjectMembers(g, f)).filter(Boolean);
  body.innerHTML = cards.length
    ? cards.map(renderProjectCard).join('')
    : '<div class="empty">No projects detected</div>';
}

// ── Event delegation (no inline handlers built from process/container data) ──
document.getElementById('proc-body').addEventListener('click', e => {
  const kill = e.target.closest('.kill-btn');
  if (kill) { askKill(Number(kill.dataset.pid), kill.dataset.project); return; }
  const opendir = e.target.closest('.opendir-btn');
  if (opendir) { openDir(opendir.dataset.path); return; }
  const portOpen = e.target.closest('.port-open');
  if (portOpen) { openUrl(portOpen.dataset.port); return; }
  const portCopy = e.target.closest('.port-copy');
  if (portCopy) { copyUrl(portCopy.dataset.port); return; }
  const dir = e.target.closest('.dir.copyable');
  if (dir) { copyPath(dir.dataset.path); return; }
});

document.getElementById('port-body').addEventListener('click', e => {
  const portOpen = e.target.closest('.port-open');
  if (portOpen) { openUrl(portOpen.dataset.port); return; }
  const portCopy = e.target.closest('.port-copy');
  if (portCopy) { copyUrl(portCopy.dataset.port); return; }
});

document.getElementById('docker-body').addEventListener('click', e => {
  const actionBtn = e.target.closest('.restart-btn, .stop-btn');
  if (actionBtn) {
    const { id, name, action } = actionBtn.dataset;
    if (action === 'restart') askDockerRestart(id, name);
    else askDockerStop(id, name);
    return;
  }
  const projRow = e.target.closest('.project-row');
  if (projRow) toggleAccordion(projRow.dataset.project);
});

// Cockpit: one delegated handler reusing all existing action functions.
document.getElementById('cockpit-view').addEventListener('click', e => {
  const portOpen = e.target.closest('.port-open');
  if (portOpen) { openUrl(portOpen.dataset.port); return; }
  const portCopy = e.target.closest('.port-copy');
  if (portCopy) { copyUrl(portCopy.dataset.port); return; }
  const kill = e.target.closest('.kill-btn');
  if (kill) { askKill(Number(kill.dataset.pid), kill.dataset.project); return; }
  const opendir = e.target.closest('.opendir-btn');
  if (opendir) { openDir(opendir.dataset.path); return; }
  const action = e.target.closest('.restart-btn, .stop-btn');
  if (action) {
    const { id, name, action: act } = action.dataset;
    if (act === 'restart') askDockerRestart(id, name); else askDockerStop(id, name);
    return;
  }
  const head = e.target.closest('.project-head');
  if (head) { toggleCard(head.dataset.card); return; }
});

// ── Init ──
applyViewClasses();
fetchData();
applyWatch();
