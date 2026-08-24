function getCsrfToken() {
  const input = document.querySelector('input[name="csrfmiddlewaretoken"]');
  return input ? input.value : null;
}

document.addEventListener('DOMContentLoaded', () => {
  const container = document.getElementById('study-link-reminder');
  if (!container) return;

  const button = document.getElementById('send-email-button');
  const input = document.getElementById('email-input');
  const feedback = document.getElementById('email-feedback');
  const sendUrl = container.dataset.sendUrl;

  function getCookie(name) {
    let cookieValue = null;
    if (document.cookie && document.cookie !== '') {
      const cookies = document.cookie.split(';');
      for (let i = 0; i < cookies.length; i++) {
        const cookie = cookies[i].trim();
        if (cookie.substring(0, name.length + 1) === (name + '=')) {
          cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
          break;
        }
      }
    }
    return cookieValue;
  }
  // Note: if this file shares scope with the instructions.js already in
  // the codebase, drop this duplicate and reuse the existing getCookie.

  function setFeedback(status, message) {
    feedback.textContent = message;
    feedback.classList.toggle('text-danger', status === 'error');
    feedback.classList.toggle('text-success', status === 'success');
  }

  function isLikelyValidEmail(value) {
    // Lightweight client-side check only — the server remains the
    // source of truth via SendStudyLink.validate_email().
    return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value);
  }

  async function sendStudyLink() {
    const email = input.value.trim();

    if (!isLikelyValidEmail(email)) {
      setFeedback('error', 'Bitte gib eine gültige E-Mail-Adresse ein.');
      input.focus();
      return;
    }

    button.disabled = true;
    const originalText = button.textContent;
    button.textContent = 'Sende...';
    setFeedback(null, '');

    try {
      const csrfToken = getCsrfToken();
      if (!csrfToken) {
        setFeedback('error', 'Es ist ein Fehler aufgetreten. Bitte lade die Seite neu.');
        return;
      }

      const response = await fetch(sendUrl, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': csrfToken,
        },
        body: JSON.stringify({ email }),
      });

      let data;
      try {
        data = await response.json();
      } catch {
        data = null;
      }

      if (response.ok && data && data.status === 'success') {
        setFeedback('success', 'Link wurde gesendet. Bitte prüfe dein Postfach.');
        input.value = '';
      } else {
        setFeedback('error', (data && data.message) || 'Es ist ein Fehler aufgetreten. Bitte versuche es erneut.');
      }
    } catch (err) {
      setFeedback('error', 'Es ist ein Fehler aufgetreten. Bitte versuche es erneut.');
    } finally {
      button.disabled = false;
      button.textContent = originalText;
    }
  }

  button.addEventListener('click', sendStudyLink);
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      sendStudyLink();
    }
  });
});
