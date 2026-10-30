// Botão de olho para ver a senha enquanto digita
(function () {
  document.querySelectorAll('input[type=password]').forEach(function (inp) {
    var b = document.createElement('button');
    b.type = 'button'; b.className = 'btn-ver-senha'; b.title = 'Mostrar senha'; b.setAttribute('aria-label', 'Mostrar senha');
    b.innerHTML = '<i class="bi bi-eye"></i>';
    var caixa = document.createElement('span'); caixa.className = 'senha-caixa';
    inp.parentNode.insertBefore(caixa, inp); caixa.appendChild(inp); caixa.appendChild(b);
    b.addEventListener('click', function () {
      var ver = inp.type === 'password'; inp.type = ver ? 'text' : 'password';
      b.innerHTML = ver ? '<i class="bi bi-eye-slash"></i>' : '<i class="bi bi-eye"></i>';
      b.title = ver ? 'Esconder senha' : 'Mostrar senha'; inp.focus();
    });
  });
})();
