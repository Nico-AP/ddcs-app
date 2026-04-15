/**
 * All config. options available here:
 * https://cookieconsent.orestbida.com/reference/configuration-reference.html
 */
CookieConsent.run({

  cookie: {
    name: '_cookie_consent',
  },

  guiOptions: {
    consentModal: {
      layout: 'cloud inline',
      position: 'bottom center',
      equalWeightButtons: true,
      flipButtons: false
    },
    preferencesModal: {
      layout: 'box',
      equalWeightButtons: true,
      flipButtons: false
    }
  },

  categories: {
    necessary: {
      enabled: true,
      readOnly: true
    },
  },

  language: {
    default: 'en',
    translations: {
      en: {
        consentModal: {
          title: 'Cookie Policy',
          description: 'Diese Webseite verwendet ausschließlich technisch notwendige Cookies für grundlegende Funktionen wie Sitzungsverwaltung und Sicherheit.',
          acceptAllBtn: 'Verstanden',
          // acceptNecessaryBtn: 'Reject all',
          showPreferencesBtn: 'mehr erfahren',
          // closeIconLabel: 'Reject all and close modal',
          footer: ``,
        },
        preferencesModal: {
          title: 'Cookie Information',
          acceptNecessaryBtn: 'Verstanden',
          closeIconLabel: 'Schliessen',
          serviceCounterLabel: 'Service|Services',
          sections: [
            {
              title: 'Wie diese Webseite Cookies verwendet',
              description: 'Diese Webseite verwendet ausschließlich technisch notwendige Cookies für grundlegende Funktionen wie Sitzungsverwaltung und Sicherheit. Wir setzen keine Cookies für Analyse, Werbung oder Tracking ein.',
            },
            {
              title: 'Technisch notwendige Cookies',
              description: 'Diese Cookies sind für den Betrieb der Website erforderlich:',
              linkedCategory: 'necessary',
              cookieTable: {
                headers: {
                  name: 'Cookie',
                  domain: 'Domain',
                  desc: 'Beschreibung'
                },
                body: [
                  {
                    name: 'sessionid',
                    domain: location.hostname,
                    desc: 'Wird erstellt, wenn Sie sich einloggen. Dieses Cookie hält Ihre Sitzung aufrecht und ermöglicht den Zugriff auf geschützte Bereiche der Website. Es ist für den Betrieb der Website notwendig.',
                  },
                  {
                    name: 'csrftoken',
                    domain: location.hostname,
                    desc: 'Dieses Cookie schützt die Website vor unbefugten Anfragen und stellt sicher, dass Aktionen wie das Absenden von Formularen nur von Ihnen ausgeführt werden können. Es ist für den sicheren Betrieb der Website notwendig.',
                  },
                  {
                    name: '_cookie_consent',
                    domain: location.hostname,
                    desc: 'Speichert Ihre Cookie-Einstellungen, sodass Sie diese nicht bei jedem Besuch erneut festlegen müssen.'
                  }
                ]
              }
            },
          ]
        }
      }
    }
  }
});
