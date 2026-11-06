"""
Fox Pneus — Carregador CSV → SQLite
=====================================
Lê os CSVs gerados pelo extrair_estoque.py e popula o banco fox_catalog.db.

Uso:
    python carregar_estoque.py                   # carrega todos os CSVs de output/ padrão
    python carregar_estoque.py --data 20261023   # filtra por data específica
    python carregar_estoque.py --dir /outro/path # diretório alternativo de CSVs

Pode ser chamado automaticamente após cada extração:
    python extrair_estoque.py --cada-filial && python carregar_estoque.py
"""

import csv
import json
import sys
import time
from datetime import date, datetime
from pathlib import Path

# Ajusta path para importar módulos do projeto
BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

import os

from database import get_conn, DB_PATH
from parser_medida import parse_item

# Diretório padrão de CSVs — env var FOX_CSV_DIR sobrescreve (usado no Render)
_csv_dir_env = os.environ.get("FOX_CSV_DIR", "").strip()
CSV_DIR_DEFAULT = Path(_csv_dir_env) if _csv_dir_env else BASE_DIR.parent / "scraping-estoque" / "output"

# Mapeamento: sufixo do arquivo → filial
SUFIXO_FILIAL = {
    "MATRIZ":    "MATRIZ",
    "ARIQUEMES": "ARIQUEMES",
    "JI-PARANA": "JI-PARANA",
    "CACOAL":    "CACOAL",
    "CAUTO_PVH": "C.AUTO PVH",
    "CAUTO_VLH": "C.AUTO VLH",
    "PARINTINS":  "PARINTINS",
    "XAPURI":    "XAPURI",
    "TODAS":     None,  # multi-filial — usa coluna Nome Estabelecimento
}

UF_POR_FILIAL = {
    "MATRIZ":    "AM",
    "ARIQUEMES": "RO",
    "JI-PARANA": "RO",
    "CACOAL":    "RO",
    "C.AUTO PVH":"RO",
    "C.AUTO VLH":"RO",
    "PARINTINS":  "AM",
    "XAPURI":    "AC",
    "MANAUS":    "AM",
}


# Mapeamento de código de modelo → marca para pneus truck
# O GoodData não exporta a coluna Marca para truck; a marca está no nome do produto.
_TRUCK_BRAND_PATTERNS = [
    # Bridgestone
    (r"\b(R269|R289|R163S|R167E|R109|M749|M788)\b",        "BRIDGESTONE"),
    # Firestone (FS = Steel, FD = Drive/Destination)
    (r"\b(FS\d{3}|FD\d{3})\b",                             "FIRESTONE"),
    # Michelin (M + 3 dígitos: M7xx, M8xx)
    (r"\bM(7\d{2}|8\d{2})\b",                              "MICHELIN"),
    # Dunlop (D + 3 dígitos: D3xx, D6xx, D7xx, D8xx, D9xx)
    (r"\bD(3\d{2}|6\d{2}|7\d{2}|8\d{2}|9\d{2})[A-Z]?\b",  "DUNLOP"),
    # Triangle (T + 3 dígitos)
    (r"\bT(8\d{2}|7\d{2})\b",                              "TRIANGLE"),
    # Linglong (L + 3 dígitos)
    (r"\bL(\d{3})\b",                                       "LINGLONG"),
    # Vipal (VI- ou RSVI-)
    (r"\b(RSVI-\d+|VI-\d+)\b",                             "VIPAL"),
    # Continental (HCS, HCR, HSC, etc.)
    (r"\b(HCS|HCR|HSC|HSR|HSU)\b",                         "CONTINENTAL"),
    # Goodyear (G + 3xx ou GL série)
    (r"\b(GL\d{3}|G\d{3}[A-Z]?)\b",                        "GOODYEAR"),
    # Triangle (TR + 2 dígitos, T2xx, T7xx, T8xx)
    (r"\b(TR\d{2}|T[278]\d{2})\b",                         "TRIANGLE"),
    # Vipal Robusto / Vittos (nomes por extenso)
    (r"\bROBUSTO\b",                                        "VIPAL"),
    # Firestone TRII / F.TRII
    (r"\bF\.?TRII?\b",                                      "FIRESTONE"),
    # Leao / LS série
    (r"\bLS\d{3}\b",                                        "LEAO"),
    # Sailun (SL série)
    (r"\bSL\d{3}\b",                                        "SAILUN"),
    # Forza
    (r"\bFORZA\b",                                          "FORZA"),
    # Double Road / DR série
    (r"\bDR\d{3}\b",                                        "DOUBLE ROAD"),
    # Tornado (Goodyear linha Tornado — código GL com TORNADO no nome)
    (r"TORNADO",                                            "GOODYEAR"),
    # GHD série (Hankook)
    (r"\bGHD\d{2}\b",                                       "HANKOOK"),
    # Formula G (Goodyear linha Cargo)
    (r"\bFORMULA\s+G\b",                                    "GOODYEAR"),
    # EasyMax D (Dunlop)
    (r"\bEASYMAX\s+D\b",                                    "DUNLOP"),
]

