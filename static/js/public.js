(() => {
  "use strict";

  const root = document.documentElement;
  const header = document.querySelector("[data-public-header]");
  const menuButton = document.querySelector("[data-public-menu-toggle]");
  const navigation = document.querySelector("[data-public-nav]");
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  const finePointer = window.matchMedia("(hover: hover) and (pointer: fine)");

  root.classList.add("js-enhanced");

  const assembleTitle = document.querySelector("[data-assemble-title]");
  if (assembleTitle) {
    const titleText = assembleTitle.textContent.trim();
    const directions = [
      [-118, -72, -16],
      [96, -84, 13],
      [-132, 38, -11],
      [122, 66, 15],
      [-44, -116, -8],
      [54, 118, 9],
      [-104, 92, -14],
      [116, -26, 12],
    ];
    let letterIndex = 0;

    assembleTitle.setAttribute("aria-label", titleText);
    assembleTitle.textContent = "";

    titleText.split(" ").forEach((word, wordIndex, words) => {
      const wordElement = document.createElement("span");
      wordElement.className = "assemble-word";
      wordElement.setAttribute("aria-hidden", "true");

      Array.from(word).forEach((character) => {
        const letterElement = document.createElement("span");
        const [x, y, rotation] = directions[letterIndex % directions.length];
        letterElement.className = "assemble-letter";
        letterElement.textContent = character;
        letterElement.style.setProperty("--assemble-index", letterIndex);
        letterElement.style.setProperty("--assemble-x", `${x}px`);
        letterElement.style.setProperty("--assemble-y", `${y}px`);
        letterElement.style.setProperty("--assemble-rotation", `${rotation}deg`);
        wordElement.appendChild(letterElement);
        letterIndex += 1;
      });

      assembleTitle.appendChild(wordElement);
      if (wordIndex < words.length - 1) {
        assembleTitle.appendChild(document.createTextNode(" "));
      }
    });

    const finishAssembly = () => assembleTitle.classList.add("is-assembled");
    if (reducedMotion.matches) {
      finishAssembly();
    } else {
      requestAnimationFrame(() => requestAnimationFrame(finishAssembly));
    }
  }

  const closeMenu = () => {
    if (!header || !menuButton) return;
    header.classList.remove("menu-open");
    menuButton.setAttribute("aria-expanded", "false");
    menuButton.setAttribute("aria-label", "Abrir menu");
  };

  if (header && menuButton && navigation) {
    menuButton.addEventListener("click", () => {
      const willOpen = !header.classList.contains("menu-open");
      header.classList.toggle("menu-open", willOpen);
      menuButton.setAttribute("aria-expanded", String(willOpen));
      menuButton.setAttribute("aria-label", willOpen ? "Fechar menu" : "Abrir menu");
    });

    navigation.addEventListener("click", (event) => {
      if (event.target.closest("a")) closeMenu();
    });

    document.addEventListener("click", (event) => {
      if (!header.contains(event.target)) closeMenu();
    });

    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") closeMenu();
    });
  }

  const updateHeader = () => {
    if (header) header.classList.toggle("is-scrolled", window.scrollY > 24);
  };
  updateHeader();
  window.addEventListener("scroll", updateHeader, { passive: true });

  const revealItems = [...document.querySelectorAll("[data-reveal]")];
  if (reducedMotion.matches || !("IntersectionObserver" in window)) {
    revealItems.forEach((item) => item.classList.add("is-visible"));
  } else {
    const revealObserver = new IntersectionObserver((entries, observer) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        entry.target.classList.add("is-visible");
        observer.unobserve(entry.target);
      });
    }, { rootMargin: "0px 0px -10% 0px", threshold: 0.08 });
    revealItems.forEach((item) => revealObserver.observe(item));
  }

  const navLinks = navigation ? [...navigation.querySelectorAll("a[href*='#']")] : [];
  const observedSections = navLinks
    .map((link) => {
      const id = new URL(link.href, window.location.href).hash.slice(1);
      const section = id ? document.getElementById(id) : null;
      return section ? { link, section } : null;
    })
    .filter(Boolean);

  if ("IntersectionObserver" in window && observedSections.length) {
    const sectionObserver = new IntersectionObserver((entries) => {
      const visible = entries
        .filter((entry) => entry.isIntersecting)
        .sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
      if (!visible) return;
      navLinks.forEach((link) => link.classList.remove("is-current"));
      const match = observedSections.find(({ section }) => section === visible.target);
      if (match) match.link.classList.add("is-current");
    }, { rootMargin: "-28% 0px -58% 0px", threshold: [0.01, 0.25, 0.5] });
    observedSections.forEach(({ section }) => sectionObserver.observe(section));
  }

  if (finePointer.matches && !reducedMotion.matches) {
    document.querySelectorAll("[data-spotlight]").forEach((card) => {
      card.addEventListener("pointermove", (event) => {
        const rect = card.getBoundingClientRect();
        card.style.setProperty("--spot-x", `${event.clientX - rect.left}px`);
        card.style.setProperty("--spot-y", `${event.clientY - rect.top}px`);
      }, { passive: true });
    });

    document.querySelectorAll("[data-parallax-card]").forEach((card) => {
      let frame = 0;
      const reset = () => {
        card.style.setProperty("--tilt-x", "2deg");
        card.style.setProperty("--tilt-y", "-4deg");
      };
      card.addEventListener("pointermove", (event) => {
        if (frame) cancelAnimationFrame(frame);
        frame = requestAnimationFrame(() => {
          const rect = card.getBoundingClientRect();
          const x = (event.clientX - rect.left) / rect.width - 0.5;
          const y = (event.clientY - rect.top) / rect.height - 0.5;
          card.style.setProperty("--tilt-x", `${(-y * 5).toFixed(2)}deg`);
          card.style.setProperty("--tilt-y", `${(x * 7).toFixed(2)}deg`);
        });
      }, { passive: true });
      card.addEventListener("pointerleave", reset, { passive: true });
    });
  }
})();
