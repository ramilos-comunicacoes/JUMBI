(() => {
  "use strict";
  const form = document.querySelector("[data-purchase-form]");
  if (!form) return;
  const add = form.querySelector("[data-add-purchase-item]");
  const container = form.querySelector("[data-purchase-items]");
  const template = document.getElementById("purchase-item-template");
  const total = form.querySelector('[name="items-TOTAL_FORMS"]');
  const limit = form.querySelector("[data-purchase-limit]");
  if (!add || !container || !template || !total) return;
  add.hidden = false;
  const update = () => {
    const count = Number(total.value);
    add.disabled = count >= 30;
    limit.textContent = count >= 30 ? "Limite de 30 linhas atingido. Desmarque a exclusão de uma linha para reutilizá-la." : "";
  };
  add.addEventListener("click", () => {
    const index = Number(total.value);
    if (!Number.isInteger(index) || index < 0 || index >= 30) return;
    const fragment = template.content.cloneNode(true);
    for (const element of fragment.querySelectorAll("[name], [id], [for]")) {
      for (const attribute of ["name", "id", "for"]) {
        const value = element.getAttribute(attribute);
        if (value) element.setAttribute(attribute, value.replaceAll("__prefix__", String(index)));
      }
    }
    const number = fragment.querySelector("[data-item-number]");
    if (number) number.textContent = String(index + 1);
    const focus = fragment.querySelector("select, input");
    container.appendChild(fragment);
    total.value = String(index + 1);
    update();
    focus?.focus();
  });
  update();
})();