import re as _re
_truck_patterns_compiled = [(_re.compile(p, _re.IGNORECASE), m) for p, m in _TRUCK_BRAND_PATTERNS]

def _inferir_marca_truck(nome: str) -> str | None:
    """Infere a marca de pneu truck a partir do código no nome do produto."""
    for pat, marca in _truck_patterns_compiled:
        if pat.search(nome):
            return marca
    return None


def _detectar_filial_e_data(caminho: Path):
    """Extrai filial e data a partir do nome do arquivo."""
    # ex: estoque_MATRIZ_20261023.csv → (MATRIZ, 2026-10-23)
    stem = caminho.stem.upper()  # estoque_MATRIZ_20261023
    partes = stem.split("_")
    data_str = None
    filial_chave = None

    for p in reversed(partes):
        if len(p) == 8 and p.isdigit():
            data_str = f"{p[:4]}-{p[4:6]}-{p[6:8]}"
        elif p in SUFIXO_FILIAL:
            filial_chave = p

    if not data_str:
        data_str = date.today().isoformat()

    filial_valor = SUFIXO_FILIAL.get(filial_chave) if filial_chave else None
    return filial_valor, data_str, filial_chave


def _coluna(row: dict, *candidatos: str):
    """Busca a primeira coluna existente no row."""
    for c in candidatos:
        if c in row and row[c] is not None:
            return row[c]
    # busca case-insensitive
    row_lower = {k.lower(): v for k, v in row.items()}
    for c in candidatos:
        v = row_lower.get(c.lower())
        if v is not None:
            return v
    return None


