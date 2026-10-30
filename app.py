"""
Tesouraria INJ — Sistema de Gestão Financeira Multi-Congregação
Igreja do Nome de Jesus

Perfis:
  tesoureiro  — lança, fecha o mês, anexa comprovantes (uma congregação)
  pastor      — consulta, aprova o fechamento, reabre mês, confirma a carta anual
  admin       — Tesouraria Nacional: congregações, usuários, regras, cartas, envios
  supervisor  — consulta os envios de todas as congregações, sem editar
"""
from flask import (Flask, render_template, request, redirect, url_for,
                   jsonify, flash, send_file, session, abort, g)
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from datetime import datetime, date, timedelta, timezone
import os, io, json, hashlib, hmac, secrets

import db
import regras as R
from regras import MESES

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY') or secrets.token_hex(32)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_SECURE=os.environ.get('COOKIE_SECURE', '1' if db.IS_PG else '0') == '1',
    PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
    MAX_CONTENT_LENGTH=6 * 1024 * 1024,
)

ANOS = list(range(2020, 2035))
MAX_ANEXO = 5 * 1024 * 1024
MAX_PDF = 2 * 1024 * 1024
TIPOS_ANEXO = {'application/pdf', 'image/jpeg', 'image/png', 'image/webp'}

LIVROS = ['FundoLocal', 'Projetos', 'Envios', 'LiqDízimos']
LIVROS_LABELS = {
    'FundoLocal': 'Fundo Local',
    'Projetos': 'Projetos',
    'Envios': 'Envios / Missões',
    'LiqDízimos': 'Liquidação de Dízimos',
}
LIVRO_NOME = {'FundoLocal': 'Caixa local', 'Projetos': 'Projetos', 'Envios': 'Envios / Missões',
              'LiqDízimos': 'Liquidação de Dízimos'}
FORMAS = ['Dinheiro', 'Pix', 'Banco']

CATEGORIAS = {
    'FundoLocal': {
        'Entrada': sorted([
            'Comitê de Família', 'Contribuição do pastor para projetos',
            'Contribuição de irmão para pastor (assembleia)', 'Marcha missionária',
            'Of. Ação de Graças', 'Of. Cultos de Quinta', 'Of. Cultos de Terça',
            'Of. Cultos Especiais', 'Of. Cultos de Sábado', 'Of. Domingo à Noite',
            'Of. Domingo E.B.D.', 'Of. na Refam', 'Of. Social (Casos Especiais)',
            'Oferta de Cavalheiros', 'Oferta de Música', 'Oferta de Obra Social',
            'Outras Ofertas', 'Parceiros Missionários', 'Voto do Talento',
            'Votos', 'Votos para Construção',
        ]),
        'Saída': sorted([
            'Aluguel de Casa Pastoral', 'Aluguel de Caçamba',
            'Aluguel de Máquina de Construção', 'Aluguel do Salão', 'Atividades Legais',
            'Ajuda ao Pastor Auxiliar', 'Cafeteria / Restaurante', 'Completar uma Oferta',
            'Compra de Instrumentos', 'Compra de Materiais de Construção',
            'Compra de Som', 'Compra de Utensílios de Limpeza',
            'Artigos de Papelaria', 'Botijão de Gás',
            'Construção e Reforma', 'Documentação e Escrituras', 'Evangelismo', 'Eventos',
            'Eventos e Alimentação', 'Manutenção da Cozinha',
            'Manutenção de Equipamento', 'Manutenção do Prédio',
            'Manutenção de Som', 'Materiais de Escritório',
            'Obra Social', 'Outras Compras para o Templo',
            'Outros Fundo Local', 'Pagamento de Parcela', 'Internet', 'Mão de Obra',
            'Produtos de Limpeza', 'Projetos da Diretoria Local',
            'Serviços Públicos (água, luz)', 'Trabalho com Crianças', 'Trabalho com Damas',
            'Trabalho com Jovens', 'Transporte Urbano', 'Viagens', 'Viagem para Assembleia',
        ]),
    },
    'Projetos': {
        'Entrada': sorted([
            'Atividades - Cantina', 'Brechó', 'Eventos', 'Fundo de Transporte',
            'Outras Entradas de Projetos', 'Vendas', 'Votos', 'Votos para Construção',
        ]),
        'Saída': sorted([
            'Aluguel de Caçamba', 'Aluguel de Máquina de Construção',
            'Compra de Instrumentos', 'Compra de Materiais de Construção',
            'Compra de Som', 'Manutenção do Prédio', 'Manutenção de Som',
            'Outras Compras para o Templo', 'Outras Saídas de Projetos',
            'Pagamento de Parcela', 'Mão de Obra',
        ]),
    },
    'Envios': {
        'Entrada': R.ITENS_ENVIO,
        'Saída': ['Outros Envios'],
    },
    'LiqDízimos': {
        'Entrada': ['Outros Dízimos'],
        'Saída': ['Outros Dízimos'],
    },
}

PAPEIS = {'tesoureiro': 'Tesoureiro(a)', 'pastor': 'Pastor', 'admin': 'Tesouraria Nacional',
          'supervisor': 'Supervisor (consulta)'}
STATUS_FECH = {
    'fechado': ('Aguardando aprovação do pastor', 'warning'),
    'aprovado': ('Aguardando comprovante', 'info'),
    'enviado': ('Enviado · mês travado', 'primary'),
    'recebido': ('Recebido pela nacional', 'success'),
}

# ═════════════════════════════════════════════
#  BANCO DE DADOS
# ═════════════════════════════════════════════
def get_db():
    return db.connect()


def _cols(conn, table):
    if db.IS_PG:
        rows = conn.execute("SELECT column_name AS c FROM information_schema.columns WHERE table_name = ?",
                            (table,)).fetchall()
        return {r['c'] for r in rows}
    return {r['name'] for r in conn.execute(f'PRAGMA table_info({table})').fetchall()}


def _add_col(conn, table, col, ddl):
    if col not in _cols(conn, table):
        conn.execute(f'ALTER TABLE {table} ADD COLUMN {col} {ddl}')


def init_db():
    conn = get_db()
    PK, BLOB = db.PK, db.BLOB
    stmts = [
        f'''CREATE TABLE IF NOT EXISTS congregacoes (
            id {PK}, nome TEXT NOT NULL, ativo INTEGER DEFAULT 1,
            criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''',
        f'''CREATE TABLE IF NOT EXISTS usuarios (
            id {PK}, cong_id INTEGER REFERENCES congregacoes(id),
            nome TEXT NOT NULL, usuario TEXT NOT NULL UNIQUE, senha_hash TEXT NOT NULL,
            papel TEXT NOT NULL, ativo INTEGER DEFAULT 1,
            criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''',
        '''CREATE TABLE IF NOT EXISTS config (
            cong_id INTEGER NOT NULL, key TEXT NOT NULL, value TEXT,
            PRIMARY KEY (cong_id, key))''',
        '''CREATE TABLE IF NOT EXISTS config_nacional (key TEXT PRIMARY KEY, value TEXT)''',
        f'''CREATE TABLE IF NOT EXISTS transacoes (
            id {PK}, cong_id INTEGER NOT NULL, livro TEXT NOT NULL, tipo TEXT NOT NULL,
            item TEXT NOT NULL, valor REAL NOT NULL, mes TEXT NOT NULL, ano INTEGER NOT NULL,
            data_registro TEXT, obs TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''',
        f'''CREATE TABLE IF NOT EXISTS orcamento (
            id {PK}, cong_id INTEGER NOT NULL, item TEXT NOT NULL, tipo TEXT NOT NULL,
            orcam_ano REAL DEFAULT 0, orcam_mes REAL DEFAULT 0, observacao TEXT, ano INTEGER NOT NULL,
            UNIQUE(cong_id, item, tipo, ano))''',
        f'''CREATE TABLE IF NOT EXISTS dizimos (
            id {PK}, cong_id INTEGER NOT NULL, dizimo_bruto REAL NOT NULL,
            pct_nacional REAL DEFAULT 0, pct_fundo_local REAL DEFAULT 0,
            valor_nacional REAL, valor_fundo_local REAL, valor_liquido REAL,
            mes TEXT NOT NULL, ano INTEGER NOT NULL, data_registro TEXT, obs TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''',
        '''CREATE TABLE IF NOT EXISTS regras (
            chave TEXT NOT NULL, valor REAL NOT NULL, vigencia TEXT NOT NULL,
            criado_por INTEGER, criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (chave, vigencia))''',
        f'''CREATE TABLE IF NOT EXISTS compromissos (
            id {PK}, cong_id INTEGER NOT NULL, ano INTEGER NOT NULL, categoria TEXT NOT NULL,
            nivelacao INTEGER NOT NULL DEFAULT 0, fundo_local_pct INTEGER NOT NULL DEFAULT 0,
            betel INTEGER NOT NULL DEFAULT 0, media REAL DEFAULT 0, meses INTEGER DEFAULT 0,
            salario_minimo REAL DEFAULT 0, observacao TEXT,
            emitido_por INTEGER, emitido_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            confirmado_por INTEGER, confirmado_em TIMESTAMP,
            UNIQUE(cong_id, ano))''',
        f'''CREATE TABLE IF NOT EXISTS fechamentos (
            id {PK}, cong_id INTEGER NOT NULL, ano INTEGER NOT NULL, mes INTEGER NOT NULL,
            status TEXT NOT NULL, calculo TEXT NOT NULL, total REAL NOT NULL,
            fechado_por INTEGER, fechado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            aprovado_por INTEGER, aprovado_em TIMESTAMP,
            comprovante_valor REAL, comprovante_data TEXT,
            comprovante_arquivo {BLOB}, comprovante_nome TEXT, comprovante_tipo TEXT,
            enviado_por INTEGER, enviado_em TIMESTAMP,
            recebido_por INTEGER, recebido_em TIMESTAMP,
            UNIQUE(cong_id, ano, mes))''',
        f'''CREATE TABLE IF NOT EXISTS anexos (
            id {PK}, transacao_id INTEGER NOT NULL, nome TEXT, tipo TEXT, dados {BLOB},
            criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''',
        f'''CREATE TABLE IF NOT EXISTS auditoria (
            id {PK}, quando TIMESTAMP DEFAULT CURRENT_TIMESTAMP, usuario_id INTEGER,
            usuario_nome TEXT, cong_id INTEGER, acao TEXT NOT NULL, detalhe TEXT,
            antes TEXT, depois TEXT)''',
        f'''CREATE TABLE IF NOT EXISTS login_falhas (
            id {PK}, chave TEXT NOT NULL, quando TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''',
    ]
    for s in stmts:
        conn.execute(s)

    # Colunas novas em bancos antigos
    _add_col(conn, 'transacoes', 'origem', 'TEXT')
    _add_col(conn, 'transacoes', 'transferencia', 'INTEGER DEFAULT 0')
    _add_col(conn, 'transacoes', 'forma', 'TEXT')
    _add_col(conn, 'transacoes', 'usuario_id', 'INTEGER')
    _add_col(conn, 'transacoes', 'pessoa', 'TEXT')
    _add_col(conn, 'dizimos', 'usuario_id', 'INTEGER')

    # Migração do modelo antigo (login na própria congregação)
    ccols = _cols(conn, 'congregacoes')
    if 'usuario' in ccols and not conn.execute('SELECT 1 FROM usuarios').fetchone():
        for c in conn.execute('SELECT * FROM congregacoes').fetchall():
            papel = 'admin' if c.get('is_admin') else 'tesoureiro'
            conn.execute('INSERT INTO usuarios (cong_id, nome, usuario, senha_hash, papel, ativo) VALUES (?,?,?,?,?,?)',
                         (None if papel == 'admin' else c['id'], c['nome'], c['usuario'],
                          c['senha_hash'], papel, c['ativo']))
            if papel == 'admin':
                conn.execute('UPDATE congregacoes SET ativo=0 WHERE id=?', (c['id'],))

    # Regras e dados da conta nacional
    for chave, valor, vig in R.REGRAS_PADRAO:
        conn.execute('INSERT INTO regras (chave, valor, vigencia) VALUES (?,?,?) ON CONFLICT (chave, vigencia) DO NOTHING',
                     (chave, valor, vig))
    for k, v in CONTA_NACIONAL_PADRAO.items():
        conn.execute('INSERT INTO config_nacional (key, value) VALUES (?,?) ON CONFLICT (key) DO NOTHING', (k, v))

    # Primeiro administrador: só por variável de ambiente (nunca senha fixa no código)
    adm_user = os.environ.get('ADMIN_USUARIO', 'admin').strip().lower()
    adm_pass = os.environ.get('ADMIN_SENHA', '')
    tem_admin = conn.execute("SELECT 1 FROM usuarios WHERE papel='admin' AND ativo=1").fetchone()
    if not tem_admin and len(adm_pass) >= 8:
        conn.execute("INSERT INTO usuarios (cong_id, nome, usuario, senha_hash, papel) VALUES (NULL,?,?,?,'admin') "
                     "ON CONFLICT (usuario) DO NOTHING",
                     ('Tesouraria Nacional', adm_user, generate_password_hash(adm_pass)))
    conn.commit()
    conn.close()


CONTA_NACIONAL_PADRAO = {
    'cnpj': '60.901.725/0001-82',
    'banco': 'Caixa Econômica Federal',
    'agencia': '4717',
    'operacao': '1388',
    'conta': '000739087232-3 (poupança)',
    'pix': '60901725000182 (CNPJ)',
    'favorecido': 'Igreja do Nome de Jesus',
    'endereco_sede': 'R. Trevo do Mato, 199 - Parque Guarani - São Paulo/SP, 08235-740',
    'inicio_uso': '2026-11',
}


def config_nacional():
    with get_db() as conn:
        return {r['key']: r['value'] for r in conn.execute('SELECT key, value FROM config_nacional').fetchall()}


def regras_em(conn, quando=None):
    """Valor de cada regra vigente na data (texto AAAA-MM-DD)."""
    quando = quando or date.today().isoformat()
    out = {}
    for r in conn.execute('SELECT chave, valor, vigencia FROM regras WHERE vigencia <= ? ORDER BY vigencia',
                          (quando,)).fetchall():
        out[r['chave']] = float(r['valor'])
    return out


# ═════════════════════════════════════════════
#  SEGURANÇA
# ═════════════════════════════════════════════
def verificar_senha(stored, senha):
    if stored.startswith(('pbkdf2:', 'scrypt:')):
        return check_password_hash(stored, senha)
    # Formato antigo (SHA-256 sem sal): aceito uma vez e substituído no login
    legado = hashlib.sha256(senha.encode('utf-8')).hexdigest()
    return hmac.compare_digest(stored, legado)


def csrf_token():
    if '_csrf' not in session:
        session['_csrf'] = secrets.token_urlsafe(32)
    return session['_csrf']


app.jinja_env.globals['csrf_token'] = csrf_token


