"""
Motor de regras da Tesouraria INJ (funções puras, sem banco de dados).

Segue o Regulamento Interno (aprovado em 31/07/2020) e as decisões
administrativas de 29/10/2026:
- Dízimo dos Dízimos: 10% da entrada de dízimos (Art. 12, § 32).
- Nivelação: +5% quando a média mensal do ano anterior passa de
  1,25 salário mínimo (Art. 13, § 2º, indexado).
- Categorias só pela entrada: plenamente formada >= 1 salário mínimo;
  em formação >= 1/3; em projeção abaixo disso. Congregação nova começa do zero.
- Fundo local: 1% por salário mínimo inteiro contido em (média − 10%),
  aplicado sobre a entrada de cada mês (Art. 12, § 34, como praticado).
- Betel: 4% do líquido depois de 10% + 5%, só plenamente formada.
- Prazo do envio: dia 5 do mês seguinte (§ 80).
"""
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

MESES = ['janeiro', 'fevereiro', 'março', 'abril', 'maio', 'junho',
         'julho', 'agosto', 'setembro', 'outubro', 'novembro', 'dezembro']

CATEGORIAS = {
    'formada': 'Plenamente formada',
    'formacao': 'Em formação',
    'projecao': 'Em projeção',
    'nova': 'Congregação nova',
}

# Valores iniciais das regras (chave, valor, início da vigência).
# Mudanças futuras entram como nova vigência, sem apagar as antigas.
REGRAS_PADRAO = [
    ('salario_minimo', 1412.00, '2024-01-01'),
    ('salario_minimo', 1518.00, '2025-01-01'),
    ('salario_minimo', 1621.00, '2026-01-01'),
    ('pct_dizimo_dizimos', 0.10, '2020-07-31'),
    ('pct_nivelacao', 0.05, '2020-07-31'),
    ('pct_betel', 0.04, '2020-07-31'),
    ('fator_nivelacao', 1.25, '2020-07-31'),
    ('fator_formacao', 1 / 3, '2020-07-31'),
    ('prazo_dia', 5, '2020-07-31'),
    ('min_invest_formada', 500.00, '2026-01-01'),
    ('min_invest_formacao', 300.00, '2026-01-01'),
    ('min_invest_projecao', 200.00, '2026-01-01'),
    ('mes_investimento', 10, '2020-07-31'),
]

REGRAS_ROTULOS = {
    'salario_minimo': 'Salário mínimo vigente (R$)',
    'pct_dizimo_dizimos': 'Dízimo dos Dízimos (fração da entrada)',
    'pct_nivelacao': 'Nivelação (fração da entrada)',
    'pct_betel': 'Associação de Pastores Betel (fração do líquido)',
    'fator_nivelacao': 'Nivelação: média acima de N salários mínimos',
    'fator_formacao': 'Em formação: média a partir de N salários mínimos',
    'prazo_dia': 'Dia limite do envio no mês seguinte',
    'min_invest_formada': 'Fundo de investimento mínimo: plenamente formada (R$)',
    'min_invest_formacao': 'Fundo de investimento mínimo: em formação (R$)',
    'min_invest_projecao': 'Fundo de investimento mínimo: em projeção (R$)',
    'mes_investimento': 'Mês em que se cobra o fundo de investimento (1 a 12)',
}

