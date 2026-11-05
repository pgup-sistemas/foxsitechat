"""
Fox Pneus — Carregador de Preços CSV → SQLite
===============================================
Lê o relatório de preços do GoodData e popula a tabela `preco`.

Uso:
    python carregar_precos.py                      # busca CSVs em output/ padrão
    python carregar_precos.py --dir /outro/caminho
    python carregar_precos.py --data 20261023       # filtra por data

Fontes lidas (em ordem de prioridade):
  1. desconto_servicos_varejo_YYYYMMDD.csv  — preços de tabela por transação (maior cobertura)
  2. matriz_precos_pecas_YYYYMMDD.csv       — preços por Cód Fabricação (peças)
"""

import csv
import sys
import time
from collections import defaultdict
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from database import get_conn, DB_PATH

CSV_DIR_DEFAULT = BASE_DIR.parent / "scraping-estoque" / "output"

# Mapeamento de nomes de estabelecimento para código de filial
NOME_PARA_FILIAL = {
    "MATRIZ":          "MATRIZ",
    "FOX PNEUS MATRIZ": "MATRIZ",
    "ARIQUEMES":       "ARIQUEMES",
    "JI-PARANA":       "JI-PARANA",
    "JI PARANA":       "JI-PARANA",
    "JI-PARANÁ":       "JI-PARANA",
    "CACOAL":          "CACOAL",
    "C.AUTO PVH":      "C.AUTO PVH",
    "CAUTO PVH":       "C.AUTO PVH",
    "PORTO VELHO":     "C.AUTO PVH",
    "C.AUTO VLH":      "C.AUTO VLH",
    "CAUTO VLH":       "C.AUTO VLH",
    "VILHENA":         "C.AUTO VLH",
    "PARINTINS":       "PARINTINS",
    "XAPURI":          "XAPURI",
}


def _normalizar_filial(nome: str) -> str | None:
    n = (nome or "").strip().upper()
    return NOME_PARA_FILIAL.get(n)


def _extrair_data(caminho: Path) -> str:
    """Extrai YYYY-MM-DD do nome do arquivo."""
    stem = caminho.stem
    for parte in reversed(stem.split("_")):
        if len(parte) == 8 and parte.isdigit():
            return f"{parte[:4]}-{parte[4:6]}-{parte[6:8]}"
    from datetime import date
    return date.today().isoformat()


