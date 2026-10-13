/* All navigation works without JavaScript; enhance focus and starting hour. */
(() => {
  const detail = document.getElementById('calendar-detail');
  if (location.hash === '#calendar-detail' && detail && detail.getClientRects().length) {
    detail.focus({ preventScroll: true });
  }
  document.querySelectorAll('[data-calendar-scroll]').forEach((scroller) => {
    const header = scroller.querySelector('.calendar-time-head');
    const allDay = scroller.querySelector('.calendar-all-day');
    const offset = Number(scroller.dataset.calendarScroll) || 0;
    scroller.style.setProperty('--calendar-time-head-height', `${header?.offsetHeight || 62}px`);
    scroller.scrollTop = offset;
    scroller.addEventListener('focusin', (event) => {
      const target = event.target.closest('.calendar-time-event');
      if (!target) return;
      const top = target.getBoundingClientRect().top;
      const visibleTop = scroller.getBoundingClientRect().top + (header?.offsetHeight || 0) + (allDay?.offsetHeight || 0);
      if (top < visibleTop) scroller.scrollTop -= visibleTop - top + 8;
    });
  });
})();
