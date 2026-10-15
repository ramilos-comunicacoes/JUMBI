/* Keep overflow inside the relevant table/board; support touch and keyboard. */
(() => {
  let sequence = 0;
  document.querySelectorAll('.table-scroll,.kanban-board,.calendar-week-scroll').forEach(scroller => {
    const tools = document.createElement('div'); tools.className = 'scroll-assist'; tools.hidden = true;
    const help = document.createElement('span');
    help.textContent = scroller.classList.contains('kanban-board') ? 'Deslize para ver as outras colunas.' : 'Deslize para ver todas as informações.';
    const previous = document.createElement('button'), next = document.createElement('button');
    previous.type = next.type = 'button'; previous.textContent = '←'; next.textContent = '→';
    previous.setAttribute('aria-label','Rolar conteúdo para a esquerda'); next.setAttribute('aria-label','Rolar conteúdo para a direita');
    if (!scroller.id) scroller.id = 'scroll-region-' + (++sequence);
    previous.setAttribute('aria-controls',scroller.id); next.setAttribute('aria-controls',scroller.id);
    tools.append(help,previous,next); scroller.before(tools);
    function update() {
      const overflow = scroller.scrollWidth - scroller.clientWidth;
      tools.hidden = overflow <= 2;
      previous.disabled = scroller.scrollLeft <= 1;
      next.disabled = scroller.scrollLeft >= overflow - 1;
      if (overflow > 2 && !scroller.hasAttribute('tabindex')) scroller.tabIndex = 0;
    }
    function move(direction) {
      const reduced = document.documentElement.dataset.motion === 'paused' || matchMedia('(prefers-reduced-motion:reduce)').matches;
      scroller.scrollBy({left: direction * Math.max(180,scroller.clientWidth * .75),behavior:reduced?'auto':'smooth'});
    }
    previous.addEventListener('click',()=>move(-1)); next.addEventListener('click',()=>move(1));
    scroller.addEventListener('scroll',update,{passive:true});
    if ('ResizeObserver' in window) {const observer = new ResizeObserver(update); observer.observe(scroller); if (scroller.firstElementChild) observer.observe(scroller.firstElementChild);}
    update();
  });
})();
