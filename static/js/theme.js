(() => {
  const key = "djumbi-theme";
  const root = document.documentElement;
  const preferred = "dark";
  const applyTheme = (theme) => {
    root.dataset.theme = theme;
    document.querySelectorAll("[data-theme-toggle]").forEach((button) => {
      button.setAttribute("aria-label", theme === "dark" ? "Ativar tema claro" : "Ativar tema escuro");
      const label = button.querySelector("span");
      if (label) label.textContent = theme === "dark" ? "Claro" : "Escuro";
    });
  };
  applyTheme(localStorage.getItem(key) || preferred);
  document.querySelectorAll("[data-theme-toggle]").forEach((button) => button.addEventListener("click", () => {
    const next = root.dataset.theme === "dark" ? "light" : "dark";
    localStorage.setItem(key, next);
    applyTheme(next);
  }));
})();
