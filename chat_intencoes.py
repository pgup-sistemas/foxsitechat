"""
Fox Pneus — Classificador de Intenção + SQL Router
====================================================
Detecta o que o usuário quer e gera a query SQL correspondente.
Sem LLM aqui — regras determinísticas para garantir respostas rápidas e corretas.

O fluxo do chat é:
    1. chat.py recebe a pergunta do usuário
    2. classificar_intencao() identifica o tipo de busca
    3. gerar_contexto_sql() executa a query e retorna os dados
    4. O resultado vira o contexto do prompt para o Llama
"""

from __future__ import annotations
import re
import sqlite3
from pathlib import Path
from typing import Optional

BASE_DIR = Path(__file__).resolve().parent
from database import get_conn, DB_PATH

# ---------------------------------------------------------------------------
# Dicionário de filiais: código → nome de exibição (carregado do banco)
# ---------------------------------------------------------------------------
_filial_map: dict[str, str] = {}

def _carregar_filial_map() -> dict[str, str]:
    """Carrega/atualiza o mapeamento código → nome_display da tabela filial."""
    global _filial_map
    try:
        conn = get_conn(DB_PATH)
        rows = conn.execute("SELECT codigo, nome_display FROM filial").fetchall()
        conn.close()
        _filial_map = {r["codigo"]: r["nome_display"] for r in rows}
    except Exception:
        pass
    return _filial_map

def filial_nome(codigo: str) -> str:
    """Converte código de filial para nome de exibição. Retorna o código se não encontrar."""
    if not _filial_map:
        _carregar_filial_map()
    return _filial_map.get(codigo, codigo)

# Carrega ao importar o módulo
_carregar_filial_map()

# ---------------------------------------------------------------------------
# Intenções possíveis
# ---------------------------------------------------------------------------
INTENCOES = {
    "busca_medida":    "usuário quer saber se tem um pneu de medida específica",
    "busca_filial":    "usuário quer saber o estoque de uma filial",
    "busca_veiculo":   "usuário menciona um veículo e quer saber a medida",
    "busca_categoria": "usuário pergunta por categoria (truck, car, agrícola)",
    "busca_marca":     "usuário pergunta por uma marca específica",
    "busca_marcas":    "usuário quer listar todas as marcas disponíveis no estoque",
    "busca_disponivel":"usuário quer saber os pneus disponíveis (sem especificar medida)",
    "lead_cotacao":    "usuário quer fazer uma cotação ou comprar",
    "geral":           "pergunta geral sobre a empresa ou produto",
}

# Mapeamento de termos para filiais
ALIASES_FILIAL = {
    "matriz":       "MATRIZ",
    "manaus":       "MATRIZ",
    "ariquemes":    "ARIQUEMES",
    "ji-paraná":    "JI-PARANA",
    "ji parana":    "JI-PARANA",
    "cacoal":       "CACOAL",
    "porto velho":  "C.AUTO PVH",
    "pvh":          "C.AUTO PVH",
    "vilhena":      "C.AUTO VLH",
    "vlh":          "C.AUTO VLH",
    "parintins":    "PARINTINS",
    "xapuri":       "XAPURI",
}

# Veículos comuns e suas medidas (base inicial — será expandida)
VEICULOS_BASE = {
    ("hilux", None):     ["265/65R17", "265/70R17", "255/70R15"],
    ("ranger", None):    ["265/65R17", "265/70R16"],
    ("s10", None):       ["265/65R17", "265/70R17"],
    ("l200", None):      ["265/65R17", "245/65R17"],
    ("amarok", None):    ["255/55R18", "235/65R17"],
    ("duster", None):    ["215/65R16", "205/60R16"],
    ("strada", None):    ["205/60R15", "205/65R15"],
    ("saveiro", None):   ["185/75R15", "185/65R15"],
    ("gol", None):       ["175/70R14", "175/65R14"],
    ("hb20", None):      ["185/60R15", "175/65R14"],
    ("uno", None):       ["175/70R13", "175/65R14"],
    ("celta", None):     ["175/70R13"],
    ("ka", None):        ["185/60R14", "175/65R14"],
    ("civic", None):     ["205/55R16", "215/45R17"],
    ("corolla", None):   ["205/55R16", "215/45R17"],
    ("cruze", None):     ["215/50R17", "205/55R16"],
    ("onix", None):      ["185/65R15", "175/65R14"],
}

