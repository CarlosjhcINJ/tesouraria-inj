"""
Camada de banco de dados da Tesouraria INJ.

- No servidor: Postgres permanente, pela variável de ambiente DATABASE_URL.
- No computador (desenvolvimento e testes): SQLite em data/tesouraria.db.

O restante do sistema escreve SQL com "?" como marcador e usa sempre
ON CONFLICT (aceito pelos dois bancos). Esta camada faz a tradução.
"""
import os
import re
import sqlite3
from decimal import Decimal

sqlite3.register_adapter(Decimal, float)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE_URL = os.environ.get('DATABASE_URL', '').strip()
SQLITE_PATH = os.environ.get('SQLITE_PATH', os.path.join(BASE_DIR, 'data', 'tesouraria.db'))

if DATABASE_URL.startswith('postgres://'):
    DATABASE_URL = 'postgresql://' + DATABASE_URL[len('postgres://'):]

IS_PG = DATABASE_URL.startswith('postgresql://')

if IS_PG:
    import psycopg
    from psycopg.rows import dict_row


class Row(dict):
    """Linha que aceita row['col'] e row.col."""
    def __getattr__(self, k):
        try:
            return self[k]
        except KeyError as e:
            raise AttributeError(k) from e

    def keys(self):  # compatibilidade com sqlite3.Row
        return list(super().keys())


_q_re = re.compile(r"\?")


def _pg_sql(sql):
    # Troca "?" por "%s" fora de textos entre aspas simples.
    out, i, in_str = [], 0, False
    for ch in sql:
        if ch == "'":
            in_str = not in_str
            out.append(ch)
        elif ch == '?' and not in_str:
            out.append('%s')
        elif ch == '%' and not in_str:
            out.append('%%')
        else:
            out.append(ch)
    return ''.join(out)


def _row(r):
    """No Postgres os valores vêm de NUMERIC(14,2) como Decimal exato; o resto do sistema recebe o mesmo
    valor em float (já exato aos centavos) para telas, gráficos e JSON."""
    if not IS_PG:
        return Row(dict(r))
    return Row({k: (float(v) if isinstance(v, Decimal) else v) for k, v in r.items()})


class Cursor:
    def __init__(self, cur):
        self._cur = cur

    def fetchone(self):
        r = self._cur.fetchone()
        if r is None:
            return None
        return _row(r)

    def fetchall(self):
        return [_row(r) for r in self._cur.fetchall()]

    @property
    def rowcount(self):
        return self._cur.rowcount


class Conn:
    def __init__(self):
        if IS_PG:
            self._c = psycopg.connect(DATABASE_URL, row_factory=dict_row)
            # datas gravadas pelo banco (CURRENT_TIMESTAMP) no horário de Brasília
            self._c.execute("SET TIME ZONE 'America/Sao_Paulo'")
        else:
            os.makedirs(os.path.dirname(SQLITE_PATH), exist_ok=True)
            self._c = sqlite3.connect(SQLITE_PATH, timeout=15)
            self._c.row_factory = sqlite3.Row
            self._c.execute('PRAGMA foreign_keys = ON')

    def execute(self, sql, params=()):
        if IS_PG:
            cur = self._c.cursor()
            cur.execute(_pg_sql(sql), tuple(params))
            return Cursor(cur)
        return Cursor(self._c.execute(sql, tuple(params)))

    def insert(self, sql, params=()):
        """INSERT que devolve o id criado."""
        if IS_PG:
            cur = self._c.cursor()
            cur.execute(_pg_sql(sql.rstrip().rstrip(';') + ' RETURNING id'), tuple(params))
            return cur.fetchone()['id']
        cur = self._c.execute(sql, tuple(params))
        return cur.lastrowid

    def commit(self):
        self._c.commit()

    def rollback(self):
        self._c.rollback()

    def close(self):
        self._c.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, *_):
        if exc_type:
            self.rollback()
        else:
            self.commit()
        self.close()


def connect():
    return Conn()


# Tipos que mudam entre os bancos
PK = 'SERIAL PRIMARY KEY' if IS_PG else 'INTEGER PRIMARY KEY AUTOINCREMENT'
BLOB = 'BYTEA' if IS_PG else 'BLOB'
# Dinheiro: exato no Postgres (NUMERIC com 2 casas). O SQLite (só uso local/testes) não tem decimal.
MONEY = 'NUMERIC(14,2)' if IS_PG else 'REAL'
NOW = 'CURRENT_TIMESTAMP'


def blob(value):
    """Converte bytes vindos do banco (memoryview no Postgres) em bytes."""
    if value is None:
        return None
    return bytes(value)
