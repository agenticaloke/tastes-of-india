// Debounced nav search — redirects after 400ms of inactivity
(function () {
  const input = document.getElementById('nav-search-input');
  const form = document.getElementById('nav-search-form');
  if (!input || !form) return;
  let timer;
  input.addEventListener('input', function () {
    clearTimeout(timer);
    if (this.value.trim().length < 2) return;
    timer = setTimeout(function () {
      form.submit();
    }, 400);
  });
})();
