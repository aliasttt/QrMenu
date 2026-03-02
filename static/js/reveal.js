/**
 * Scroll reveal using IntersectionObserver.
 * Usage: add data-reveal and optional data-delay="150" (ms).
 */
(function () {
  "use strict";

  var ATTR_REVEAL = "data-reveal";
  var ATTR_DELAY = "data-delay";

  function revealElement(el) {
    var delay = parseInt(el.getAttribute(ATTR_DELAY) || "0", 10);

    var run = function () {
      el.classList.add("is-visible");
    };

    if (delay > 0) {
      setTimeout(run, delay);
    } else {
      run();
    }
  }

  function initReveal() {
    var elements = document.querySelectorAll("[" + ATTR_REVEAL + "]");
    if (!elements.length) return;

    var observer = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (entry) {
          if (!entry.isIntersecting) return;
          revealElement(entry.target);
          observer.unobserve(entry.target);
        });
      },
      {
        root: null,
        rootMargin: "0px 0px -12% 0px",
        threshold: 0.15,
      }
    );

    elements.forEach(function (el) {
      observer.observe(el);
    });
  }

  function initNavbarShadow() {
    var nav = document.querySelector("[data-nav-sticky]");
    if (!nav) return;
    function onScroll() {
      if (window.scrollY > 8) {
        nav.classList.add("shadow-md", "border-slate-200");
      } else {
        nav.classList.remove("shadow-md", "border-slate-200");
      }
    }
    window.addEventListener("scroll", onScroll, { passive: true });
    onScroll();
  }

  function boot() {
    initReveal();
    initNavbarShadow();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();