# Linhas do Relatório Econômico e os itens de lançamento (livro Envios,
# tipo Entrada) que alimentam cada uma.
LINHAS_NACIONAL = [
    ('dia_missionario', 'Oferta Dia Missionário', ['Of. Dia Missionário']),
    ('raios', 'Raios de Luz', ['Of. Raios De Luz']),
    ('dorcas', 'Oferta semestral Dorcas', ['Of. Damas Miss. Metade Ano', 'Of. Damas Miss. Fim Ano']),
    ('safras', 'Safras para Cristo', ['Of. Safras Para Cristo']),
    ('conquistadores', 'Oferta semestral Conquistadores', ['Of. Jovens Miss. Metade Ano', 'Of. Jovens Miss. Fim Ano']),
    ('investimento', 'Fundo de investimento', ['Fundo de Investimento']),
]
LINHAS_DISTRITAL = [
    ('pastor_auxiliar', 'Dízimos pastor auxiliar', ['Dízimos Pastor Auxiliar']),
    ('entradas_extras', 'Dízimos de entradas extras', ['Dízimos de Entradas Extras']),
    ('voluntarias', 'Ofertas voluntárias', ['Ofertas Voluntárias']),
    ('culto_distrital', 'Oferta culto missionário distrital', ['Of. Distrital']),
    ('voto_pastor', 'Voto pastor', ['Voto Pastor']),
    ('socio', 'Sócio missionário', ['Sócio Missionário']),
    ('votos', 'Votos', ['Votos Distritais']),
    ('outros', 'Outros', ['Outros Envios Distritais']),
]
ITENS_ENVIO = sorted({i for _, _, its in LINHAS_NACIONAL + LINHAS_DISTRITAL for i in its})


CENTAVO = Decimal('0.01')


def D(v):
    """Número como Decimal exato (float passa pelo texto: 0.1 vira 0.1, não 0.1000000000000000055)."""
    if isinstance(v, Decimal):
        return v
    return Decimal(str(v if v is not None else 0))


def centavos(v):
    """Decimal arredondado aos centavos, meio para cima (123,455 -> 123,46)."""
    return D(v).quantize(CENTAVO, rounding=ROUND_HALF_UP)


def r2(v):
    return float(centavos(v))


def soma(valores):
    """Soma exata em Decimal, devolvida aos centavos."""
    return float(sum((D(v) for v in valores), Decimal(0)).quantize(CENTAVO, rounding=ROUND_HALF_UP))


def mes_num(nome):
    return MESES.index(nome) + 1


def classificar(media, sm, fator_formacao):
    if media >= sm:
        return 'formada'
    if media >= sm * fator_formacao:
        return 'formacao'
    return 'projecao'


def carta_anual(valores_mensais, sm, reg):
    """valores_mensais: dízimo bruto de cada mês da janela (0 = sem lançamento)."""
    vals = [v for v in valores_mensais if v and v > 0]
    total = soma(vals)
    n = len(vals)
    media = total / n if n else 0.0
    if n == 0:
        categoria = 'nova'
    else:
        categoria = classificar(media, sm, reg['fator_formacao'])
    nivelacao = n > 0 and media > sm * reg['fator_nivelacao']
    dez = r2(media * reg['pct_dizimo_dizimos'])
    saldo = r2(media - dez)
    razao = saldo / sm if sm else 0.0
    fundo_local = int(razao) if n else 0
    return {
        'total': r2(total), 'meses': n, 'media': r2(media), 'categoria': categoria,
        'nivelacao': nivelacao, 'dez': dez, 'saldo': saldo, 'razao': razao,
        'fundo_local_pct': fundo_local, 'betel': categoria == 'formada', 'sm': sm,
    }


def liquidar_dizimo(bruto, comp, reg):
    """Divide o dízimo bruto do mês conforme os compromissos do ano. Contas em Decimal, centavo a centavo."""
    b = centavos(bruto)
    dd = centavos(b * D(reg['pct_dizimo_dizimos']))
    niv = centavos(b * D(reg['pct_nivelacao'])) if comp['nivelacao'] else Decimal('0.00')
    base_betel = b - dd - niv
    betel = centavos(base_betel * D(reg['pct_betel'])) if comp['betel'] else Decimal('0.00')
    # Fundo local: residual. O % do ano incide sobre o que sobra depois do Dízimo dos Dízimos, da Nivelação e do Betel.
    base_fl = base_betel - betel
    fundo_local = centavos(base_fl * D(comp['fundo_local_pct']) / 100)
    liquido = b - dd - niv - betel - fundo_local
    return {k: float(v) for k, v in {'bruto': b, 'dd': dd, 'niv': niv, 'base_betel': base_betel, 'betel': betel,
                                      'base_fl': base_fl, 'fundo_local': fundo_local, 'liquido': liquido}.items()}


