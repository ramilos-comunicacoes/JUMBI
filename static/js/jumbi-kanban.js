(() => {
  'use strict';
  const board = document.querySelector('[data-kanban-board]');
  const dialog = document.querySelector('[data-move-dialog]');
  if (!board || !dialog || !dialog.showModal) return;
  const form = dialog.querySelector('form');
  const errorBox = dialog.querySelector('[data-move-error]');
  let dragged = null;
  let trigger = null;
  let busy = false;
  const setRequirements = () => {
    form.elements.note.required = form.elements.destination.value === 'done' ||
      (form.elements.expected_status.value === 'done' && form.elements.destination.value !== 'done');
  };
  const open = (card, destination, origin) => {
    if (busy) return;
    trigger = origin;
    form.action = card.dataset.moveUrl;
    form.elements.expected_status.value = card.dataset.taskStatus;
    form.elements.destination.value = destination || card.dataset.taskStatus;
    form.elements.note.value = '';
    dialog.querySelector('[data-task-title]').textContent = card.querySelector('h3').textContent;
    errorBox.hidden = true;
    setRequirements();
    dialog.showModal();
  };
  board.querySelectorAll('[data-move-button]').forEach(link => link.addEventListener('click', event => {
    event.preventDefault(); open(link.closest('[data-task-id]'), null, link);
  }));
  board.addEventListener('dragstart', event => {
    const card = event.target.closest('[data-task-id]');
    if (!card || busy) { event.preventDefault(); return; }
    dragged = card;
    event.dataTransfer.setData('text/plain', card.dataset.taskId);
    event.dataTransfer.effectAllowed = 'move';
    card.classList.add('is-dragging');
  });
  board.addEventListener('dragend', () => {
    board.querySelectorAll('.is-dragging,.is-drop-target').forEach(node => node.classList.remove('is-dragging', 'is-drop-target'));
    dragged = null;
  });
  board.querySelectorAll('[data-drop-status]').forEach(column => {
    column.addEventListener('dragover', event => {
      if (!dragged || busy) return;
      event.preventDefault(); event.dataTransfer.dropEffect = 'move'; column.classList.add('is-drop-target');
    });
    column.addEventListener('dragleave', event => { if (!column.contains(event.relatedTarget)) column.classList.remove('is-drop-target'); });
    column.addEventListener('drop', event => {
      event.preventDefault(); column.classList.remove('is-drop-target');
      if (dragged && dragged.dataset.taskStatus !== column.dataset.dropStatus) {
        open(dragged, column.dataset.dropStatus, dragged.querySelector('[data-move-button]'));
      }
    });
  });
  form.elements.destination.addEventListener('change', setRequirements);
  dialog.querySelectorAll('[data-dialog-close]').forEach(button => button.addEventListener('click', () => { if (!busy) dialog.close(); }));
  dialog.addEventListener('cancel', event => { if (busy) event.preventDefault(); });
  dialog.addEventListener('close', () => trigger?.focus());
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (busy || !form.reportValidity()) return;
    busy = true;
    const submit = form.querySelector('[type=submit]');
    submit.disabled = true; submit.textContent = 'Salvando…'; errorBox.hidden = true;
    try {
      const response = await fetch(form.action, {method: 'POST', body: new FormData(form), headers: {'Accept': 'application/json'}, credentials: 'same-origin'});
      const data = await response.json();
      if (!response.ok || !data.ok) {
        const errors = Object.values(data.errors || {}).flat().map(item => item.message);
        throw new Error(errors.join(' ') || 'Não foi possível salvar. Atualize o quadro e tente novamente.');
      }
      window.location.reload();
    } catch (error) {
      errorBox.textContent = error.message || 'Falha de conexão. Sua tarefa permaneceu na etapa anterior.';
      errorBox.hidden = false; errorBox.focus();
      busy = false; submit.disabled = false; submit.textContent = 'Salvar movimentação';
    }
  });
})();