@app.before_request
def protecao_csrf():
    if request.method == 'POST' and not app.config.get('TESTING_SEM_CSRF'):
        token = request.form.get('csrf_token') or request.headers.get('X-CSRF-Token')
        if not token or not hmac.compare_digest(token, session.get('_csrf', '')):
            flash('A página expirou. Tente de novo.', 'warning')
            return redirect(request.referrer or url_for('login'))


def auditar(conn, acao, detalhe='', antes=None, depois=None, cong_id=None):
    conn.execute('INSERT INTO auditoria (usuario_id, usuario_nome, cong_id, acao, detalhe, antes, depois) '
                 'VALUES (?,?,?,?,?,?,?)',
                 (session.get('user_id'), session.get('user_nome'),
                  cong_id if cong_id is not None else session.get('cong_id'), acao, detalhe,
                  json.dumps(antes, default=str, ensure_ascii=False) if antes is not None else None,
                  json.dumps(depois, default=str, ensure_ascii=False) if depois is not None else None))


def login_required(f):
    @wraps(f)
    def wrapper(*a, **kw):
        if not session.get('user_id'):
            return redirect(url_for('login', next=request.path))
        return f(*a, **kw)
    return wrapper


def papel_required(*papeis):
    def deco(f):
        @wraps(f)
        def wrapper(*a, **kw):
            if not session.get('user_id'):
                return redirect(url_for('login', next=request.path))
            admin_na_cong = session.get('papel') == 'admin' and session.get('cong_id') and 'tesoureiro' in papeis
            if session.get('papel') not in papeis and not admin_na_cong:
                flash('Você não tem permissão para esta página.', 'danger')
                return redirect(url_for('inicio'))
            return f(*a, **kw)
        return wrapper
    return deco


def cong_required(f):
    """Páginas da tesouraria local: exigem usuário ligado a uma congregação."""
    @wraps(f)
    def wrapper(*a, **kw):
        if not session.get('user_id'):
            return redirect(url_for('login', next=request.path))
        if not session.get('cong_id'):
            return redirect(url_for('nacional_envios'))
        return f(*a, **kw)
    return wrapper


def pode_editar():
    return session.get('papel') == 'tesoureiro' or (session.get('papel') == 'admin' and bool(session.get('cong_id')))


def get_cong_id():
    return session.get('cong_id')


def get_cfg():
    cid = get_cong_id()
    if not cid:
        return {'nome_congregacao': 'Tesouraria Nacional', 'ano_atual': str(datetime.now().year)}
    with get_db() as conn:
        rows = conn.execute('SELECT key, value FROM config WHERE cong_id=?', (cid,)).fetchall()
    return {r['key']: r['value'] for r in rows}


def _config_defaults(nome_cong=''):
    return {
        'nome_congregacao': nome_cong or 'Igreja do Nome de Jesus',
        'nome_pastor': '', 'nome_tesoureiro': '', 'nome_auxiliar': '', 'endereco': '',
        'ano_atual': str(datetime.now().year), 'saldo_ano_anterior': '0',
    }


def cadastro_falta(conn, cid, ano, cfg=None):
    """O que falta no cadastro antes de lançar: nomes e a classificação do ano."""
    cfg = cfg if cfg is not None else get_cfg()
    falta = []
    if not cfg.get('nome_pastor') or not cfg.get('nome_tesoureiro'):
        falta.append('os nomes do pastor e do tesoureiro')
    if not conn.execute('SELECT 1 FROM compromissos WHERE cong_id=? AND ano=?', (cid, ano)).fetchone():
        falta.append(f'os dízimos do ano anterior (para definir a classificação e a liquidação de {ano})')
    return falta


def exigir_cadastro(ano):
    """Redireciona ao cadastro se faltar algo. Retorna None quando está tudo certo."""
    cid = get_cong_id()
    with get_db() as conn:
        falta = cadastro_falta(conn, cid, ano)
    if falta:
        flash('Antes de lançar, complete o cadastro: falta ' + ' e '.join(falta) + '.', 'warning')
        return redirect(url_for('configuracoes', ano=ano))
    return None


def mes_travado(conn, cid, ano, mes_nome):
    if mes_nome not in MESES:
        return None
    return conn.execute('SELECT status FROM fechamentos WHERE cong_id=? AND ano=? AND mes=?',
                        (cid, int(ano), R.mes_num(mes_nome))).fetchone()


def parse_valor(txt):
    txt = (txt or '').strip().replace('R$', '').replace(' ', '')
    if ',' in txt:
        txt = txt.replace('.', '').replace(',', '.')
    v = float(txt)
    if v < 0 or v > 10_000_000:
        raise ValueError('valor fora do limite')
    return round(v, 2)


MES_ORDEM = 'CASE mes ' + ' '.join(f"WHEN '{m}' THEN {i + 1}" for i, m in enumerate(MESES)) + ' ELSE 13 END'


# ═════════════════════════════════════════════
#  FILTROS JINJA
# ═════════════════════════════════════════════
def fmt_brl(value):
    try:
        v = round(float(value), 2) + 0.0
        if v == 0:
            v = 0.0
        return f"R$ {v:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
    except Exception:
        return "R$ 0,00"


def fmt_data(v):
    if not v:
        return '—'
    if isinstance(v, (datetime, date)):
        return v.strftime('%d/%m/%Y')
    s = str(v)
    try:
        return datetime.fromisoformat(s[:19]).strftime('%d/%m/%Y')
    except ValueError:
        return s[:10]


_UNI = ['zero', 'um', 'dois', 'três', 'quatro', 'cinco', 'seis', 'sete', 'oito', 'nove', 'dez', 'onze', 'doze',
        'treze', 'quatorze', 'quinze', 'dezesseis', 'dezessete', 'dezoito', 'dezenove']
_DEZ = ['', '', 'vinte', 'trinta', 'quarenta', 'cinquenta', 'sessenta', 'setenta', 'oitenta', 'noventa']
_CEN = ['', 'cento', 'duzentos', 'trezentos', 'quatrocentos', 'quinhentos', 'seiscentos', 'setecentos',
        'oitocentos', 'novecentos']