# Ofertas semestrais: um departamento em maio, o outro em junho (julho fica para quem não
# conseguiu em junho); no fim do ano, novembro e dezembro. Lembrete, não obrigação.
SEMESTRAIS = {
    'dorcas': ('Dorcas', {1: 'Of. Damas Miss. Metade Ano', 2: 'Of. Damas Miss. Fim Ano'}),
    'conquistadores': ('Conquistadores', {1: 'Of. Jovens Miss. Metade Ano', 2: 'Of. Jovens Miss. Fim Ano'}),
}
MESES_SEMESTRAIS = {5: 1, 6: 1, 7: 1, 11: 2, 12: 2}
INICIO_SEMESTRAL = {1: 5, 2: 11}


def lembretes_semestrais(mes, feitos):
    """mes: 1-12. feitos: {'dorcas': bool, 'conquistadores': bool} já lançados no período do semestre."""
    sem = MESES_SEMESTRAIS.get(mes)
    if not sem:
        return []
    faltam = [nome for chave, (nome, _) in SEMESTRAIS.items() if not feitos.get(chave)]
    if not faltam:
        return []
    quem = ' e '.join(faltam)
    if mes == 7:
        return [f'Julho é o último mês para a oferta semestral de {quem} de metade do ano (para quem não conseguiu em junho).']
    if sem == 1:
        return [f'Mês das ofertas semestrais (maio e junho). Ainda não lançada: {quem}.']
    return [f'Mês das ofertas semestrais de fim de ano (novembro e dezembro). Ainda não lançada: {quem}.']


def fechar_mes(bruto, comp, envios, reg, mes=None):
    """
    bruto: dízimo bruto do mês.
    comp: compromissos do ano (categoria, nivelacao, fundo_local_pct, betel).
    envios: {item de lançamento: valor} do livro Envios no mês.
    Devolve o cálculo completo e as linhas do Relatório Econômico.
    """
    liq = liquidar_dizimo(bruto, comp, reg)
    somar = lambda itens: soma(envios.get(i, 0) for i in itens)

    nacional = [
        {'chave': 'dd', 'rotulo': 'Dízimo dos Dízimos 10%', 'valor': liq['dd'], 'base': liq['bruto']},
        {'chave': 'nivelacao', 'rotulo': 'Nivelação 5%', 'valor': liq['niv'],
         'base': liq['bruto'] if comp['nivelacao'] else None},
    ]
    for chave, rotulo, itens in LINHAS_NACIONAL:
        nacional.append({'chave': chave, 'rotulo': rotulo, 'valor': somar(itens), 'base': None})
    nacional.insert(-1, {'chave': 'betel', 'rotulo': 'Associação de Pastores Betel 4%', 'valor': liq['betel'],
                         'base': liq['base_betel'] if comp['betel'] else None})
    distrital = [{'chave': c, 'rotulo': r, 'valor': somar(i), 'base': None} for c, r, i in LINHAS_DISTRITAL]

    tot_nac = soma(l['valor'] for l in nacional)
    tot_dist = soma(l['valor'] for l in distrital)
    valores = {l['chave']: l['valor'] for l in nacional + distrital}

    avisos = []
    falta = []
    if not valores.get('dia_missionario'):
        falta.append('oferta missionária')
    if comp['categoria'] == 'formada':
        if not valores.get('raios'):
            falta.append('Raios de Luz')
        if not valores.get('safras'):
            falta.append('Safras para Cristo')
    if falta:
        avisos.append(f"Obrigatório para {CATEGORIAS[comp['categoria']].lower()}: {', '.join(falta)}.")
    minimo = reg.get('min_invest_' + comp['categoria'], 0) or 0
    mes_inv = int(reg.get('mes_investimento') or 10)
    if minimo and (mes is None or mes == mes_inv) and valores.get('investimento', 0) < minimo:
        valor_txt = f'{minimo:,.2f}'.replace(',', 'X').replace('.', ',').replace('X', '.')
        avisos.append(f"Fundo de investimento abaixo do mínimo de R$ {valor_txt} (obrigatório, com tolerância).")
    if bruto <= 0:
        avisos.append('Nenhum dízimo lançado neste mês.')

    return {
        'liquidacao': liq, 'nacional': nacional, 'distrital': distrital,
        'total_nacional': tot_nac, 'total_distrital': tot_dist, 'total': soma([tot_nac, tot_dist]),
        'compromisso': dict(comp), 'avisos': avisos,
    }


