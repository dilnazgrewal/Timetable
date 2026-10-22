// Lane C (Venues and events): Alpine component for /venues.html. Use TW.api() for every request.
// Tabs: #book (find + request a venue) · #requests (mine) · #inbox (approvers) · #slots (event slot finder).
function venuesApp() {
  const iso = d => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  const nextWeekday = () => { const d = new Date(); do d.setDate(d.getDate() + 1); while (d.getDay() === 0 || d.getDay() === 6); return iso(d); };
  const addDays = (s, n) => { const d = new Date(s + 'T00:00'); d.setDate(d.getDate() + n); return iso(d); };
  const CHIPS = {
    pending: ['Waiting for advisor', 'bg-amber-100 text-amber-800'],
    endorsed: ['Endorsed · waiting for final OK', 'bg-sky-100 text-sky-800'],
    approved: ['Approved ✓', 'bg-emerald-100 text-emerald-800'],
    rejected: ['Not approved', 'bg-red-100 text-red-800'],
    cancelled: ['Cancelled', 'bg-slate-100 text-slate-600'],
  };

  return {
    user: null, meta: null, periods: [], features: [], sections: [], departments: [],
    tab: 'book', today: iso(new Date()), busy: false, flash: null,
    can: { request: false, slots: false, approve: false },
    form: { date: nextWeekday(), from: 4, to: 5, attendees: 60, needs: ['projector'] },
    results: null, sheet: null, draft: { title: '', purpose: '' },
    mine: [], inbox: [], notes: {},
    sf: { dept: '', year: 0, sections: [], duration: 2, attendees: null, from: iso(new Date()), to: addDays(iso(new Date()), 13), needs: [] },
    slots: null,

    async init() {
      this.user = await TW.ready;
      this.meta = await TW.api('/api/meta');
      this.periods = this.meta.periods;
      this.features = this.meta.features;
      this.sections = this.meta.sections;
      this.departments = this.meta.departments;
      const role = this.user.role;
      const advisor = (TW.users.clubs || []).some(c => c.advisor === this.user.id);
      this.can = { request: ['club', 'teacher', 'hod', 'org', 'admin'].includes(role),
                   slots: ['org', 'hod', 'teacher', 'admin'].includes(role),
                   approve: ['hod', 'admin'].includes(role) || advisor };
      if (role === 'club') this.form.attendees = 100;
      const depts = this.deptsWithSections();
      this.sf.dept = (depts.find(d => d.code === this.user.dept) || depts[0] || {}).code || '';
      this.sf.year = this.yearsOf(this.sf.dept)[0] || 0;
      const fromHash = location.hash.slice(1);
      this.tab = this.tabs().some(t => t.id === fromHash) ? fromHash : (this.can.request ? 'book' : this.can.slots ? 'slots' : 'requests');
      window.addEventListener('hashchange', () => { const h = location.hash.slice(1); if (this.tabs().some(t => t.id === h)) { this.tab = h; this.sheet = null; } });
      await this.loadLists();
    },

    tabs() {
      const t = [{ id: 'book', label: 'Book a venue', short: 'Book' }, { id: 'requests', label: 'My requests', short: 'Mine' }];
      if (this.can.approve) t.push({ id: 'inbox', label: 'Approvals inbox', short: 'Inbox', count: this.inbox.length });
      if (this.can.slots) t.push({ id: 'slots', label: 'Event slot finder', short: 'Slot finder' });
      return t;
    },
    go(id) { this.tab = id; this.flash = null; this.sheet = null; if (id === 'requests' || id === 'inbox') this.loadLists(); },

    async loadLists() {
      try {
        this.mine = (await TW.api('/api/venues/requests?mine=1')).items;
        if (this.can.approve) this.inbox = (await TW.api('/api/venues/requests?inbox=1')).items;
      } catch (e) { this.say(e.message, false); }
    },

    // ---------- book a venue ----------
    block() { const a = Math.min(this.form.from, this.form.to), b = Math.max(this.form.from, this.form.to); return Array.from({ length: b - a + 1 }, (_, i) => a + i); },
    async search() {
      if (this.form.to < this.form.from) this.form.to = this.form.from;
      this.busy = true; this.flash = null;
      try {
        this.results = await TW.api('/api/venues/rank', { method: 'POST', body: JSON.stringify({
          date: this.form.date, periods: this.block(), attendees: this.form.attendees, needs: this.form.needs }) });
      } catch (e) { this.results = null; this.say(e.message, false); }
      this.busy = false;
    },
    openRequest(v, title = '') {
      this.sheet = { venue: v, date: this.results.date, periods: this.results.periods, attendees: this.results.attendees, needs: this.results.needs };
      this.draft = { title, purpose: '' };
    },
    async submitRequest() {
      const s = this.sheet;
      this.busy = true;
      try {
        const res = await TW.api('/api/venues/requests', { method: 'POST', body: JSON.stringify({
          title: this.draft.title, purpose: this.draft.purpose, attendees: s.attendees, needs: s.needs,
          date: s.date, periods: s.periods, room: s.venue.id }) });
        this.sheet = null; this.results = null;
        const r = res.request;
        const msg = r.status === 'approved' ? `Booked ${r.room} for ${r.when}.` : `Request sent. Waiting for ${r.waiting_for}.`;
        this.say([msg, ...res.warnings].join(' '), true);
        location.hash = 'requests'; this.tab = 'requests';
        await this.loadLists();
      } catch (e) { this.sheet = null; this.say(e.message, false); }
      this.busy = false;
    },
    approvalPath(v) {
      const final = v.dept ? `HOD ${v.dept}` : 'Timetable office';
      if ((v.dept && this.user.role === 'hod' && this.user.dept === v.dept) || (!v.dept && this.user.role === 'admin'))
        return 'none needed, it is your room';
      return this.user.role === 'club' ? `faculty advisor → ${final}` : final;
    },

    // ---------- requests and approvals ----------
    async decide(r, decision) {
      const note = (this.notes[r.id] || '').trim();
      if (decision === 'rejected' && !note) return this.say('Please write a short reason before rejecting, so the requester knows what to change.', false);
      try {
        const res = await TW.api(`/api/venues/requests/${r.id}/decide`, { method: 'POST', body: JSON.stringify({ decision, note }) });
        const s = res.request.status;
        this.say(s === 'approved' ? `Approved. ${r.room} is booked and no longer shows as a free room for that time.`
               : s === 'endorsed' ? `Endorsed. Sent on to ${res.request.waiting_for}.` : 'Rejected. The requester has been told why.', s !== 'rejected');
      } catch (e) { this.say(e.message, false); }
      await this.loadLists();
    },
    async cancel(r) {
      if (!confirm(r.status === 'approved' ? `Cancel the booking of ${r.room}? The room becomes free again.` : 'Withdraw this request?')) return;
      try { await TW.api(`/api/venues/requests/${r.id}/cancel`, { method: 'POST' }); this.say('Done. The room is free again.', true); }
      catch (e) { this.say(e.message, false); }
      await this.loadLists();
    },
    chip(status) { const [label, cls] = CHIPS[status] || [status, 'bg-slate-100']; return { label, cls }; },

    // ---------- event slot finder ----------
    deptsWithSections() { return this.departments.filter(d => this.sections.some(s => s.dept === d.code)); },
    yearsOf(dept) { return [...new Set(this.sections.filter(s => s.dept === dept).map(s => s.year))].sort(); },
    sectionsOf(dept, year) { return this.sections.filter(s => s.dept === dept && s.year === year); },
    yearLabel(y) { return y <= 4 ? `D${y} (year ${y})` : y === 5 ? 'M.Tech' : y === 6 ? 'PhD' : `Year ${y}`; },
    async findSlots() {
      this.busy = true; this.flash = null;
      const body = { duration: this.sf.duration, from: this.sf.from, to: this.sf.to, needs: this.sf.needs };
      if (this.sf.sections.length) body.sections = this.sf.sections; else Object.assign(body, { dept: this.sf.dept, year: this.sf.year });
      if (this.sf.attendees) body.attendees = this.sf.attendees;
      try { this.slots = await TW.api('/api/venues/slot-finder', { method: 'POST', body: JSON.stringify(body) }); }
      catch (e) { this.slots = null; this.say(e.message, false); }
      this.busy = false;
    },
    byDay(list) {
      const days = [];
      for (const s of list) {
        let d = days.find(x => x.date === s.date);
        if (!d) days.push(d = { date: s.date, label: s.day, slots: [] });
        d.slots.push(s);
      }
      return days;
    },
    async bookSlot(s) {
      Object.assign(this.form, { date: s.date, from: s.periods[0], to: s.periods[s.periods.length - 1],
                                 attendees: this.slots.audience.attendees, needs: [...this.sf.needs] });
      const label = this.slots.audience.label;
      location.hash = 'book'; this.tab = 'book';
      await this.search();
      const v = this.results && (this.results.venues.find(x => x.id === s.venues[0].id) || this.results.venues[0]);
      if (v) this.openRequest(v, `Session for ${label}`);
    },

    // ---------- formatting ----------
    say(text, ok) { this.flash = { text, ok }; },
    toggle(list, x) { const i = list.indexOf(x); i < 0 ? list.push(x) : list.splice(i, 1); },
    nice(f) { return f === 'ac' ? 'AC' : f.replace('_', ' '); },
    clock(hhmm) { const [h, m] = hhmm.split(':'); return `${(+h % 12) || 12}:${m}`; },
    periodsText(ps) {
      const a = this.periods[ps[0]], b = this.periods[ps[ps.length - 1]];
      return `${ps.length > 1 ? a.label + '–' + b.label : a.label} · ${this.clock(a.start)}–${this.clock(b.end)}`;
    },
    whenText(date, ps) {
      const d = new Date(date + 'T00:00');
      return `${d.toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' })} · ${this.periodsText(ps)}`;
    },
  };
}
