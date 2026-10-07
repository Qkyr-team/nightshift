(function () {
  // --- подтверждения опасных действий
  document.addEventListener('submit', function (e) {
    var msg = e.target.getAttribute('data-confirm');
    if (msg && !confirm(msg)) { e.preventDefault(); return; }
    // защита от двойной отправки
    var form = e.target;
    setTimeout(function () {
      form.querySelectorAll('button[type=submit],button:not([type])').forEach(function (b) { b.disabled = true; });
    }, 0);
  });

  // --- Cmd/Ctrl+Enter отправляет форму
  document.querySelectorAll('textarea[data-submit]').forEach(function (ta) {
    ta.addEventListener('keydown', function (e) {
      if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') { e.preventDefault(); ta.form.requestSubmit(); }
    });
    ta.addEventListener('input', function () { ta.style.height = '44px'; ta.style.height = Math.min(ta.scrollHeight, 160) + 'px'; });
  });

  // --- предпросмотр фото товара
  var photoInput = document.getElementById('photo-input');
  var drop = document.getElementById('drop');
  if (photoInput && drop) {
    photoInput.addEventListener('change', function () {
      var f = photoInput.files[0]; if (!f) return;
      drop.style.backgroundImage = 'url(' + URL.createObjectURL(f) + ')';
      drop.classList.add('has');
    });
  }
  // --- значок «прикреплено фото» в чате
  var attach = document.querySelector('.attach input');
  if (attach) attach.addEventListener('change', function () { attach.parentNode.classList.toggle('has', !!attach.files.length); });

  // --- чипы размеров
  document.querySelectorAll('[data-chips]').forEach(function (wrap) {
    var input = document.getElementById(wrap.getAttribute('data-chips'));
    function read() { return input.value.split(',').map(function (s) { return s.trim(); }).filter(Boolean); }
    function paint() { var cur = read(); wrap.querySelectorAll('.chip').forEach(function (c) { c.classList.toggle('on', cur.indexOf(c.dataset.v) > -1); }); }
    wrap.querySelectorAll('.chip').forEach(function (c) {
      c.addEventListener('click', function () {
        var cur = read(), i = cur.indexOf(c.dataset.v);
        if (i > -1) cur.splice(i, 1); else cur.push(c.dataset.v);
        input.value = cur.join(','); paint();
      });
    });
    input.addEventListener('input', paint); paint();
  });

  // --- прокрутка чата вниз
  var msgs = document.getElementById('msgs');
  if (msgs) msgs.scrollTop = msgs.scrollHeight;

  // --- живые счётчики и автообновление диалога
  var unread0 = parseInt(document.body.dataset.unread || '0', 10);
  var baseTitle = document.title;
  function setBadge(name, n) {
    document.querySelectorAll('[data-badge="' + name + '"]').forEach(function (el) {
      el.textContent = n > 0 ? n : ''; el.setAttribute('data-zero', n > 0 ? '0' : '1');
    });
  }
  function poll() {
    fetch('/api/counts', { headers: { 'Accept': 'application/json' }, credentials: 'same-origin' })
      .then(function (r) { return r.headers.get('content-type').indexOf('json') > -1 ? r.json() : null; })
      .then(function (d) {
        if (!d) return;
        setBadge('orders', d.orders); setBadge('custom', d.custom); setBadge('unread', d.unread);
        document.title = (d.unread + d.orders > 0 ? '(' + (d.unread + d.orders) + ') ' : '') + baseTitle;
        var inChat = !!document.getElementById('msgs');
        var ta = document.querySelector('.composer textarea');
        var typing = ta && (ta.value.trim() || document.activeElement === ta);
        if (inChat && d.unread > unread0 && !typing) location.reload();
        unread0 = d.unread;
      }).catch(function () {});
  }
  setInterval(poll, 8000);
})();
