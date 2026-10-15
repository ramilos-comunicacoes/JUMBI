(() => {
  'use strict';
  const board = document.querySelector('[data-kanban-board]');
  const dialog = document.querySelector('[data-move-dialog]');
  const toast = document.getElementById('kanban-toast');
  const toastMsg = document.getElementById('toast-message');

  if (!board) return;

  const form = dialog ? dialog.querySelector('form') : null;
  const errorBox = dialog ? dialog.querySelector('[data-move-error]') : null;

  let dragged = null;
  let sourceColumn = null;
  let placeholder = document.createElement('div');
  placeholder.className = 'drop-placeholder';
  let busy = false;

  const showToast = (message, duration = 3000) => {
    if (!toast || !toastMsg) return;
    toastMsg.textContent = message;
    toast.classList.add('is-visible');
    setTimeout(() => {
      toast.classList.remove('is-visible');
    }, duration);
  };

  const updateColumnCount = (colCode, delta) => {
    const el = document.getElementById(`count-${colCode}`);
    if (el) {
      const current = parseInt(el.textContent.trim(), 10) || 0;
      el.textContent = Math.max(0, current + delta);
    }
  };

  const checkColumnEmptyState = (colCardsContainer, colCode) => {
    if (!colCardsContainer) return;
    const cards = colCardsContainer.querySelectorAll('.kanban-card:not(.is-dragging)');
    const emptyEl = colCardsContainer.querySelector('.kanban-empty');
    if (cards.length > 0) {
      if (emptyEl) emptyEl.remove();
    } else {
      if (!emptyEl) {
        const newEmpty = document.createElement('div');
        newEmpty.className = 'kanban-empty';
        newEmpty.innerHTML = `<svg class="icon"><use href="#i-check"/></svg><p>${colCode === 'overdue' ? 'Sem atrasos neste recorte' : 'Nenhuma tarefa nesta etapa'}</p>`;
        colCardsContainer.appendChild(newEmpty);
      } else {
        emptyEl.style.display = 'block';
      }
    }
  };

  // Initial check on load to prune any misplaced placeholders
  board.querySelectorAll('[data-column-cards]').forEach(container => {
    checkColumnEmptyState(container, container.dataset.columnCards);
  });

  const executeBackgroundMove = async (card, destStatus, originStatus, moveUrl) => {
    const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]')?.value || '';
    const body = new FormData();
    body.append('destination', destStatus);
    body.append('expected_status', originStatus);
    body.append('csrfmiddlewaretoken', csrfToken);

    try {
      const response = await fetch(moveUrl, {
        method: 'POST',
        body: body,
        headers: { 'Accept': 'application/json' },
        credentials: 'same-origin'
      });
      const data = await response.json();
      if (!response.ok || !data.ok) {
        throw new Error('Falha ao sincronizar movimentação com o servidor.');
      }
      card.dataset.taskStatus = destStatus;
      const statusLabels = { todo: 'A fazer', doing: 'Em execução', done: 'Concluída' };
      showToast(`Tarefa movida para ${statusLabels[destStatus] || destStatus}`);
    } catch (err) {
      // Revert card back to source
      showToast('Erro ao mover. Restaurando etapa anterior...', 4000);
      setTimeout(() => {
        window.location.reload();
      }, 1000);
    }
  };

  const openMoveDialog = (card, destination, origin) => {
    if (!dialog || !form) return;
    form.action = card.dataset.moveUrl;
    form.elements.expected_status.value = card.dataset.taskStatus;
    form.elements.destination.value = destination || card.dataset.taskStatus;
    form.elements.note.value = '';
    const titleEl = dialog.querySelector('[data-task-title]');
    if (titleEl) {
      titleEl.textContent = card.querySelector('h3')?.textContent || 'Tarefa';
    }
    if (errorBox) errorBox.hidden = true;
    dialog.showModal();
  };

  // Button Click manual move
  board.querySelectorAll('[data-move-button]').forEach(link => {
    link.addEventListener('click', event => {
      event.preventDefault();
      const card = link.closest('[data-task-id]');
      openMoveDialog(card, null, link);
    });
  });

  // Drag & Drop (Trello Logic)
  board.addEventListener('dragstart', event => {
    const card = event.target.closest('[data-task-id]');
    if (!card || busy) { event.preventDefault(); return; }
    dragged = card;
    sourceColumn = card.closest('[data-column-cards]');
    event.dataTransfer.setData('text/plain', card.dataset.taskId);
    event.dataTransfer.effectAllowed = 'move';
    card.classList.add('is-dragging');
  });

  board.addEventListener('dragend', () => {
    if (placeholder && placeholder.parentNode) {
      placeholder.parentNode.removeChild(placeholder);
    }
    board.querySelectorAll('.is-dragging,.is-drop-target').forEach(node => {
      node.classList.remove('is-dragging', 'is-drop-target');
    });
    dragged = null;
  });

  board.querySelectorAll('[data-drop-status]').forEach(column => {
    const cardsContainer = column.querySelector('[data-column-cards]');
    const targetStatus = column.dataset.dropStatus;

    column.addEventListener('dragover', event => {
      if (!dragged) return;
      event.preventDefault();
      event.dataTransfer.dropEffect = 'move';
      column.classList.add('is-drop-target');

      const emptyEl = cardsContainer.querySelector('.kanban-empty');
      if (emptyEl) emptyEl.style.display = 'none';

      const afterElement = getDragAfterElement(cardsContainer, event.clientY);
      if (afterElement == null) {
        cardsContainer.appendChild(placeholder);
      } else {
        cardsContainer.insertBefore(placeholder, afterElement);
      }
    });

    column.addEventListener('dragleave', event => {
      if (!column.contains(event.relatedTarget)) {
        column.classList.remove('is-drop-target');
        checkColumnEmptyState(cardsContainer, targetStatus);
      }
    });

    column.addEventListener('drop', event => {
      event.preventDefault();
      column.classList.remove('is-drop-target');
      if (!dragged) return;

      const originStatus = dragged.dataset.taskStatus;
      const originCode = sourceColumn?.dataset.columnCards || originStatus;

      // Rule: Moving to 'done' or moving out of 'done' requires note evidence
      if (targetStatus === 'done' || originStatus === 'done') {
        if (placeholder.parentNode) placeholder.parentNode.removeChild(placeholder);
        openMoveDialog(dragged, targetStatus, null);
        return;
      }

      if (targetStatus !== originStatus) {
        // Trello Optimistic Move
        if (placeholder.parentNode) {
          placeholder.parentNode.insertBefore(dragged, placeholder);
          placeholder.parentNode.removeChild(placeholder);
        } else {
          cardsContainer.appendChild(dragged);
        }

        // Update counts
        updateColumnCount(originCode, -1);
        updateColumnCount(targetStatus, +1);

        // Update empty placeholders
        if (sourceColumn) checkColumnEmptyState(sourceColumn, originCode);
        checkColumnEmptyState(cardsContainer, targetStatus);

        // Send background move
        executeBackgroundMove(dragged, targetStatus, originStatus, dragged.dataset.moveUrl);
      } else {
        // Reordering in same column
        if (placeholder.parentNode) {
          placeholder.parentNode.insertBefore(dragged, placeholder);
          placeholder.parentNode.removeChild(placeholder);
        }
      }
    });
  });

  function getDragAfterElement(container, y) {
    const draggableElements = [...container.querySelectorAll('.kanban-card:not(.is-dragging)')];
    return draggableElements.reduce((closest, child) => {
      const box = child.getBoundingClientRect();
      const offset = y - box.top - box.height / 2;
      if (offset < 0 && offset > closest.offset) {
        return { offset: offset, element: child };
      } else {
        return closest;
      }
    }, { offset: Number.NEGATIVE_INFINITY }).element;
  }

  // Dialog handling
  if (dialog && form) {
    dialog.querySelectorAll('[data-dialog-close]').forEach(button => {
      button.addEventListener('click', () => { if (!busy) dialog.close(); });
    });

    form.addEventListener('submit', async event => {
      event.preventDefault();
      if (busy || !form.reportValidity()) return;
      busy = true;
      const submit = form.querySelector('[type=submit]');
      submit.disabled = true;
      submit.textContent = 'Salvando…';
      if (errorBox) errorBox.hidden = true;

      try {
        const response = await fetch(form.action, {
          method: 'POST',
          body: new FormData(form),
          headers: { 'Accept': 'application/json' },
          credentials: 'same-origin'
        });
        const data = await response.json();
        if (!response.ok || !data.ok) {
          const errors = Object.values(data.errors || {}).flat().map(i => i.message);
          throw new Error(errors.join(' ') || 'Não foi possível salvar.');
        }
        window.location.reload();
      } catch (err) {
        if (errorBox) {
          errorBox.textContent = err.message || 'Falha de conexão.';
          errorBox.hidden = false;
        }
        busy = false;
        submit.disabled = false;
        submit.textContent = 'Salvar';
      }
    });
  }
})();
