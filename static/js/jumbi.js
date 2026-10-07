(function () {
  'use strict';
  const root = document.documentElement;
  const sidebar = document.getElementById('main-sidebar');
  const backdrop = document.querySelector('.sidebar-backdrop');
  const openButton = document.querySelector('[data-sidebar-open]');
  const compactButton = document.querySelector('[data-sidebar-toggle]');
  const mobile = window.matchMedia('(max-width: 980px)');
  let previousFocus = null;
  const save = (key, value) => { try { localStorage.setItem(key, value); } catch (_) {} };
  function updateThemeButtons() {
    const isDark = root.dataset.theme !== 'light';
    document.querySelectorAll('[data-theme-toggle]').forEach(button => {
      button.setAttribute('aria-label', isDark ? 'Ativar tema claro' : 'Ativar tema escuro');
      button.setAttribute('title', isDark ? 'Ativar tema claro' : 'Ativar tema escuro');
      button.setAttribute('aria-pressed', String(!isDark));
    });
    const themeMeta = document.querySelector('meta[name="theme-color"]');
    if (themeMeta) themeMeta.content = isDark ? '#0b1320' : '#f8fafc';
  }
  document.querySelectorAll('[data-theme-toggle]').forEach(button => {
    button.addEventListener('click', () => {
      root.dataset.theme = root.dataset.theme === 'light' ? 'dark' : 'light';
      save('jumbi-theme', root.dataset.theme);
      updateThemeButtons();
    });
  });
  updateThemeButtons();
  function updateCompactButton() {
    if (!compactButton) return;
    const collapsed = root.classList.contains('sidebar-collapsed');
    compactButton.setAttribute('aria-expanded', String(!collapsed));
    compactButton.setAttribute('aria-label', collapsed ? 'Expandir menu lateral' : 'Recolher menu lateral');
    const text = compactButton.querySelector('span');
    if (text) text.textContent = collapsed ? 'Expandir menu' : 'Recolher menu';
  }
  if (compactButton) compactButton.addEventListener('click', () => {
    root.classList.toggle('sidebar-collapsed');
    save('jumbi-sidebar', root.classList.contains('sidebar-collapsed') ? 'collapsed' : 'expanded');
    updateCompactButton();
  });
  updateCompactButton();
  function setDrawer(open) {
    if (!sidebar) return;
    root.classList.toggle('sidebar-open', open);
    if (backdrop) backdrop.hidden = !open;
    if (openButton) openButton.setAttribute('aria-expanded', String(open));
    if (mobile.matches) sidebar.inert = !open;
    const appMain = document.querySelector('.app-main');
    if (appMain) appMain.inert = open;
    document.body.style.overflow = open ? 'hidden' : '';
    if (open) {
      previousFocus = document.activeElement;
      sidebar.querySelector('[data-sidebar-close]')?.focus();
    } else if (previousFocus) {
      previousFocus.focus();
      previousFocus = null;
    }
  }
  if (openButton) openButton.addEventListener('click', () => setDrawer(true));
  document.querySelectorAll('[data-sidebar-close]').forEach(button => button.addEventListener('click', () => setDrawer(false)));
  function syncViewport() {
    setDrawer(false);
    if (sidebar) sidebar.inert = mobile.matches;
  }
  mobile.addEventListener('change', syncViewport);
  syncViewport();
  document.addEventListener('keydown', event => {
    if (!root.classList.contains('sidebar-open')) return;
    if (event.key === 'Escape') { event.preventDefault(); setDrawer(false); return; }
    if (event.key !== 'Tab' || !sidebar) return;
    const focusable = [...sidebar.querySelectorAll('a[href], button:not([disabled]), [tabindex="0"]')].filter(el => el.offsetParent !== null);
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
  });
  if (sidebar) sidebar.querySelectorAll('a').forEach(link => link.addEventListener('click', () => {
    if (mobile.matches) setDrawer(false);
  }));
  document.querySelectorAll('[data-dismiss-message]').forEach(button => button.addEventListener('click', () => button.closest('.alert')?.remove()));
  document.querySelectorAll('[data-copy-target]').forEach(button => button.addEventListener('click', async () => {
    const target = document.getElementById(button.dataset.copyTarget);
    if (!target) return;
    const feedback = button.parentElement.querySelector('.copy-feedback');
    try {
      await navigator.clipboard.writeText(target.value);
      if (feedback) feedback.textContent = 'Link copiado.';
    } catch (_) {
      target.focus();
      target.select();
      if (feedback) feedback.textContent = 'Link selecionado. Use Ctrl+C para copiar.';
    }
  }));
  document.querySelectorAll('form[data-confirm]').forEach(form => form.addEventListener('submit', event => {
    if (!window.confirm(form.dataset.confirm)) event.preventDefault();
  }));
  document.querySelectorAll('a[data-confirm],button[data-confirm]').forEach(control => control.addEventListener('click', event => {
    if (!window.confirm(control.dataset.confirm)) event.preventDefault();
  }));
  document.querySelectorAll('.has-error input,.has-error select,.has-error textarea').forEach(control => control.setAttribute('aria-invalid', 'true'));
  const firstError = document.querySelector('.has-error input:not([type=hidden]),.has-error select,.has-error textarea');
  if (firstError) firstError.focus();

  // The operating system's reduced-motion preference always takes precedence.
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  let motionPreference = 'auto';
  try { motionPreference = localStorage.getItem('jumbi-motion') || 'auto'; } catch (_) {}
  const motionPaused = () => reducedMotion.matches || motionPreference === 'paused';
  function updateMotion() {
    const paused = motionPaused();
    root.dataset.motion = paused ? 'paused' : 'auto';
    root.classList.toggle('j-motion-ready', !paused);
    document.querySelectorAll('[data-motion-toggle]').forEach(button => {
      button.hidden = false;
      button.setAttribute('aria-pressed', String(paused));
      const label = reducedMotion.matches ? 'Movimento reduzido' : paused ? 'Ativar efeitos' : 'Pausar efeitos';
      button.title = reducedMotion.matches ? 'Animações desativadas pela preferência de acessibilidade do dispositivo' : label;
      button.setAttribute('aria-label', button.title);
      button.querySelector('[data-motion-label]').textContent = label;
      button.querySelector('[data-motion-symbol]').textContent = paused ? '▷' : 'Ⅱ';
      button.disabled = reducedMotion.matches;
    });
    if (paused) document.querySelectorAll('[data-tilt],.j-cta,.j-magnetic').forEach(el => { el.style.transform = ''; });
  }
  document.querySelectorAll('[data-motion-toggle]').forEach(button => button.addEventListener('click', () => {
    motionPreference = motionPreference === 'paused' ? 'auto' : 'paused';
    save('jumbi-motion', motionPreference);
    updateMotion();
  }));
  reducedMotion.addEventListener('change', updateMotion);
  updateMotion();

  // Progressive enhancement: all editorial content stays visible without JS.
  if ('IntersectionObserver' in window) {
    const revealObserver = new IntersectionObserver(entries => {
      entries.forEach(entry => {
        if (!entry.isIntersecting) return;
        entry.target.classList.add('j-revealed');
        revealObserver.unobserve(entry.target);
      });
    }, { threshold: 0.12 });
    document.querySelectorAll('[data-reveal]').forEach(el => revealObserver.observe(el));
    const counterObserver = new IntersectionObserver(entries => {
      entries.forEach(entry => {
        if (!entry.isIntersecting) return;
        counterObserver.unobserve(entry.target);
        const target = Number(entry.target.dataset.count);
        if (motionPaused() || !Number.isFinite(target)) return;
        let start;
        function tick(time) {
          if (!start) start = time;
          const progress = Math.min((time - start) / 850, 1);
          entry.target.textContent = String(Math.round(target * (1 - Math.pow(1 - progress, 3))));
          if (progress < 1 && !motionPaused()) requestAnimationFrame(tick);
          else entry.target.textContent = String(target);
        }
        requestAnimationFrame(tick);
      });
    }, { threshold: 0.7 });
    document.querySelectorAll('[data-count]').forEach(el => counterObserver.observe(el));
  }

  const previewTabs = [...document.querySelectorAll('[data-preview-tab]')];
  if (previewTabs.length) {
    document.querySelector('[data-preview-tabs]').hidden = false;
    document.querySelectorAll('[data-preview-panel]').forEach(panel => {
      panel.setAttribute('role', 'tabpanel');
      panel.setAttribute('aria-labelledby', 'preview-tab-' + panel.dataset.previewPanel);
      panel.tabIndex = 0;
    });
    function activateTab(tab, focus) {
      previewTabs.forEach(item => {
        const active = item === tab;
        item.setAttribute('aria-selected', String(active));
        item.tabIndex = active ? 0 : -1;
      });
      document.querySelectorAll('[data-preview-panel]').forEach(panel => {
        panel.hidden = panel.dataset.previewPanel !== tab.dataset.previewTab;
      });
      if (focus) tab.focus();
    }
    previewTabs.forEach((tab, index) => {
      tab.addEventListener('click', () => activateTab(tab, false));
      tab.addEventListener('keydown', event => {
        let next;
        if (event.key === 'ArrowRight') next = (index + 1) % previewTabs.length;
        if (event.key === 'ArrowLeft') next = (index - 1 + previewTabs.length) % previewTabs.length;
        if (event.key === 'Home') next = 0;
        if (event.key === 'End') next = previewTabs.length - 1;
        if (next === undefined) return;
        event.preventDefault();
        activateTab(previewTabs[next], true);
      });
    });
  }

  // Pointer tilt only on large screens, at most 30 updates/sec, never a polling loop.
  const precisePointer = window.matchMedia('(hover: hover) and (pointer: fine) and (min-width: 981px)');
  document.querySelectorAll('[data-tilt]').forEach(card => {
    let lastUpdate = 0;
    card.addEventListener('pointermove', event => {
      if (motionPaused() || !precisePointer.matches || event.timeStamp - lastUpdate < 33) return;
      lastUpdate = event.timeStamp;
      const bounds = card.getBoundingClientRect();
      const x = (event.clientX - bounds.left) / bounds.width - 0.5;
      const y = (event.clientY - bounds.top) / bounds.height - 0.5;
      card.style.transform = `rotateY(${x * 6}deg) rotateX(${-y * 5}deg)`;
    }, { passive: true });
    card.addEventListener('pointerleave', () => { card.style.transform = ''; });
    precisePointer.addEventListener('change', () => { card.style.transform = ''; });
  });

  // Small magnetic response keeps links in place and remains optional.
  document.querySelectorAll('.j-cta,.j-magnetic').forEach(button => {
    let lastMove = 0;
    button.addEventListener('pointermove', event => {
      if (motionPaused() || !precisePointer.matches || event.timeStamp - lastMove < 33) return;
      lastMove = event.timeStamp;
      const bounds = button.getBoundingClientRect();
      const x = ((event.clientX - bounds.left) / bounds.width - 0.5) * 7;
      const y = ((event.clientY - bounds.top) / bounds.height - 0.5) * 5;
      button.style.transform = `translate(${x}px,${y}px)`;
    }, { passive: true });
    button.addEventListener('pointerleave', () => { button.style.transform = ''; });
    button.addEventListener('blur', () => { button.style.transform = ''; });
    precisePointer.addEventListener('change', () => { button.style.transform = ''; });
  });
  document.querySelectorAll('.j-glass-card').forEach(card => {
    let lastMove = 0;
    card.addEventListener('pointermove', event => {
      if (motionPaused() || !precisePointer.matches || event.timeStamp - lastMove < 33) return;
      lastMove = event.timeStamp;
      const bounds = card.getBoundingClientRect();
      card.style.setProperty('--glow-x', (event.clientX - bounds.left) + 'px');
      card.style.setProperty('--glow-y', (event.clientY - bounds.top) + 'px');
    }, { passive: true });
  });
})();
