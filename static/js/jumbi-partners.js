(() => {
  const checkbox = document.querySelector('input[name=is_partner]');
  if (!checkbox) return;
  const form = checkbox.form;
  function update() {
    for (const name of ['plan','expires_at']) {
      const field = form.elements[name];
      if (field) field.closest('.form-field').hidden = checkbox.checked;
    }
    const status = form.elements.status || form.elements.subscription_status;
    if (status) {
      for (const option of status.options) if (['pending','demo'].includes(option.value)) option.disabled = checkbox.checked;
      if (checkbox.checked && ['pending','demo'].includes(status.value)) status.value = 'active';
    }
  }
  checkbox.addEventListener('change',update);update();
})();