def _ate_mil(n):
    if n == 100:
        return 'cem'
    partes = []
    if n >= 100:
        partes.append(_CEN[n // 100]); n %= 100
    if n >= 20:
        partes.append(_DEZ[n // 10]); n %= 10
    if n:
        partes.append(_UNI[n])
    return ' e '.join(partes)


def _inteiro_extenso(n):
    if n == 0:
        return 'zero'
    grupos = [(1_000_000_000, 'bilhão', 'bilhões'), (1_000_000, 'milhão', 'milhões'), (1000, 'mil', 'mil')]
    partes, resto = [], n
    for base, sing, plur in grupos:
        q, resto = divmod(resto, base)
        if q:
            if base == 1000:
                partes.append('mil' if q == 1 else f'{_ate_mil(q)} mil')
            else:
                partes.append(f"{_ate_mil(q)} {sing if q == 1 else plur}")
    if resto:
        sep = ' e ' if partes and (resto < 100 or resto % 100 == 0) else ' '
        return (', '.join(partes) + sep + _ate_mil(resto)) if partes else _ate_mil(resto)
    return ', '.join(partes)


def valor_extenso(v):
    """1250.5 -> 'mil duzentos e cinquenta reais e cinquenta centavos'."""
    v = round(abs(float(v or 0)), 2)
    reais, cent = int(v), int(round((v - int(v)) * 100))
    txt = []
    if reais:
        r = _inteiro_extenso(reais)
        de = ' de' if reais % 1_000_000 == 0 else ''
        txt.append(f"{r}{de} {'real' if reais == 1 else 'reais'}")
    if cent:
        txt.append(f"{_ate_mil(cent)} {'centavo' if cent == 1 else 'centavos'}")
    return ' e '.join(txt) if txt else 'zero real'


app.jinja_env.filters['extenso'] = valor_extenso
app.jinja_env.filters['brl'] = fmt_brl
app.jinja_env.filters['data'] = fmt_data
app.jinja_env.globals['now'] = datetime.now
app.jinja_env.globals['enumerate'] = enumerate
app.jinja_env.globals['MESES'] = MESES
app.jinja_env.globals['CATEGORIAS_CONG'] = R.CATEGORIAS
app.jinja_env.globals['STATUS_FECH'] = STATUS_FECH
app.jinja_env.globals['PAPEIS'] = PAPEIS


@app.context_processor
def ctx():
    return {'papel': session.get('papel'), 'pode_editar': pode_editar()}


# ═════════════════════════════════════════════
#  LOGIN / LOGOUT
# ═════════════════════════════════════════════
def _agora_utc():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _bloqueado(conn, chave):
    limite = (_agora_utc() - timedelta(minutes=15)).strftime('%Y-%m-%d %H:%M:%S')
    n = conn.execute('SELECT COUNT(*) AS n FROM login_falhas WHERE chave=? AND quando > ?',
                     (chave, limite)).fetchone()['n']
    return n >= 5


@app.route('/login', methods=['GET', 'POST'])
def login():
    if session.get('user_id'):
        return redirect(url_for('inicio'))
    with get_db() as conn:
        sem_admin = not conn.execute("SELECT 1 FROM usuarios WHERE papel='admin' AND ativo=1").fetchone()
    if request.method == 'POST':
        usuario = request.form.get('usuario', '').strip().lower()
        senha = request.form.get('senha', '')
        chave = f"{usuario}|{request.headers.get('X-Forwarded-For', request.remote_addr or '').split(',')[0]}"
        with get_db() as conn:
            if _bloqueado(conn, chave):
                flash('Muitas tentativas. Aguarde 15 minutos e tente de novo.', 'danger')
                return render_template('login.html', sem_admin=sem_admin)
            u = conn.execute('SELECT * FROM usuarios WHERE usuario=? AND ativo=1', (usuario,)).fetchone()
            cong = None
            if u and u['cong_id']:
                cong = conn.execute('SELECT * FROM congregacoes WHERE id=?', (u['cong_id'],)).fetchone()
            if u and verificar_senha(u['senha_hash'], senha) and (not u['cong_id'] or (cong and cong['ativo'])):
                if not u['senha_hash'].startswith(('pbkdf2:', 'scrypt:')):
                    conn.execute('UPDATE usuarios SET senha_hash=? WHERE id=?', (generate_password_hash(senha), u['id']))
                conn.execute('DELETE FROM login_falhas WHERE chave=?', (chave,))
                session.clear()
                session.permanent = True
                session.update(user_id=u['id'], user_nome=u['nome'], usuario=u['usuario'], papel=u['papel'],
                               cong_id=u['cong_id'], cong_nome=cong['nome'] if cong else 'Tesouraria Nacional',
                               is_admin=u['papel'] == 'admin')
                nxt = request.args.get('next', '')
                if not nxt.startswith('/') or nxt.startswith('//'):
                    nxt = url_for('inicio')
                return redirect(nxt)
            conn.execute('INSERT INTO login_falhas (chave, quando) VALUES (?,?)',
                         (chave, _agora_utc().strftime('%Y-%m-%d %H:%M:%S')))
        flash('Usuário ou senha incorretos.', 'danger')
    return render_template('login.html', sem_admin=sem_admin)


@app.route('/logout')
def logout():
    session.clear()
    flash('Sessão encerrada.', 'info')
    return redirect(url_for('login'))


@app.route('/ver/<int:cid>')
@papel_required('admin', 'supervisor')
def ver_congregacao(cid):
    with get_db() as conn:
        c = conn.execute('SELECT * FROM congregacoes WHERE id=?', (cid,)).fetchone()
    if not c:
        abort(404)
    session['cong_id'] = c['id']
    session['cong_nome'] = c['nome']
    return redirect(url_for('dashboard'))


@app.route('/ver/nacional')
@papel_required('admin', 'supervisor')
def ver_nacional():
    session['cong_id'] = None
    session['cong_nome'] = 'Tesouraria Nacional'
    return redirect(url_for('nacional_envios'))


@app.context_processor
def ctx_congregacoes():
    if session.get('papel') in ('admin', 'supervisor'):
        try:
            with get_db() as conn:
                lista = conn.execute('SELECT id, nome FROM congregacoes WHERE ativo=1 ORDER BY nome').fetchall()
        except Exception:
            lista = []
        return {'lista_congregacoes': lista}
    return {'lista_congregacoes': []}


@app.route('/inicio')
@login_required
def inicio():
    if session.get('cong_id'):
        return redirect(url_for('dashboard'))
    return redirect(url_for('nacional_envios'))


# ═════════════════════════════════════════════
#  DASHBOARD
# ═════════════════════════════════════════════
@app.route('/')
@cong_required
def dashboard():
    """Página inicial: resumo do mês e caminhos guiados."""
    cfg = get_cfg()
    cid = get_cong_id()
    hoje = date.today()
    ano = int(request.args.get('ano', hoje.year))
    mes = int(request.args.get('mes', hoje.month))
    nome_mes = MESES[mes - 1]
    with get_db() as conn:
        def soma(where, params):
            return conn.execute('SELECT COALESCE(SUM(valor),0) AS t FROM transacoes WHERE cong_id=? AND ano=? '
                                'AND COALESCE(transferencia,0)=0 ' + where, (cid, ano, *params)).fetchone()['t']
        ent_mes = soma("AND mes=? AND tipo='Entrada'", (nome_mes,))
        sai_mes = soma("AND mes=? AND tipo='Saída'", (nome_mes,))
        diz_mes = conn.execute('SELECT COALESCE(SUM(dizimo_bruto),0) AS t FROM dizimos WHERE cong_id=? AND ano=? AND mes=?',
                               (cid, ano, nome_mes)).fetchone()['t']
        ent_ano = soma("AND tipo='Entrada'", ())
        sai_ano = soma("AND tipo='Saída'", ())
        orc = conn.execute("SELECT COALESCE(SUM(orcam_ano),0) AS t FROM orcamento WHERE cong_id=? AND ano=? AND tipo='Saída'",
                           (cid, ano)).fetchone()['t']
        n_mes = conn.execute('SELECT COUNT(*) AS n FROM transacoes WHERE cong_id=? AND ano=? AND mes=? AND origem IS NULL',
                             (cid, ano, nome_mes)).fetchone()['n']
        fech = conn.execute('SELECT * FROM fechamentos WHERE cong_id=? AND ano=? AND mes=?', (cid, ano, mes)).fetchone()
        livros = {}
        for lv in LIVROS:
            r = conn.execute('''SELECT SUM(CASE WHEN tipo='Entrada' THEN valor ELSE 0 END) AS e,
                                       SUM(CASE WHEN tipo='Saída' THEN valor ELSE 0 END) AS s
                                FROM transacoes WHERE cong_id=? AND ano=? AND mes=? AND livro=?''',
                             (cid, ano, nome_mes, lv)).fetchone()
            livros[lv] = {'e': r['e'] or 0, 's': r['s'] or 0}
        recentes = conn.execute('SELECT * FROM transacoes WHERE cong_id=? AND origem IS NULL ORDER BY id DESC LIMIT 6',
                                (cid,)).fetchall()
        comp = conn.execute('SELECT * FROM compromissos WHERE cong_id=? AND ano=?', (cid, ano)).fetchone()
        falta = cadastro_falta(conn, cid, ano, cfg)
    if comp and not comp['confirmado_em']:
        falta.append(f'a confirmação do pastor nas porcentagens de {ano}')
    saldo_ant = float(cfg.get('saldo_ano_anterior', 0) or 0)
    return render_template('inicio.html', falta=falta, comp=comp, cfg=cfg, ano=ano, mes=mes, nome_mes=nome_mes, anos=ANOS,
                           ent_mes=ent_mes, sai_mes=sai_mes, diz_mes=diz_mes, saldo=saldo_ant + ent_ano - sai_ano,
                           orc=orc, sai_ano=sai_ano, n_mes=n_mes, fech=fech, livros=livros, livros_labels=LIVROS_LABELS,
                           recentes=recentes)


@app.route('/visao-geral')
@cong_required
def visao_geral():
    cfg = get_cfg()
    cid = get_cong_id()
    ano = int(request.args.get('ano', cfg.get('ano_atual', datetime.now().year)))
    with get_db() as conn:
        base = 'FROM transacoes WHERE cong_id=? AND ano=? AND COALESCE(transferencia,0)=0'
        totais = conn.execute(f'SELECT tipo, COALESCE(SUM(valor),0) AS total {base} GROUP BY tipo', (cid, ano)).fetchall()
        total_e = sum(r['total'] for r in totais if r['tipo'] == 'Entrada')
        total_s = sum(r['total'] for r in totais if r['tipo'] == 'Saída')
        saldo_ant = float(cfg.get('saldo_ano_anterior', 0) or 0)
        saldo = saldo_ant + total_e - total_s
        por_livro = conn.execute(f'''SELECT livro,
                SUM(CASE WHEN tipo='Entrada' THEN valor ELSE 0 END) AS entradas,
                SUM(CASE WHEN tipo='Saída' THEN valor ELSE 0 END) AS saidas
                {base} GROUP BY livro''', (cid, ano)).fetchall()
        fluxo_mensal = []
        for mes in MESES:
            row = conn.execute(f'''SELECT SUM(CASE WHEN tipo='Entrada' THEN valor ELSE 0 END) AS e,
                   SUM(CASE WHEN tipo='Saída' THEN valor ELSE 0 END) AS s {base} AND mes=?''', (cid, ano, mes)).fetchone()
            fluxo_mensal.append({'mes': mes[:3].capitalize(), 'e': round(row['e'] or 0, 2), 's': round(row['s'] or 0, 2)})
        top_saidas = conn.execute(f'''SELECT item, SUM(valor) AS total {base} AND tipo='Saída'
                GROUP BY item ORDER BY total DESC LIMIT 7''', (cid, ano)).fetchall()
        recentes = conn.execute('SELECT * FROM transacoes WHERE cong_id=? AND ano=? ORDER BY id DESC LIMIT 10',
                                (cid, ano)).fetchall()
        pend = conn.execute('SELECT mes, status FROM fechamentos WHERE cong_id=? AND ano=?', (cid, ano)).fetchall()
    return render_template('dashboard.html',
        cfg=cfg, ano=ano, anos=ANOS, total_e=total_e, total_s=total_s, saldo=saldo, saldo_ant=saldo_ant,
        por_livro=por_livro, fluxo_mensal=json.dumps(fluxo_mensal),
        top_saidas=json.dumps([{'item': r['item'], 'total': round(r['total'], 2)} for r in top_saidas]),
        recentes=recentes, livros_labels=LIVROS_LABELS, fechamentos={p['mes']: p['status'] for p in pend})


# ═════════════════════════════════════════════
#  LANÇAMENTOS
# ═════════════════════════════════════════════
def _comprimir_imagem(dados):
    """Reduz fotos de comprovante para cerca de 150-300 KB (banco gratuito tem 1 GB)."""
    from PIL import Image, ImageOps
    im = Image.open(io.BytesIO(dados))
    im = ImageOps.exif_transpose(im).convert('RGB')
    im.thumbnail((1600, 1600))
    out = io.BytesIO()
    im.save(out, 'JPEG', quality=70, optimize=True)
    return out.getvalue()


def _ler_anexo(campo):
    f = request.files.get(campo)
    if not f or not f.filename:
        return None
    dados = f.read()
    tipo = f.mimetype or 'application/octet-stream'
    if tipo not in TIPOS_ANEXO:
        raise ValueError('Envie o comprovante em PDF, JPG ou PNG.')
    nome = os.path.basename(f.filename)[:120]
    if tipo.startswith('image/'):
        try:
            dados = _comprimir_imagem(dados)
        except Exception:
            raise ValueError('Não foi possível ler a imagem. Envie em JPG, PNG ou PDF.')
        tipo = 'image/jpeg'
        nome = os.path.splitext(nome)[0] + '.jpg'
    elif len(dados) > MAX_PDF:
        raise ValueError('O PDF passa de 2 MB. Envie uma foto do comprovante ou um PDF menor.')
    return {'nome': nome, 'tipo': tipo, 'dados': dados}


@app.route('/lancamentos', methods=['GET', 'POST'])
@cong_required
def lancamentos():
    cfg = get_cfg()
    cid = get_cong_id()
    ano_sel = int(request.args.get('ano', cfg.get('ano_atual', datetime.now().year)))
    mes_sel = request.args.get('mes', '')
    livro_sel = request.args.get('livro', '')

    if request.method == 'POST':
        if not pode_editar():
            abort(403)
        try:
            livro, tipo, item = request.form['livro'], request.form['tipo'], request.form['item']
            if livro not in CATEGORIAS or tipo not in ('Entrada', 'Saída') or item not in CATEGORIAS[livro][tipo]:
                raise ValueError('Escolha o livro, o tipo e o item da lista.')
            valor = parse_valor(request.form['valor'])
            mes, ano = request.form['mes'], int(request.form['ano'])
            if mes not in MESES:
                raise ValueError('Mês inválido.')
            anexo = _ler_anexo('anexo')
        except (ValueError, KeyError) as e:
            flash(str(e) if str(e) else 'Confira os campos do lançamento.', 'danger')
            return redirect(url_for('lancamentos', ano=ano_sel, mes=mes_sel))
        bloqueio = exigir_cadastro(ano)
        if bloqueio:
            return bloqueio
        with get_db() as conn:
            if mes_travado(conn, cid, ano, mes):
                flash(f'{mes.capitalize()}/{ano} já foi fechado. Peça ao pastor para reabrir o mês.', 'danger')
                return redirect(url_for('lancamentos', ano=ano, mes=mes))
            tid = conn.insert('''INSERT INTO transacoes (cong_id,livro,tipo,item,valor,mes,ano,data_registro,obs,forma,usuario_id,pessoa)
                                 VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',
                              (cid, livro, tipo, item, valor, mes, ano,
                               request.form.get('data_registro', datetime.now().strftime('%d/%m/%Y')),
                               request.form.get('obs', '')[:300], request.form.get('forma') if request.form.get('forma') in FORMAS else None,
                               session['user_id'], request.form.get('pessoa', '').strip()[:120] or None))
            if anexo:
                conn.execute('INSERT INTO anexos (transacao_id, nome, tipo, dados) VALUES (?,?,?,?)',
                             (tid, anexo['nome'], anexo['tipo'], anexo['dados']))
        msg = f'{tipo} de {fmt_brl(valor)} registrada: {item}.'
        if tipo == 'Saída' and not anexo:
            msg += ' Falta anexar o comprovante da despesa (§ 95).'
            flash(msg, 'warning')
        else:
            flash(msg, 'success')
        if request.form.get('voltar') == 'lancar':
            return redirect(url_for('lancar', tipo=tipo, ultimo=tid))
        return redirect(url_for('lancamentos', ano=ano, mes=mes))

    with get_db() as conn:
        q = '''SELECT t.*, (SELECT COUNT(*) FROM anexos a WHERE a.transacao_id=t.id) AS n_anexos
               FROM transacoes t WHERE t.cong_id=? AND t.ano=?'''
        p = [cid, ano_sel]
        if mes_sel:
            q += ' AND t.mes=?'
            p.append(mes_sel)
        if livro_sel in LIVROS:
            q += ' AND t.livro=?'
            p.append(livro_sel)
        q += ' ORDER BY t.id DESC'
        lista = conn.execute(q, p).fetchall()
        travados = {MESES[f['mes'] - 1] for f in
                    conn.execute('SELECT mes FROM fechamentos WHERE cong_id=? AND ano=?', (cid, ano_sel)).fetchall()}
    vis = [t for t in lista if not t.get('transferencia')]
    total_e = sum(t['valor'] for t in vis if t['tipo'] == 'Entrada')
    total_s = sum(t['valor'] for t in vis if t['tipo'] == 'Saída')
    return render_template('lancamentos.html',
        cfg=cfg, categorias=CATEGORIAS, meses=MESES, anos=ANOS, livros=LIVROS, formas=FORMAS,
        livros_labels=LIVROS_LABELS, transacoes=lista, travados=travados,
        ano_sel=ano_sel, mes_sel=mes_sel, livro_sel=livro_sel, total_e=total_e, total_s=total_s)


GRUPOS_LANCAR = {
    'Entrada': [('FundoLocal', 'Caixa local', 'Ofertas dos cultos, votos, ofertas especiais'),
                ('Projetos', 'Projetos', 'Cantina, brechó, vendas, votos para construção'),
                ('Envios', 'Envios (vão para a nacional)', 'Ofertas missionárias, Raios de Luz, Safras, distritais')],
    'Saída': [('FundoLocal', 'Caixa local', 'Aluguel, água e luz, manutenção, materiais, evangelismo'),
              ('Projetos', 'Projetos', 'Compras e gastos dos projetos e da construção')],
}


@app.route('/lancar')
@cong_required
def lancar():
    if not pode_editar():
        flash('Somente o tesoureiro registra lançamentos.', 'info')
        return redirect(url_for('lancamentos'))
    hoje = date.today()
    bloqueio = exigir_cadastro(hoje.year)
    if bloqueio:
        return bloqueio
    tipo = request.args.get('tipo', '')
    if tipo not in ('Entrada', 'Saída'):
        tipo = ''
    grupos = []
    for livro, rotulo, ajuda in GRUPOS_LANCAR.get(tipo, []):
        grupos.append({'livro': livro, 'rotulo': rotulo, 'ajuda': ajuda, 'itens': CATEGORIAS[livro][tipo]})
    ultimo = None
    if request.args.get('ultimo', '').isdigit():
        with get_db() as conn:
            ultimo = conn.execute('SELECT * FROM transacoes WHERE id=? AND cong_id=?',
                                  (int(request.args['ultimo']), get_cong_id())).fetchone()
    return render_template('lancar.html', cfg=get_cfg(), tipo=tipo, grupos=grupos, meses=MESES, anos=ANOS, formas=FORMAS,
                           ultimo=ultimo,
                           mes_atual=MESES[hoje.month - 1], ano_atual=hoje.year,
                           livro=request.args.get('livro', ''), item=request.args.get('item', ''))


@app.route('/livro-do-mes')
@cong_required
def livro_do_mes():
    """Livro caixa para imprimir: do mês ou do ano, de todos os livros ou de um só."""
    cfg = get_cfg()
    cid = get_cong_id()
    hoje = date.today()
    ano = int(request.args.get('ano', hoje.year))
    anual = request.args.get('periodo') == 'ano'
    mes = 12 if anual else int(request.args.get('mes', hoje.month))
    if not 1 <= mes <= 12:
        abort(400)
    nome_mes = MESES[mes - 1]
    meses_mov = MESES if anual else [nome_mes]
    anteriores = [] if anual else MESES[:mes - 1]
    so_livro = request.args.get('livro', '')
    livros = [so_livro] if so_livro in LIVROS else LIVROS
    saldo_ano_ant = float(cfg.get('saldo_ano_anterior', 0) or 0)

    def ordem(t):
        try:
            d = datetime.strptime(t['data_registro'] or '', '%d/%m/%Y')
        except ValueError:
            d = datetime(ano, R.mes_num(t['mes']), 28)
        return (R.mes_num(t['mes']), d, t['id'])

    blocos = []
    with get_db() as conn:
        for lv in livros:
            ant = 0.0
            if anteriores:
                marcas = ','.join('?' * len(anteriores))
                r = conn.execute(f'''SELECT SUM(CASE WHEN tipo='Entrada' THEN valor ELSE -valor END) AS t
                                     FROM transacoes WHERE cong_id=? AND ano=? AND livro=? AND mes IN ({marcas})''',
                                 (cid, ano, lv, *anteriores)).fetchone()
                ant = r['t'] or 0.0
            if lv == 'FundoLocal':
                ant += saldo_ano_ant
            marcas = ','.join('?' * len(meses_mov))
            movs = sorted(conn.execute(f'SELECT * FROM transacoes WHERE cong_id=? AND ano=? AND livro=? AND mes IN ({marcas})',
                                       (cid, ano, lv, *meses_mov)).fetchall(), key=ordem)
            linhas, saldo, te, ts = [], ant, 0.0, 0.0
            for t in movs:
                if t['tipo'] == 'Entrada':
                    saldo += t['valor']; te += t['valor']
                else:
                    saldo -= t['valor']; ts += t['valor']
                linhas.append({'t': t, 'saldo': saldo})
            blocos.append({'livro': lv, 'rotulo': LIVRO_NOME[lv], 'anterior': ant, 'linhas': linhas,
                           'entradas': te, 'saidas': ts, 'final': saldo})
        marcas = ','.join('?' * len(meses_mov))
        dizimos_mes = [] if so_livro else sorted(conn.execute(
            f'SELECT * FROM dizimos WHERE cong_id=? AND ano=? AND mes IN ({marcas})', (cid, ano, *meses_mov)).fetchall(),
            key=lambda d: (R.mes_num(d['mes']), d['id']))
        fech = None if anual else conn.execute('SELECT * FROM fechamentos WHERE cong_id=? AND ano=? AND mes=?',
                                               (cid, ano, mes)).fetchone()
        cong = conn.execute('SELECT * FROM congregacoes WHERE id=?', (cid,)).fetchone()
    titulo = ('LIVRO CAIXA DO ANO' if anual else 'LIVRO CAIXA DO MÊS') if not so_livro else \
             f"LIVRO {LIVRO_NOME[so_livro].upper()} — {'ANO' if anual else 'MÊS'}"
    periodo_txt = f'Ano de {ano}' if anual else f'{nome_mes.capitalize()} de {ano}'
    return render_template('livro_do_mes.html', cfg=cfg, cong=cong, ano=ano, mes=mes, nome_mes=nome_mes, blocos=blocos,
                           dizimos_mes=dizimos_mes, fech=fech, anual=anual, titulo=titulo, periodo_txt=periodo_txt,
                           total_e=sum(b['entradas'] for b in blocos), total_s=sum(b['saidas'] for b in blocos),
                           total_ant=sum(b['anterior'] for b in blocos), total_final=sum(b['final'] for b in blocos))


# ═════════════════════════════════════════════
#  RECIBOS
# ═════════════════════════════════════════════
@app.route('/recibo/<tipo>/<int:rid>')
@cong_required
def recibo(tipo, rid):
    """Recibo em duas vias para imprimir (lançamento ou dízimo)."""
    cid = get_cong_id()
    with get_db() as conn:
        if tipo == 'lancamento':
            r = conn.execute('SELECT * FROM transacoes WHERE id=? AND cong_id=?', (rid, cid)).fetchone()
            if not r or r['origem']:
                abort(404)
            entrada = r['tipo'] == 'Entrada'
            dados = {'numero': f"L-{rid:05d}", 'valor': r['valor'], 'data': r['data_registro'] or '',
                     'entrada': entrada, 'pessoa': r['pessoa'] or '', 'forma': r['forma'] or '',
                     'referente': f"{r['item']} ({LIVRO_NOME.get(r['livro'], r['livro'])}) — {r['mes']}/{r['ano']}",
                     'obs': r['obs'] or ''}
        elif tipo == 'dizimo':
            r = conn.execute('SELECT * FROM dizimos WHERE id=? AND cong_id=?', (rid, cid)).fetchone()
            if not r:
                abort(404)
            dados = {'numero': f"D-{rid:05d}", 'valor': r['dizimo_bruto'], 'data': r['data_registro'] or '',
                     'entrada': True, 'pessoa': '', 'forma': '', 'referente': f"Dízimos — {r['mes']}/{r['ano']}",
                     'obs': r['obs'] or ''}
        else:
            abort(404)
        cong = conn.execute('SELECT * FROM congregacoes WHERE id=?', (cid,)).fetchone()
    return render_template('recibo.html', cfg=get_cfg(), cong=cong, r=dados)


# ═════════════════════════════════════════════
#  IMPRIMIR (central de impressão) E BALANÇO
# ═════════════════════════════════════════════
@app.route('/imprimir')
@cong_required
def imprimir():
    cid = get_cong_id()
    hoje = date.today()
    ano = int(request.args.get('ano', hoje.year))
    mes = int(request.args.get('mes', hoje.month))
    with get_db() as conn:
        fechs = conn.execute('SELECT * FROM fechamentos WHERE cong_id=? AND ano=? ORDER BY mes', (cid, ano)).fetchall()
        recentes = conn.execute('SELECT * FROM transacoes WHERE cong_id=? AND origem IS NULL ORDER BY id DESC LIMIT 10',
                                (cid,)).fetchall()
    return render_template('imprimir.html', cfg=get_cfg(), ano=ano, mes=mes, anos=ANOS, fechs=fechs, recentes=recentes,
                           livros=LIVROS, livro_nome=LIVRO_NOME)


@app.route('/balanco')
@cong_required
def balanco():
    """Balanço do ano (ou de um mês) com gráficos: por livro, por item, mês a mês e orçado x realizado."""
    cfg = get_cfg()
    cid = get_cong_id()
    hoje = date.today()
    ano = int(request.args.get('ano', hoje.year))
    mes = int(request.args.get('mes', 0) or 0)
    meses_sel = [MESES[mes - 1]] if 1 <= mes <= 12 else MESES
    anteriores = MESES[:mes - 1] if 1 <= mes <= 12 else []
    saldo_ano_ant = float(cfg.get('saldo_ano_anterior', 0) or 0)
    mk = ','.join('?' * len(meses_sel))
    real = 'COALESCE(transferencia,0)=0'
    with get_db() as conn:
        livros = []
        for lv in LIVROS:
            ant = saldo_ano_ant if lv == 'FundoLocal' else 0.0
            if anteriores:
                ma = ','.join('?' * len(anteriores))
                ant += conn.execute(f'''SELECT COALESCE(SUM(CASE WHEN tipo='Entrada' THEN valor ELSE -valor END),0) AS t
                                       FROM transacoes WHERE cong_id=? AND ano=? AND livro=? AND mes IN ({ma})''',
                                    (cid, ano, lv, *anteriores)).fetchone()['t']
            r = conn.execute(f'''SELECT COALESCE(SUM(CASE WHEN tipo='Entrada' THEN valor ELSE 0 END),0) AS e,
                                       COALESCE(SUM(CASE WHEN tipo='Saída' THEN valor ELSE 0 END),0) AS s
                                FROM transacoes WHERE cong_id=? AND ano=? AND livro=? AND mes IN ({mk})''',
                             (cid, ano, lv, *meses_sel)).fetchone()
            livros.append({'livro': lv, 'nome': LIVRO_NOME[lv], 'anterior': ant, 'e': r['e'], 's': r['s'],
                           'final': ant + r['e'] - r['s']})

        def por_item(tipo):
            return [dict(x) for x in conn.execute(
                f'''SELECT livro, item, SUM(valor) AS t FROM transacoes WHERE cong_id=? AND ano=? AND tipo=? AND {real}
                    AND mes IN ({mk}) GROUP BY livro, item ORDER BY t DESC''', (cid, ano, tipo, *meses_sel)).fetchall()]
        entradas, saidas = por_item('Entrada'), por_item('Saída')
        diz = conn.execute(f'''SELECT COALESCE(SUM(dizimo_bruto),0) AS bruto, COALESCE(SUM(valor_nacional),0) AS nac,
                                 COALESCE(SUM(valor_fundo_local),0) AS fl, COALESCE(SUM(valor_liquido),0) AS liq
                              FROM dizimos WHERE cong_id=? AND ano=? AND mes IN ({mk})''', (cid, ano, *meses_sel)).fetchone()
        mensal, acum = [], saldo_ano_ant
        for m in MESES:
            r = conn.execute(f'''SELECT COALESCE(SUM(CASE WHEN tipo='Entrada' THEN valor ELSE 0 END),0) AS e,
                                       COALESCE(SUM(CASE WHEN tipo='Saída' THEN valor ELSE 0 END),0) AS s
                                FROM transacoes WHERE cong_id=? AND ano=? AND mes=? AND {real}''', (cid, ano, m)).fetchone()
            d = conn.execute('SELECT COALESCE(SUM(dizimo_bruto),0) AS t FROM dizimos WHERE cong_id=? AND ano=? AND mes=?',
                             (cid, ano, m)).fetchone()['t']
            acum += r['e'] - r['s']
            mensal.append({'mes': m[:3].capitalize(), 'e': round(r['e'], 2), 's': round(r['s'], 2),
                           'd': round(d, 2), 'saldo': round(acum, 2)})
        orc = {(o['item'], o['tipo']): o['orcam_ano'] for o in
               conn.execute('SELECT item, tipo, orcam_ano FROM orcamento WHERE cong_id=? AND ano=?', (cid, ano)).fetchall()}
        cong = conn.execute('SELECT * FROM congregacoes WHERE id=?', (cid,)).fetchone()
    tot_e = sum(x['t'] for x in entradas)
    tot_s = sum(x['t'] for x in saidas)
    orc_vs = []
    for tipo, lista in (('Entrada', entradas), ('Saída', saidas)):
        reais = {}
        for x in lista:
            reais[x['item']] = reais.get(x['item'], 0) + x['t']
        for (item, t), v in orc.items():
            if t == tipo and v:
                reais.setdefault(item, 0)
        for item, v in reais.items():
            o = orc.get((item, tipo), 0) or 0
            if o:
                orc_vs.append({'tipo': tipo, 'item': item, 'orcado': o, 'real': v})
    return render_template('balanco.html', cfg=cfg, cong=cong, ano=ano, mes=mes, anos=ANOS, livros=livros,
                           entradas=entradas, saidas=saidas, tot_e=tot_e, tot_s=tot_s, diz=diz,
                           mensal=mensal, mensal_json=json.dumps(mensal), orc_vs=orc_vs, livro_nome=LIVRO_NOME,
                           periodo_txt=(f'{MESES[mes - 1].capitalize()} de {ano}' if mes else f'Ano de {ano}'))


@app.route('/lancamentos/<int:tid>/editar', methods=['GET', 'POST'])
@cong_required
def editar_lancamento(tid):
    cfg = get_cfg()
    cid = get_cong_id()
    with get_db() as conn:
        t = conn.execute('SELECT * FROM transacoes WHERE id=? AND cong_id=?', (tid, cid)).fetchone()
        if not t or t.get('origem'):
            flash('Este lançamento não pode ser editado aqui.', 'danger')
            return redirect(url_for('lancamentos'))
        if request.method == 'POST':
            if not pode_editar():
                abort(403)
            try:
                livro, tipo, item = request.form['livro'], request.form['tipo'], request.form['item']
                if livro not in CATEGORIAS or tipo not in ('Entrada', 'Saída') or item not in CATEGORIAS[livro][tipo]:
                    raise ValueError('Escolha o livro, o tipo e o item da lista.')
                valor = parse_valor(request.form['valor'])
                mes, ano = request.form['mes'], int(request.form['ano'])
                if mes not in MESES:
                    raise ValueError('Mês inválido.')
            except (ValueError, KeyError) as e:
                flash(str(e) or 'Confira os campos.', 'danger')
                return redirect(url_for('editar_lancamento', tid=tid))
            if mes_travado(conn, cid, t['ano'], t['mes']) or mes_travado(conn, cid, ano, mes):
                flash('O mês está fechado. Peça ao pastor para reabrir antes de corrigir.', 'danger')
                return redirect(url_for('lancamentos', ano=t['ano']))
            novo = dict(livro=livro, tipo=tipo, item=item, valor=valor, mes=mes, ano=ano,
                        data_registro=request.form.get('data_registro', ''), obs=request.form.get('obs', '')[:300],
                        pessoa=request.form.get('pessoa', '').strip()[:120] or None)
            conn.execute('''UPDATE transacoes SET livro=?,tipo=?,item=?,valor=?,mes=?,ano=?,data_registro=?,obs=?,pessoa=?
                            WHERE id=? AND cong_id=?''', (*novo.values(), tid, cid))
            auditar(conn, 'lancamento.editar', f'Lançamento #{tid}', antes=dict(t), depois=novo)
            flash('Lançamento atualizado. A alteração ficou registrada no histórico.', 'success')
            return redirect(url_for('lancamentos', ano=ano))
    return render_template('editar_lancamento.html', cfg=cfg, t=t, categorias=CATEGORIAS, meses=MESES,
                           anos=ANOS, livros=LIVROS, livros_labels=LIVROS_LABELS)


@app.route('/lancamentos/<int:tid>/deletar', methods=['POST'])
@papel_required('tesoureiro')
def deletar_lancamento(tid):
    cid = get_cong_id()
    with get_db() as conn:
        t = conn.execute('SELECT * FROM transacoes WHERE id=? AND cong_id=?', (tid, cid)).fetchone()
        if not t:
            abort(404)
        if t.get('origem'):
            flash('Lançamentos gerados pelo fechamento só saem reabrindo o mês.', 'danger')
        elif mes_travado(conn, cid, t['ano'], t['mes']):
            flash('O mês está fechado. Peça ao pastor para reabrir antes de excluir.', 'danger')
        else:
            conn.execute('DELETE FROM anexos WHERE transacao_id=?', (tid,))
            conn.execute('DELETE FROM transacoes WHERE id=? AND cong_id=?', (tid, cid))
            auditar(conn, 'lancamento.excluir', f'Lançamento #{tid}', antes=dict(t))
            flash('Lançamento excluído. A exclusão ficou registrada no histórico.', 'warning')
    return redirect(url_for('lancamentos', ano=t['ano']))


@app.route('/lancamentos/<int:tid>/anexo', methods=['GET', 'POST'])
@cong_required
def anexo_lancamento(tid):
    cid = get_cong_id()
    with get_db() as conn:
        t = conn.execute('SELECT * FROM transacoes WHERE id=? AND cong_id=?', (tid, cid)).fetchone()
        if not t:
            abort(404)
        if request.method == 'POST':
            if not pode_editar():
                abort(403)
            try:
                anexo = _ler_anexo('anexo')
                if not anexo:
                    raise ValueError('Escolha um arquivo.')
            except ValueError as e:
                flash(str(e), 'danger')
                return redirect(url_for('lancamentos', ano=t['ano'], mes=t['mes']))
            conn.execute('INSERT INTO anexos (transacao_id, nome, tipo, dados) VALUES (?,?,?,?)',
                         (tid, anexo['nome'], anexo['tipo'], anexo['dados']))
            flash('Comprovante anexado.', 'success')
            return redirect(url_for('lancamentos', ano=t['ano'], mes=t['mes']))
        a = conn.execute('SELECT * FROM anexos WHERE transacao_id=? ORDER BY id DESC', (tid,)).fetchone()
    if not a:
        abort(404)
    return send_file(io.BytesIO(db.blob(a['dados'])), mimetype=a['tipo'], download_name=a['nome'] or 'comprovante')


# ═════════════════════════════════════════════
#  DÍZIMOS
# ═════════════════════════════════════════════
def compromisso_de(conn, cid, ano):
    c = conn.execute('SELECT * FROM compromissos WHERE cong_id=? AND ano=?', (cid, ano)).fetchone()
    if not c:
        return None
    return {'categoria': c['categoria'], 'nivelacao': bool(c['nivelacao']),
            'fundo_local_pct': int(c['fundo_local_pct']), 'betel': bool(c['betel']),
            'confirmado': bool(c['confirmado_em']), 'id': c['id']}


@app.route('/dizimos', methods=['GET', 'POST'])
@cong_required
def dizimos():
    cfg = get_cfg()
    cid = get_cong_id()
    ano_sel = int(request.args.get('ano', cfg.get('ano_atual', datetime.now().year)))
    if request.method == 'POST':
        if not pode_editar():
            abort(403)
        try:
            bruto = parse_valor(request.form['dizimo_bruto'])
            mes, ano = request.form['mes'], int(request.form['ano'])
            if mes not in MESES or bruto <= 0:
                raise ValueError
        except (ValueError, KeyError):
            flash('Informe o valor e o mês do dízimo.', 'danger')
            return redirect(url_for('dizimos', ano=ano_sel))
        bloqueio = exigir_cadastro(ano)
        if bloqueio:
            return bloqueio
        with get_db() as conn:
            if mes_travado(conn, cid, ano, mes):
                flash(f'{mes.capitalize()}/{ano} já foi fechado. Peça ao pastor para reabrir o mês.', 'danger')
                return redirect(url_for('dizimos', ano=ano))
            comp = compromisso_de(conn, cid, ano) or {'categoria': 'nova', 'nivelacao': False, 'fundo_local_pct': 0, 'betel': False}
            reg = regras_em(conn, f'{ano}-{R.mes_num(mes):02d}-01')
            liq = R.liquidar_dizimo(bruto, comp, reg)
            conn.insert('''INSERT INTO dizimos (cong_id,dizimo_bruto,pct_nacional,pct_fundo_local,valor_nacional,
                           valor_fundo_local,valor_liquido,mes,ano,data_registro,obs,usuario_id)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',
                        (cid, bruto, reg['pct_dizimo_dizimos'] + (reg['pct_nivelacao'] if comp['nivelacao'] else 0),
                         comp['fundo_local_pct'] / 100, liq['dd'] + liq['niv'] + liq['betel'], liq['fundo_local'],
                         liq['liquido'], mes, ano, request.form.get('data_registro', datetime.now().strftime('%d/%m/%Y')),
                         request.form.get('obs', '')[:300], session['user_id']))
        flash(f'Dízimo de {fmt_brl(bruto)} registrado em {mes}.', 'success')
        return redirect(url_for('dizimos', ano=ano))

    if pode_editar():
        bloqueio = exigir_cadastro(ano_sel)
        if bloqueio:
            return bloqueio
    with get_db() as conn:
        historico = conn.execute(f'SELECT * FROM dizimos WHERE cong_id=? AND ano=? ORDER BY {MES_ORDEM}, id',
                                 (cid, ano_sel)).fetchall()
        comp = compromisso_de(conn, cid, ano_sel)
        reg = regras_em(conn, f'{ano_sel}-12-31')
    return render_template('dizimos.html', cfg=cfg, meses=MESES, anos=ANOS, ano_sel=ano_sel,
                           historico=historico, comp=comp, reg=reg)


@app.route('/dizimos/<int:did>/deletar', methods=['POST'])
@papel_required('tesoureiro')
def deletar_dizimo(did):
    cid = get_cong_id()
    with get_db() as conn:
        d = conn.execute('SELECT * FROM dizimos WHERE id=? AND cong_id=?', (did, cid)).fetchone()
        if not d:
            abort(404)
        if mes_travado(conn, cid, d['ano'], d['mes']):
            flash('O mês está fechado. Peça ao pastor para reabrir antes de excluir.', 'danger')
        else:
            conn.execute('DELETE FROM dizimos WHERE id=? AND cong_id=?', (did, cid))
            auditar(conn, 'dizimo.excluir', f'Dízimo #{did}', antes=dict(d))
            flash('Registro excluído. A exclusão ficou registrada no histórico.', 'warning')
    return redirect(url_for('dizimos', ano=d['ano']))


# ═════════════════════════════════════════════
#  FECHAMENTO DO MÊS
# ═════════════════════════════════════════════
def calcular_mes(conn, cid, ano, mes):
    nome = MESES[mes - 1]
    bruto = conn.execute('SELECT COALESCE(SUM(dizimo_bruto),0) AS t FROM dizimos WHERE cong_id=? AND ano=? AND mes=?',
                         (cid, ano, nome)).fetchone()['t']
    envios = {r['item']: r['t'] for r in conn.execute(
        '''SELECT item, SUM(valor) AS t FROM transacoes WHERE cong_id=? AND ano=? AND mes=? AND livro='Envios'
           AND tipo='Entrada' AND origem IS NULL GROUP BY item''', (cid, ano, nome)).fetchall()}
    comp = compromisso_de(conn, cid, ano)
    reg = regras_em(conn, f'{ano}-{mes:02d}-01')
    if not comp:
        return None, reg
    return R.fechar_mes(float(bruto), comp, envios, reg), reg


def _lancar_fechamento(conn, cid, f_id, ano, mes, calc):
    """Gera os lançamentos de saída do mês fechado (envios, fundo local, sustento)."""
    nome = MESES[mes - 1]
    origem = f'fechamento:{f_id}'
    liq = calc['liquidacao']
    hoje = datetime.now().strftime('%d/%m/%Y')
    linhas = []
    if liq['bruto']:
        linhas.append(('LiqDízimos', 'Entrada', 'Dízimo bruto do mês', liq['bruto'], 0))
    for chave, rotulo in (('dd', 'Envio Dízimo dos Dízimos 10%'), ('niv', 'Envio Nivelação 5%'), ('betel', 'Envio Betel 4%')):
        if liq[chave]:
            linhas.append(('LiqDízimos', 'Saída', rotulo, liq[chave], 0))
    if liq['fundo_local']:
        linhas.append(('LiqDízimos', 'Saída', 'Aporte ao fundo local', liq['fundo_local'], 1))
        linhas.append(('FundoLocal', 'Entrada', 'Aporte da liquidação de dízimos', liq['fundo_local'], 1))
    if liq['liquido']:
        linhas.append(('LiqDízimos', 'Saída', 'Sustento pastoral (§ 66)', liq['liquido'], 0))
    for l in calc['nacional'] + calc['distrital']:
        if l['chave'] in ('dd', 'nivelacao', 'betel') or not l['valor']:
            continue
        linhas.append(('Envios', 'Saída', 'Envio: ' + l['rotulo'], l['valor'], 0))
    for livro, tipo, item, valor, transf in linhas:
        conn.execute('''INSERT INTO transacoes (cong_id,livro,tipo,item,valor,mes,ano,data_registro,obs,origem,transferencia,usuario_id)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',
                     (cid, livro, tipo, item, valor, nome, ano, hoje, 'Gerado pelo fechamento do mês',
                      origem, transf, session.get('user_id')))


@app.route('/fechamento')
@cong_required
def fechamento():
    cfg = get_cfg()
    cid = get_cong_id()
    hoje = date.today()
    ano = int(request.args.get('ano', cfg.get('ano_atual', hoje.year)))
    padrao_mes = hoje.month - 1 if hoje.month > 1 else 12
    mes = int(request.args.get('mes', padrao_mes))
    if not 1 <= mes <= 12:
        abort(400)
    with get_db() as conn:
        f = conn.execute('SELECT * FROM fechamentos WHERE cong_id=? AND ano=? AND mes=?', (cid, ano, mes)).fetchone()
        if f:
            calc = json.loads(f['calculo'])
            reg = regras_em(conn, f'{ano}-{mes:02d}-01')
        else:
            calc, reg = calcular_mes(conn, cid, ano, mes)
        comp = compromisso_de(conn, cid, ano)
        status_ano = {r['mes']: r['status'] for r in
                      conn.execute('SELECT mes, status FROM fechamentos WHERE cong_id=? AND ano=?', (cid, ano)).fetchall()}
    limite = R.prazo_envio(ano, mes, int(reg.get('prazo_dia', 5)))
    return render_template('fechamento.html', cfg=cfg, ano=ano, mes=mes, anos=ANOS, f=f, calc=calc, comp=comp,
                           limite=limite, status_ano=status_ano, nacional=config_nacional())


@app.route('/fechamento/fechar', methods=['POST'])
@papel_required('tesoureiro')
def fechamento_fechar():
    cid = get_cong_id()
    ano, mes = int(request.form['ano']), int(request.form['mes'])
    with get_db() as conn:
        if conn.execute('SELECT 1 FROM fechamentos WHERE cong_id=? AND ano=? AND mes=?', (cid, ano, mes)).fetchone():
            flash('Este mês já está fechado.', 'warning')
            return redirect(url_for('fechamento', ano=ano, mes=mes))
        calc, _ = calcular_mes(conn, cid, ano, mes)
        if not calc:
            flash(f'A carta anual de {ano} ainda não foi emitida pela Tesouraria Nacional. Sem ela não há percentuais para fechar o mês.', 'danger')
            return redirect(url_for('fechamento', ano=ano, mes=mes))
        fid = conn.insert('INSERT INTO fechamentos (cong_id, ano, mes, status, calculo, total, fechado_por) VALUES (?,?,?,?,?,?,?)',
                          (cid, ano, mes, 'fechado', json.dumps(calc, ensure_ascii=False), calc['total'], session['user_id']))
        auditar(conn, 'fechamento.fechar', f'{MESES[mes - 1]}/{ano}', depois={'total': calc['total']})
    flash('Mês fechado. Agora o pastor precisa aprovar o relatório.', 'success')
    return redirect(url_for('fechamento', ano=ano, mes=mes))


@app.route('/fechamento/<int:fid>/aprovar', methods=['POST'])
@papel_required('pastor')
def fechamento_aprovar(fid):
    cid = get_cong_id()
    with get_db() as conn:
        f = conn.execute('SELECT * FROM fechamentos WHERE id=? AND cong_id=?', (fid, cid)).fetchone()
        if not f or f['status'] != 'fechado':
            abort(400)
        conn.execute("UPDATE fechamentos SET status='aprovado', aprovado_por=?, aprovado_em=CURRENT_TIMESTAMP WHERE id=?",
                     (session['user_id'], fid))
        auditar(conn, 'fechamento.aprovar', f"{MESES[f['mes'] - 1]}/{f['ano']}")
    flash('Relatório aprovado. O tesoureiro já pode depositar e anexar o comprovante.', 'success')
    return redirect(url_for('fechamento', ano=f['ano'], mes=f['mes']))


@app.route('/fechamento/<int:fid>/comprovante', methods=['POST'])
@papel_required('tesoureiro')
def fechamento_comprovante(fid):
    cid = get_cong_id()
    with get_db() as conn:
        f = conn.execute('SELECT * FROM fechamentos WHERE id=? AND cong_id=?', (fid, cid)).fetchone()
        if not f or f['status'] != 'aprovado':
            abort(400)
        try:
            valor = parse_valor(request.form['valor'])
            data_dep = date.fromisoformat(request.form['data'])
            anexo = _ler_anexo('arquivo')
            if not anexo:
                raise ValueError('Anexe o comprovante do banco.')
        except (ValueError, KeyError) as e:
            flash(str(e) or 'Informe o valor, a data e o arquivo do comprovante.', 'danger')
            return redirect(url_for('fechamento', ano=f['ano'], mes=f['mes']))
        if abs(valor - f['total']) >= 0.005:
            flash(f"O comprovante ({fmt_brl(valor)}) não confere com o relatório ({fmt_brl(f['total'])}). "
                  f"Diferença de {fmt_brl(valor - f['total'])}. Corrija o depósito ou peça ao pastor para reabrir o mês.", 'danger')
            return redirect(url_for('fechamento', ano=f['ano'], mes=f['mes']))
        conn.execute('''UPDATE fechamentos SET status='enviado', comprovante_valor=?, comprovante_data=?,
                        comprovante_arquivo=?, comprovante_nome=?, comprovante_tipo=?, enviado_por=?,
                        enviado_em=CURRENT_TIMESTAMP WHERE id=?''',
                     (valor, data_dep.isoformat(), anexo['dados'], anexo['nome'], anexo['tipo'], session['user_id'], fid))
        _lancar_fechamento(conn, cid, fid, f['ano'], f['mes'], json.loads(f['calculo']))
        auditar(conn, 'fechamento.comprovante', f"{MESES[f['mes'] - 1]}/{f['ano']}", depois={'valor': valor, 'data': data_dep})
        reg = regras_em(conn)
    limite = R.prazo_envio(f['ano'], f['mes'], int(reg.get('prazo_dia', 5)))
    if data_dep > limite:
        flash(f'Comprovante confere e o mês está travado. Atenção: o depósito saiu depois do prazo de {limite:%d/%m} (§ 80).', 'warning')
    else:
        flash('Comprovante confere. O mês está travado e o envio foi registrado.', 'success')
    return redirect(url_for('fechamento', ano=f['ano'], mes=f['mes']))


@app.route('/fechamento/<int:fid>/reabrir', methods=['POST'])
@papel_required('pastor')
def fechamento_reabrir(fid):
    cid = get_cong_id()
    motivo = request.form.get('motivo', '').strip()
    with get_db() as conn:
        f = conn.execute('SELECT * FROM fechamentos WHERE id=? AND cong_id=?', (fid, cid)).fetchone()
        if not f:
            abort(404)
        if f['status'] == 'recebido':
            flash('A nacional já confirmou o recebimento deste mês. Para corrigir, fale com a Tesouraria Nacional.', 'danger')
            return redirect(url_for('fechamento', ano=f['ano'], mes=f['mes']))
        if len(motivo) < 5:
            flash('Escreva o motivo da reabertura.', 'danger')
            return redirect(url_for('fechamento', ano=f['ano'], mes=f['mes']))
        conn.execute('DELETE FROM transacoes WHERE cong_id=? AND origem=?', (cid, f'fechamento:{fid}'))
        conn.execute('DELETE FROM fechamentos WHERE id=?', (fid,))
        antes = {k: v for k, v in f.items() if k != 'comprovante_arquivo'}
        auditar(conn, 'fechamento.reabrir', f"{MESES[f['mes'] - 1]}/{f['ano']} — motivo: {motivo}", antes=antes)
    flash('Mês reaberto. O motivo ficou registrado no histórico.', 'warning')
    return redirect(url_for('fechamento', ano=f['ano'], mes=f['mes']))


def _pode_ver_fechamento(f):
    return session.get('papel') in ('admin', 'supervisor') or f['cong_id'] == session.get('cong_id')


@app.route('/fechamento/<int:fid>/relatorio')
@login_required
def fechamento_relatorio(fid):
    with get_db() as conn:
        f = conn.execute('SELECT * FROM fechamentos WHERE id=?', (fid,)).fetchone()
        if not f or not _pode_ver_fechamento(f):
            abort(404)
        cfg = {r['key']: r['value'] for r in conn.execute('SELECT key, value FROM config WHERE cong_id=?', (f['cong_id'],)).fetchall()}
        cong = conn.execute('SELECT * FROM congregacoes WHERE id=?', (f['cong_id'],)).fetchone()
    return render_template('relatorio_economico.html', f=f, calc=json.loads(f['calculo']), cfg=cfg, cong=cong,
                           nacional=config_nacional())


@app.route('/fechamento/<int:fid>/comprovante.arquivo')
@login_required
def fechamento_arquivo(fid):
    with get_db() as conn:
        f = conn.execute('SELECT * FROM fechamentos WHERE id=?', (fid,)).fetchone()
    if not f or not _pode_ver_fechamento(f) or not f['comprovante_arquivo']:
        abort(404)
    return send_file(io.BytesIO(db.blob(f['comprovante_arquivo'])), mimetype=f['comprovante_tipo'],
                     download_name=f['comprovante_nome'] or 'comprovante')


# ═════════════════════════════════════════════
#  CARTA ANUAL (visão da congregação)
# ═════════════════════════════════════════════
def _carta_ctx(conn, cid, ano):
    c = conn.execute('SELECT * FROM compromissos WHERE cong_id=? AND ano=?', (cid, ano)).fetchone()
    if not c:
        return None
    dados = {'categoria': c['categoria'], 'nivelacao': bool(c['nivelacao']), 'fundo_local_pct': c['fundo_local_pct'],
             'betel': bool(c['betel']), 'meses': c['meses'], 'media': c['media']}
    cong = conn.execute('SELECT nome FROM congregacoes WHERE id=?', (cid,)).fetchone()
    p1, p2 = R.texto_carta(cong['nome'], ano, dados)
    conf = None
    if c['confirmado_por']:
        conf = conn.execute('SELECT nome FROM usuarios WHERE id=?', (c['confirmado_por'],)).fetchone()
    return {'c': c, 'p1': p1, 'p2': p2, 'lista': R.lista_compromissos(dados), 'cong_nome': cong['nome'],
            'confirmado_nome': conf['nome'] if conf else None}


@app.route('/carta')
@cong_required
def carta():
    cfg = get_cfg()
    cid = get_cong_id()
    ano = int(request.args.get('ano', cfg.get('ano_atual', datetime.now().year)))
    with get_db() as conn:
        ctx_c = _carta_ctx(conn, cid, ano)
    return render_template('carta.html', cfg=cfg, ano=ano, anos=ANOS, carta=ctx_c, nacional=config_nacional())


@app.route('/carta/<int:ano>/confirmar', methods=['POST'])
@papel_required('pastor')
def carta_confirmar(ano):
    cid = get_cong_id()
    with get_db() as conn:
        conn.execute('UPDATE compromissos SET confirmado_por=?, confirmado_em=CURRENT_TIMESTAMP WHERE cong_id=? AND ano=?',
                     (session['user_id'], cid, ano))
        auditar(conn, 'carta.confirmar', f'Carta anual {ano}')
    flash(f'Carta de {ano} confirmada.', 'success')
    return redirect(url_for('carta', ano=ano))


# ═════════════════════════════════════════════
#  ORÇAMENTO
# ═════════════════════════════════════════════
@app.route('/orcamento', methods=['GET', 'POST'])
@cong_required
def orcamento():
    cfg = get_cfg()
    cid = get_cong_id()
    ano_sel = int(request.args.get('ano', cfg.get('ano_atual', datetime.now().year)))
    if request.method == 'POST':
        if session.get('papel') not in ('tesoureiro', 'pastor'):
            abort(403)
        items = request.form.getlist('item[]')
        tipos = request.form.getlist('tipo[]')
        anos_f = request.form.getlist('ano[]')
        orcam_anos = request.form.getlist('orcam_ano[]')
        orcam_meses = request.form.getlist('orcam_mes[]')
        obs_list = request.form.getlist('obs[]')
        with get_db() as conn:
            for i in range(len(items)):
                if items[i]:
                    conn.execute('''INSERT INTO orcamento (cong_id,item,tipo,orcam_ano,orcam_mes,observacao,ano)
                        VALUES (?,?,?,?,?,?,?)
                        ON CONFLICT (cong_id,item,tipo,ano) DO UPDATE SET
                            orcam_ano=excluded.orcam_ano, orcam_mes=excluded.orcam_mes, observacao=excluded.observacao''',
                                 (cid, items[i], tipos[i], float(orcam_anos[i] or 0), float(orcam_meses[i] or 0),
                                  obs_list[i] if i < len(obs_list) else '',
                                  int(anos_f[i]) if i < len(anos_f) else ano_sel))
        flash('Orçamento salvo.', 'success')
        return redirect(url_for('orcamento', ano=ano_sel))

    with get_db() as conn:
        orc_rows = conn.execute('SELECT * FROM orcamento WHERE cong_id=? AND ano=?', (cid, ano_sel)).fetchall()
        orc_map = {(r['item'], r['tipo']): r for r in orc_rows}
        reais = {(r['item'], r['tipo']): r['t'] for r in conn.execute(
            '''SELECT item, tipo, SUM(valor) AS t FROM transacoes WHERE cong_id=? AND ano=?
               AND COALESCE(transferencia,0)=0 GROUP BY item, tipo''', (cid, ano_sel)).fetchall()}
    todos_e = sorted(set(i for l in CATEGORIAS.values() for i in l.get('Entrada', [])))
    todos_s = sorted(set(i for l in CATEGORIAS.values() for i in l.get('Saída', [])))

    def comparativo(itens, tipo):
        result = []
        for item in itens:
            real = reais.get((item, tipo), 0) or 0
            orc = orc_map.get((item, tipo))
            orcado = orc['orcam_ano'] if orc else 0
            if real > 0 or orcado > 0:
                pct = round(real / orcado * 100, 1) if orcado > 0 else 0
                result.append({'item': item, 'orcado': orcado, 'real': real, 'pct': pct})
        return result

    return render_template('orcamento.html', cfg=cfg, ano_sel=ano_sel, anos=ANOS, categorias=CATEGORIAS, livros=LIVROS,
                           comparativo_e=comparativo(todos_e, 'Entrada'), comparativo_s=comparativo(todos_s, 'Saída'),
                           orc_map={k: dict(v) for k, v in orc_map.items()})


# ═════════════════════════════════════════════
#  RELATÓRIOS
# ═════════════════════════════════════════════
@app.route('/relatorio')
@cong_required
def relatorio():
    cfg = get_cfg()
    cid = get_cong_id()
    ano_sel = int(request.args.get('ano', cfg.get('ano_atual', datetime.now().year)))
    livro_sel = request.args.get('livro', '')
    tipo_sel = request.args.get('tipo', '')
    item_sel = request.args.get('item', '')
    mes_sel = request.args.get('mes', '')
    with get_db() as conn:
        q = 'SELECT * FROM transacoes WHERE cong_id=? AND ano=? AND COALESCE(transferencia,0)=0'
        p = [cid, ano_sel]
        if livro_sel:
            q += ' AND livro=?'; p.append(livro_sel)
        if tipo_sel:
            q += ' AND tipo=?'; p.append(tipo_sel)
        if item_sel:
            q += ' AND item LIKE ?'; p.append(f'%{item_sel}%')
        if mes_sel:
            q += ' AND mes=?'; p.append(mes_sel)
        q += f' ORDER BY {MES_ORDEM}, id'
        lista = conn.execute(q, p).fetchall()
        total_e = sum(t['valor'] for t in lista if t['tipo'] == 'Entrada')
        total_s = sum(t['valor'] for t in lista if t['tipo'] == 'Saída')
        superavit = total_e - total_s
        pct = round(superavit / total_e * 100, 2) if total_e > 0 else 0
        resumo_mensal = []
        for mes in MESES:
            q2 = 'SELECT tipo, COALESCE(SUM(valor),0) AS t FROM transacoes WHERE cong_id=? AND ano=? AND mes=? AND COALESCE(transferencia,0)=0'
            p2 = [cid, ano_sel, mes]
            if livro_sel:
                q2 += ' AND livro=?'; p2.append(livro_sel)
            q2 += ' GROUP BY tipo'
            rows = conn.execute(q2, p2).fetchall()
            e = sum(r['t'] for r in rows if r['tipo'] == 'Entrada')
            s = sum(r['t'] for r in rows if r['tipo'] == 'Saída')
            if e > 0 or s > 0:
                resumo_mensal.append({'mes': mes, 'entradas': e, 'saidas': s, 'saldo': e - s})
        resumo_livro = conn.execute('''SELECT livro,
                   SUM(CASE WHEN tipo='Entrada' THEN valor ELSE 0 END) AS e,
                   SUM(CASE WHEN tipo='Saída' THEN valor ELSE 0 END) AS s
            FROM transacoes WHERE cong_id=? AND ano=? AND COALESCE(transferencia,0)=0 GROUP BY livro''', (cid, ano_sel)).fetchall()
        items_disp = conn.execute('SELECT DISTINCT item FROM transacoes WHERE cong_id=? AND ano=? ORDER BY item',
                                  (cid, ano_sel)).fetchall()
    return render_template('relatorio.html', cfg=cfg, anos=ANOS, meses=MESES, livros=LIVROS, livros_labels=LIVROS_LABELS,
        ano_sel=ano_sel, livro_sel=livro_sel, tipo_sel=tipo_sel, item_sel=item_sel, mes_sel=mes_sel, transacoes=lista,
        total_e=total_e, total_s=total_s, superavit=superavit, pct=pct, resumo_mensal=resumo_mensal,
        resumo_livro=resumo_livro, items_disponiveis=items_disp)


# ═════════════════════════════════════════════
#  CONFIGURAÇÕES / CONTA / TUTORIAL
# ═════════════════════════════════════════════
@app.route('/configuracoes', methods=['GET', 'POST'])
@cong_required
def configuracoes():
    """Configurar a congregação: responsáveis (saem nos livros, recibos e relatórios) e porcentagens do ano."""
    cid = get_cong_id()
    papel = session.get('papel')
    pode = papel in ('tesoureiro', 'pastor') or (papel == 'admin' and cid)
    cfg = get_cfg()
    ano = int(request.values.get('ano', cfg.get('ano_atual') or date.today().year))
    if request.method == 'POST':
        if not pode:
            abort(403)
        acao = request.form.get('acao')
        with get_db() as conn:
            if acao == 'dados':
                dados = {k: request.form.get(k, '').strip()[:200] for k in
                         ['nome_congregacao', 'nome_pastor', 'nome_tesoureiro', 'nome_auxiliar', 'endereco',
                          'ano_atual', 'saldo_ano_anterior']}
                try:
                    dados['saldo_ano_anterior'] = str(parse_valor(dados['saldo_ano_anterior'] or '0'))
                except ValueError:
                    dados['saldo_ano_anterior'] = '0'
                antes = {r['key']: r['value'] for r in conn.execute('SELECT key, value FROM config WHERE cong_id=?', (cid,)).fetchall()}
                for k, v in dados.items():
                    conn.execute('INSERT INTO config (cong_id, key, value) VALUES (?,?,?) '
                                 'ON CONFLICT (cong_id, key) DO UPDATE SET value=excluded.value', (cid, k, v))
                if dados['nome_congregacao']:
                    conn.execute('UPDATE congregacoes SET nome=? WHERE id=?', (dados['nome_congregacao'], cid))
                    session['cong_nome'] = dados['nome_congregacao']
                auditar(conn, 'config.salvar', 'Responsáveis e dados da congregação', antes=antes, depois=dados)
                flash('Dados salvos. Os nomes já saem nos livros, recibos e no relatório dos envios.', 'success')
            elif acao == 'porcentagens':
                atual = conn.execute('SELECT * FROM compromissos WHERE cong_id=? AND ano=?', (cid, ano)).fetchone()
                if atual and atual['confirmado_em'] and papel != 'admin':
                    flash(f'As porcentagens de {ano} já foram confirmadas pelo pastor. '
                          'Para mudar, fale com a Tesouraria Nacional.', 'danger')
                    return redirect(url_for('configuracoes', ano=ano))
                vals = []
                for i in range(12):
                    try:
                        vals.append(max(0.0, parse_valor(request.form.get(f'm{i}', '') or '0')))
                    except ValueError:
                        vals.append(0.0)
                sm = regras_em(conn, f'{ano - 1}-12-31')['salario_minimo']
                reg = regras_em(conn, f'{ano}-01-01')
                p = R.carta_anual(vals, sm, reg)
                conn.execute('INSERT INTO config (cong_id, key, value) VALUES (?,?,?) '
                             'ON CONFLICT (cong_id, key) DO UPDATE SET value=excluded.value',
                             (cid, f'base_carta_{ano}', json.dumps(vals)))
                obs = 'Ajustada pela Tesouraria Nacional' if papel == 'admin' else 'Calculada pelo cadastro da congregação'
                conf_por = session['user_id'] if papel == 'pastor' else None
                conn.execute('''INSERT INTO compromissos (cong_id, ano, categoria, nivelacao, fundo_local_pct, betel, media, meses,
                                salario_minimo, observacao, emitido_por, emitido_em, confirmado_por, confirmado_em)
                                VALUES (?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP,?,?)
                                ON CONFLICT (cong_id, ano) DO UPDATE SET categoria=excluded.categoria, nivelacao=excluded.nivelacao,
                                fundo_local_pct=excluded.fundo_local_pct, betel=excluded.betel, media=excluded.media,
                                meses=excluded.meses, salario_minimo=excluded.salario_minimo, observacao=excluded.observacao,
                                emitido_por=excluded.emitido_por, emitido_em=CURRENT_TIMESTAMP,
                                confirmado_por=excluded.confirmado_por, confirmado_em=excluded.confirmado_em''',
                             (cid, ano, p['categoria'], int(p['nivelacao']), int(p['fundo_local_pct']), int(p['betel']),
                              p['media'], p['meses'], sm, obs, session['user_id'],
                              conf_por, datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S') if conf_por else None))
                auditar(conn, 'porcentagens.calcular', f'Classificação e liquidação {ano}',
                        antes=dict(atual) if atual else None, depois={k: p[k] for k in ('categoria', 'media', 'meses', 'nivelacao', 'fundo_local_pct', 'betel')})
                flash(f'{ano}: {R.CATEGORIAS[p["categoria"]]}, fundo local {p["fundo_local_pct"]}%'
                      f'{", com nivelação" if p["nivelacao"] else ""}{", com Betel" if p["betel"] else ""}.'
                      + ('' if conf_por else ' Falta o pastor confirmar.'), 'success')
            else:
                abort(400)
        return redirect(url_for('configuracoes', ano=ano))

    janela = R.janela_carta(ano)
    with get_db() as conn:
        comp = conn.execute('SELECT * FROM compromissos WHERE cong_id=? AND ano=?', (cid, ano)).fetchone()
        reg = regras_em(conn, f'{ano}-01-01')
        sm = regras_em(conn, f'{ano - 1}-12-31')['salario_minimo']
        sistema = [float(conn.execute('SELECT COALESCE(SUM(dizimo_bruto),0) AS t FROM dizimos WHERE cong_id=? AND ano=? AND mes=?',
                                      (cid, a_, MESES[m_ - 1])).fetchone()['t']) for a_, m_ in janela]
    try:
        salvos = json.loads(cfg.get(f'base_carta_{ano}') or '[]')
    except ValueError:
        salvos = []
    base = [sistema[i] or (salvos[i] if i < len(salvos) else 0) for i in range(12)]
    meses_base = [{'rotulo': f'{MESES[m_ - 1][:3].capitalize()}/{a_}', 'valor': base[i], 'do_sistema': bool(sistema[i])}
                  for i, (a_, m_) in enumerate(janela)]
    exemplo = None
    if comp:
        c = {'categoria': comp['categoria'], 'nivelacao': bool(comp['nivelacao']),
             'fundo_local_pct': int(comp['fundo_local_pct']), 'betel': bool(comp['betel'])}
        exemplo = R.liquidar_dizimo(1000, c, reg)
    travado = bool(comp and comp['confirmado_em']) and papel != 'admin'
    return render_template('configuracoes.html', cfg=cfg, anos=ANOS, ano=ano, comp=comp, reg=reg, exemplo=exemplo,
                           pode=pode, travado=travado, sm=sm, meses_base=meses_base)


@app.route('/tutorial')
@login_required
def tutorial():
    return render_template('tutorial.html', cfg=get_cfg())


@app.route('/minha-conta', methods=['GET', 'POST'])
@login_required
def minha_conta():
    cfg = get_cfg()
    if request.method == 'POST':
        atual, nova, conf = request.form['senha_atual'], request.form['nova_senha'], request.form['confirmar_senha']
        with get_db() as conn:
            u = conn.execute('SELECT * FROM usuarios WHERE id=?', (session['user_id'],)).fetchone()
            if not verificar_senha(u['senha_hash'], atual):
                flash('Senha atual incorreta.', 'danger')
            elif nova != conf:
                flash('As senhas não coincidem.', 'danger')
            elif len(nova) < 8:
                flash('A nova senha deve ter pelo menos 8 caracteres.', 'danger')
            else:
                conn.execute('UPDATE usuarios SET senha_hash=? WHERE id=?', (generate_password_hash(nova), u['id']))
                auditar(conn, 'usuario.senha', 'Troca da própria senha')
                flash('Senha alterada.', 'success')
    return render_template('minha_conta.html', cfg=cfg)


@app.route('/api/categorias/<livro>/<tipo>')
@login_required
def api_categorias(livro, tipo):
    return jsonify(CATEGORIAS.get(livro, {}).get(tipo, []))


# ═════════════════════════════════════════════
#  TESOURARIA NACIONAL
# ═════════════════════════════════════════════
@app.route('/nacional/envios')
@papel_required('admin', 'supervisor')
def nacional_envios():
    hoje = date.today()
    ano = int(request.args.get('ano', hoje.year))
    with get_db() as conn:
        congs = conn.execute('SELECT * FROM congregacoes WHERE ativo=1 ORDER BY nome').fetchall()
        fechs = conn.execute('SELECT id, cong_id, mes, status, total, comprovante_data FROM fechamentos WHERE ano=?', (ano,)).fetchall()
        comps = {c['cong_id']: c for c in conn.execute('SELECT * FROM compromissos WHERE ano=?', (ano,)).fetchall()}
        reg = regras_em(conn)
    dia = int(reg.get('prazo_dia', 5))
    inicio = (config_nacional().get('inicio_uso') or '2000-01')[:7]
    por = {}
    for f in fechs:
        por.setdefault(f['cong_id'], {})[f['mes']] = f
    linhas, total_ano, total_recebido = [], 0, 0
    for c in congs:
        meses, atrasados = [], 0
        for m in range(1, 13):
            f = por.get(c['id'], {}).get(m)
            venc = R.prazo_envio(ano, m, dia)
            antes_do_sistema = f'{ano}-{m:02d}' < inicio
            atrasado = (not f or f['status'] in ('fechado', 'aprovado')) and hoje > venc and not antes_do_sistema
            if atrasado:
                atrasados += 1
            meses.append({'m': m, 'f': f, 'atrasado': atrasado, 'antes': antes_do_sistema and not f})
            if f and f['status'] in ('enviado', 'recebido'):
                total_ano += f['total']
                if f['status'] == 'recebido':
                    total_recebido += f['total']
        linhas.append({'c': c, 'meses': meses, 'atrasados': atrasados, 'comp': comps.get(c['id'])})
    return render_template('nacional_envios.html', cfg=get_cfg(), ano=ano, anos=ANOS, linhas=linhas,
                           total_ano=total_ano, total_recebido=total_recebido)


@app.route('/nacional/fechamento/<int:fid>/receber', methods=['POST'])
@papel_required('admin')
def nacional_receber(fid):
    with get_db() as conn:
        f = conn.execute('SELECT * FROM fechamentos WHERE id=?', (fid,)).fetchone()
        if not f or f['status'] != 'enviado':
            abort(400)
        conn.execute("UPDATE fechamentos SET status='recebido', recebido_por=?, recebido_em=CURRENT_TIMESTAMP WHERE id=?",
                     (session['user_id'], fid))
        auditar(conn, 'nacional.receber', f"{MESES[f['mes'] - 1]}/{f['ano']}", cong_id=f['cong_id'])
    flash('Recebimento confirmado.', 'success')
    return redirect(request.referrer or url_for('nacional_envios', ano=f['ano']))


@app.route('/nacional/cartas', methods=['GET', 'POST'])
@papel_required('admin')
def nacional_cartas():
    ano = int(request.values.get('ano', date.today().year + (1 if date.today().month >= 11 else 0)))
    with get_db() as conn:
        congs = conn.execute('SELECT * FROM congregacoes WHERE ativo=1 ORDER BY nome').fetchall()
        sm = regras_em(conn, f'{ano - 1}-12-31')['salario_minimo']
        reg = regras_em(conn, f'{ano}-01-01')
        janela = R.janela_carta(ano)

        def proposta(cid):
            vals = []
            for a, m in janela:
                t = conn.execute('SELECT COALESCE(SUM(dizimo_bruto),0) AS t FROM dizimos WHERE cong_id=? AND ano=? AND mes=?',
                                 (cid, a, MESES[m - 1])).fetchone()['t']
                vals.append(float(t))
            return R.carta_anual(vals, sm, reg)

        if request.method == 'POST':
            acao = request.form.get('acao')
            alvos = [int(request.form['cong_id'])] if acao in ('emitir', 'manual') else [c['id'] for c in congs]
            for cid in alvos:
                if acao == 'manual':
                    cat = request.form.get('categoria')
                    if cat not in R.CATEGORIAS:
                        abort(400)
                    p = {'categoria': cat, 'nivelacao': request.form.get('nivelacao') == '1',
                         'fundo_local_pct': max(0, min(30, int(request.form.get('fundo_local_pct') or 0))),
                         'betel': request.form.get('betel') == '1', 'media': float(request.form.get('media') or 0),
                         'meses': int(request.form.get('meses') or 0)}
                    obs = request.form.get('observacao', '')[:300] or 'Emitida manualmente'
                else:
                    p = proposta(cid)
                    obs = 'Calculada pelo sistema'
                antes = conn.execute('SELECT * FROM compromissos WHERE cong_id=? AND ano=?', (cid, ano)).fetchone()
                if acao == 'todas' and antes:
                    continue
                conn.execute('''INSERT INTO compromissos (cong_id, ano, categoria, nivelacao, fundo_local_pct, betel, media, meses,
                                salario_minimo, observacao, emitido_por, emitido_em, confirmado_por, confirmado_em)
                                VALUES (?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP,NULL,NULL)
                                ON CONFLICT (cong_id, ano) DO UPDATE SET categoria=excluded.categoria, nivelacao=excluded.nivelacao,
                                fundo_local_pct=excluded.fundo_local_pct, betel=excluded.betel, media=excluded.media,
                                meses=excluded.meses, salario_minimo=excluded.salario_minimo, observacao=excluded.observacao,
                                emitido_por=excluded.emitido_por, emitido_em=CURRENT_TIMESTAMP, confirmado_por=NULL, confirmado_em=NULL''',
                             (cid, ano, p['categoria'], int(p['nivelacao']), int(p['fundo_local_pct']), int(p['betel']),
                              p.get('media', 0), p.get('meses', 0), sm, obs, session['user_id']))
                auditar(conn, 'carta.emitir', f'Carta anual {ano}', antes=dict(antes) if antes else None, depois=p, cong_id=cid)
            flash('Cartas emitidas. Os pastores precisam confirmar cada uma no sistema.', 'success')
            return redirect(url_for('nacional_cartas', ano=ano))

        linhas = []
        for c in congs:
            atual = conn.execute('SELECT * FROM compromissos WHERE cong_id=? AND ano=?', (c['id'], ano)).fetchone()
            linhas.append({'c': c, 'proposta': proposta(c['id']), 'atual': atual})
    return render_template('nacional_cartas.html', cfg=get_cfg(), ano=ano, anos=ANOS, linhas=linhas, sm=sm,
                           janela=janela)


@app.route('/nacional/carta/<int:cid>/<int:ano>')
@papel_required('admin', 'supervisor')
def nacional_carta_ver(cid, ano):
    with get_db() as conn:
        ctx_c = _carta_ctx(conn, cid, ano)
    if not ctx_c:
        abort(404)
    return render_template('carta.html', cfg=get_cfg(), ano=ano, anos=ANOS, carta=ctx_c, nacional=config_nacional(),
                           visao_nacional=True)


@app.route('/nacional/regras', methods=['GET', 'POST'])
@papel_required('admin')
def nacional_regras():
    with get_db() as conn:
        if request.method == 'POST':
            if request.form.get('acao') == 'conta':
                for k in CONTA_NACIONAL_PADRAO:
                    conn.execute('INSERT INTO config_nacional (key, value) VALUES (?,?) ON CONFLICT (key) DO UPDATE SET value=excluded.value',
                                 (k, request.form.get(k, '')[:200]))
                auditar(conn, 'nacional.conta', 'Dados da conta nacional')
                flash('Dados da conta nacional salvos.', 'success')
            else:
                chave = request.form.get('chave')
                try:
                    valor = float(request.form.get('valor', '').replace(',', '.'))
                    vig = date.fromisoformat(request.form.get('vigencia', '')).isoformat()
                except ValueError:
                    flash('Informe um valor e uma data válidos.', 'danger')
                    return redirect(url_for('nacional_regras'))
                if chave not in R.REGRAS_ROTULOS:
                    abort(400)
                conn.execute('INSERT INTO regras (chave, valor, vigencia, criado_por) VALUES (?,?,?,?) '
                             'ON CONFLICT (chave, vigencia) DO UPDATE SET valor=excluded.valor, criado_por=excluded.criado_por',
                             (chave, valor, vig, session['user_id']))
                auditar(conn, 'regra.vigencia', f'{chave} = {valor} desde {vig}', cong_id=0)
                flash('Nova vigência registrada. Os meses anteriores continuam com a regra antiga.', 'success')
            return redirect(url_for('nacional_regras'))
        todas = conn.execute('SELECT * FROM regras ORDER BY chave, vigencia DESC').fetchall()
        vigentes = regras_em(conn)
    return render_template('nacional_regras.html', cfg=get_cfg(), regras=todas, vigentes=vigentes,
                           rotulos=R.REGRAS_ROTULOS, nacional=config_nacional(), campos_conta=CONTA_NACIONAL_PADRAO)


@app.route('/nacional/auditoria')
@papel_required('admin')
def nacional_auditoria():
    cid = request.args.get('cong', '')
    with get_db() as conn:
        q = '''SELECT a.*, c.nome AS cong_nome FROM auditoria a LEFT JOIN congregacoes c ON c.id=a.cong_id'''
        p = []
        if cid:
            q += ' WHERE a.cong_id=?'
            p.append(int(cid))
        q += ' ORDER BY a.id DESC LIMIT 500'
        itens = conn.execute(q, p).fetchall()
        congs = conn.execute('SELECT id, nome FROM congregacoes ORDER BY nome').fetchall()
    return render_template('nacional_auditoria.html', cfg=get_cfg(), itens=itens, congs=congs, cong_sel=cid)


# ═════════════════════════════════════════════
#  ADMIN — CONGREGAÇÕES E USUÁRIOS
# ═════════════════════════════════════════════
def _novo_usuario(conn, cid, nome, usuario, senha, papel):
    usuario = usuario.strip().lower()
    if not usuario or not all(ch.isalnum() or ch in '-_.' for ch in usuario):
        raise ValueError('Usuário: use letras minúsculas, números, ponto, - ou _.')
    if len(senha) < 8:
        raise ValueError('A senha precisa ter pelo menos 8 caracteres.')
    if conn.execute('SELECT 1 FROM usuarios WHERE usuario=?', (usuario,)).fetchone():
        raise ValueError(f'O usuário "{usuario}" já existe.')
    return conn.insert('INSERT INTO usuarios (cong_id, nome, usuario, senha_hash, papel) VALUES (?,?,?,?,?)',
                       (cid, nome.strip()[:120] or usuario, usuario, generate_password_hash(senha), papel))


@app.route('/admin')
@papel_required('admin')
def admin():
    with get_db() as conn:
        congs = conn.execute('SELECT * FROM congregacoes ORDER BY nome').fetchall()
        users = conn.execute('SELECT id, cong_id, nome, usuario, papel, ativo FROM usuarios ORDER BY papel, nome').fetchall()
    por_cong = {}
    for u in users:
        por_cong.setdefault(u['cong_id'], []).append(u)
    return render_template('admin.html', congs=congs, por_cong=por_cong, nacionais=por_cong.get(None, []), cfg=get_cfg())


@app.route('/admin/nova', methods=['GET', 'POST'])
@papel_required('admin')
def admin_nova_cong():
    if request.method == 'POST':
        nome = request.form['nome'].strip()
        try:
            with get_db() as conn:
                if not nome:
                    raise ValueError('Informe o nome da congregação.')
                legado = 'usuario' in _cols(conn, 'congregacoes')
                if legado:
                    cid = conn.insert('INSERT INTO congregacoes (nome, usuario, senha_hash) VALUES (?,?,?)',
                                      (nome, 'cong-' + secrets.token_hex(6), '-'))
                else:
                    cid = conn.insert('INSERT INTO congregacoes (nome) VALUES (?)', (nome,))
                padrao = _config_defaults(nome)
                padrao['nome_tesoureiro'] = request.form.get('tes_nome', '').strip()[:200]
                padrao['nome_pastor'] = request.form.get('pas_nome', '').strip()[:200]
                for k, v in padrao.items():
                    conn.execute('INSERT INTO config (cong_id, key, value) VALUES (?,?,?) ON CONFLICT (cong_id, key) DO NOTHING',
                                 (cid, k, v))
                _novo_usuario(conn, cid, request.form.get('tes_nome', ''), request.form['tes_usuario'],
                              request.form['tes_senha'], 'tesoureiro')
                if request.form.get('pas_usuario'):
                    _novo_usuario(conn, cid, request.form.get('pas_nome', ''), request.form['pas_usuario'],
                                  request.form['pas_senha'], 'pastor')
                auditar(conn, 'admin.nova_congregacao', nome, cong_id=cid)
            flash(f'Congregação "{nome}" criada.', 'success')
            return redirect(url_for('admin'))
        except ValueError as e:
            flash(str(e), 'danger')
    return render_template('admin_nova.html', cfg=get_cfg())


@app.route('/admin/usuario/novo', methods=['POST'])
@papel_required('admin')
def admin_novo_usuario():
    papel = request.form.get('papel')
    if papel not in PAPEIS:
        abort(400)
    cid = request.form.get('cong_id') or None
    if papel in ('tesoureiro', 'pastor') and not cid:
        flash('Tesoureiro e pastor precisam estar ligados a uma congregação.', 'danger')
        return redirect(url_for('admin'))
    if papel in ('admin', 'supervisor'):
        cid = None
    try:
        with get_db() as conn:
            _novo_usuario(conn, int(cid) if cid else None, request.form.get('nome', ''), request.form.get('usuario', ''),
                          request.form.get('senha', ''), papel)
            auditar(conn, 'admin.novo_usuario', f"{request.form.get('usuario')} ({papel})", cong_id=int(cid) if cid else 0)
        flash('Usuário criado.', 'success')
    except ValueError as e:
        flash(str(e), 'danger')
    return redirect(url_for('admin'))


@app.route('/admin/usuario/<int:uid>/senha', methods=['POST'])
@papel_required('admin')
def admin_reset_senha(uid):
    nova = request.form.get('nova_senha', '')
    if len(nova) < 8:
        flash('A senha precisa ter pelo menos 8 caracteres.', 'danger')
        return redirect(url_for('admin'))
    with get_db() as conn:
        conn.execute('UPDATE usuarios SET senha_hash=? WHERE id=?', (generate_password_hash(nova), uid))
        auditar(conn, 'admin.reset_senha', f'Usuário #{uid}', cong_id=0)
    flash('Senha redefinida.', 'success')
    return redirect(url_for('admin'))


@app.route('/admin/usuario/<int:uid>/toggle', methods=['POST'])
@papel_required('admin')
def admin_toggle_usuario(uid):
    if uid == session.get('user_id'):
        flash('Você não pode desativar o próprio acesso.', 'danger')
        return redirect(url_for('admin'))
    with get_db() as conn:
        conn.execute('UPDATE usuarios SET ativo = 1 - ativo WHERE id=?', (uid,))
        auditar(conn, 'admin.toggle_usuario', f'Usuário #{uid}', cong_id=0)
    flash('Acesso atualizado.', 'success')
    return redirect(url_for('admin'))


@app.route('/admin/<int:cid>/toggle', methods=['POST'])
@papel_required('admin')
def admin_toggle_cong(cid):
    with get_db() as conn:
        conn.execute('UPDATE congregacoes SET ativo = 1 - ativo WHERE id=?', (cid,))
        auditar(conn, 'admin.toggle_congregacao', f'Congregação #{cid}', cong_id=cid)
    flash('Status atualizado.', 'success')
    return redirect(url_for('admin'))


# ═════════════════════════════════════════════
#  EXPORTAR EXCEL
# ═════════════════════════════════════════════
@app.route('/exportar/excel')
@cong_required
def exportar_excel():
    """Planilha completa do ano (abre no Excel e no Google Planilhas): cadastro, livros, dízimos, resumo e balanço."""
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter
    cfg = get_cfg()
    cid = get_cong_id()
    ano = int(request.args.get('ano', cfg.get('ano_atual', datetime.now().year)))
    saldo_ini = float(cfg.get('saldo_ano_anterior', 0) or 0)
    with get_db() as conn:
        trans = conn.execute('SELECT * FROM transacoes WHERE cong_id=? AND ano=?', (cid, ano)).fetchall()
        diz = conn.execute('SELECT * FROM dizimos WHERE cong_id=? AND ano=?', (cid, ano)).fetchall()
        comp = conn.execute('SELECT * FROM compromissos WHERE cong_id=? AND ano=?', (cid, ano)).fetchone()
        cong = conn.execute('SELECT nome FROM congregacoes WHERE id=?', (cid,)).fetchone()

    def ordem(t):
        try:
            d = datetime.strptime(t['data_registro'] or '', '%d/%m/%Y')
        except ValueError:
            d = datetime(ano, R.mes_num(t['mes']), 28)
        return (R.mes_num(t['mes']), d, t['id'])
    trans = sorted(trans, key=ordem)
    diz = sorted(diz, key=lambda d: (R.mes_num(d['mes']), d['id']))

    wb = openpyxl.Workbook()
    NAVY = PatternFill('solid', fgColor='25307A')
    CLARO = PatternFill('solid', fgColor='E9EEFB')
    BR = Font(color='FFFFFF', bold=True)
    B = Font(bold=True)
    MOEDA = '"R$" #,##0.00;[Red]-"R$" #,##0.00'
    fina = Side(style='thin', color='C9D1E3')

    def titulo(ws, texto, ncols):
        ws.cell(1, 1, f'IGREJA DO NOME DE JESUS — {cong["nome"]}').font = Font(bold=True, size=13, color='25307A')
        ws.cell(2, 1, texto).font = Font(bold=True, size=11)
        ws.cell(3, 1, f'Pastor: {cfg.get("nome_pastor") or "—"}   ·   Tesoureiro(a): {cfg.get("nome_tesoureiro") or "—"}').font = Font(color='5D6D7E')
        ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=ncols)

    def cabec(ws, linha, cols, larguras):
        for ci, (c, w) in enumerate(zip(cols, larguras), 1):
            cell = ws.cell(linha, ci, c)
            cell.font, cell.fill = BR, NAVY
            cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
            ws.column_dimensions[get_column_letter(ci)].width = w
        ws.freeze_panes = ws.cell(linha + 1, 1)

    # 1. Cadastro
    ws = wb.active
    ws.title = 'Cadastro'
    titulo(ws, f'Cadastro e liquidação — {ano}', 2)
    linhas = [('Congregação', cong['nome']), ('Pastor', cfg.get('nome_pastor') or ''), ('Tesoureiro(a)', cfg.get('nome_tesoureiro') or ''),
              ('Auxiliar', cfg.get('nome_auxiliar') or ''), ('Endereço', cfg.get('endereco') or ''), ('Saldo no início do ano', saldo_ini)]
    if comp:
        linhas += [('Classificação', R.CATEGORIAS.get(comp['categoria'], comp['categoria'])),
                   ('Média mensal de dízimos (ano anterior)', comp['media'] or 0),
                   ('Dízimo dos Dízimos', '10%'), ('Nivelação', 'Sim (5%)' if comp['nivelacao'] else 'Não'),
                   ('Betel', 'Sim (4% do líquido)' if comp['betel'] else 'Não'),
                   ('Aporte ao fundo local', f"{comp['fundo_local_pct']}%"),
                   ('Confirmado pelo pastor', 'Sim' if comp['confirmado_em'] else 'Pendente')]
    for i, (k, v) in enumerate(linhas, 5):
        ws.cell(i, 1, k).font = B
        c = ws.cell(i, 2, v)
        if isinstance(v, float):
            c.number_format = MOEDA
    ws.column_dimensions['A'].width = 40
    ws.column_dimensions['B'].width = 45

    # 2. Todos os lançamentos
    ws = wb.create_sheet('Lançamentos')
    titulo(ws, f'Todos os lançamentos — {ano}', 10)
    cols = ['Nº', 'Mês', 'Data', 'Livro', 'Entrada/Saída', 'Tipo', 'Recebido de / pago a', 'Forma', 'Valor', 'Observação']
    cabec(ws, 5, cols, [7, 11, 12, 22, 13, 34, 28, 10, 15, 34])
    for r, t in enumerate(trans, 6):
        vals = [t['id'], t['mes'].capitalize(), t['data_registro'] or '', LIVRO_NOME.get(t['livro'], t['livro']), t['tipo'], t['item'],
                t.get('pessoa') or '', t.get('forma') or '', round(t['valor'], 2),
                (t['obs'] or '') + (' [repasse interno]' if t.get('transferencia') else '')]
        for ci, v in enumerate(vals, 1):
            ws.cell(r, ci, v)
        ws.cell(r, 9).number_format = MOEDA
        ws.cell(r, 5).font = Font(color='1E8449' if t['tipo'] == 'Entrada' else 'A93226', bold=True)
    ws.auto_filter.ref = f'A5:J{max(6, len(trans) + 5)}'

    # 3. Um livro por aba, com saldo corrido por fórmula
    for lv in LIVROS:
        ws = wb.create_sheet(LIVRO_NOME[lv][:31].replace('/', '-'))
        titulo(ws, f'Livro {LIVRO_NOME[lv]} — {ano}', 7)
        cabec(ws, 5, ['Mês', 'Data', 'Tipo', 'Recebido de / pago a', 'Entrada', 'Saída', 'Saldo'], [11, 12, 34, 28, 15, 15, 16])
        ws.cell(6, 3, 'Saldo inicial do ano').font = B
        ws.cell(6, 7, saldo_ini if lv == 'FundoLocal' else 0).number_format = MOEDA
        for c in range(1, 8):
            ws.cell(6, c).fill = CLARO
        r = 7
        for t in (x for x in trans if x['livro'] == lv):
            ws.cell(r, 1, t['mes'].capitalize()); ws.cell(r, 2, t['data_registro'] or '')
            ws.cell(r, 3, t['item']); ws.cell(r, 4, t.get('pessoa') or '')
            ws.cell(r, 5 if t['tipo'] == 'Entrada' else 6, round(t['valor'], 2))
            ws.cell(r, 7, f'=G{r - 1}+E{r}-F{r}')
            for c in (5, 6, 7):
                ws.cell(r, c).number_format = MOEDA
            r += 1
        ws.cell(r, 3, 'TOTAIS DO ANO').font = B
        ws.cell(r, 5, f'=SUM(E7:E{r - 1})' if r > 7 else 0)
        ws.cell(r, 6, f'=SUM(F7:F{r - 1})' if r > 7 else 0)
        ws.cell(r, 7, f'=G{r - 1}')
        for c in range(1, 8):
            ws.cell(r, c).fill = CLARO; ws.cell(r, c).font = B
        for c in (5, 6, 7):
            ws.cell(r, c).number_format = MOEDA

    # 4. Dízimos e liquidação
    ws = wb.create_sheet('Dízimos')
    titulo(ws, f'Dízimos e liquidação — {ano}', 7)
    cabec(ws, 5, ['Mês', 'Data', 'Dízimo bruto', 'Enviado à nacional', 'Fundo local', 'Sustento pastoral', 'Observação'],
          [11, 12, 16, 18, 15, 18, 34])
    r = 6
    for d in diz:
        for ci, v in enumerate([d['mes'].capitalize(), d['data_registro'] or '', d['dizimo_bruto'], d['valor_nacional'] or 0,
                                d['valor_fundo_local'] or 0, d['valor_liquido'] or 0, d['obs'] or ''], 1):
            c = ws.cell(r, ci, v)
            if 3 <= ci <= 6:
                c.number_format = MOEDA
        r += 1
    ws.cell(r, 1, 'TOTAL').font = B
    for ci in range(3, 7):
        col = get_column_letter(ci)
        c = ws.cell(r, ci, f'=SUM({col}6:{col}{r - 1})' if r > 6 else 0)
        c.number_format, c.font = MOEDA, B

    # 5. Resumo mensal
    ws = wb.create_sheet('Resumo mensal')
    titulo(ws, f'Resumo mensal — {ano}', 6)
    cabec(ws, 5, ['Mês', 'Entradas', 'Saídas', 'Resultado', 'Saldo acumulado', 'Dízimos'], [12, 16, 16, 16, 18, 16])
    ws.cell(6, 1, 'Saldo inicial'); ws.cell(6, 5, saldo_ini).number_format = MOEDA
    for i, m in enumerate(MESES):
        r = 7 + i
        reais = [t for t in trans if t['mes'] == m and not t.get('transferencia')]
        e = sum(t['valor'] for t in reais if t['tipo'] == 'Entrada')
        s_ = sum(t['valor'] for t in reais if t['tipo'] == 'Saída')
        ws.cell(r, 1, m.capitalize())
        ws.cell(r, 2, round(e, 2)); ws.cell(r, 3, round(s_, 2))
        ws.cell(r, 4, f'=B{r}-C{r}'); ws.cell(r, 5, f'=E{r - 1}+D{r}')
        ws.cell(r, 6, round(sum(d['dizimo_bruto'] for d in diz if d['mes'] == m), 2))
        for c in range(2, 7):
            ws.cell(r, c).number_format = MOEDA
    ws.cell(19, 1, 'TOTAL').font = B
    for ci in (2, 3, 4, 6):
        col = get_column_letter(ci)
        c = ws.cell(19, ci, f'=SUM({col}7:{col}18)'); c.number_format, c.font = MOEDA, B
    c = ws.cell(19, 5, '=E18'); c.number_format, c.font = MOEDA, B

    # 6. Balanço por livro
    ws = wb.create_sheet('Balanço')
    titulo(ws, f'Balanço por livro — {ano}', 5)
    cabec(ws, 5, ['Livro', 'Saldo inicial', 'Entradas', 'Saídas', 'Saldo final'], [26, 16, 16, 16, 16])
    for i, lv in enumerate(LIVROS):
        r = 6 + i
        e = sum(t['valor'] for t in trans if t['livro'] == lv and t['tipo'] == 'Entrada')
        s_ = sum(t['valor'] for t in trans if t['livro'] == lv and t['tipo'] == 'Saída')
        ws.cell(r, 1, LIVRO_NOME[lv]); ws.cell(r, 2, saldo_ini if lv == 'FundoLocal' else 0)
        ws.cell(r, 3, round(e, 2)); ws.cell(r, 4, round(s_, 2)); ws.cell(r, 5, f'=B{r}+C{r}-D{r}')
        for c in range(2, 6):
            ws.cell(r, c).number_format = MOEDA
    r = 6 + len(LIVROS)
    ws.cell(r, 1, 'TOTAL').font = B
    for ci in range(2, 6):
        col = get_column_letter(ci)
        c = ws.cell(r, ci, f'=SUM({col}6:{col}{r - 1})'); c.number_format, c.font = MOEDA, B
    ws.cell(r + 2, 1, f'Gerado pelo sistema Tesouraria INJ em {datetime.now().strftime("%d/%m/%Y %H:%M")}.').font = Font(italic=True, color='5D6D7E')

    for w in wb.worksheets:
        w.sheet_view.showGridLines = True
        w.page_setup.orientation = 'landscape'
        w.page_setup.fitToWidth = 1
    out = io.BytesIO()
    wb.save(out)
    out.seek(0)
    nome = ''.join(ch if ch.isalnum() else '_' for ch in cong['nome']).strip('_')
    return send_file(out, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                     as_attachment=True, download_name=f'Tesouraria_{nome}_{ano}.xlsx')


@app.errorhandler(413)
def muito_grande(_):
    flash('O arquivo é grande demais. O limite é 5 MB.', 'danger')
    return redirect(request.referrer or url_for('inicio'))


@app.cli.command('criar-admin')
def criar_admin_cli():
    """Cria um usuário da Tesouraria Nacional: flask --app app criar-admin"""
    import getpass
    init_db()
    usuario = input('Usuário: ').strip().lower()
    senha = getpass.getpass('Senha (mínimo 8 caracteres): ')
    with get_db() as conn:
        _novo_usuario(conn, None, 'Tesouraria Nacional', usuario, senha, 'admin')
    print('Administrador criado.')


# ═════════════════════════════════════════════
#  MAIN
# ═════════════════════════════════════════════
if os.environ.get('RENDER') and not db.IS_PG:
    raise SystemExit('DATABASE_URL não definida: no Render os dados só ficam guardados num banco Postgres '
                     '(ex.: Neon gratuito). Defina DATABASE_URL antes de publicar.')
init_db()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    print('\n' + '=' * 60)
    print('  TESOURARIA INJ — Sistema Multi-Congregação')
    print('=' * 60)
    print(f'  Neste computador: http://127.0.0.1:{port}')
    print('  Primeiro acesso: defina ADMIN_SENHA ou rode "flask --app app criar-admin"')
    print('=' * 60 + '\n')
    app.run(debug=False, host='0.0.0.0', port=port)