# Padrão de medida de pneu (ex: 185/65R15, 175R14, ou "aro 14")
_PAT_MEDIDA = re.compile(
    r"\b(\d{3}/\d{2,3}[Rr]\d{2}(?:\.\d)?|\d{3,4}[Rr]\d{2}(?:\.\d)?|\d{3,4}-\d{2})\b"
)
_PAT_ARO = re.compile(r"\baro\s*(\d{2})\b", re.IGNORECASE)

# Marcas conhecidas
MARCAS = {
    "pirelli", "bridgestone", "michelin", "goodyear", "dunlop", "continental",
    "firestone", "hankook", "yokohama", "toyo", "kumho", "nexen", "falken",
    "xbri", "sunset", "rotalla", "linglong", "routeway", "crosswind",
    "anteo", "marte", "centauro", "magnum", "durable",
}


# ---------------------------------------------------------------------------
# Classificador
# ---------------------------------------------------------------------------

def classificar_intencao(pergunta: str) -> dict:
    """
    Retorna dict com:
        intencao: str
        medida: str|None
        filial: str|None
        veiculo: str|None
        marca: str|None
        categoria: str|None
        termos: list[str]
    """
    texto = pergunta.lower().strip()
    palavras = re.findall(r"[\w\-\.]+", texto)

    # Extrai medida explícita ou aro
    medida = None
    m = _PAT_MEDIDA.search(pergunta)
    if m:
        medida = m.group(1).upper()
    else:
        a = _PAT_ARO.search(pergunta)
        if a:
            medida = f"ARO{a.group(1)}"  # marcador interno → LIKE %R14%

    # Extrai filial
    filial = None
    for alias, cod in ALIASES_FILIAL.items():
        if alias in texto:
            filial = cod
            break

    # Extrai marca
    marca = None
    for mrc in MARCAS:
        if mrc in texto or mrc.replace(" ", "") in texto:
            marca = mrc.upper()
            break

    # Extrai categoria
    categoria = None
    if any(t in texto for t in ["truck", "caminhão", "caminhao", "carreta", "bi-truck"]):
        categoria = "truck"
    elif any(t in texto for t in ["suv", "4x4", "pickup", "picape"]):
        categoria = "suv"
    elif any(t in texto for t in ["van", "kombi", "sprinter", "ducato", "master"]):
        categoria = "van"
    elif any(t in texto for t in ["carro", "passeio", "sedan", "hatch"]):
        categoria = "car"
    elif any(t in texto for t in ["agric", "trator", "máquina agrícola", "colheitadeira"]):
        categoria = "agricola"
    elif any(t in texto for t in ["empilhadeira", "industrial", "retro"]):
        categoria = "industrial"

    # Extrai veículo
    veiculo = None
    for (nome_v, _), _ in VEICULOS_BASE.items():
        if nome_v in texto:
            veiculo = nome_v
            break

    # Classifica intenção
    intencao = "geral"

    cotacao_terms = ["cotação", "cotacao", "comprar", "compra", "preço", "preco", "valor", "quanto custa"]
    marcas_terms  = ["listar marcas", "quais marcas", "marcas disponíveis", "marcas disponiveis",
                     "que marcas", "lista de marcas", "marcas vocês têm", "marcas voces tem",
                     "marcas tem", "marcas há", "marcas ha"]
    if any(t in texto for t in cotacao_terms):
        intencao = "lead_cotacao"
    elif any(t in texto for t in marcas_terms):
        intencao = "busca_marcas"
    elif medida:
        intencao = "busca_medida"
    elif veiculo:
        intencao = "busca_veiculo"
    elif filial and not categoria and not marca:
        intencao = "busca_filial"
    elif marca:
        intencao = "busca_marca"
    elif categoria:
        intencao = "busca_categoria"
    elif any(t in texto for t in ["disponível", "disponivel", "tem estoque", "tem no estoque", "o que tem"]):
        intencao = "busca_disponivel"

    return {
        "intencao": intencao,
        "medida": medida,
        "filial": filial,
        "veiculo": veiculo,
        "marca": marca,
        "categoria": categoria,
        "termos": palavras,
    }


