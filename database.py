"""
Fox Pneus — Schema SQLite
==========================
Define e cria o banco fox_catalog.db com todas as tabelas do sistema.

Uso:
    python database.py             # cria/migra o banco
    python database.py --reset     # apaga e recria do zero (CUIDADO)
"""

import sqlite3
import sys
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "fox_catalog.db"

# ---------------------------------------------------------------------------
# DDL — definição das tabelas
# ---------------------------------------------------------------------------

SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- Tabela mestre de produtos (um registro por cod_item único)
CREATE TABLE IF NOT EXISTS produto (
    cod_item        TEXT PRIMARY KEY,        -- código interno GoodData/MOVERE
    cod_fabricacao  TEXT,                    -- código do fabricante
    nome            TEXT NOT NULL,           -- nome original do sistema
    marca           TEXT,
    medida          TEXT,                    -- ex: 185/65R15
    largura         INTEGER,                 -- mm
    perfil          INTEGER,                 -- %
    aro             REAL,                    -- pol
    categoria       TEXT,                    -- car | truck | agricola | industrial | camara | protetor
    tipo_banda      TEXT,                    -- liso | misto | borrachudo | rodoviario
    indice_carga    TEXT,
    codigo_vel      TEXT,
    nome_modelo     TEXT,
    formato_medida  TEXT,
    foto_url        TEXT,                    -- URL da foto (preenchido manualmente / futuramente)
    ativo           INTEGER NOT NULL DEFAULT 1,
    criado_em       TEXT NOT NULL DEFAULT (datetime('now')),
    atualizado_em   TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Índices de busca frequentes
CREATE INDEX IF NOT EXISTS idx_produto_medida     ON produto(medida);
CREATE INDEX IF NOT EXISTS idx_produto_categoria  ON produto(categoria);
CREATE INDEX IF NOT EXISTS idx_produto_marca      ON produto(marca);
CREATE INDEX IF NOT EXISTS idx_produto_aro        ON produto(aro);

-- Estoque por filial (atualizado a cada extração do GoodData)
CREATE TABLE IF NOT EXISTS estoque (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    cod_item        TEXT NOT NULL REFERENCES produto(cod_item) ON DELETE CASCADE,
    filial          TEXT NOT NULL,           -- MATRIZ | ARIQUEMES | ...
    uf              TEXT,                    -- AM | RO | AC
    qtd             REAL NOT NULL DEFAULT 0,
    custo           REAL,
    data_extracao   TEXT NOT NULL,           -- YYYY-MM-DD
    criado_em       TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_estoque_cod    ON estoque(cod_item);
CREATE INDEX IF NOT EXISTS idx_estoque_filial ON estoque(filial);
CREATE INDEX IF NOT EXISTS idx_estoque_data   ON estoque(data_extracao);
CREATE INDEX IF NOT EXISTS idx_estoque_cod_filial_data ON estoque(cod_item, filial, data_extracao);

-- Visão consolidada: estoque atual por produto/filial
-- (sempre pegar data_extracao = MAX)
CREATE VIEW IF NOT EXISTS v_estoque_atual AS
    SELECT
        e.cod_item,
        e.filial,
        e.uf,
        e.qtd,
        e.custo,
        e.data_extracao,
        p.nome,
        p.marca,
        p.medida,
        p.largura,
        p.perfil,
        p.aro,
        p.categoria,
        p.tipo_banda,
        p.foto_url
    FROM estoque e
    JOIN produto p ON p.cod_item = e.cod_item
    WHERE e.data_extracao = (
        SELECT MAX(e2.data_extracao)
        FROM estoque e2
        WHERE e2.cod_item = e.cod_item AND e2.filial = e.filial
    );

-- Preços de tabela por produto/filial (vindos do report 783365 e outros)
CREATE TABLE IF NOT EXISTS preco (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    cod_item        TEXT NOT NULL REFERENCES produto(cod_item) ON DELETE CASCADE,
    filial          TEXT NOT NULL,
    preco_tabela    REAL,
    fonte           TEXT,                    -- report_id ou 'movere'
    data_referencia TEXT NOT NULL,
    criado_em       TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_preco_cod    ON preco(cod_item);
CREATE INDEX IF NOT EXISTS idx_preco_filial ON preco(filial);

-- Tabela de filiais
CREATE TABLE IF NOT EXISTS filial (
    codigo          TEXT PRIMARY KEY,        -- MATRIZ, ARIQUEMES, etc.
    nome_display    TEXT NOT NULL,
    uf              TEXT NOT NULL,
    cidade          TEXT,
    whatsapp        TEXT,                    -- número com DDI: 5592...
    ativa           INTEGER NOT NULL DEFAULT 1
);

-- Compatibilidade veicular (preenchida futuramente)
CREATE TABLE IF NOT EXISTS compatibilidade (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    medida          TEXT NOT NULL,
    veiculo_marca   TEXT NOT NULL,
    veiculo_modelo  TEXT NOT NULL,
    ano_inicio      INTEGER,
    ano_fim         INTEGER,                 -- NULL = até hoje
    posicao         TEXT,                    -- dianteiro | traseiro | todos
    fonte           TEXT                     -- manual | sindipneus | ...
);

CREATE INDEX IF NOT EXISTS idx_compat_medida  ON compatibilidade(medida);
CREATE INDEX IF NOT EXISTS idx_compat_veiculo ON compatibilidade(veiculo_marca, veiculo_modelo);

-- Leads / cotações WhatsApp
CREATE TABLE IF NOT EXISTS lead (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    nome_cliente    TEXT,
    telefone        TEXT,
    medida_buscada  TEXT,
    veiculo         TEXT,
    filial_interesse TEXT,
    itens_json      TEXT,                    -- JSON dos produtos cotados
    status          TEXT NOT NULL DEFAULT 'novo',  -- novo | contatado | fechado | perdido
    origem          TEXT NOT NULL DEFAULT 'web',
    criado_em       TEXT NOT NULL DEFAULT (datetime('now')),
    atualizado_em   TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Configurações editáveis pelo admin (chave/valor)
CREATE TABLE IF NOT EXISTS config (
    chave       TEXT PRIMARY KEY,
    valor       TEXT NOT NULL DEFAULT '',
    descricao   TEXT,
    atualizado_em TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Log de extrações do GoodData
CREATE TABLE IF NOT EXISTS extracao_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    data_extracao   TEXT NOT NULL,
    report_id       TEXT,
    filial          TEXT,
    linhas          INTEGER,
    status          TEXT,                    -- ok | erro
    mensagem        TEXT,
    duracao_seg     REAL,
    criado_em       TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

# Filiais iniciais
FILIAIS_INICIAIS = [
    ("MATRIZ",    "Fox Pneus Matriz",       "AM", "Manaus",     None),
    ("ARIQUEMES", "Fox Pneus Ariquemes",    "RO", "Ariquemes",  None),
    ("JI-PARANA", "Fox Pneus Ji-Paraná",   "RO", "Ji-Paraná",  None),
    ("CACOAL",    "Fox Pneus Cacoal",       "RO", "Cacoal",     None),
    ("C.AUTO PVH","Centauro Auto PVH",      "RO", "Porto Velho", None),
    ("C.AUTO VLH","Centauro Auto Vilhena",  "RO", "Vilhena",    None),
    ("PARINTINS",  "Fox Pneus Parintins",   "AM", "Parintins",  None),
    ("XAPURI",     "Fox Pneus Xapuri",      "AC", "Xapuri",     None),
]


CONFIG_PADRAO = [
    ("empresa_nome",        "Fox Pneus",                           "Nome da empresa"),
    ("empresa_whatsapp",    "5569992323013",                       "WhatsApp com DDI (apenas números)"),
    ("empresa_whatsapp_fmt","(69) 99232-3013",                     "WhatsApp formatado para exibição"),
    ("empresa_email",       "contato@redefox.com.br",              "E-mail de contato"),
    ("empresa_site",        "https://catalogo.redefox.com.br",     "URL do site/catálogo"),
    ("empresa_slogan",      "Pneus em RO, AM e AC",               "Slogan exibido no site e e-mails"),
    ("empresa_filiais",     "Porto Velho · Ji-Paraná · Ariquemes · Cacoal · Vilhena · Manaus · Parintins · Xapuri",
                                                                   "Filiais listadas nos e-mails"),
    ("email_boas_vindas_ativo", "1",                               "Enviar e-mail de boas-vindas ao lead (1=sim, 0=não)"),
]


def criar_banco(db_path: Path = DB_PATH, reset: bool = False) -> sqlite3.Connection:
    """Cria ou abre o banco SQLite, aplicando o schema."""
    if reset and db_path.exists():
        db_path.unlink()
        print(f"  Banco apagado: {db_path}")

    conn = sqlite3.connect(str(db_path), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)

    # Popula filiais se ainda não existirem
    for row in FILIAIS_INICIAIS:
        conn.execute(
            "INSERT OR IGNORE INTO filial(codigo, nome_display, uf, cidade, whatsapp) VALUES (?,?,?,?,?)",
            row,
        )
    # Popula config padrão se ainda não existir
    for chave, valor, desc in CONFIG_PADRAO:
        conn.execute(
            "INSERT OR IGNORE INTO config(chave, valor, descricao) VALUES (?,?,?)",
            (chave, valor, desc),
        )
    conn.commit()
    print(f"  Banco: {db_path}")
    return conn


def get_conn(db_path: Path = DB_PATH) -> sqlite3.Connection:
    """Abre o banco existente (cria se necessário)."""
    if not db_path.exists():
        return criar_banco(db_path)
    conn = sqlite3.connect(str(db_path), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


if __name__ == "__main__":
    reset = "--reset" in sys.argv
    print(f"\n  Fox Pneus — {'Recriando' if reset else 'Criando/verificando'} banco SQLite\n")
    conn = criar_banco(reset=reset)
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tabelas = [r[0] for r in cur]
    print(f"  Tabelas: {', '.join(tabelas)}")
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='view'")
    views = [r[0] for r in cur]
    print(f"  Views:   {', '.join(views)}")
    cur = conn.execute("SELECT COUNT(*) FROM filial")
    print(f"  Filiais: {cur.fetchone()[0]}")
    conn.close()
    print("\n  Pronto.\n")
