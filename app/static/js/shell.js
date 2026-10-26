// Shared top bar for every page: logo, navigation, demo-account switcher and notifications.
// Owned by Lane A. Pages include <div id="tw-shell"></div> and this script, then use:
//   await TW.ready          -> the signed-in demo user ({id, name, role, dept, group, teacher_id, club})
//   await TW.api(path, opts) -> fetch JSON with the X-User header; throws Error(detail) on 4xx/5xx
(function () {
  const KEY = 'tw-user';
  const read = () => { try { return localStorage.getItem(KEY) || 'admin'; } catch { return 'admin'; } };
  const ROLE_LABEL = { admin: 'Timetable office', hod: 'HODs', teacher: 'Teachers', student: 'Students',
                       club: 'Club leads', org: 'Visitors & T&P' };
  const ROLE_ORDER = ['student', 'teacher', 'hod', 'club', 'org', 'admin'];
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  const TW = window.TW = {
    userId: read(), user: null, users: null, notes: { items: [], unread: 0 },
    async api(path, opts = {}) {
      const res = await fetch(path, { ...opts, headers: { 'Content-Type': 'application/json', ...(opts.headers || {}), 'X-User': TW.userId } });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw Object.assign(new Error(body.detail || res.statusText), { status: res.status, body });
      return body;
    },
    setUser(id) { try { localStorage.setItem(KEY, id); } catch {} location.reload(); },
  };

  async function loadNotes() {
    try { TW.notes = await TW.api('/api/notifications'); } catch { return; }
    const badge = document.getElementById('tw-badge');
    if (badge) { badge.textContent = TW.notes.unread; badge.style.display = TW.notes.unread ? '' : 'none'; }
  }

  function render() {
    const mount = document.getElementById('tw-shell');
    if (!mount) return;
    const here = location.pathname + location.hash;
    const links = [['/', 'Timetable'], ['/compare.html', 'Optimised CSE'], ['/#rooms', 'Free rooms'], ['/venues.html', 'Venues & events'], ['/#ask', 'Ask ✨']];
    const nav = links.map(([href, label]) => {
      const active = href === '/' ? here === '/' || here === '/#' : here.startsWith(href);
      return `<a href="${href}" class="px-3 py-1.5 rounded-lg text-sm whitespace-nowrap ${active ? 'bg-indigo-50 text-indigo-700 font-semibold' : 'text-slate-600 hover:bg-slate-100'}">${label}</a>`;
    }).join('');
    const groups = ROLE_ORDER.filter(r => TW.users.roles[r]).map(r =>
      `<optgroup label="${ROLE_LABEL[r]}">${TW.users.roles[r].map(u =>
        `<option value="${esc(u.id)}" ${u.id === TW.userId ? 'selected' : ''}>${esc(u.name)}</option>`).join('')}</optgroup>`).join('');
    mount.innerHTML = `
      <header class="no-print flex flex-wrap items-center gap-3 py-3">
        <a href="/" class="flex items-center gap-2 mr-2">
          <span class="h-9 w-9 rounded-xl bg-indigo-600 text-white grid place-items-center font-bold">TW</span>
          <span class="font-bold text-lg">TimeWeave</span>
        </a>
        <nav class="flex gap-1 overflow-x-auto order-3 sm:order-none w-full sm:w-auto">${nav}</nav>
        <div class="ml-auto flex items-center gap-2">
          <span class="hidden sm:inline text-xs px-2 py-1 rounded bg-amber-100 text-amber-800">demo account</span>
          <select id="tw-user" class="border rounded-lg px-2 py-1.5 bg-white text-sm max-w-[13rem]">${groups}</select>
          <button id="tw-bell" class="relative h-9 w-9 rounded-lg border bg-white grid place-items-center" aria-label="Notifications">🔔
            <span id="tw-badge" class="absolute -top-1 -right-1 text-[10px] bg-red-600 text-white rounded-full px-1.5" style="display:none">0</span>
          </button>
        </div>
        <div id="tw-notes" class="hidden fixed right-4 top-16 z-50 w-80 max-w-[calc(100vw-2rem)] rounded-xl border bg-white shadow-lg p-2 text-sm"></div>
      </header>`;
    document.getElementById('tw-user').addEventListener('change', e => TW.setUser(e.target.value));
    document.getElementById('tw-bell').addEventListener('click', async () => {
      const box = document.getElementById('tw-notes');
      box.classList.toggle('hidden');
      if (box.classList.contains('hidden')) return;
      box.innerHTML = TW.notes.items.length ? TW.notes.items.map(n =>
        `<a href="${esc(n.link || '#')}" class="block rounded-lg px-2 py-1.5 hover:bg-slate-50 ${n.read ? 'text-slate-500' : 'font-medium'}">${esc(n.text)}
         <div class="text-[10px] text-slate-400">${esc((n.at || '').replace('T', ' '))}</div></a>`).join('')
        : '<div class="px-2 py-3 text-slate-400">No notifications yet</div>';
      if (TW.notes.unread) { await TW.api('/api/notifications/read', { method: 'POST' }).catch(() => {}); loadNotes(); }
    });
  }

  TW.ready = (async () => {
    try { TW.user = await TW.api('/api/me'); }
    catch { TW.userId = 'admin'; TW.user = await TW.api('/api/me'); }
    TW.users = await TW.api('/api/users');
    render();
    loadNotes();
    setInterval(loadNotes, 30000);
    document.dispatchEvent(new CustomEvent('tw:ready', { detail: TW.user }));
    return TW.user;
  })();
})();
