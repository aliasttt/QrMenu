(function () {
  const root = document.querySelector('.menu-v2');
  if (!root) return;

  // Category filtering
  const sections = Array.from(document.querySelectorAll('[data-category-section]'));
  const buttons = Array.from(document.querySelectorAll('[data-category-btn]'));
  function setCategory(categoryId) {
    buttons.forEach((b) => b.classList.toggle('is-active', b.dataset.categoryBtn === categoryId));
    sections.forEach((s) => {
      const id = s.dataset.categorySection;
      s.style.display = categoryId === 'all' || id === categoryId ? '' : 'none';
    });
    const allOnly = document.querySelectorAll('[data-only-all]');
    allOnly.forEach((el) => {
      el.style.display = categoryId === 'all' ? '' : 'none';
    });
  }
  buttons.forEach((btn) => btn.addEventListener('click', () => setCategory(btn.dataset.categoryBtn || 'all')));
  setCategory('all');

  // Horizontal category scroll arrows
  const scrollEl = document.querySelector('[data-cat-scroll]');
  const prevBtn = document.querySelector('[data-cat-prev]');
  const nextBtn = document.querySelector('[data-cat-next]');
  if (scrollEl && prevBtn && nextBtn) {
    prevBtn.addEventListener('click', () => scrollEl.scrollBy({ left: -220, behavior: 'smooth' }));
    nextBtn.addEventListener('click', () => scrollEl.scrollBy({ left: 220, behavior: 'smooth' }));
  }

  // Image carousel per card (reads image list from json_script)
  const cards = Array.from(document.querySelectorAll('[data-carousel-card]'));
  cards.forEach((card) => {
    const img = card.querySelector('[data-carousel-img]');
    const prev = card.querySelector('[data-carousel-prev]');
    const next = card.querySelector('[data-carousel-next]');
    const scriptId = card.getAttribute('data-images-script');
    if (!img || !scriptId) return;

    let images = [];
    try {
      const script = document.getElementById(scriptId);
      if (script) images = JSON.parse(script.textContent || '[]') || [];
    } catch (_) {
      images = [];
    }
    if (!images.length) {
      if (prev) prev.style.display = 'none';
      if (next) next.style.display = 'none';
      return;
    }

    let idx = 0;
    function render() {
      img.src = images[idx];
    }
    render();

    if (prev) {
      prev.addEventListener('click', () => {
        idx = (idx - 1 + images.length) % images.length;
        render();
      });
    }
    if (next) {
      next.addEventListener('click', () => {
        idx = (idx + 1) % images.length;
        render();
      });
    }
  });
})();
