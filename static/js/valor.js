// Mostra o valor que será gravado e recusa formatos ambíguos (ex.: 1,234.56) e datas que não existem.
(function () {
  const RE_MIL = /^\d{1,3}(\.\d{3})+(,\d{1,2})?$/, RE_BR = /^\d+(,\d{1,2})?$/, RE_PONTO = /^\d+\.\d{1,2}$/;
  function ler(txt) {
    const t = (txt || '').replace(/R\$|\s/g, '');
    if (!t) return null;
    if (RE_MIL.test(t) || RE_BR.test(t)) return Number(t.replace(/\./g, '').replace(',', '.'));
    if (RE_PONTO.test(t)) return Number(t);
    return NaN;
  }
  const brl = v => v.toLocaleString('pt-BR', {style: 'currency', currency: 'BRL'});
  function dica(inp) {
    const ancora = inp.closest('.input-group') || inp;
    let d = ancora.nextElementSibling;
    if (!d || !d.classList.contains('dica-valor')) { d = document.createElement('div'); d.className = 'form-text dica-valor'; ancora.after(d); }
    return d;
  }
  document.querySelectorAll('input[data-reais]').forEach(inp => {
    const atualizar = () => {
      const v = ler(inp.value), d = dica(inp);
      if (v === null) { inp.setCustomValidity(''); d.textContent = ''; return; }
      if (isNaN(v)) {
        inp.setCustomValidity('Escreva como 1.234,56');
        d.className = 'form-text dica-valor text-danger';
        d.textContent = 'Não entendi o valor. Escreva como 1.234,56 (ponto nos milhares, vírgula nos centavos).';
      } else if (v < 0.01) {
        inp.setCustomValidity('Mínimo R$ 0,01');
        d.className = 'form-text dica-valor text-danger'; d.textContent = 'O valor precisa ser de pelo menos R$ 0,01.';
      } else {
        inp.setCustomValidity('');
        d.className = 'form-text dica-valor text-success fw-semibold'; d.textContent = 'Será registrado: ' + brl(v);
      }
    };
    inp.addEventListener('input', atualizar); atualizar();
  });
  document.querySelectorAll('input[data-data]').forEach(inp => {
    const atualizar = () => {
      const m = (inp.value || '').trim().match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})$/);
      let d = inp.parentElement.querySelector('.dica-data');
      if (!d) { d = document.createElement('div'); d.className = 'form-text dica-data'; inp.after(d); }
      if (!inp.value.trim()) { inp.setCustomValidity(''); d.textContent = ''; return; }
      const dt = m && new Date(+m[3], +m[2] - 1, +m[1]);
      if (!m || dt.getDate() !== +m[1] || dt.getMonth() !== +m[2] - 1) {
        inp.setCustomValidity('Data inválida');
        d.className = 'form-text dica-data text-danger'; d.textContent = 'Essa data não existe. Use dd/mm/aaaa.';
        return;
      }
      inp.setCustomValidity('');
      const hoje = new Date(); hoje.setHours(23, 59, 59);
      d.className = 'form-text dica-data text-warning-emphasis';
      d.textContent = dt > hoje ? 'Atenção: a data está no futuro.' : '';
    };
    inp.addEventListener('input', atualizar); atualizar();
  });
})();
