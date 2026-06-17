/* ── Reading progress bar ───────────────────────────────────────────────── */
(function () {
  const bar = document.createElement('div');
  bar.id = 'reading-progress';
  document.body.prepend(bar);

  function updateProgress() {
    const scrollTop = window.scrollY || document.documentElement.scrollTop;
    const docHeight = document.documentElement.scrollHeight - window.innerHeight;
    bar.style.width = (docHeight > 0 ? (scrollTop / docHeight) * 100 : 0) + '%';
  }
  window.addEventListener('scroll', updateProgress, { passive: true });
  updateProgress();
})();

/* ── "Was this page helpful?" widget ────────────────────────────────────── */
function aegisAddFeedback() {
  const inner = document.querySelector('.md-content__inner');
  if (!inner || !inner.querySelector('h1') || inner.querySelector('.feedback-widget')) return;

  const widget = document.createElement('div');
  widget.className = 'feedback-widget';
  widget.innerHTML = [
    '<div class="feedback-widget__inner">',
    '  <span class="feedback-widget__prompt">Was this page helpful?</span>',
    '  <div class="feedback-widget__buttons">',
    '    <button class="feedback-widget__btn feedback-widget__btn--yes">👍 Yes</button>',
    '    <button class="feedback-widget__btn feedback-widget__btn--no">Could be better</button>',
    '  </div>',
    '</div>',
  ].join('');
  inner.appendChild(widget);

  widget.querySelectorAll('.feedback-widget__btn').forEach(function (btn) {
    btn.addEventListener('click', function () {
      widget.innerHTML = '<div class="feedback-widget__thanks">Thanks for the feedback ✓</div>';
    });
  });
}

// Run after full page load so Material's document$ observable is ready
window.addEventListener('load', function () {
  aegisAddFeedback();
  // Hook into Material's instant navigation for subsequent page changes
  if (typeof document$ !== 'undefined') {
    document$.subscribe(function () {
      // Small delay lets Material swap the content into the DOM first
      setTimeout(aegisAddFeedback, 50);
    });
  }
});