def carregar_csv_estoque(caminho: Path, conn, filial_fixo: str = None):
    """Carrega um CSV de estoque no banco. Retorna (linhas_ok, linhas_erro)."""
    filial_detectada, data_extracao, _ = _detectar_filial_e_data(caminho)
    filial_padrao = filial_fixo or filial_detectada

    ok = erro = 0
    cur = conn.cursor()
    t0 = time.time()

    with open(caminho, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            nome = (_coluna(row, "Item", "item", "Nome", "Descrição") or "").strip()
            if not nome:
                erro += 1
                continue

            cod = (_coluna(row, "Cód Item", "cod_item", "Código") or "").strip()
            cod_fab = (_coluna(row, "Cód Fabricação", "cod_fabricacao") or "").strip()
            marca = (_coluna(row, "Marca", "marca") or "").strip()
            if not marca:
                marca = _inferir_marca_truck(nome) or ""
            filial = (
                filial_padrao
                or (_coluna(row, "Nome Estabelecimento", "filial", "Estab") or "").strip()
                or "DESCONHECIDA"
            )
            qtd_raw = _coluna(row, "Saldo em Estoque Atual", "Estoque total Sugestão", "Qtd", "qtd") or "0"
            custo_raw = _coluna(row, "Custo", "custo") or ""

            try:
                qtd = float(str(qtd_raw).replace(",", ".") or 0)
            except (ValueError, TypeError):
                qtd = 0.0

            try:
                custo = float(str(custo_raw).replace(",", ".")) if custo_raw else None
            except (ValueError, TypeError):
                custo = None

            # Parser de medida
            parsed = parse_item(nome)
            medida = parsed.get("medida")

            # Usa cod_item se existir, senão fallback para cod_fab ou hash do nome
            if not cod and cod_fab:
                cod = cod_fab
            if not cod:
                # gera ID interno baseado no nome normalizado
                cod = "AUTO_" + str(abs(hash(nome)) % 10_000_000)

            uf = UF_POR_FILIAL.get(filial.upper(), UF_POR_FILIAL.get(filial, None))

            # Upsert produto
            cur.execute("""
                INSERT INTO produto(
                    cod_item, cod_fabricacao, nome, marca, medida,
                    largura, perfil, aro, categoria, tipo_banda,
                    indice_carga, codigo_vel, nome_modelo, formato_medida,
                    atualizado_em
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'))
                ON CONFLICT(cod_item) DO UPDATE SET
                    cod_fabricacao  = excluded.cod_fabricacao,
                    nome            = excluded.nome,
                    marca           = COALESCE(excluded.marca, produto.marca),
                    medida          = COALESCE(excluded.medida, produto.medida),
                    largura         = COALESCE(excluded.largura, produto.largura),
                    perfil          = COALESCE(excluded.perfil, produto.perfil),
                    aro             = COALESCE(excluded.aro, produto.aro),
                    categoria       = COALESCE(excluded.categoria, produto.categoria),
                    tipo_banda      = COALESCE(excluded.tipo_banda, produto.tipo_banda),
                    indice_carga    = COALESCE(excluded.indice_carga, produto.indice_carga),
                    codigo_vel      = COALESCE(excluded.codigo_vel, produto.codigo_vel),
                    nome_modelo     = COALESCE(excluded.nome_modelo, produto.nome_modelo),
                    formato_medida  = COALESCE(excluded.formato_medida, produto.formato_medida),
                    atualizado_em   = datetime('now')
            """, (
                cod, cod_fab or None, nome, marca or None, medida,
                parsed.get("largura"), parsed.get("perfil"), parsed.get("aro"),
                parsed.get("categoria"), parsed.get("tipo_banda"),
                parsed.get("indice_carga"), parsed.get("codigo_velocidade"),
                parsed.get("nome_modelo"), parsed.get("formato_medida"),
            ))

            # Insere registro de estoque
            cur.execute("""
                INSERT INTO estoque(cod_item, filial, uf, qtd, custo, data_extracao)
                VALUES (?,?,?,?,?,?)
            """, (cod, filial, uf, qtd, custo, data_extracao))

            ok += 1

    conn.commit()
    duracao = time.time() - t0

    # Log da extração
    cur.execute("""
        INSERT INTO extracao_log(data_extracao, report_id, filial, linhas, status, duracao_seg)
        VALUES (?,?,?,?,?,?)
    """, (data_extracao, caminho.name, filial_padrao or "multi", ok + erro, "ok", round(duracao, 2)))
    conn.commit()

    return ok, erro, duracao


def _datas_com_filiais_individuais(arquivos: list) -> set:
    """Retorna datas para as quais existem CSVs de filiais específicas."""
    datas = set()
    for arq in arquivos:
        _, data, filial_chave = _detectar_filial_e_data(arq)
        if filial_chave and filial_chave != "TODAS":
            datas.add(data)
    return datas


def carregar_tudo(csv_dir: Path = CSV_DIR_DEFAULT, filtro_data: str = None):
    """Carrega todos os CSVs de estoque_*.csv do diretório."""
    conn = get_conn()
    print(f"\n  Fox Pneus — Carregador de Estoque")
    print(f"  Banco:  {DB_PATH}")
    print(f"  CSVs:   {csv_dir}")
    if filtro_data:
        print(f"  Filtro data: {filtro_data}")
    print()

    arquivos = sorted(csv_dir.glob("estoque_*.csv"))
    if filtro_data:
        arquivos = [a for a in arquivos if filtro_data in a.name]
    # Exclui _parsed.csv e arquivos não relacionados a estoque de filiais
    arquivos = [a for a in arquivos if "_parsed" not in a.name]
    # Exclui arquivos auxiliares que não são estoque por filial
    _EXCLUIR_SUFIXOS = ("cotacoes_uf", "custo_itens", "pecas_reposicao", "pecas_sugestao")
    arquivos = [a for a in arquivos if not any(s in a.name for s in _EXCLUIR_SUFIXOS)]

    # Deduplicação: pula estoque_TODAS quando existem CSVs individuais para a mesma data
    datas_com_individuais = _datas_com_filiais_individuais(arquivos)
    arquivos_filtrados = []
    pulados = []
    for arq in arquivos:
        _, data, filial_chave = _detectar_filial_e_data(arq)
        if filial_chave == "TODAS" and data in datas_com_individuais:
            pulados.append(arq.name)
            continue
        arquivos_filtrados.append(arq)
    if pulados:
        print(f"  Deduplicação: {len(pulados)} arquivo(s) TODAS ignorados (filiais individuais presentes):")
        for p in pulados:
            print(f"    - {p}")
        print()
    arquivos = arquivos_filtrados

    if not arquivos:
        print("  Nenhum arquivo encontrado.")
        return

    total_ok = total_erro = 0
    for arq in arquivos:
        ok, erro, dur = carregar_csv_estoque(arq, conn)
        total_ok += ok
        total_erro += erro
        print(f"  {arq.name:<45} {ok:>5} linhas  {dur:.1f}s")

    # Estatísticas do banco após carga
    print()
    for tabela in ("produto", "estoque"):
        n = conn.execute(f"SELECT COUNT(*) FROM {tabela}").fetchone()[0]
        print(f"  {tabela:<12}: {n:,} registros")

    cats = conn.execute(
        "SELECT categoria, COUNT(DISTINCT cod_item) n FROM produto GROUP BY categoria ORDER BY n DESC"
    ).fetchall()
    print()
    print("  Produtos por categoria:")
    for r in cats:
        print(f"    {(r['categoria'] or 'N/A'):<15}: {r['n']:>5}")

    # Oculta produtos que não são pneus (categoria desconhecido = peças, filtros, etc.)
    inativos = conn.execute(
        "UPDATE produto SET ativo=0 WHERE categoria='desconhecido' OR categoria IS NULL"
    ).rowcount
    conn.commit()
    if inativos:
        print(f"  Marcados ativo=0: {inativos:,} produtos não-pneus (categoria desconhecido/NULL)")

    conn.close()
    print(f"\n  Total: {total_ok:,} itens carregados, {total_erro} ignorados.\n")


if __name__ == "__main__":
    csv_dir = CSV_DIR_DEFAULT
    filtro_data = None

    args = sys.argv[1:]
    for i, a in enumerate(args):
        if a == "--dir" and i + 1 < len(args):
            csv_dir = Path(args[i + 1])
        elif a == "--data" and i + 1 < len(args):
            filtro_data = args[i + 1]

    carregar_tudo(csv_dir=csv_dir, filtro_data=filtro_data)
