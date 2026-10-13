(() => {
  const form = document.querySelector('[data-fee-form]');
  if (form) {
    const preview = form.querySelector('[data-fee-preview]');
    const refresh = form.querySelector('[data-fee-refresh]');
    const stale = (event) => {
      if (!preview || event.target.name === 'reviewed' || event.target.type === 'hidden') return;
      preview.hidden = true;
      preview.querySelectorAll('button[name="action"][value="create"]').forEach(button => { button.disabled = true; });
      const checked = preview.querySelector('input[name="reviewed"]');
      if (checked) checked.checked = false;
      if (refresh) refresh.hidden = false;
    };
    form.addEventListener('input', stale);
    form.addEventListener('change', stale);
  }
  document.querySelectorAll('[data-fee-print]').forEach(button => button.addEventListener('click', () => window.print()));
})();
