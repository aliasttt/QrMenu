/**
 * Lightweight scroll-triggered animations using IntersectionObserver.
 * Use data-animate="fade-up" | "fade-in" and optional data-delay="100" (ms).
 */
(function () {
  "use strict";

  var ANIMATE_ATTR = "data-animate";
  var DELAY_ATTR = "data-delay";
  var VISIBLE_CLASS = "animate-visible";

  var defaultOptions = {
    root: null,
    rootMargin: "0px 0px -8% 0px",
    threshold: 0.05,
  };

  function applyAnimation(el) {
    var delay = parseInt(el.getAttribute(DELAY_ATTR) || "0", 10);

    var run = function () {
      el.classList.add(VISIBLE_CLASS);
      el.style.transition = "opacity 0.7s ease-out, transform 0.7s ease-out";
    };

    if (delay > 0) {
      setTimeout(run, delay);
    } else {
      run();
    }
  }

  function init() {
    var elements = document.querySelectorAll("[" + ANIMATE_ATTR + "]");
    if (!elements.length) return;

    var observer = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (entry) {
          if (!entry.isIntersecting) return;
          applyAnimation(entry.target);
          observer.unobserve(entry.target);
        });
      },
      defaultOptions
    );

    elements.forEach(function (el) {
      observer.observe(el);
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