def carregar_desconto_varejo(caminho: Path, conn) -> int:
    """
    Lê desconto_servicos_varejo_*.csv.
    Agrupa por (Cód Item, Filial) e salva o preço de tabela mais recente.
    Retorna número de registros inseridos/atualizados.
    """
    data_ref = _extrair_data(caminho)
    # {(cod_item, filial): preco_tabela}
    precos: dict[tuple, float] = {}

    with open(caminho, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            cod = (row.get("Cód Item") or "").strip()
            filial_nome = (row.get("Nome Estabelecimento") or "").strip()
            preco_raw = (row.get("Preço tabela") or "").strip()

            if not cod or not preco_raw:
                continue

            filial = _normalizar_filial(filial_nome)
            if not filial:
                continue

            try:
                preco = float(preco_raw.replace(",", "."))
            except ValueError:
                continue

            if preco <= 0:
                continue

            key = (cod, filial)
            # Mantém o maior preço de tabela (mais completo)
            if key not in precos or preco > precos[key]:
                precos[key] = preco

    if not precos:
        return 0

    cur = conn.cursor()
    for (cod, filial), preco in precos.items():
        # Verifica se cod_item existe no banco
        existe = cur.execute(
            "SELECT 1 FROM produto WHERE cod_item = ?", (cod,)
        ).fetchone()
        if not existe:
            continue

        cur.execute("""
            INSERT INTO preco(cod_item, filial, preco_tabela, fonte, data_referencia)
            VALUES (?, ?, ?, 'desconto_varejo', ?)
            ON CONFLICT DO NOTHING
        """, (cod, filial, preco, data_ref))

    conn.commit()
    return len(precos)


def carregar_precos_pecas(caminho: Path, conn) -> int:
    """
    Lê matriz_precos_pecas_*.csv (Item, Nome Estabelecimento, Cód Fabricação, Preço tabela).
    Faz join via Cód Fabricação → cod_item.
    """
    data_ref = _extrair_data(caminho)
    cur = conn.cursor()
    ok = 0

    with open(caminho, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            cod_fab = (row.get("Cód Fabricação") or "").strip()
            filial_nome = (row.get("Nome Estabelecimento") or "").strip()
            preco_raw = (row.get("Preço tabela") or "").strip()

            if not cod_fab or not preco_raw:
                continue

            filial = _normalizar_filial(filial_nome)
            if not filial:
                continue

            try:
                preco = float(preco_raw.replace(",", "."))
            except ValueError:
                continue

            if preco <= 0:
                continue

            # Busca cod_item via cod_fabricacao
            produto = cur.execute(
                "SELECT cod_item FROM produto WHERE cod_fabricacao = ? LIMIT 1", (cod_fab,)
            ).fetchone()
            if not produto:
                continue

            cur.execute("""
                INSERT INTO preco(cod_item, filial, preco_tabela, fonte, data_referencia)
                VALUES (?, ?, ?, 'precos_pecas', ?)
                ON CONFLICT DO NOTHING
            """, (produto[0], filial, preco, data_ref))
            ok += 1

    conn.commit()
    return ok


def carregar_custo_itens(caminho: Path, conn) -> int:
    """
    Lê estoque_custo_itens_*.csv (Nome Estabelecimento, Item, Custo).
    Faz join via nome do produto para obter cod_item.
    Popula a tabela preco com o custo como referência de preço.
    """
    data_ref = _extrair_data(caminho)
    cur = conn.cursor()

    # Constrói índice nome_upper → cod_item para match rápido
    idx_nome: dict[str, str] = {}
    for row in cur.execute("SELECT cod_item, nome FROM produto").fetchall():
        idx_nome[row[1].strip().upper()] = row[0]

    ok = 0
    with open(caminho, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            filial_nome = (row.get("Nome Estabelecimento") or "").strip()
            item = (row.get("Item") or "").strip()
            custo_raw = (row.get("Custo") or "").strip()

            if not item or not custo_raw:
                continue

            filial = _normalizar_filial(filial_nome)
            if not filial:
                continue

            try:
                custo = float(custo_raw.replace(",", "."))
            except ValueError:
                continue

            if custo <= 0:
                continue

            cod = idx_nome.get(item.upper())
            if not cod:
                continue

            cur.execute("""
                INSERT INTO preco(cod_item, filial, preco_tabela, fonte, data_referencia)
                VALUES (?, ?, ?, 'custo_gooddata', ?)
                ON CONFLICT DO NOTHING
            """, (cod, filial, custo, data_ref))
            ok += 1

    conn.commit()
    return ok


def carregar_tudo_precos(csv_dir: Path = CSV_DIR_DEFAULT, filtro_data: str = None):
    conn = get_conn(DB_PATH)
    print(f"\n  Fox Pneus — Carregador de Preços")
    print(f"  Banco: {DB_PATH}")
    print(f"  Dir:   {csv_dir}\n")

    conn.execute("DELETE FROM preco")
    conn.commit()
    print("  Tabela preco limpa.\n")

    total = 0

    # 1. estoque_custo_itens — fonte principal de custo de pneus
    for arq in sorted(csv_dir.glob("estoque_custo_itens_*.csv")):
        if filtro_data and filtro_data not in arq.name:
            continue
        t0 = time.time()
        n = carregar_custo_itens(arq, conn)
        total += n
        print(f"  {arq.name:<50} {n:>6} preços  {time.time()-t0:.1f}s")

    # 2. matriz_precos_pecas — complementar por Cód Fabricação
    for arq in sorted(csv_dir.glob("matriz_precos_pecas_*.csv")):
        if filtro_data and filtro_data not in arq.name:
            continue
        t0 = time.time()
        n = carregar_precos_pecas(arq, conn)
        total += n
        print(f"  {arq.name:<50} {n:>6} preços  {time.time()-t0:.1f}s")

    n_total = conn.execute("SELECT COUNT(*) FROM preco").fetchone()[0]
    n_prod_c_preco = conn.execute("SELECT COUNT(DISTINCT cod_item) FROM preco").fetchone()[0]
    n_prod_total = conn.execute("SELECT COUNT(*) FROM produto").fetchone()[0]

    print(f"\n  Total inseridos : {total:,}")
    print(f"  Registros na tabela preco: {n_total:,}")
    pct = n_prod_c_preco / n_prod_total * 100 if n_prod_total else 0
    print(f"  Produtos com preço: {n_prod_c_preco:,} / {n_prod_total:,} ({pct:.1f}%)")
    print(f"\n  NOTA: preço = custo GoodData (preço de venda virá do MOVERE)")
    conn.close()
    return total


if __name__ == "__main__":
    csv_dir = CSV_DIR_DEFAULT
    filtro_data = None
    args = sys.argv[1:]
    for i, a in enumerate(args):
        if a == "--dir" and i + 1 < len(args):
            csv_dir = Path(args[i + 1])
        elif a == "--data" and i + 1 < len(args):
            filtro_data = args[i + 1]
    carregar_tudo_precos(csv_dir=csv_dir, filtro_data=filtro_data)
