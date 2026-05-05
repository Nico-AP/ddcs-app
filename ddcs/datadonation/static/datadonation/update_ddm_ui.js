function applyDOMChanges() {

  /* Hide file select section heading */
  document.querySelectorAll('.section-heading').forEach(el => {
    const targets = [
      'Datei auswählen',
      'Select file',
      'Sélectionner un fichier',
      'Seleziona file',
    ]
    if (targets.includes(el.textContent.trim())) {
      const parent = el.closest('div.d-flex')
      if (parent) {
        parent.classList.add('d-none')
      }
    }
  });

  /* Hide file selection hint */
  document.querySelectorAll('.fw-bold').forEach(el => {
    if (el.textContent.trim() === 'Hier klicken um eine Datei auszuwählen') {
      el.textContent = 'Warte auf Datei';
    } else if (el.textContent.trim() === 'Click to select a file from your device') {
      el.textContent = 'Waiting for file';
    }
  });

  /* Hide all buttons except for the buttons to expand/collapse the data review tables */
  document.querySelectorAll('.uploader-section button').forEach(btn => {
    const targets = [
      'Show all data',
      'alle Daten anzeigen',
      'Show less',
      'weniger anzeigen',
      'afficher toutes les données',
      'afficher moins',
      'mostra tutti i dati',
      'mostra meno',
    ]
    if (!targets.includes(btn.textContent.trim())) {
      btn.style.display = 'none';
    }
  });

  /* Hide instruction section */
  const container = document.querySelector('div.uploader-container');
  if (container) {
    const sections = container.querySelectorAll(':scope > div.uploader-section');
    if (sections.length === 3) {
      sections[0].style.display = 'none';
    }
  }

  /* Uploader is hidden first, until all customization steps above are applied */
  const uapp = document.getElementById('uapp');
  if (uapp) {
    uapp.style.visibility = 'visible';
  }

}

document.addEventListener('DOMContentLoaded', () => {
  setTimeout(applyDOMChanges, 0);

  new MutationObserver(applyDOMChanges).observe(document.body, {
    childList: true,
    subtree: true,
  });
});
