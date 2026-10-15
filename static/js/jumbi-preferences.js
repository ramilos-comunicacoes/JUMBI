/* Run before paint; all configurable values come from validated office preferences. */
(() => {
  const root = document.documentElement;
  const key = root.dataset.preferenceKey || 'jumbi';
  const theme = root.dataset.defaultTheme || 'dark';
  let selected = theme;
  try { selected = localStorage.getItem(key + ':theme') || theme; } catch (_) {}
  root.dataset.theme = selected === 'system' ? (matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark') : selected;
  if (root.dataset.sidebarMode !== 'manual' && matchMedia('(min-width:981px) and (hover:hover) and (pointer:fine)').matches) {
    root.classList.add('sidebar-auto', 'sidebar-collapsed');
  } else if (matchMedia('(min-width:981px)').matches) {
    try { if (localStorage.getItem(key + ':sidebar') === 'collapsed') root.classList.add('sidebar-collapsed'); } catch (_) {}
  }
})();
