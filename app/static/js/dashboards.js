// Lane B (Dashboards UI): the Alpine component behind index.html (role home, timetable views,
// find a teacher + meetings, now / next, leave + substitutions, free rooms, teacher load, ask). Every request goes
// through TW.api() (the signed-in session). What a person may do comes from TW.can (the server's permission
// table); the role is only used for wording.

const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const isoDate = d => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
const toMin = s => +s.slice(0, 2) * 60 + +s.slice(3);
const shortName = n => (n || '').replace(/^(Dr\.|Prof\.|Er\.) /, '');
const FEATURE_ICON = { projector: '📽', ac: '❄️', sound: '🔊', computers: '💻', smart_board: '🖊', stage: '🎤' };
// today if it's a weekday, else the coming Monday (no classes at the weekend)
const schoolDay = (d = new Date()) => { d = new Date(d); while (d.getDay() === 0 || d.getDay() === 6) d.setDate(d.getDate() + 1); return isoDate(d); };
const STATE_CHIP = { open: ['Needs cover', 'bg-red-100 text-red-700'], covered: ['Covered by co-teacher', 'bg-sky-100 text-sky-800'],
                     substituted: ['Substitute', 'bg-emerald-100 text-emerald-800'], cancelled: ['Cancelled', 'bg-slate-200 text-slate-600'] };
// 'student' = one student type: a real combination of group + electives (FET group numbers alone are
// re-used across electives in 3rd/4th year, so a group is not a set of people)
const VIEW_BY = [['student', 'Student'], ['section', 'Section'], ['year', 'Year'], ['dept', 'Department'], ['teacher', 'Teacher'], ['room', 'Room']];

