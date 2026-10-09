(() => {
  const source = document.querySelector('[data-contract-source]');
  const preview = document.querySelector('[data-contract-preview]');
  if (!source) return;
  const valueFields = [...document.querySelectorAll('[data-contract-value]')];
  const update = () => {
    if (!preview) return;
    const values = Object.fromEntries(valueFields.map(field => [field.dataset.contractValue, field.value.trim()]));
    preview.textContent = source.value.replace(/\[\[([a-z_]+)\]\]/g, (token, key) => values[key] || token);
  };
  document.querySelectorAll('[data-insert-token]').forEach(button => {
    button.addEventListener('click', () => {
      source.setRangeText(button.dataset.insertToken, source.selectionStart, source.selectionEnd, 'end');
      source.focus();
      update();
    });
  });
  source.addEventListener('input', update);
  valueFields.forEach(field => field.addEventListener('input', update));
  const dataElement = document.getElementById('contract-fill-data');
  const fill = document.querySelector('[data-contract-fill]');
  if (dataElement && fill) {
    const data = JSON.parse(dataElement.textContent);
    const matterField = document.getElementById('id_matter');
    const clientField = document.getElementById('id_client');
    matterField?.addEventListener('change', () => {
      const matter = data.matters.find(item => String(item.id) === matterField.value);
      if (matter?.client_id) clientField.value = String(matter.client_id);
    });
    fill.addEventListener('click', () => {
      const matter = data.matters.find(item => String(item.id) === matterField.value);
      const client = data.contacts.find(item => String(item.id) === clientField.value);
      const values = {};
      if (matter) values.pasta_titulo = matter.title;
      if (client) Object.assign(values, {cliente_nome: client.name, cliente_documento: client.document, cliente_email: client.email, cliente_telefone: client.phone});
      valueFields.forEach(field => {
        if (Object.hasOwn(values, field.dataset.contractValue)) field.value = values[field.dataset.contractValue];
      });
      const status = document.querySelector('[data-fill-status]');
      if (status) status.textContent = client ? 'Dados cadastrais preenchidos. Revise os campos e complete as condições.' : 'Selecione um contratante para preencher seus dados.';
      update();
    });
  }
  update();
})();