# ---------------------------------------------------------------------------
# SQL Router — gera contexto para o LLM
# ---------------------------------------------------------------------------

def gerar_contexto_sql(intencao: dict, conn: sqlite3.Connection) -> dict:
    """
    Executa a query correspondente à intenção e retorna:
        dados: list[dict]   — resultado da query
        sql_executado: str  — para debug
        resumo: str         — sumário textual dos dados para o prompt
    """
    dados = []
    sql = ""
    resumo = ""

    # --- Busca por medida -------------------------------------------------
    if intencao["intencao"] == "busca_medida" and intencao["medida"]:
        medida = intencao["medida"]
        filial_where = "AND e.filial = ?" if intencao["filial"] else ""

        # "ARO14" → LIKE '%R14%'; medida completa → igualdade
        import re as _re2
        aro_m = _re2.match(r'^ARO(\d{2})$', medida)
        if aro_m:
            medida_where = "p.medida LIKE ?"
            medida_param = f"%R{aro_m.group(1)}%"
        else:
            medida_where = "p.medida = ?"
            medida_param = medida

        params = [medida_param]
        if intencao["filial"]:
            params.append(intencao["filial"])

        sql = f"""
            WITH ultima_data AS (
                SELECT cod_item, filial, MAX(data_extracao) AS max_data
                FROM estoque GROUP BY cod_item, filial
            )
            SELECT p.cod_item, p.nome, p.marca, p.medida,
                   p.tipo_banda, p.indice_carga, p.codigo_vel,
                   e.filial,
                   COALESCE(f.nome_display, e.filial) AS filial_nome,
                   e.qtd, e.data_extracao
            FROM produto p
            JOIN estoque e ON e.cod_item = p.cod_item
            JOIN ultima_data ud ON ud.cod_item = e.cod_item AND ud.filial = e.filial AND e.data_extracao = ud.max_data
            LEFT JOIN filial f ON f.codigo = e.filial
            WHERE {medida_where}
              {filial_where}
              AND e.qtd > 0
            ORDER BY e.qtd DESC
            LIMIT 20
        """
        rows = conn.execute(sql, params).fetchall()
        dados = [dict(r) for r in rows]

        if dados:
            filiais_unicas = list({d["filial_nome"] for d in dados if d["filial_nome"] not in ("DESCONHECIDA", None)}) or ["várias filiais"]
            total = sum(d["qtd"] for d in dados)
            marcas = list({d["marca"] for d in dados if d["marca"]})
            nomes = list({d["nome"] for d in dados if d["nome"]})[:5]
            resumo = (
                f"Medida {medida}: {len(dados)} opções em estoque. "
                f"Filiais: {', '.join(filiais_unicas)}. "
                f"Estoque total: {total:.0f} unidades. "
                + (f"Marcas: {', '.join(marcas)}. " if marcas else f"Produtos: {'; '.join(nomes)}. ")
            )
        else:
            resumo = f"Medida {medida}: nenhum produto em estoque no momento."

    # --- Busca por filial --------------------------------------------------
    elif intencao["intencao"] == "busca_filial" and intencao["filial"]:
        filial = intencao["filial"]
        sql = """
            SELECT p.categoria, COUNT(DISTINCT p.cod_item) produtos,
                   SUM(e.qtd) total_qtd
            FROM produto p
            JOIN estoque e ON e.cod_item = p.cod_item
            WHERE e.filial = ?
              AND e.qtd > 0
              AND e.data_extracao = (
                  SELECT MAX(e2.data_extracao) FROM estoque e2
                  WHERE e2.cod_item = e.cod_item AND e2.filial = e.filial
              )
            GROUP BY p.categoria
            ORDER BY total_qtd DESC
        """
        rows = conn.execute(sql, [filial]).fetchall()
        dados = [dict(r) for r in rows]

        if dados:
            resumo = f"Estoque na filial {filial_nome(filial)}: " + "; ".join(
                f"{d['categoria']}: {d['produtos']} produtos ({d['total_qtd']:.0f} unidades)"
                for d in dados
            )
        else:
            resumo = f"Filial {filial_nome(filial)}: sem dados de estoque."

    # --- Busca por veículo ------------------------------------------------
    elif intencao["intencao"] == "busca_veiculo" and intencao["veiculo"]:
        veiculo = intencao["veiculo"]
        medidas_compat = []

        # Consulta banco de compatibilidade
        rows = conn.execute("""
            SELECT DISTINCT medida FROM compatibilidade
            WHERE LOWER(veiculo_modelo) LIKE ?
        """, [f"%{veiculo}%"]).fetchall()
        medidas_compat = [r["medida"] for r in rows]

        # Fallback: tabela local
        if not medidas_compat:
            for (nome_v, _), meds in VEICULOS_BASE.items():
                if nome_v == veiculo:
                    medidas_compat = meds
                    break

        if medidas_compat:
            # Busca estoque para cada medida
            disponibilidade = {}
            for med in medidas_compat:
                n = conn.execute("""
                    SELECT COUNT(*) FROM produto p
                    JOIN estoque e ON e.cod_item = p.cod_item
                    WHERE p.medida = ? AND e.qtd > 0
                """, [med]).fetchone()[0]
                disponibilidade[med] = n

            dados = [{"medida": m, "produtos_em_estoque": n} for m, n in disponibilidade.items()]
            resumo = (
                f"Para o {veiculo.upper()}, medidas compatíveis: "
                + ", ".join(
                    f"{m} ({'disponível' if n > 0 else 'sem estoque'})"
                    for m, n in disponibilidade.items()
                )
            )
        else:
            resumo = f"Veículo '{veiculo}' não encontrado na base de compatibilidade."

    # --- Busca por categoria -----------------------------------------------
    elif intencao["intencao"] == "busca_categoria" and intencao["categoria"]:
        cat = intencao["categoria"]
        filial_where = "AND e.filial = ?" if intencao["filial"] else ""
        params = [cat]
        if intencao["filial"]:
            params.append(intencao["filial"])

        sql = f"""
            SELECT p.medida, COUNT(DISTINCT p.cod_item) produtos,
                   COUNT(DISTINCT e.filial) filiais, SUM(e.qtd) total
            FROM produto p
            JOIN estoque e ON e.cod_item = p.cod_item
            WHERE p.categoria = ? AND e.qtd > 0
              {filial_where}
              AND e.data_extracao = (
                  SELECT MAX(e2.data_extracao) FROM estoque e2
                  WHERE e2.cod_item = e.cod_item AND e2.filial = e.filial
              )
            GROUP BY p.medida
            ORDER BY total DESC
            LIMIT 15
        """
        rows = conn.execute(sql, params).fetchall()
        dados = [dict(r) for r in rows]

        if dados:
            total_prod = sum(d["produtos"] for d in dados)
            resumo = (
                f"Categoria {cat}: {total_prod} produtos em {len(dados)} medidas diferentes. "
                f"Principais medidas: " + ", ".join(d["medida"] for d in dados[:5])
            )
        else:
            resumo = f"Categoria {cat}: sem estoque disponível."

    # --- Busca por marca ---------------------------------------------------
    elif intencao["intencao"] == "busca_marca" and intencao["marca"]:
        marca = intencao["marca"]
        sql = """
            SELECT p.medida, p.nome, p.categoria,
                   e.filial, COALESCE(f.nome_display, e.filial) AS filial_nome,
                   e.qtd
            FROM produto p
            JOIN estoque e ON e.cod_item = p.cod_item
            LEFT JOIN filial f ON f.codigo = e.filial
            WHERE UPPER(p.marca) = ? AND e.qtd > 0
              AND e.data_extracao = (
                  SELECT MAX(e2.data_extracao) FROM estoque e2
                  WHERE e2.cod_item = e.cod_item AND e2.filial = e.filial
              )
            ORDER BY e.qtd DESC
            LIMIT 20
        """
        rows = conn.execute(sql, [marca]).fetchall()
        dados = [dict(r) for r in rows]

        if dados:
            medidas = list({d["medida"] for d in dados if d["medida"]})
            filiais = list({d["filial_nome"] for d in dados if d["filial_nome"] not in ("DESCONHECIDA", None)})
            filiais_str = ", ".join(filiais) if filiais else "consultar consultor"
            resumo = (
                f"Marca {marca}: {len(dados)} itens em estoque. "
                f"Medidas: {', '.join(medidas[:8])}. "
                f"Filiais confirmadas: {filiais_str}."
            )
        else:
            resumo = f"Marca {marca}: sem estoque disponível."

    # --- Lista de marcas reais do banco -----------------------------------
    elif intencao["intencao"] == "busca_marcas":
        filial_where = "AND e.filial = ?" if intencao["filial"] else ""
        medida_where = ""
        params = []
        if intencao.get("medida"):
            import re as _re3
            aro_m = _re3.match(r'^ARO(\d{2})$', intencao["medida"])
            if aro_m:
                medida_where = "AND p.medida LIKE ?"
                params.append(f"%R{aro_m.group(1)}%")
            else:
                medida_where = "AND p.medida = ?"
                params.append(intencao["medida"])
        if intencao["filial"]:
            params.append(intencao["filial"])
        sql = f"""
            SELECT p.marca, COUNT(DISTINCT p.cod_item) produtos,
                   COUNT(DISTINCT p.medida) medidas, SUM(e.qtd) total
            FROM produto p
            JOIN estoque e ON e.cod_item = p.cod_item
            WHERE p.marca IS NOT NULL AND e.qtd > 0
              {medida_where}
              {filial_where}
              AND e.data_extracao = (
                  SELECT MAX(e2.data_extracao) FROM estoque e2
                  WHERE e2.cod_item = e.cod_item AND e2.filial = e.filial
              )
            GROUP BY p.marca ORDER BY total DESC LIMIT 20
        """
        rows = conn.execute(sql, params).fetchall()
        dados = [dict(r) for r in rows]
        if dados:
            marcas_str = ", ".join(f"{d['marca']} ({d['produtos']} produtos)" for d in dados)
            ctx_extra = f" Medida filtro: {intencao.get('medida')}." if intencao.get("medida") else ""
            ctx_filial = f" Filial: {intencao['filial']}." if intencao.get("filial") else ""
            resumo = f"Marcas disponíveis no estoque Fox Pneus:{ctx_extra}{ctx_filial} {marcas_str}."
        else:
            resumo = "Nenhuma marca encontrada para esse filtro."

    # --- Disponibilidade geral --------------------------------------------
    elif intencao["intencao"] == "busca_disponivel":
        sql = """
            SELECT p.categoria, COUNT(DISTINCT p.medida) medidas,
                   COUNT(DISTINCT p.cod_item) produtos,
                   COUNT(DISTINCT e.filial) filiais
            FROM produto p
            JOIN estoque e ON e.cod_item = p.cod_item
            WHERE e.qtd > 0
              AND e.data_extracao = (
                  SELECT MAX(e2.data_extracao) FROM estoque e2
                  WHERE e2.cod_item = e.cod_item AND e2.filial = e.filial
              )
            GROUP BY p.categoria
            ORDER BY produtos DESC
        """
        rows = conn.execute(sql).fetchall()
        dados = [dict(r) for r in rows]

        if dados:
            resumo = "Estoque disponível por categoria: " + "; ".join(
                f"{d['categoria']} ({d['produtos']} produtos, {d['medidas']} medidas)"
                for d in dados
            )

    # --- Cotação / lead ---------------------------------------------------
    elif intencao["intencao"] == "lead_cotacao":
        resumo = (
            "O usuário quer fazer uma cotação. "
            "Peça: nome, telefone, medida desejada ou veículo, e filial de preferência."
        )

    # --- Geral ------------------------------------------------------------
    else:
        sql = """
            SELECT COUNT(DISTINCT p.cod_item) total_produtos,
                   COUNT(DISTINCT p.medida) total_medidas,
                   COUNT(DISTINCT e.filial) total_filiais,
                   MAX(e.data_extracao) ultima_atualizacao
            FROM produto p JOIN estoque e ON e.cod_item = p.cod_item
            WHERE e.qtd > 0
        """
        row = conn.execute(sql).fetchone()
        if row:
            dados = [dict(row)]
            resumo = (
                f"Fox Pneus tem {row['total_produtos']} produtos em estoque, "
                f"{row['total_medidas']} medidas diferentes, "
                f"distribuídos em {row['total_filiais']} filiais. "
                f"Dados de {row['ultima_atualizacao']}."
            )

    return {"dados": dados, "sql": sql.strip(), "resumo": resumo}
