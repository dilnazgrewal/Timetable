// Lane C (Venues and events): Alpine component for /venues.html. Use TW.api() for every request.
function venuesApp() {
  return {
    status: 'Loading…',
    async init() {
      const user = await TW.ready;
      const ping = await TW.api('/api/venues/ping');
      this.status = `Venues lane is wired up for ${user.name} (${ping.lane}). Booking, approvals and the event slot finder come next.`;
    },
  };
}