function dash() {
  return {
    user: null, can: {}, meta: null, tt: { ready: false, issues: [], entries: [] },
    tab: 'timetable', today: isoDate(new Date()), generating: false, elapsed: 0, problems: [], toast: '',
    VIEW_BY,

    // timetable view: what to show (f) and which week
    f: { by: 'dept', dept: 'CSE', year: '', section: '', student: '', teacher: '', room: '' },
    weekMode: 'dated', weekOf: isoDate(new Date()), view: { items: [], dates: [] }, mobileDay: 0, loadingView: false,

    // now / next card (demo date + time can be changed)
    clock: { on: isoDate(new Date()), time: new Date().toTimeString().slice(0, 5), live: true }, nowCard: null,

    // find a teacher
    ft: { q: '', id: '', on: isoDate(new Date()), day: null, week: [], ask: null, note: '' },
    meetings: { sent: [], received: [], pending: 0 }, replyText: {},

    // free rooms
    fr: { on: isoDate(new Date()), period: 0, sittable: true, kind: '', near: '', res: null },

    // leave (teacher marks own; HOD/admin mark anyone in their department) and the substitutions board
    leave: { open: false, teacher: '', on: schoolDay(), whole: true, periods: [], reason: '', busy: false, result: null },
    subs: { on: schoolDay(), days: [], board: null, busy: '', openCount: 0 },

    chat: { msgs: [], input: '', busy: false },
    suggestions: ['Find me an empty classroom right now'],

    // ---------------------------------------------------------------- start-up and roles
    async init() {
      this.user = await TW.ready;
      this.can = TW.can || {};
      this.meta = await TW.api('/api/meta');
      const wd = new Date().getDay();
      this.mobileDay = wd >= 1 && wd <= 5 ? wd - 1 : 0;
      this.fr.period = Math.max(0, Math.min(this.periodAt(this.clock.time), this.meta.periods.length - 1));
      this.myView();
      this.suggestions = this.askSuggestions();
      await Promise.all([this.load(), this.loadView(), this.loadNow(), this.loadMeetings(), this.loadSubDays()]);
      const openHash = () => {
        const h = location.hash.slice(1);
        this.go(this.tabs().some(t => t.id === h) ? h : 'timetable', false);
      };
      openHash();
      window.addEventListener('hashchange', openHash);
      setInterval(() => { if (this.clock.live) this.tick(); }, 60000);
    },
    get role() { return this.user?.role || ''; },
    get isStudent() { return this.role === 'student'; },  // wording only
    get isTeacher() { return !!this.user?.teacher_id; },  // wording only
    get canGenerate() { return !!this.can.generate; },
    get hasCard() { return !!this.can.my_timetable; },
    get canSubs() { return !!this.can.substitutions; },
    // department-wide numbers (metrics, real-vs-generated, teacher load): office, HOD, coordinator, Dean
    get showInsights() { return !!this.can.insights; },
    // the leave board: those who arrange cover, plus the Dean read-only (no capability key for that yet)
    get showSubs() { return this.canSubs || this.role === 'dean'; },
    tabs() {
      const c = this.can;
      const t = [{ id: 'timetable', label: this.isStudent ? 'My timetable' : this.role === 'teacher' ? 'My schedule' : 'Timetable' }];
      if (c.find_teacher) t.push({ id: 'teacher', label: 'Find a teacher' });
      if (c.free_rooms) t.push({ id: 'rooms', label: 'Free rooms' });
      if (c.request_meeting || c.reply_meetings) t.push({ id: 'meetings', label: 'Meetings', badge: this.meetings.pending });
      if (this.showSubs) t.push({ id: 'subs', label: 'Substitutions', badge: this.subs.openCount });
      if (this.showInsights) t.push({ id: 'load', label: 'Teacher load' });
      if (c.chat) t.push({ id: 'ask', label: 'Ask ✨' });
      return t;
    },
    go(id, push = true) {
      this.tab = id;
      if (push) history.replaceState(null, '', id === 'timetable' ? '/' : '#' + id);
      if (id === 'rooms') this.findRooms();
      if (id === 'meetings') this.loadMeetings();
      if (id === 'teacher' && this.ft.id) this.loadTeacher();
      if (id === 'subs') this.loadSubDays(true);
    },
    greeting() {
      if (!this.user) return '';
      const h = new Date().getHours();
      return `${h < 12 ? 'Good morning' : h < 17 ? 'Good afternoon' : 'Good evening'}, ${this.user.name}`;
    },
    homeLabel() {
      return this.isStudent ? 'My timetable' : this.role === 'teacher' ? 'My schedule' : 'My department';
    },
    myView() {
      const u = this.user;
      if (u.role === 'student') {
        const s = this.meta.sections.find(s => s.id === u.section);
        Object.assign(this.f, { by: 'student', dept: s?.dept || u.dept, year: s?.year ?? '', section: s?.id || '', student: u.student_type });
      } else if (u.role === 'teacher' && u.teacher_id) {
        const t = this.meta.teachers.find(t => t.id === u.teacher_id);
        Object.assign(this.f, { by: 'teacher', dept: t?.dept || u.dept, teacher: u.teacher_id });
      } else {
        Object.assign(this.f, { by: 'dept', dept: u.dept || this.meta.departments[0].code });
      }
      this.cascade();
    },
    isMine() {
      const u = this.user || {};
      if (u.role === 'student') return this.f.by === 'student' && this.f.student === u.student_type;
      if (u.role === 'teacher') return this.f.by === 'teacher' && this.f.teacher === u.teacher_id;
      return this.f.by === 'dept' && this.f.dept === (u.dept || this.meta?.departments[0].code);
    },
    async load() {
      try { this.tt = await TW.api('/api/timetable'); } catch { this.tt = { ready: false }; }
      if (!this.tt.ready) this.tt = { ready: false, issues: [], entries: [] };
    },
    // header badge (staff see issues; the published data can list one combined class in two departments)
    teacherClashes() { return (this.tt.issues || []).filter(i => i.startsWith('CLASH Teacher')).length; },
    issuesLabel() {
      const n = (this.tt.issues || []).length;
      if (!n) return '✔ Timetable verified: 0 clashes';
      return n === this.teacherClashes() ? `⚠ ${n} teacher double-booking${n === 1 ? '' : 's'}, as published` : `✖ ${n} timetable issues`;
    },
    issuesHelp() {
      const n = this.teacherClashes();
      return n ? `${n} place${n === 1 ? '' : 's'} where a teacher appears in two departments' timetables at once (combined classes, as published).` : '';
    },
    flash(msg) { this.toast = msg; clearTimeout(this._t); this._t = setTimeout(() => this.toast = '', 3500); },

    // ---------------------------------------------------------------- timetable filters
    deptOptions() {
      if (!this.meta) return [];
      const withSections = new Set(this.meta.sections.filter(s => s.kind !== 'elective').map(s => s.dept));
      if (['student', 'section', 'year'].includes(this.f.by)) return this.meta.departments.filter(d => withSections.has(d.code));
      if (this.f.by === 'room') return [...this.meta.departments.filter(d => this.meta.rooms.some(r => r.dept === d.code && r.kind !== 'Other department')),
                                        { code: 'CENTRAL', name: 'Shared / central' }];
      return this.meta.departments;
    },
    yearOptions() { return [...new Set((this.meta?.sections || []).filter(s => s.dept === this.f.dept && s.kind !== 'elective').map(s => s.year))].sort(); },
    sectionOptions() {
      // real class sections only: elective audiences (kind "elective") have no student types of their own
      return (this.meta?.sections || []).filter(s => s.dept === this.f.dept && s.kind !== 'elective' && (this.f.by === 'section' || this.f.by === 'student' ? true : String(s.year) === String(this.f.year)));
    },
    studentOptions() { return (this.meta?.student_types || []).filter(t => t.section === this.f.section); },
    teacherOptions() { return (this.meta?.teachers || []).filter(t => t.dept === this.f.dept); },
    // "Other department" rooms are placeholders for classes taught elsewhere, not real rooms
    roomOptions() { return (this.meta?.rooms || []).filter(r => r.kind !== 'Other department' && (this.f.dept === 'CENTRAL' ? !r.dept : r.dept === this.f.dept)); },
    yearLabel(y) { return { 1: '1st year', 2: '2nd year', 3: '3rd year', 4: '4th year' }[y] || `Year ${y}`; },
    // "D4 CS A · A2 · CV · SC A1 group · TA A3" -> "A2 · CV · SC A1 group · TA A3"
    typeLabel(t) { return t ? t.name.split(' · ').slice(1).join(' · ') || t.name : ''; },
    typeTitle(t) { return t ? Object.entries(t.details || {}).map(([k, v]) => `${k}: ${v}`).join('\n') : ''; },
    studentType(id) { return (this.meta?.student_types || []).find(t => t.id === id); },
    // keep every lower filter valid after a higher one changes, then reload
    cascade() {
      const pick = (list, cur, key = x => x) => list.some(x => String(key(x)) === String(cur)) ? cur : (list.length ? key(list[0]) : '');
      this.f.dept = pick(this.deptOptions(), this.f.dept, d => d.code);
      this.f.year = pick(this.yearOptions(), this.f.year);
      this.f.section = pick(this.sectionOptions(), this.f.section, s => s.id);
      this.f.student = pick(this.studentOptions(), this.f.student, t => t.id);
      this.f.teacher = pick(this.teacherOptions(), this.f.teacher, t => t.id);
      this.f.room = pick(this.roomOptions(), this.f.room, r => r.id);
    },
    changed() { this.cascade(); this.loadView(); },
    viewQuery() {
      const f = this.f, q = new URLSearchParams();
      if (f.by === 'student') q.set('student', f.student);
      if (f.by === 'section') q.set('section', f.section);
      if (f.by === 'year') { q.set('dept', f.dept); q.set('year', f.year); }
      if (f.by === 'dept') q.set('dept', f.dept);
      if (f.by === 'teacher') q.set('teacher', f.teacher);
      if (f.by === 'room') q.set('room', f.room);
      if (this.weekMode === 'dated') q.set('week_of', this.weekOf || this.today);
      return q.toString();
    },
    async loadView() {
      if (!this.meta) return;
      this.loadingView = true;
      try { this.view = await TW.api('/api/dash/views?' + this.viewQuery()); }
      catch (e) { this.view = { items: [], dates: [] }; this.flash(e.message); }
      this.loadingView = false;
    },
    shiftWeek(n) {
      const d = new Date((this.weekOf || this.today) + 'T12:00'); d.setDate(d.getDate() + 7 * n);
      this.weekOf = isoDate(d); this.loadView();
    },
    viewTitle() {
      const f = this.f, m = this.meta; if (!m) return '';
      const dept = m.departments.find(d => d.code === f.dept);
      if (f.by === 'student') {
        const t = this.studentType(f.student);
        return `Student timetable: ${t ? t.name : f.student}`;
      }
      if (f.by === 'section') return `Class timetable: ${m.sections.find(s => s.id === f.section)?.name || f.section}`;
      if (f.by === 'year') return `${f.dept} ${this.yearLabel(+f.year)}: all sections`;
      if (f.by === 'dept') return `Department: ${dept ? dept.name : f.dept}`;
      if (f.by === 'teacher') return `Teacher timetable: ${m.teachers.find(t => t.id === f.teacher)?.name || f.teacher}`;
      const r = m.rooms.find(r => r.id === f.room);
      return `Room timetable: ${f.room}${r ? ' (' + r.kind + ')' : ''}`;
    },
    weekLabel() {
      if (this.weekMode !== 'dated' || !this.view.dates?.length) return 'Usual weekly timetable';
      const fmt = s => new Date(s + 'T12:00').toLocaleDateString(undefined, { day: 'numeric', month: 'short' });
      return `Week of ${fmt(this.view.dates[0])} – ${fmt(this.view.dates[this.view.dates.length - 1])}`;
    },
    dayDate(di) {
      const d = this.view.dates?.[di];
      return d ? new Date(d + 'T12:00').toLocaleDateString(undefined, { day: 'numeric', month: 'short' }) : '';
    },
    isToday(di) {
      if (this.weekMode === 'dated') return this.view.dates?.[di] === this.today;
      const wd = new Date().getDay(); return wd - 1 === di;
    },
    cell(d, p) {
      return this.view.items.filter(e => e.day === d && p >= e.start && p < e.start + e.duration);
    },
    weeklyHours() {
      const set = new Set();
      this.view.items.filter(e => e.kind === 'class').forEach(e => { for (let p = e.start; p < e.start + e.duration; p++) set.add(e.day + ':' + p); });
      return set.size;
    },
    hue(code) { let h = 0; for (const c of code) h = (h * 31 + c.charCodeAt(0)) % 360; return h; },
    chip(e, p) {
      if (e.kind === 'booking') {
        return `<div class="chip rounded-md px-2 py-1 leading-tight bg-violet-50 border-violet-500">
          <div class="font-semibold text-xs">📌 Event</div>
          <div class="text-[11px] text-slate-700 truncate" title="${esc(e.title)}">${esc(e.title)}</div>
          <div class="text-[10px] text-slate-500">${esc(e.room)}</div></div>`;
      }
      const h = this.hue(e.code + e.dept), lab = e.lesson_kind === 'lab', by = this.f.by;
      const part = lab ? `<span class="text-[10px] text-slate-500">${p === e.start ? 'lab 1/2' : 'lab 2/2'}</span>` : '';
      let sub;
      if (by === 'teacher') sub = `${e.section} · ${e.room}`;
      else if (by === 'room') sub = `${e.section} · ${shortName(e.teacher_name)}`;
      else if (by === 'student' || by === 'section') sub = `${shortName(e.teacher_name)} · ${e.room}`;
      else sub = `${e.section} · ${e.room}`;
      const batch = lab && (by === 'student' || by === 'section')
        ? `<span class="ml-1 text-[10px] px-1 rounded bg-white/70 border">${esc(e.batches[0].split('-').pop())}</span>` : '';
      const flag = e.status === 'substituted'
        ? `<div class="mt-0.5 text-[10px] font-semibold text-amber-800 bg-amber-100 rounded px-1">↺ Substitute: ${esc(e.teacher_name)}${e.regular_teacher_name ? ' (for ' + esc(shortName(e.regular_teacher_name)) + ')' : ''}</div>`
        : e.status === 'room_changed' ? `<div class="text-[10px] font-semibold text-amber-700">⇄ moved to ${esc(e.room)}</div>` : '';
      const ring = e.status !== 'normal' ? ' ring-2 ring-amber-400' : '';
      return `<div class="chip rounded-md px-2 py-1 leading-tight${ring}" style="background:hsl(${h} 85% 95%);border-color:hsl(${h} 60% 50%)">
        <div class="flex justify-between gap-1"><span class="font-semibold text-xs">${esc(e.code)}${batch}</span>${part}</div>
        <div class="text-[11px] text-slate-700 truncate" title="${esc(e.name)}">${esc(e.name)}</div>
        <div class="text-[10px] text-slate-500 truncate">${esc(sub)}</div>${flag}</div>`;
    },
    openTeacher(id) {
      const t = this.meta.teachers.find(t => t.id === id); if (!t) return;
      Object.assign(this.f, { by: 'teacher', dept: t.dept, teacher: t.id }); this.cascade(); this.loadView(); this.go('timetable');
    },

    // ---------------------------------------------------------------- now / next card
    periodAt(hhmm) {
      const ps = this.meta?.periods || [], m = toMin(hhmm);
      if (!ps.length || m < toMin(ps[0].start)) return -1;
      const i = ps.findIndex(p => m >= toMin(p.start) && m < toMin(p.end));
      return i >= 0 ? i : ps.length;
    },
    tick() {
      const n = new Date(); this.clock.on = isoDate(n); this.clock.time = n.toTimeString().slice(0, 5); this.loadNow();
    },
    async loadNow() {
      if (!this.hasCard) return;
      try { this.nowCard = await TW.api(`/api/dash/now?on=${this.clock.on}&period=${this.periodAt(this.clock.time)}`); }
      catch { this.nowCard = null; }
    },
    setClock() { this.clock.live = false; this.loadNow(); },
    resetClock() { this.clock.live = true; this.tick(); },
    nowLine(e) { return e ? `${e.code} · ${e.name}` : ''; },
    nowSub(e) {
      if (!e) return '';
      const who = this.isStudent ? shortName(e.teacher_name) : e.section;
      return `${e.room} · ${who} · till ${e.until}`;
    },
    periodLabel(i) { const p = this.meta?.periods[i]; return p ? `${p.label} · ${p.start}` : ''; },

    // ---------------------------------------------------------------- find a teacher + meetings
    teacherMatches() {
      const q = this.ft.q.trim().toLowerCase(), list = this.meta?.teachers || [];
      if (!q) return list.filter(t => t.dept === (this.user?.dept || 'CSE')).slice(0, 12);
      return list.filter(t => (t.name + ' ' + t.dept + ' ' + t.id).toLowerCase().includes(q)).slice(0, 12);
    },
    pickTeacher(t) { this.ft.id = t.id; this.ft.q = ''; this.ft.ask = null; this.loadTeacher(); },
    teacher() { return this.meta?.teachers.find(t => t.id === this.ft.id); },
    async loadTeacher() {
      if (!this.ft.id) return;
      const [day, week] = await Promise.all([
        TW.api(`/api/dash/teacher/${encodeURIComponent(this.ft.id)}/free?on=${this.ft.on}`),
        TW.api(`/api/dash/views?teacher=${encodeURIComponent(this.ft.id)}&week_of=${this.ft.on}`)]);
      this.ft.day = day; this.ft.week = week;
    },
    // weekly availability strip: teaching / unavailable / free for each day × period
    weekState(d, p) {
      const w = this.ft.week; if (!w?.items) return 'free';
      if (w.items.some(e => e.day === d && p >= e.start && p < e.start + e.duration)) return 'teaching';
      if ((this.teacher()?.unavailable || []).some(([dd, pp]) => dd === d && pp === p)) return 'unavailable';
      return 'free';
    },
    stateClass(s) {
      return { free: 'bg-emerald-100 text-emerald-800 border-emerald-200', teaching: 'bg-slate-100 text-slate-500 border-slate-200',
               leave: 'bg-amber-50 text-amber-700 border-amber-200',
               unavailable: 'bg-red-50 text-red-400 border-red-100', meeting: 'bg-indigo-50 text-indigo-700 border-indigo-200' }[s];
    },
    async requestMeeting() {
      const a = this.ft.ask;
      try {
        await TW.api('/api/dash/meetings', { method: 'POST', body: JSON.stringify({ teacher: this.ft.id, date: this.ft.on, period: a.period, note: this.ft.note }) });
        this.flash(`Request sent to ${this.teacher().name}. You'll get a 🔔 when they reply.`);
        this.ft.ask = null; this.ft.note = ''; this.loadMeetings();
      } catch (e) { this.flash(e.message); }
    },
    async loadMeetings() {
      if (!this.can.request_meeting && !this.can.reply_meetings) return;
      try { this.meetings = await TW.api('/api/dash/meetings'); } catch {}
    },
    async reply(m, status) {
      try {
        await TW.api(`/api/dash/meetings/${m.id}/reply`, { method: 'POST', body: JSON.stringify({ status, reply: this.replyText[m.id] || '' }) });
        this.flash(status === 'accepted' ? 'Accepted. The student has been notified.' : 'Declined. The student has been notified.');
        this.loadMeetings(); this.loadNow();
      } catch (e) { this.flash(e.message); }
    },
    statusClass(s) { return { pending: 'bg-amber-100 text-amber-800', accepted: 'bg-emerald-100 text-emerald-800', declined: 'bg-red-100 text-red-700' }[s]; },
    isPast(day, end) { return day < this.today || (day === this.today && toMin(end) <= toMin(new Date().toTimeString().slice(0, 5))); },
    niceDate(s) { return s ? new Date(s + 'T12:00').toLocaleDateString(undefined, { weekday: 'short', day: 'numeric', month: 'short' }) : ''; },

    // ---------------------------------------------------------------- leave and substitutions
    leaveTeachers() {  // whom this account may mark on leave (the server checks leave.mark again)
      const ts = this.meta?.teachers || [];
      if (this.role === 'admin') return ts;
      if (this.can.mark_dept_leave) return ts.filter(t => t.dept === this.user.dept);  // HOD, coordinator
      return this.can.mark_own_leave ? ts.filter(t => t.id === this.user?.teacher_id) : [];
    },
    openLeave(teacherId) {
      Object.assign(this.leave, { open: true, result: null, whole: true, periods: [], reason: '',
                                  teacher: teacherId || this.user.teacher_id || this.leaveTeachers()[0]?.id || '',
                                  on: this.tab === 'subs' ? this.subs.on : schoolDay() });
    },
    togglePeriod(i) {
      const ps = this.leave.periods; ps.includes(i) ? ps.splice(ps.indexOf(i), 1) : ps.push(i);
    },
    async submitLeave() {
      const l = this.leave;
      if (!l.whole && !l.periods.length) return this.flash('Pick the periods you will miss, or choose Whole day.');
      l.busy = true;
      try {
        l.result = await TW.api('/api/leave', { method: 'POST', body: JSON.stringify({
          teacher: l.teacher, date: l.on, periods: l.whole ? [] : [...l.periods].sort((a, b) => a - b), reason: l.reason.trim() }) });
        const open = l.result.classes.filter(c => c.state === 'open').length;
        this.flash(l.result.classes.length ? `Leave saved. ${open} class${open === 1 ? ' needs' : 'es need'} cover; the HOD has been notified.`
                                           : 'Leave saved. There are no classes in that time.');
        if (this.canSubs) { this.subs.on = l.on; await this.loadSubDays(); }
        this.loadNow(); this.loadView();
      } catch (e) { this.flash(e.message); }
      l.busy = false;
    },
    // the board shows one date; the strip above it shows the next school days and how many classes need cover
    async loadSubDays(pickBusy = false) {
      if (!this.showSubs) return;
      const days = [], d = new Date(schoolDay() + 'T12:00');
      while (days.length < 6) { if (d.getDay() % 6) days.push(isoDate(d)); d.setDate(d.getDate() + 1); }
      if (!days.includes(this.subs.on)) days.unshift(this.subs.on);
      const boards = await Promise.all(days.map(on => TW.api('/api/leave?on=' + on).catch(() => ({ date: on, leaves: [] }))));
      this.subs.days = boards.map(b => ({ date: b.date, leaves: b.leaves.length,
                                          open: b.leaves.reduce((n, l) => n + l.classes.filter(c => c.state === 'open').length, 0) }));
      this.subs.openCount = this.subs.days.reduce((n, d) => n + d.open, 0);
      const cur = this.subs.days.find(d => d.date === this.subs.on);
      if (pickBusy && !cur?.leaves) this.subs.on = (this.subs.days.find(d => d.leaves) || cur || this.subs.days[0]).date;
      this.subs.board = boards.find(b => b.date === this.subs.on) || await TW.api('/api/leave?on=' + this.subs.on);
    },
    async loadSubs() {
      try { this.subs.board = await TW.api('/api/leave?on=' + this.subs.on); } catch (e) { this.flash(e.message); }
    },
    async decide(c, teacher) {
      this.subs.busy = c.key;
      const body = teacher ? { date: this.subs.on, entry_key: c.key, teacher } : { date: this.subs.on, entry_key: c.key, cancel: true };
      try {
        const r = await TW.api('/api/substitutions', { method: 'POST', body: JSON.stringify(body) });
        this.flash(r.message);
      } catch (e) { this.flash(e.message); }  // 409: that teacher is no longer free
      this.subs.busy = '';
      await this.loadSubDays(); this.loadView();
    },
    stateChip(c) {
      const [label, cls] = STATE_CHIP[c.state] || [c.state, 'bg-slate-100'];
      const who = c.by_name && c.state !== 'cancelled' ? (c.state === 'covered' ? ': ' : ': ') + c.by_name : '';
      return { text: label + who, cls };
    },
    dayChip(d) { return new Date(d + 'T12:00').toLocaleDateString(undefined, { weekday: 'short', day: 'numeric' }); },

    // ---------------------------------------------------------------- free rooms
    roomsNow() {
      this.fr.on = isoDate(new Date());
      this.fr.period = Math.max(0, Math.min(this.periodAt(new Date().toTimeString().slice(0, 5)), this.meta.periods.length - 1));
      this.findRooms();
    },
    async findRooms() {
      if (!this.meta) return;
      const q = new URLSearchParams({ on: this.fr.on, period: this.fr.period });
      if (this.fr.sittable) q.set('sittable_only', 'true');
      if (this.fr.kind) q.set('kind', this.fr.kind);
      try { this.fr.res = await TW.api('/api/free-rooms?' + q); } catch (e) { this.fr.res = null; this.flash(e.message); }
    },
    nearRoom() { return this.meta?.rooms.find(r => r.id === this.fr.near); },
    // free rooms grouped building → floor; with "near me" set, my building (my floor first) comes first
    roomGroups() {
      if (!this.meta || !this.fr.res) return [];
      const rooms = this.fr.res.free, near = this.nearRoom(), out = [];
      const bOrder = this.meta.buildings.map(b => b.id);
      const blds = [...new Set(rooms.map(r => r.building))].sort((a, b) =>
        (near && b === near.building) - (near && a === near.building) || bOrder.indexOf(a) - bOrder.indexOf(b));
      for (const bid of blds) {
        const b = this.meta.buildings.find(b => b.id === bid) || { id: bid, name: bid || 'Other', floors: [] };
        const floors = [...new Set(rooms.filter(r => r.building === bid).map(r => r.floor))].sort((x, y) =>
          (near && bid === near.building ? (y === near.floor) - (x === near.floor) : 0) || b.floors.indexOf(x) - b.floors.indexOf(y));
        out.push({ id: bid, name: b.name, here: near && bid === near.building,
                   floors: floors.map(fl => ({ name: fl, here: near && bid === near.building && fl === near.floor,
                                               rooms: rooms.filter(r => r.building === bid && r.floor === fl) }))
                                 .filter(fl => fl.rooms.length) });
      }
      return out.filter(b => b.floors.length);
    },
    floorName(f) { return f === 'Ground' ? 'Ground floor' : f ? `${f} floor` : 'Floor not set'; },
    buildingRooms(bid) { return (this.meta?.rooms || []).filter(r => r.building === bid && r.kind !== 'Other department'); },
    features(r) { return (r.features || []).map(f => FEATURE_ICON[f] || '').join(' '); },
    isWeekend(s) { const d = new Date(s + 'T12:00').getDay(); return d === 0 || d === 6; },

    // ---------------------------------------------------------------- generate, print, ask
    async generate() {
      this.generating = true; this.problems = []; this.elapsed = 0;
      const timer = setInterval(() => this.elapsed++, 1000);
      try {
        const r = await TW.api('/api/generate?time_limit=30', { method: 'POST' });
        if (r.ok === false) this.problems = r.problems || ['Generation failed'];
        await Promise.all([this.load(), this.loadView(), this.loadNow()]);
      } catch (err) { this.problems = [err.message || 'Could not reach the server']; }
      clearInterval(timer); this.generating = false;
    },
    printSubtitle() {
      return `${this.weekLabel()} · ${this.weeklyHours()} periods / week`;
    },
    // Ask-tab starters built from the live college, so they stay valid whatever data is loaded
    askSuggestions() {
      const m = this.meta, out = [];
      const lab = m.rooms.find(r => !r.sittable), teacher = m.teachers.find(t => t.id === this.user?.teacher_id) || m.teachers[0];
      const sec = m.sections.find(s => s.id === this.user?.section) || m.sections.find(s => s.dept === this.f.dept) || m.sections[0];
      if (lab) out.push(`Is ${lab.id} free after lunch on Friday?`);
      if (teacher) out.push(`When is ${shortName(teacher.name)} free on Wednesday?`);
      if (sec) out.push(`What does ${sec.name} have on Monday?`);
      return [...out, 'Find me an empty classroom right now'];
    },
    async send(text) {
      const q = (text ?? this.chat.input).trim();
      if (!q || this.chat.busy) return;
      this.chat.msgs.push({ role: 'user', content: q }); this.chat.input = ''; this.chat.busy = true;
      this.$nextTick(() => this.$refs.chatEnd?.scrollIntoView({ behavior: 'smooth' }));
      try {
        const r = await TW.api('/api/chat', { method: 'POST', body: JSON.stringify({ messages: this.chat.msgs.map(m => ({ role: m.role, content: m.content })) }) });
        this.chat.msgs.push({ role: 'assistant', content: r.answer || 'Something went wrong.', tools: r.tools_used || [] });
      } catch (err) { this.chat.msgs.push({ role: 'assistant', content: err.message || 'Could not reach the server.', tools: [] }); }
      this.chat.busy = false;
      this.$nextTick(() => this.$refs.chatEnd?.scrollIntoView({ behavior: 'smooth' }));
    },
  };
}
