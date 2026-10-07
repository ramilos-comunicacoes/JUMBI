(() => {
  const shell = () => document.querySelector("[data-app-shell]");
  const menuToggle = () => document.querySelector("[data-app-menu]");

  const refreshIcons = () => {
    if (window.lucide) window.lucide.createIcons();
  };

  const syncNavigationState = () => {
    const main = document.querySelector("[data-app-main]");
    const module = main?.dataset.module;
    if (!module) return;
    shell()?.setAttribute("data-current-module", module);
    document.querySelectorAll("[data-app-module]").forEach((link) => {
      const active = link.dataset.appModule === module;
      link.classList.toggle("is-active", active);
      if (active) link.setAttribute("aria-current", "page");
      else link.removeAttribute("aria-current");
    });
  };

  const resetMainViewport = () => {
    const main = document.querySelector("[data-app-main]");
    window.scrollTo({ top: 0, left: 0, behavior: "auto" });
    main?.focus({ preventScroll: true });
  };

  const closeMenu = () => {
    shell()?.classList.remove("sidebar-open");
    menuToggle()?.setAttribute("aria-expanded", "false");
  };

  const openMenu = () => {
    shell()?.classList.add("sidebar-open");
    menuToggle()?.setAttribute("aria-expanded", "true");
  };

  const openDialog = (id) => {
    const dialog = document.getElementById(id);
    if (!dialog) return;
    if (typeof dialog.showModal === "function") {
      if (!dialog.open) dialog.showModal();
    } else {
      dialog.setAttribute("open", "");
    }
    window.lucide?.createIcons();
  };

  const closeDialog = (dialog) => {
    if (!dialog) return;
    if (typeof dialog.close === "function") dialog.close();
    else dialog.removeAttribute("open");
  };

  const normalizeSearch = (value) =>
    value
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .toLowerCase()
      .trim();

  const filterList = (input) => {
    const target = document.getElementById(input.dataset.listFilter);
    if (!target) return;
    const query = normalizeSearch(input.value);
    target.querySelectorAll("[data-search-item]").forEach((item) => {
      item.hidden = query !== "" && !normalizeSearch(item.dataset.searchItem || "").includes(query);
    });
  };

  const filterMatterTypes = (areaSelect) => {
    const form = areaSelect.closest("form");
    const matterSelect = form?.querySelector('[name$="-matter_type"]');
    if (!matterSelect) return;
    const areaName = areaSelect.selectedOptions[0]?.textContent?.trim() || "";
    [...matterSelect.options].forEach((option) => {
      if (!option.value) return;
      const belongsToArea = !areaSelect.value || option.textContent.trim().startsWith(`${areaName} ·`);
      option.hidden = !belongsToArea;
      option.disabled = !belongsToArea;
      if (!belongsToArea && option.selected) matterSelect.value = "";
    });
  };

  const initializeCaseFields = (root = document) => {
    root.querySelectorAll?.('[name$="-practice_area"]').forEach(filterMatterTypes);
  };

  const toggleFullscreen = async () => {
    try {
      if (document.fullscreenElement) await document.exitFullscreen?.();
      else await document.documentElement.requestFullscreen?.();
    } catch (_) {
      // Fullscreen can be blocked by the browser; the interface remains usable.
    }
  };

  const updateBrandPreview = (input) => {
    const preview = document.querySelector(".branding-preview");
    if (!preview || input.type !== "color") return;
    const variables = {
      "branding-brand_primary_color": "--preview-primary",
      "branding-brand_accent_color": "--preview-accent",
      "branding-brand_sidebar_color": "--preview-sidebar",
    };
    const variable = variables[input.id];
    if (variable) preview.style.setProperty(variable, input.value);
  };

  document.addEventListener("click", (event) => {
    const dialogOpener = event.target.closest("[data-dialog-open]");
    if (dialogOpener) {
      openDialog(dialogOpener.dataset.dialogOpen);
      return;
    }
    const dialogCloser = event.target.closest("[data-dialog-close]");
    if (dialogCloser) {
      closeDialog(dialogCloser.closest("dialog"));
      return;
    }
    if (event.target.matches("dialog.legal-dialog")) {
      closeDialog(event.target);
      return;
    }
    if (event.target.closest("[data-app-fullscreen]")) {
      toggleFullscreen();
      return;
    }
    const toggle = event.target.closest("[data-app-menu]");
    if (toggle) {
      shell()?.classList.contains("sidebar-open") ? closeMenu() : openMenu();
      return;
    }
    if (event.target.closest("[data-app-menu-close]")) {
      closeMenu();
      return;
    }
    if (event.target.closest(".sidebar-nav a") && window.matchMedia("(max-width: 720px)").matches) {
      closeMenu();
    }
  });

  document.addEventListener("input", (event) => {
    updateBrandPreview(event.target);
    if (event.target.matches("[data-list-filter]")) filterList(event.target);
  });

  document.addEventListener("change", (event) => {
    if (event.target.matches('[name$="-practice_area"]')) filterMatterTypes(event.target);
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeMenu();
  });

  document.addEventListener("htmx:beforeRequest", (event) => {
    if (event.detail.elt.closest(".sidebar-nav") && window.matchMedia("(max-width: 720px)").matches) {
      closeMenu();
    }
  });

  document.addEventListener("htmx:afterSwap", (event) => {
    refreshIcons();
    initializeCaseFields(event.detail.target);
    if (event.detail.target?.matches?.("[data-app-main]")) {
      syncNavigationState();
      requestAnimationFrame(resetMainViewport);
    }
    document.querySelectorAll(".topbar-notifications[open]").forEach((details) => details.removeAttribute("open"));
  });
  document.addEventListener("htmx:historyRestore", () => {
    refreshIcons();
    syncNavigationState();
  });
  window.addEventListener("load", () => {
    refreshIcons();
    syncNavigationState();
    initializeCaseFields();
  });
})();
