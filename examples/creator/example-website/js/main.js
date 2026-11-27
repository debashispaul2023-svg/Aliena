(function () {
  'use strict';
  var toggle = document.querySelector('.nav-toggle');
  var links = document.getElementById('nav-links');
  if (toggle && links) {
    toggle.addEventListener('click', function () {
      var open = links.classList.toggle('open');
      toggle.setAttribute('aria-expanded', String(open));
    });
  }
  var form = document.getElementById('contact-form');
  if (!form) { return; }
  var status = form.querySelector('.form-status');
  function setError(name, msg) {
    var el = form.querySelector('[data-for="' + name + '"]');
    if (el) { el.textContent = msg; }
  }
  form.addEventListener('submit', function (event) {
    event.preventDefault();
    var data = { name: form.name.value.trim(), email: form.email.value.trim(), message: form.message.value.trim() };
    var ok = true;
    setError('name', data.name ? '' : 'Please enter your name.');
    setError('email', /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(data.email) ? '' : 'Please enter a valid email.');
    setError('message', data.message ? '' : 'Please enter a message.');
    ok = data.name && /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(data.email) && data.message;
    if (!ok) { status.textContent = 'Please fix the errors above.'; status.className = 'form-status'; return; }
    if (window.submitContact) {
      window.submitContact(data).then(function () {
        status.textContent = 'Thank you! Your message was sent.'; status.className = 'form-status ok'; form.reset();
      }).catch(function () {
        status.textContent = 'Sorry, sending failed. Please try again later.'; status.className = 'form-status';
      });
    } else {
      status.textContent = 'Thank you! (Demo: no backend is connected.)'; status.className = 'form-status ok'; form.reset();
    }
  });
})();
