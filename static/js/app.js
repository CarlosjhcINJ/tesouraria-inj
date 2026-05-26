/* ════════════════════════════════════════════
   TESOURARIA INJ — JavaScript Principal
   ════════════════════════════════════════════ */

// ── Sidebar toggle ──────────────────────────
document.addEventListener('DOMContentLoaded', function () {
  const toggle = document.getElementById('sidebarToggle');
  const sidebar = document.getElementById('sidebar');
  const main = document.getElementById('mainContent');

  if (toggle && sidebar) {
    toggle.addEventListener('click', function () {
      if (window.innerWidth <= 768) {
        sidebar.classList.toggle('open');
      } else {
        sidebar.classList.toggle('collapsed');
      }
    });
  }

  // Fechar sidebar ao clicar fora no mobile
  document.addEventListener('click', function (e) {
    if (window.innerWidth <= 768 && sidebar && sidebar.classList.contains('open')) {
      if (!sidebar.contains(e.target) && !toggle.contains(e.target)) {
        sidebar.classList.remove('open');
      }
    }
  });
});

// ── Formulário de Lançamentos ───────────────
function setupLancamentoForm() {
  const livroSel = document.getElementById('livroSelect');
  const tipoSel  = document.getElementById('tipoSelect');
  const itemSel  = document.getElementById('itemSelect');

  if (!livroSel || !tipoSel || !itemSel) return;

  function carregarCategorias() {
    const livro = livroSel.value;
    const tipo  = tipoSel.value;
    if (!livro || !tipo) return;

    fetch(`/api/categorias/${encodeURIComponent(livro)}/${encodeURIComponent(tipo)}`)
      .then(r => r.json())
      .then(cats => {
        const current = itemSel.value;
        itemSel.innerHTML = '<option value="">— Selecione o item —</option>';
        cats.forEach(cat => {
          const opt = document.createElement('option');
          opt.value = cat;
          opt.textContent = cat;
          if (cat === current) opt.selected = true;
          itemSel.appendChild(opt);
        });
      });
  }

  livroSel.addEventListener('change', carregarCategorias);
  tipoSel.addEventListener('change', carregarCategorias);

  // Carregar ao iniciar se já há valores
  if (livroSel.value && tipoSel.value) carregarCategorias();
}

document.addEventListener('DOMContentLoaded', setupLancamentoForm);

// ── Formatação de valor em BRL ───────────────
function formatBRL(input) {
  let val = input.value.replace(/[^\d,]/g, '');
  input.value = val;
}

// ── Confirmar exclusão ───────────────────────
function confirmarExclusao(form, msg) {
  if (confirm(msg || 'Tem certeza que deseja excluir este registro?')) {
    form.submit();
  }
}

// ── Gráfico de Fluxo Mensal ──────────────────
function renderFluxoChart(canvasId, data) {
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;
  const ctx = canvas.getContext('2d');

  const meses   = data.map(d => d.mes);
  const entradas = data.map(d => d.e !== undefined ? d.e : d.entradas);
  const saidas   = data.map(d => d.s !== undefined ? d.s : d.saidas);

  new Chart(ctx, {
    type: 'bar',
    data: {
      labels: meses,
      datasets: [
        {
          label: 'Entradas',
          data: entradas,
          backgroundColor: 'rgba(39,174,96,0.75)',
          borderColor: '#27ae60',
          borderWidth: 1,
          borderRadius: 6,
        },
        {
          label: 'Saídas',
          data: saidas,
          backgroundColor: 'rgba(231,76,60,0.75)',
          borderColor: '#e74c3c',
          borderWidth: 1,
          borderRadius: 6,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { position: 'top', labels: { font: { family: 'Inter', size: 12 } } },
        tooltip: {
          callbacks: {
            label: ctx => ' R$ ' + ctx.parsed.y.toLocaleString('pt-BR', { minimumFractionDigits: 2 }),
          },
        },
      },
      scales: {
        x: { grid: { display: false }, ticks: { font: { family: 'Inter', size: 11 } } },
        y: {
          grid: { color: '#f0f0f0' },
          ticks: {
            font: { family: 'Inter', size: 11 },
            callback: v => 'R$ ' + v.toLocaleString('pt-BR'),
          },
        },
      },
    },
  });
}

// ── Gráfico de pizza (categorias) ────────────
function renderPizzaChart(canvasId, data) {
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;
  const ctx = canvas.getContext('2d');

  const cores = [
    '#3498db','#e74c3c','#27ae60','#f39c12','#9b59b6',
    '#1abc9c','#e67e22','#2ecc71','#e91e63','#607d8b',
  ];

  new Chart(ctx, {
    type: 'doughnut',
    data: {
      labels: data.map(d => d.item),
      datasets: [{
        data: data.map(d => d.total),
        backgroundColor: cores.slice(0, data.length),
        borderWidth: 2,
        borderColor: '#fff',
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { position: 'right', labels: { font: { family: 'Inter', size: 11 }, boxWidth: 14 } },
        tooltip: {
          callbacks: {
            label: ctx => ' R$ ' + ctx.parsed.toLocaleString('pt-BR', { minimumFractionDigits: 2 }),
          },
        },
      },
      cutout: '60%',
    },
  });
}

// ── Calcular dízimo em tempo real ─────────────
function setupDizimoCalc() {
  const bruto = document.getElementById('dizimoBruto');
  const pctNac = document.getElementById('pctNacional');
  const pctFL  = document.getElementById('pctFundoLocal');

  const elNac     = document.getElementById('calcNacional');
  const elFL      = document.getElementById('calcFundoLocal');
  const elLiquido = document.getElementById('calcLiquido');

  if (!bruto) return;

  function calcular() {
    const b  = parseFloat(bruto.value.replace(',', '.')) || 0;
    const pn = parseFloat(pctNac.value) || 0.15;
    const pf = parseFloat(pctFL.value) || 0.03;
    const vn = b * pn;
    const vf = b * pf;
    const vl = b - vn - vf;

    function fmt(v) {
      return 'R$ ' + v.toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    }

    if (elNac)     elNac.textContent     = fmt(vn);
    if (elFL)      elFL.textContent      = fmt(vf);
    if (elLiquido) elLiquido.textContent = fmt(vl);
  }

  [bruto, pctNac, pctFL].forEach(el => el && el.addEventListener('input', calcular));
  calcular();
}

document.addEventListener('DOMContentLoaded', setupDizimoCalc);

// ── Auto dismiss alerts ───────────────────────
document.addEventListener('DOMContentLoaded', function () {
  setTimeout(() => {
    document.querySelectorAll('.alert:not(.alert-danger)').forEach(el => {
      const bsAlert = bootstrap.Alert.getOrCreateInstance(el);
      if (bsAlert) bsAlert.close();
    });
  }, 4000);
});
