/**
 * KI-Massenermittlung - Authentifizierung
 */

(function () {
  'use strict';

  const API_BASE = window.location.origin;

  // Elements
  const tabs = document.querySelectorAll('.auth-tab');
  const loginForm = document.getElementById('login-form');
  const registerForm = document.getElementById('register-form');
  const alertEl = document.getElementById('alert');

  // --- Check if already logged in ---
  const token = localStorage.getItem('token');
  if (token) {
    window.location.href = 'dashboard.html';
    return;
  }

  // --- Tab Switching ---
  tabs.forEach(function (tab) {
    tab.addEventListener('click', function () {
      var target = this.getAttribute('data-tab');
      tabs.forEach(function (t) { t.classList.remove('active'); });
      this.classList.add('active');

      if (target === 'login') {
        loginForm.classList.remove('hidden');
        registerForm.classList.add('hidden');
      } else {
        loginForm.classList.add('hidden');
        registerForm.classList.remove('hidden');
      }
      hideAlert();
    });
  });

  // --- Alert Helpers ---
  function showAlert(message, type) {
    alertEl.textContent = message;
    alertEl.className = 'alert alert-' + (type || 'error') + ' visible';
  }

  function hideAlert() {
    alertEl.className = 'alert alert-error';
  }

  // --- Login ---
  loginForm.addEventListener('submit', function (e) {
    e.preventDefault();
    hideAlert();

    var email = document.getElementById('login-email').value.trim();
    var password = document.getElementById('login-password').value;

    if (!email || !password) {
      showAlert('Bitte füllen Sie alle Felder aus.');
      return;
    }

    var submitBtn = loginForm.querySelector('button[type="submit"]');
    submitBtn.disabled = true;
    submitBtn.textContent = 'Wird angemeldet...';

    fetch(API_BASE + '/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: email, passwort: password })
    })
      .then(function (res) {
        if (!res.ok) {
          return res.json().then(function (data) {
            throw new Error(data.detail || data.message || 'Anmeldung fehlgeschlagen');
          });
        }
        return res.json();
      })
      .then(function (data) {
        localStorage.setItem('token', data.token);
        if (data.firma) {
          localStorage.setItem('firma', JSON.stringify(data.firma));
        }
        window.location.href = 'dashboard.html';
      })
      .catch(function (err) {
        showAlert(err.message);
      })
      .finally(function () {
        submitBtn.disabled = false;
        submitBtn.textContent = 'Anmelden';
      });
  });

  // --- Register ---
  registerForm.addEventListener('submit', function (e) {
    e.preventDefault();
    hideAlert();

    var company = document.getElementById('reg-company').value.trim();
    var email = document.getElementById('reg-email').value.trim();
    var password = document.getElementById('reg-password').value;

    if (!company || !email || !password) {
      showAlert('Bitte füllen Sie alle Felder aus.');
      return;
    }

    if (password.length < 8) {
      showAlert('Das Passwort muss mindestens 8 Zeichen lang sein.');
      return;
    }

    var submitBtn = registerForm.querySelector('button[type="submit"]');
    submitBtn.disabled = true;
    submitBtn.textContent = 'Wird registriert...';

    fetch(API_BASE + '/api/auth/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: company, email: email, passwort: password })
    })
      .then(function (res) {
        if (!res.ok) {
          return res.json().then(function (data) {
            throw new Error(data.detail || data.message || 'Registrierung fehlgeschlagen');
          });
        }
        return res.json();
      })
      .then(function (data) {
        localStorage.setItem('token', data.token);
        if (data.firma) {
          localStorage.setItem('firma', JSON.stringify(data.firma));
        }
        window.location.href = 'dashboard.html';
      })
      .catch(function (err) {
        showAlert(err.message);
      })
      .finally(function () {
        submitBtn.disabled = false;
        submitBtn.textContent = 'Registrieren';
      });
  });
})();
