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
