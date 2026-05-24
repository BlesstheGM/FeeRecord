// ── File upload drop zone ──
(function () {
  const zone = document.getElementById('drop-zone');
  const input = document.getElementById('file-input');
  const label = document.getElementById('file-label');

  if (!zone || !input) return;

  zone.addEventListener('click', () => input.click());

  zone.addEventListener('dragover', e => {
    e.preventDefault();
    zone.classList.add('drag-over');
  });

  zone.addEventListener('dragleave', () => zone.classList.remove('drag-over'));

  zone.addEventListener('drop', e => {
    e.preventDefault();
    zone.classList.remove('drag-over');
    const file = e.dataTransfer.files[0];
    if (file) {
      input.files = e.dataTransfer.files;
      updateLabel(file.name);
    }
  });

  input.addEventListener('change', () => {
    if (input.files[0]) updateLabel(input.files[0].name);
  });

  function updateLabel(name) {
    if (label) label.textContent = name;
    const sub = zone.querySelector('.drop-sub');
    if (sub) sub.textContent = 'Ready to upload';
    zone.style.borderColor = '#2c7a4b';
  }
})();

// ── Select-all checkbox on upload review ──
(function () {
  const master = document.getElementById('select-all');
  if (!master) return;
  master.addEventListener('change', function () {
    document.querySelectorAll('input[name="accept"]').forEach(cb => {
      cb.checked = master.checked;
    });
  });
})();
