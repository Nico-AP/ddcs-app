/**
 * On .ddm-dropzone error state (.dropzone-info.error-info-container
 * appearing), inserts a custom message after it, removes the plain
 * .dropzone-info and .dropzone-retry, and hides the "Weiter" button.
 * Restores the button once the error clears.
 *
 * Dropzone and button markup are Vue-managed, so we can't rely on
 * data-v-* attributes or a one-off scan — a single MutationObserver
 * on <body> reacts to structural changes and to class-attribute
 * changes (in case Vue re-renders and strips our 'd-none' class).
 * We hide via a class rather than inline style, since the button's
 * `style=""` attribute suggests Vue reactively controls :style —
 * fighting over the class attribute instead avoids that conflict.
 *
 * There can be multiple "Weiter" buttons in the DOM at once (one per
 * step) with only one actually visible — so the visible one is
 * captured by reference when an error appears, rather than re-queried
 * each time (which would risk grabbing a hidden button from another
 * step, or losing track once we've hidden it ourselves).
 */
(function () {
  // Resolved via a JSON blob in the host template, not a {% url %}
  // tag here — this file is a static asset, never Django-rendered.
  // Expected: <script id="switch-path-url" type="application/json">{"url": "..."}</script>
  function getSwitchPathUrl() {
    const el = document.getElementById('switch-path-url');
    if (!el) return null;
    try {
      return JSON.parse(el.textContent).url || null;
    } catch {
      return null;
    }
  }

  function buildReplacementElement() {
    const url = getSwitchPathUrl();
    const linkHtml = url
      ? `<a href="${url}">Du kannst stattdessen hier deine Daten direkt in der App selber anfordern und hochladen</a>`
      : 'Du kannst stattdessen deine Daten direkt in der App selber anfordern und hochladen';

    const wrapper = document.createElement('div');
    wrapper.innerHTML = `
      <div class="dropzone-info dropzone-error-message">
        <div class="fs-6">
          Bei der Übertragung der Daten von TikTok ist etwas schiefgegangen.
          ${linkHtml}
        </div>
      </div>
    `.trim();
    return wrapper.firstElementChild;
  }

  // Marks a dropzone as already handled; also lets us tell "we left
  // the error container in place" apart from "Vue cleared the error".
  const REPLACEMENT_MARKER_CLASS = 'dropzone-error-message';

  // Both nav buttons share this class, so text distinguishes them.
  const CONTINUE_BUTTON_CLASS = 'ddm-primary-button-base';
  const CONTINUE_BUTTON_TEXT = 'Weiter';

  const trackedDropzones = new Set();
  const dropzoneHasError = new WeakMap();
  let hiddenButton = null; // the exact button element we've force-hidden, if any

  function isContinueButton(el) {
    return (
      el.nodeType === 1 &&
      el.tagName === 'BUTTON' &&
      el.classList.contains(CONTINUE_BUTTON_CLASS) &&
      el.textContent.trim().includes(CONTINUE_BUTTON_TEXT)
    );
  }

  // Among possibly several "Weiter" buttons (one per step), pick the
  // one actually rendered visible right now. offsetParent (not
  // computed display) accounts for an ancestor being hidden too.
  function pickVisibleContinueButton() {
    return Array.from(document.querySelectorAll('button.' + CONTINUE_BUTTON_CLASS))
      .filter(isContinueButton)
      .find((btn) => btn.offsetParent !== null);
  }

  function anyDropzoneHasError() {
    return Array.from(trackedDropzones).some((dz) => dropzoneHasError.get(dz));
  }

  function updateContinueButtonVisibility() {
    const hasError = anyDropzoneHasError();

    // Our hidden button got replaced/removed by Vue — drop the stale ref.
    if (hiddenButton && !document.contains(hiddenButton)) {
      hiddenButton = null;
    }

    if (hasError && !hiddenButton) {
      const btn = pickVisibleContinueButton();
      if (!btn) return;
      btn.classList.add('d-none');
      hiddenButton = btn;
    } else if (!hasError && hiddenButton) {
      hiddenButton.classList.remove('d-none');
      hiddenButton = null;
    }
  }

  function replaceErrorElements(dropzone) {
    const errorContainer = dropzone.querySelector('.dropzone-info.error-info-container');
    const marker = dropzone.querySelector('.' + REPLACEMENT_MARKER_CLASS);

    if (errorContainer && !marker) {
      const genericInfo = Array.from(dropzone.querySelectorAll('.dropzone-info')).find(
        (el) => !el.classList.contains('error-info-container')
      );
      const retryEl = dropzone.querySelector('.dropzone-retry');

      errorContainer.insertAdjacentElement('afterend', buildReplacementElement());
      if (genericInfo) genericInfo.remove();
      if (retryEl) retryEl.remove();

      dropzoneHasError.set(dropzone, true);
      updateContinueButtonVisibility();
      return;
    }

    // No error container AND no marker (i.e. not just us leaving the
    // container in place) means Vue re-rendered the error away.
    if (!errorContainer && !marker && dropzoneHasError.get(dropzone)) {
      dropzoneHasError.set(dropzone, false);
      updateContinueButtonVisibility();
    }
  }

  function observeDropzone(dropzone) {
    if (dropzone.dataset.errorWatcherAttached) return;
    dropzone.dataset.errorWatcherAttached = 'true';
    trackedDropzones.add(dropzone);
    dropzoneHasError.set(dropzone, false);
    replaceErrorElements(dropzone); // in case the error is already showing
  }

  function scanForDropzones(root) {
    if (root.nodeType !== 1) return;
    if (root.matches?.('.ddm-dropzone')) observeDropzone(root);
    root.querySelectorAll?.('.ddm-dropzone').forEach(observeDropzone);
  }

  document.addEventListener('DOMContentLoaded', () => {
    scanForDropzones(document.body);
    updateContinueButtonVisibility(); // in case error(s) already present at load

    // One observer for everything: childList catches new/replaced
    // dropzones and buttons; the style-attribute watch catches Vue
    // resetting our forced display:none on the hidden button.
    const bodyObserver = new MutationObserver((mutations) => {
      mutations.forEach((mutation) => {
        if (mutation.type === 'childList') {
          mutation.addedNodes.forEach(scanForDropzones);
          trackedDropzones.forEach(replaceErrorElements);
          updateContinueButtonVisibility();
        } else if (
          mutation.type === 'attributes' &&
          mutation.attributeName === 'class' &&
          mutation.target === hiddenButton &&
          anyDropzoneHasError() &&
          !hiddenButton.classList.contains('d-none')
        ) {
          hiddenButton.classList.add('d-none'); // Vue reset the class list — reassert
        }
      });
    });

    bodyObserver.observe(document.body, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ['class'],
    });
  });
})();
