(() => {
  "use strict";
  const root = document.querySelector(".client-map-workspace");
  if (!root) return;
  const name = root.querySelector("[data-map-live-name]");
  const count = root.querySelector("[data-map-live-count]");
  const states = [...root.querySelectorAll("[data-map-state]")];
  if (!name || !count || !states.length) return;
  const defaultName = name.textContent;
  const defaultCount = count.textContent;
  const show = state => {
    const quantity = Number(state.dataset.stateCount);
    name.textContent = `${state.dataset.stateName} · ${state.dataset.mapState}`;
    count.textContent = quantity ? `${quantity} cadastro${quantity === 1 ? "" : "s"}` : "Nenhum cadastro";
  };
  const reset = () => {
    const focused = states.find(state => state === document.activeElement);
    const selected = states.find(state => state.classList.contains("is-selected"));
    if (focused || selected) show(focused || selected);
    else { name.textContent = defaultName; count.textContent = defaultCount; }
  };
  for (const state of states) {
    state.addEventListener("pointerenter", () => show(state));
    state.addEventListener("pointerleave", reset);
    state.addEventListener("focus", () => show(state));
    state.addEventListener("blur", () => requestAnimationFrame(reset));
  }
  // Links remain native links: filters, keyboard activation and the complete
  // state directory continue to work when scripts are unavailable.
  reset();
})();
