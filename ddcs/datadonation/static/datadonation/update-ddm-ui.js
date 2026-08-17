function applyDOMChanges() {

  /* Change file selection hint */
  document.querySelectorAll('.dropzone-label').forEach(el => {
    if (el.dataset.tiktokLabelSet) return; // already handled, skip entirely

    const elText = el.textContent.trim();
    const replacements = {
      'Drag and drop a file here': 'File is downloaded from TikTok',
      'Datei hierher ziehen': 'Die Datei wird von TikTok heruntergeladen',
      'un fichier ici': 'Le fichier est téléchargé depuis TikTok',
      'Trascina un file qui': 'Il file viene scaricato da TikTok',
      'Datei erfolgreich verarbeitet': 'Datei wurde von TikTok heruntergeladen',
      'File successfully processed': 'File was downloaded from TikTok',
      'Fichier traité avec succès': 'Fichier téléchargé depuis TikTok',
      'File elaborato con successo': 'File scaricato da TikTok',
    };
    const match = Object.keys(replacements).find(k => elText.includes(k));
    const newText = match ? replacements[match] : 'File is downloaded from TikTok';

    el.textContent = newText;
    el.dataset.tiktokLabelSet = 'true'; // mark so future runs skip this element
  });

  /* Change step indicator label */
  document.querySelectorAll('.step-label').forEach(el => {
    if (el.dataset.tiktokLabelSet) return; // already handled, skip entirely

    const elText = el.textContent.trim();
    const replacements = {
      'Daten hochladen': 'Daten herunterladen',
      'Upload data': 'Download data',
      'Téléverser des données': 'Télécharger des données',
      'Caricare i dati': 'Scaricare i dati',
    };

    if (!Object.prototype.hasOwnProperty.call(replacements, elText)) return; // not a target, leave untouched

    el.textContent = replacements[elText];
    el.dataset.tiktokLabelSet = 'true'; // mark so future runs skip this element
  });

  /* Swap download icon */
  document.querySelectorAll('i.bi-upload').forEach(el => {
    if (el.dataset.iconSwapped) return;
    el.classList.remove('bi-upload');
    el.classList.add('bi-download');
    el.dataset.iconSwapped = 'true';
  });


  /* Hide retry button */
  document.querySelectorAll('.retry-button-container').forEach(el => {
    el.classList.add('d-none');
  })

  /* Hide step heading container */
  document.querySelectorAll('.step-heading-container').forEach(el => {
    el.classList.add('d-none');
  })

  /* Uploader is hidden first, until all customization steps above are applied */
  const uapp = document.getElementById('uapp');
  if (uapp) {
    uapp.style.visibility = 'visible';
  }

}

document.addEventListener('DOMContentLoaded', () => {
  applyDOMChanges();

  const observer = new MutationObserver(() => {
    // Temporarily disconnect so our own writes don't retrigger this callback
    observer.disconnect();
    applyDOMChanges();
    observer.observe(document.body, { childList: true, subtree: true });
  });

  observer.observe(document.body, { childList: true, subtree: true });
});
