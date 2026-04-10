/**
 * KI-Massenermittlung - Auth (direkt via Supabase RPC)
 */
(function () {
  'use strict';

  if (getSession()) {
    window.location.href = 'dashboard.html';
    return;
  }

  var tabs = document.querySelectorAll('.auth-tab');
  var loginForm = document.getElementById('login-form');
  var registerForm = document.getElementById('register-form');
  var alertEl = document.getElementById('alert');

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

  function showAlert(msg, type) {
    alertEl.textContent = msg;
    alertEl.className = 'alert alert-' + (type || 'error') + ' visible';
  }
  function hideAlert() { alertEl.className = 'alert alert-error'; }

  // Login
  loginForm.addEventListener('submit', function (e) {
    e.preventDefault();
    hideAlert();
    var email = document.getElementById('login-email').value.trim();
    var password = document.getElementById('login-password').value;
    if (!email || !password) { showAlert('Bitte alle Felder ausfüllen.'); return; }

    var btn = loginForm.querySelector('button[type="submit"]');
    btn.disabled = true;
    btn.textContent = 'Wird angemeldet...';

    sbRpc('login_firma', { p_email: email, p_passwort: password })
      .then(function (firma) {
        setSession(firma);
        window.location.href = 'dashboard.html';
      })
      .catch(function (err) {
        showAlert(err.message || 'Anmeldung fehlgeschlagen');
      })
      .finally(function () {
        btn.disabled = false;
        btn.textContent = 'Anmelden';
      });
  });

  // Register
  registerForm.addEventListener('submit', function (e) {
    e.preventDefault();
    hideAlert();
    var company = document.getElementById('reg-company').value.trim();
    var email = document.getElementById('reg-email').value.trim();
    var password = document.getElementById('reg-password').value;
    if (!company || !email || !password) { showAlert('Bitte alle Felder ausfüllen.'); return; }
    if (password.length < 8) { showAlert('Passwort muss mindestens 8 Zeichen haben.'); return; }

    var btn = registerForm.querySelector('button[type="submit"]');
    btn.disabled = true;
    btn.textContent = 'Wird registriert...';

    sbRpc('register_firma', { p_name: company, p_email: email, p_passwort: password })
      .then(function (firma) {
        setSession(firma);
        window.location.href = 'dashboard.html';
      })
      .catch(function (err) {
        showAlert(err.message || 'Registrierung fehlgeschlagen');
      })
      .finally(function () {
        btn.disabled = false;
        btn.textContent = 'Registrieren';
      });
  });
})();
