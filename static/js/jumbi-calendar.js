/* Navigation, date selection and agenda remain available without JavaScript. */
(() => {
  const detail = document.getElementById('calendar-detail');
  if (location.hash === '#calendar-detail' && detail) {
    detail.focus({ preventScroll: true });
  }
})();
