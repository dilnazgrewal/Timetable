// Shared top bar for every page: logo, navigation, account menu and notifications. Owned by Lane A.
// Pages include <div id="tw-shell"></div> and this script, then use:
//   await TW.ready           -> the signed-in user ({id, name, role, role_name, dept, student_type, section, teacher_id, club, can})
//   TW.can.<capability>      -> what this person may do (from the server's permission table; never re-implement rules)
//   await TW.api(path, opts) -> fetch JSON with the session cookie; throws Error(detail) on 4xx/5xx
// Nobody signed in -> /login.html (in demo mode the last demo account is signed in again automatically).
(function () {
  const KEY = 'tw-user';  // demo mode: remembers the last demo account
  const remembered = () => { try { return localStorage.getItem(KEY); } catch { return null; } };
  const remember = id => { try { id ? localStorage.setItem(KEY, id) : localStorage.removeItem(KEY); } catch {} };

  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const toLogin = () => { location.href = '/login.html?next=' + encodeURIComponent(location.pathname + location.search + location.hash); };

  const TW = window.TW = {
    user: null, can: {}, users: null, notes: { items: [], unread: 0 },
    async api(path, opts = {}) {
      const res = await fetch(path, { credentials: 'same-origin', ...opts, headers: { 'Content-Type': 'application/json', ...(opts.headers || {}) } });
      const body = await res.json().catch(() => ({}));
      if (res.status === 401 && !path.startsWith('/api/auth/')) { toLogin(); throw Object.assign(new Error('Please sign in.'), { status: 401 }); }
      if (!res.ok) throw Object.assign(new Error(body.detail || res.statusText), { status: res.status, body });
      return body;
    },
    async signIn(id) {  // demo mode
      await TW.api('/api/auth/demo-login', { method: 'POST', body: JSON.stringify({ user: id }) });
      remember(id);
      try {  // the sign-in page offers these as "Continue as"
        const recent = JSON.parse(localStorage.getItem('tw-recent') || '[]').filter(x => x !== id);
        localStorage.setItem('tw-recent', JSON.stringify([id, ...recent].slice(0, 6)));
      } catch {}
    },
    async setUser(id) { await TW.signIn(id); location.reload(); },
    async signOut() { remember(null); await TW.api('/api/auth/logout', { method: 'POST' }).catch(() => {}); location.href = '/login.html'; },
  };

  async function me() {
    const res = await fetch('/api/me', { credentials: 'same-origin' });
    if (res.ok) return res.json();
    if (res.status === 401 && remembered()) {  // demo mode: sign the last demo account in again
      try { await TW.signIn(remembered()); return await (await fetch('/api/me', { credentials: 'same-origin' })).json(); } catch {}
    }
    return null;
  }

  async function loadNotes() {
    try { TW.notes = await TW.api('/api/notifications'); } catch { return; }
    const badge = document.getElementById('tw-badge');
    if (badge) { badge.textContent = TW.notes.unread; badge.style.display = TW.notes.unread ? '' : 'none'; }
  }

  function render() {
    const mount = document.getElementById('tw-shell');
    if (!mount) return;
    const c = TW.can, here = location.pathname + location.hash;
    const links = [
      ['/', c.my_timetable ? 'My timetable' : 'Timetable', c.view_timetables],
      ['/compare.html', 'Optimised timetables', c.optimised_view],
      ['/#rooms', 'Free rooms', c.free_rooms],
      ['/venues.html', 'Venues & events', c.request_venue || c.approve_venues || c.endorse_venues || c.slot_finder],
      ['/concerns.html', 'Concerns', c.raise_concerns || c.view_concerns],
      ['/audit.html', 'Audit log', c.audit],
      ['/#ask', 'Ask ✨', c.chat],
    ].filter(l => l[2]);
    const nav = links.map(([href, label]) => {
      const active = href === '/' ? here === '/' || here === '/#' : here.startsWith(href);
      return `<a href="${href}" class="px-3 py-1.5 rounded-lg text-sm whitespace-nowrap ${active ? 'bg-indigo-50 text-indigo-700 font-semibold' : 'text-slate-600 hover:bg-slate-100'}">${label}</a>`;
    }).join('');
    // demo: switch account on the sign-in page (four roles; students pick year, section and subjects)
    const switcher = TW.user.demo ? `<button id="tw-switch" class="h-9 px-3 rounded-lg border bg-white text-sm text-slate-700 hover:bg-slate-50 flex items-center gap-2 max-w-[18rem]" title="Demo: sign in as someone else"><span class="truncate">${esc(TW.user.name)}</span><span class="shrink-0 font-semibold text-indigo-700">Switch</span></button>` : `<span class="text-sm text-slate-700 max-w-[16rem] truncate">${esc(TW.user.name)}</span>`;
    mount.innerHTML = `
      <header class="no-print flex flex-wrap items-center gap-3 py-3">
        <a href="/" class="flex items-center gap-2 mr-2">
          <span class="h-9 w-9 rounded-xl bg-indigo-600 text-white grid place-items-center font-bold">TW</span>
          <span class="font-bold text-lg">TimeWeave</span>
        </a>
        <nav class="flex gap-1 overflow-x-auto order-3 sm:order-none w-full sm:w-auto">${nav}</nav>
        <div class="ml-auto flex items-center gap-2">
          <span class="hidden md:inline text-xs px-2 py-1 rounded bg-slate-100 text-slate-700" title="${esc(TW.user.name)}">${esc(TW.user.role_name)}${TW.user.dept ? ' · ' + esc(TW.user.dept) : ''}</span>
          ${TW.user.demo ? '<span class="hidden sm:inline text-xs px-2 py-1 rounded bg-amber-100 text-amber-800">demo</span>' : ''}
          ${switcher}
          <button id="tw-bell" class="relative h-9 w-9 rounded-lg border bg-white grid place-items-center" aria-label="Notifications">🔔
            <span id="tw-badge" class="absolute -top-1 -right-1 text-[10px] bg-red-600 text-white rounded-full px-1.5" style="display:none">0</span>
          </button>
          <button id="tw-out" class="h-9 px-2 rounded-lg border bg-white text-sm text-slate-600 hover:bg-slate-50" title="Sign out">Sign out</button>
        </div>
        <div id="tw-notes" class="hidden fixed right-4 top-16 z-50 w-80 max-w-[calc(100vw-2rem)] rounded-xl border bg-white shadow-lg p-2 text-sm"></div>
      </header>`;
    document.getElementById('tw-switch')?.addEventListener('click', () => TW.signOut());
    document.getElementById('tw-out').addEventListener('click', () => TW.signOut());
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
    const user = await me();
    if (!user) { toLogin(); return new Promise(() => {}); }  // never resolves: the page is leaving
    TW.user = user; TW.can = user.can || {};
    if (user.demo) { try { TW.users = await TW.api('/api/auth/demo-accounts'); } catch {} }
    render();
    loadNotes();
    setInterval(loadNotes, 30000);
    document.dispatchEvent(new CustomEvent('tw:ready', { detail: TW.user }));
    return TW.user;
  })();
})();
