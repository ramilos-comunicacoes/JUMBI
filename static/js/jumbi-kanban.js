/* Navie task interactions on JUMBI's tenant-scoped, audited endpoints. */
(() => {
  'use strict';
  const workspace = document.querySelector('[data-kanban-workspace]');
  if (!workspace) return;
  const moveDialog = workspace.querySelector('[data-move-dialog]');
  const moveForm = workspace.querySelector('[data-move-form]');
  const preview = workspace.querySelector('[data-task-dialog]');
  const editor = workspace.querySelector('[data-task-editor]');
  const toast = workspace.querySelector('[data-board-toast]');
  const terminal = status => ['done', 'cancelled'].includes(status);
  const motion = () => document.documentElement.dataset.motion !== 'paused' && document.documentElement.dataset.officeMotion !== 'paused' && !matchMedia('(prefers-reduced-motion:reduce)').matches;
  let busy = false, previewCard, returnFocus, returnTaskId, noticeTimer, editorRequest;
  let sortables = [], resizeObserver;

  function notify(message, error = false) {
    clearTimeout(noticeTimer); toast.textContent = message; toast.dataset.error = String(error); toast.hidden = false;
    noticeTimer = setTimeout(() => {toast.hidden = true;}, error ? 12000 : 4500);
  }
  function focusBack() {
    if (workspace.querySelector('dialog[open]')) return;
    const visibleOrigin = returnFocus?.isConnected && returnFocus.getClientRects().length && !returnFocus.closest('dialog:not([open])');
    const target = visibleOrigin ? returnFocus : workspace.querySelector(`[data-task-id="${returnTaskId}"] [data-task-preview]`) || workspace.querySelector('[data-board-filter-toggle]');
    target?.focus({preventScroll: true});
  }
  function showDialog(dialog, origin, card) {
    if (!dialog || busy) return;
    if (origin) returnFocus = origin;
    if (card) returnTaskId = card.dataset.taskId;
    workspace.querySelectorAll('dialog[open]').forEach(open => open.close());
    dialog.showModal();
  }
  workspace.querySelectorAll('dialog').forEach(dialog => {
    dialog.addEventListener('cancel', event => {if (busy) event.preventDefault();});
    dialog.addEventListener('close', () => {
      if (dialog === editor) editorRequest?.abort();
      queueMicrotask(focusBack);
    });
  });

  function updateMoveHelp() {
    if (!moveForm) return;
    const from = moveForm.elements.expected_status.value, to = moveForm.elements.destination.value;
    const required = from !== to && (terminal(from) || terminal(to));
    moveForm.elements.note.required = required;
    const label = moveForm.querySelector('[data-move-note-label]');
    label.firstChild.textContent = to === 'done' ? 'Evidência de conclusão' : to === 'cancelled' ? 'Motivo do cancelamento' : terminal(from) ? 'Motivo da reabertura' : 'Observação (opcional)';
    moveForm.querySelector('[data-move-help]').textContent = required ? 'Preenchimento obrigatório. A informação ficará registrada no histórico.' : 'A movimentação será registrada no histórico, sem alterar a data de entrega.';
    moveForm.querySelector('[data-overdue-warning]').hidden = moveForm.dataset.overdue !== 'true' || terminal(to);
  }
  function openMove(card, destination, origin) {
    if (!moveForm || busy || !card) return;
    moveForm.action = card.dataset.moveUrl;
    moveForm.elements.expected_status.value = card.dataset.taskStatus;
    moveForm.elements.destination.value = destination || card.dataset.taskStatus;
    moveForm.elements.note.value = '';
    moveForm.dataset.overdue = card.dataset.overdue;
    moveForm.querySelector('[data-task-title]').textContent = card.querySelector('h3').textContent;
    moveForm.querySelector('[data-move-error]').hidden = true;
    updateMoveHelp(); showDialog(moveDialog, origin || card.querySelector('[data-move-button]'), card);
    moveForm.elements.destination.focus();
  }
  moveForm?.elements.destination.addEventListener('change', updateMoveHelp);

  function updateScroll() {
    const board = workspace.querySelector('[data-kanban-board]');
    const controls = workspace.querySelector('[data-board-scroll-controls]');
    const overflow = board.scrollWidth - board.clientWidth;
    controls.hidden = overflow < 3;
    controls.querySelector('[data-board-scroll="-1"]').disabled = board.scrollLeft <= 1;
    controls.querySelector('[data-board-scroll="1"]').disabled = board.scrollLeft >= overflow - 1;
  }
  function initializeBoard() {
    sortables.forEach(instance => instance.destroy()); sortables = []; resizeObserver?.disconnect();
    const board = workspace.querySelector('[data-kanban-board]');
    board.addEventListener('scroll', updateScroll, {passive: true});
    resizeObserver = new ResizeObserver(updateScroll); resizeObserver.observe(board); updateScroll();
    if (board.dataset.editable !== 'true' || !window.Sortable) return;
    board.querySelectorAll('[data-column-cards]').forEach(list => {
      sortables.push(new Sortable(list, {
        group: {name: 'jumbi-tasks', pull: true, put: list.dataset.columnCards !== 'overdue'},
        draggable: '.kanban-card', filter: 'button,a,input,select,textarea', preventOnFilter: false,
        sort: false, animation: motion() ? 150 : 0, delay: 180, delayOnTouchOnly: true, touchStartThreshold: 5,
        ghostClass: 'kanban-ghost', chosenClass: 'kanban-chosen', dragClass: 'kanban-drag', fallbackOnBody: true,
        scroll: true, bubbleScroll: true, scrollSensitivity: 60, scrollSpeed: 12,
        onMove: event => !busy && event.to.dataset.columnCards !== 'overdue',
        onStart: () => {board.dataset.dragging = 'true';},
        onEnd: event => {
          delete board.dataset.dragging;
          if (event.from === event.to) return;
          const destination = event.to.dataset.columnCards;
          // A drop requests a transition. Keep server state until explicitly saved.
          const cards = [...event.from.children].filter(node => node.matches('.kanban-card') && node !== event.item);
          event.from.insertBefore(event.item, cards[event.oldDraggableIndex] || null);
          if (destination !== 'overdue') openMove(event.item, destination);
        }
      }));
    });
  }
  async function refreshBoard() {
    const board = workspace.querySelector('[data-kanban-board]');
    const scrollLeft = board.scrollLeft;
    const scrolls = new Map([...board.querySelectorAll('[data-column-cards]')].map(el => [el.dataset.columnCards, el.scrollTop]));
    const filtersOpen = !workspace.querySelector('[data-board-filters]').hidden;
    const response = await fetch(location.href, {credentials: 'same-origin', cache: 'no-store'});
    const doc = new DOMParser().parseFromString(await response.text(), 'text/html');
    const content = doc.querySelector('[data-kanban-content]');
    if (!response.ok || !content) throw new Error('A alteração foi salva, mas o quadro não foi atualizado. Recarregue a página para conferir.');
    workspace.querySelector('[data-kanban-content]').replaceWith(content);
    if (filtersOpen) {workspace.querySelector('[data-board-filters]').hidden = false; workspace.querySelector('[data-board-filter-toggle]').setAttribute('aria-expanded', 'true');}
    initializeBoard();
    workspace.querySelector('[data-kanban-board]').scrollLeft = scrollLeft;
    workspace.querySelectorAll('[data-column-cards]').forEach(el => {el.scrollTop = scrolls.get(el.dataset.columnCards) || 0;});
    focusBack();
  }
  function setBusy(value) {
    busy = value;
    workspace.setAttribute('aria-busy', String(value));
    sortables.forEach(instance => instance.option('disabled', value));
    workspace.querySelectorAll('dialog button').forEach(button => {button.disabled = value;});
  }
  moveForm?.addEventListener('submit', async event => {
    event.preventDefault(); if (busy || !moveForm.reportValidity()) return;
    const errorBox = moveForm.querySelector('[data-move-error]'); errorBox.hidden = true;
    const submit = moveForm.querySelector('[type=submit]'); const title = submit.textContent;
    const payload = new FormData(moveForm); setBusy(true); submit.textContent = 'Salvando…';
    let saved = false;
    try {
      const response = await fetch(moveForm.action, {method: 'POST', body: payload, headers: {Accept: 'application/json'}, credentials: 'same-origin'});
      if (!response.headers.get('Content-Type')?.includes('application/json')) throw new Error('Não foi possível confirmar o acesso. Atualize a página e entre novamente, se necessário.');
      const data = await response.json();
      if (!response.ok || !data.ok) throw new Error(Object.values(data.errors || {}).flat().map(error => error.message).join(' ') || 'Não foi possível mover esta tarefa.');
      saved = true; moveDialog.close(); await refreshBoard(); notify('Etapa atualizada. Histórico e contadores conferidos.');
    } catch (error) {
      if (saved) notify(error.message, true);
      else {errorBox.textContent = error.message || 'Falha de conexão. A tarefa não foi movimentada no quadro.'; errorBox.hidden = false;}
    } finally {setBusy(false); submit.textContent = title;}
  });

  function mountEditor(html, url) {
    const doc = new DOMParser().parseFromString(html, 'text/html');
    const form = doc.querySelector('[data-record-form]');
    if (!form?.elements.title || !form.elements.due_date || !form.elements.owner) throw new Error('O formulário não está disponível. Atualize a página para conferir seu acesso.');
    // The filters and editor share field names, but every label needs its own ID.
    const ids = new Map();
    form.querySelectorAll('[id]').forEach(node => {ids.set(node.id, 'task-editor-' + node.id); node.id = ids.get(node.id);});
    form.querySelectorAll('[for],[aria-describedby],[aria-labelledby],[list]').forEach(node => {
      for (const attr of ['for', 'aria-describedby', 'aria-labelledby', 'list']) {
        if (node.hasAttribute(attr)) node.setAttribute(attr, node.getAttribute(attr).split(/\s+/).map(id => ids.get(id) || id).join(' '));
      }
    });
    form.action = url; form.dataset.taskEditorForm = 'true';
    const cancel = form.querySelector('.form-actions a');
    if (cancel) {const button = document.createElement('button'); button.type = 'button'; button.className = cancel.className; button.textContent = 'Cancelar'; button.dataset.dialogClose = ''; cancel.replaceWith(button);}
    editor.querySelector('[data-task-editor-body]').replaceChildren(form);
    const first = form.querySelector('.has-error input,.has-error select,.has-error textarea') || form.elements.title;
    first?.focus();
  }
  async function openEditor(link) {
    if (!editor || busy) return;
    const url = new URL(link.href, location.origin); if (url.origin !== location.origin) return;
    const card = link.closest('[data-task-id]') || previewCard;
    editorRequest?.abort(); editorRequest = new AbortController();
    editor.querySelector('h2').textContent = link.dataset.editorTitle || 'Editar tarefa';
    editor.querySelector('[data-editor-error]').hidden = true;
    editor.querySelector('[data-task-editor-body]').textContent = 'Carregando formulário…';
    showDialog(editor, link, card);
    try {
      const response = await fetch(url, {credentials: 'same-origin', cache: 'no-store', signal: editorRequest.signal});
      if (!response.ok) throw new Error('Não foi possível abrir esta tarefa. Confira seu acesso ou tente novamente.');
      mountEditor(await response.text(), url.href);
    } catch (error) {if (error.name !== 'AbortError') {const box = editor.querySelector('[data-editor-error]'); box.textContent = error.message; box.hidden = false;}}
  }
  editor?.addEventListener('submit', async event => {
    const form = event.target.closest('[data-task-editor-form]'); if (!form) return;
    event.preventDefault(); if (busy || !form.reportValidity()) return;
    const payload = new FormData(form); const errorBox = editor.querySelector('[data-editor-error]'); errorBox.hidden = true;
    setBusy(true); let saved = false;
    try {
      const response = await fetch(form.action, {method: 'POST', body: payload, credentials: 'same-origin', headers: {Accept: 'application/json'}});
      if (response.headers.get('Content-Type')?.includes('application/json')) {
        const data = await response.json();
        if (!response.ok || !data.ok) throw new Error('Não foi possível salvar a tarefa.');
        saved = true; returnTaskId = String(data.id); editor.close(); await refreshBoard(); notify('Tarefa salva. O quadro foi atualizado.');
      } else {
        if (response.status >= 403) throw new Error('Não foi possível salvar. Confira seu acesso e atualize a página.');
        mountEditor(await response.text(), form.action);
      }
    } catch (error) {if (saved) notify(error.message, true); else {errorBox.textContent = error.message; errorBox.hidden = false;}}
    finally {setBusy(false);}
  });

  workspace.addEventListener('click', event => {
    const target = event.target;
    const close = target.closest('[data-dialog-close]');
    if (close) {if (!busy) close.closest('dialog').close(); return;}
    const edit = target.closest('[data-task-edit]');
    if (edit && !event.ctrlKey && !event.metaKey && !event.shiftKey) {event.preventDefault(); openEditor(edit); return;}
    const move = target.closest('[data-move-button]');
    if (move && !event.ctrlKey && !event.metaKey) {event.preventDefault(); openMove(move.closest('[data-task-id]'), null, move); return;}
    const details = target.closest('[data-task-preview]');
    if (details && !busy) {
      previewCard = details.closest('[data-task-id]');
      preview.querySelector('[data-task-preview-body]').replaceChildren(previewCard.querySelector('template').content.cloneNode(true));
      showDialog(preview, details, previewCard); return;
    }
    if (target.closest('[data-preview-move]')) {openMove(previewCard, null, returnFocus); return;}
    const toggle = target.closest('[data-board-filter-toggle]');
    if (toggle) {const panel = workspace.querySelector('[data-board-filters]'); panel.hidden = !panel.hidden; toggle.setAttribute('aria-expanded', String(!panel.hidden)); return;}
    const scroll = target.closest('[data-board-scroll]');
    if (scroll) {const board = workspace.querySelector('[data-kanban-board]'); board.scrollBy({left: Number(scroll.dataset.boardScroll) * board.clientWidth * .85, behavior: motion() ? 'smooth' : 'auto'}); return;}
    const jump = target.closest('[data-column-jump]');
    if (jump) {event.preventDefault(); const board = workspace.querySelector('[data-kanban-board]'); const column = document.getElementById('column-' + jump.dataset.columnJump); board.scrollBy({left: column.getBoundingClientRect().left - board.getBoundingClientRect().left, behavior: motion() ? 'smooth' : 'auto'});}
  });
  initializeBoard();
})();