def prazo_envio(ano, mes, dia=5):
    """Data limite do envio referente ao mês (1-12) do ano: dia N do mês seguinte."""
    if mes == 12:
        return date(ano + 1, 1, dia)
    return date(ano, mes + 1, dia)


def meses_em_atraso(pendentes_vencidos):
    """Quantidade de meses vencidos sem envio confirmado."""
    return len(pendentes_vencidos)


def janela_carta(ano):
    """Meses usados na carta do ano: dezembro do ano retrasado a novembro do ano anterior."""
    jan = [(ano - 2, 12)] + [(ano - 1, m) for m in range(1, 12)]
    return jan


def texto_carta(nome_cong, ano, c):
    from_txt = ('Conforme o disposto no Regulamento Interno (Art. 12, §§ 32 a 35, e Art. 13)')
    brl = lambda v: ('R$ ' + f'{v:,.2f}'.replace(',', 'X').replace('.', ',').replace('X', '.'))
    if c['categoria'] == 'nova':
        p1 = (f"{from_txt}, a congregação de {nome_cong} inicia suas atividades em {ano} sem histórico de entradas. "
              f"Ela começa do zero, sem aporte ao fundo local neste primeiro ano, e sua categoria será definida "
              f"pela entrada dos primeiros meses.")
    else:
        p1 = (f"{from_txt} e com base no estudo da tesouraria local de {c['meses']} meses, com média mensal de "
              f"dízimos de {brl(c['media'])}, a congregação de {nome_cong} fica classificada como "
              f"{CATEGORIAS[c['categoria']].upper()}.")
    p2 = (f"Após enviar o Dízimo dos Dízimos à Tesouraria Nacional, a congregação fará mensalmente o aporte de "
          f"{c['fundo_local_pct']}% da entrada de dízimos do mês ao fundo local, calculado à razão de 1% para cada "
          f"salário mínimo contido na média mensal do ano anterior, descontado o Dízimo dos Dízimos. "
          f"Os envios devem ser feitos até o dia 5 de cada mês.")
    return p1, p2


def lista_compromissos(c):
    L = [('Dízimo dos Dízimos à Tesouraria Nacional', '10%')]
    if c['nivelacao']:
        L.append(('Nivelação (fundo nacional de nivelação)', '5%'))
    if c['betel']:
        L.append(('Associação de Pastores Betel', '4% do líquido'))
    L.append(('Aporte ao fundo local', f"{c['fundo_local_pct']}% da entrada mensal"))
    L.append(('Oferta missionária', 'Sim'))
    if c['categoria'] == 'formada':
        L += [('Oferta Raios de Luz', 'Sim'), ('Oferta Safras para Cristo', 'Sim'),
              ('Oferta semestral de Dorcas', 'Sim'), ('Oferta semestral de Jovens', 'Sim')]
    elif c['categoria'] == 'formacao':
        L.append(('Raios de Luz e Safras para Cristo', 'A critério do pastor'))
    return L
