"""
Fox Pneus — API REST (FastAPI)
================================
Backend do catálogo web de pneus.

Instalar dependências:
    pip install fastapi uvicorn

Rodar:
    uvicorn api:app --reload --port 8000

Endpoints:
    GET  /                            health check
    GET  /filiais                     lista filiais
    GET  /medidas                     medidas disponíveis em estoque
    GET  /busca?medida=185/65R15      busca por medida (+ filtros opcionais)
    GET  /busca?categoria=car         busca por categoria
    GET  /produto/{cod_item}          detalhe do produto com estoque por filial
    GET  /disponibilidade/{cod_item}  estoque atual em todas as filiais
    POST /cotacao                     registra lead/cotação
    GET  /cotacao/{id}                consulta cotação (uso interno)
    POST /admin/recarregar            recarrega CSVs no banco (uso interno)
"""

from __future__ import annotations

import json
import os, time, collections, threading
from datetime import date
from pathlib import Path
from typing import Optional, List

BASE_DIR = Path(__file__).resolve().parent

# Carrega variáveis do .env (se existir) sem sobrescrever o ambiente
try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / ".env", override=False)
except ImportError:
    pass

try:
    from fastapi import FastAPI, HTTPException, Query, Request
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.staticfiles import StaticFiles
    from fastapi.responses import FileResponse
    from pydantic import BaseModel
except ImportError:
    raise SystemExit(
        "\n  Instale as dependências:\n"
        "  pip install fastapi uvicorn\n"
    )

from database import get_conn, DB_PATH
from carregar_estoque import carregar_tudo
from chat import responder as chat_responder, ollama_ok, limpar_historico, LLAMA_MODEL

# ---------------------------------------------------------------------------
# Rate limiter simples (in-memory): max N req/min por IP
# ---------------------------------------------------------------------------
_rl_lock    = threading.Lock()
_rl_buckets: dict = collections.defaultdict(list)  # ip → [timestamps]
_RL_MAX     = int(os.environ.get("FOX_RATE_LIMIT", "60"))   # req por janela
_RL_WINDOW  = 60  # segundos

def _rate_limit(request):
    ip = request.client.host if request.client else "unknown"
    now = time.time()
    with _rl_lock:
        timestamps = _rl_buckets[ip]
        # Remove entradas fora da janela
        _rl_buckets[ip] = [t for t in timestamps if now - t < _RL_WINDOW]
        if len(_rl_buckets[ip]) >= _RL_MAX:
            from fastapi import HTTPException
            raise HTTPException(429, "Muitas requisições — tente novamente em instantes.")
        _rl_buckets[ip].append(now)


app = FastAPI(
    title="Fox Pneus — Catálogo API",
    description="Consulta de estoque, produtos e cotações Fox Pneus",
    version="0.1.0",
)

_origins_raw = os.environ.get("FOX_ALLOWED_ORIGINS", "*")
_allowed_origins = [o.strip() for o in _origins_raw.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
    allow_credentials=False,
)

# Serve frontend estático em /static (ex: /static/index.html)
_STATIC = BASE_DIR / "static"
if _STATIC.exists():
    app.mount("/static", StaticFiles(directory=str(_STATIC)), name="static")

@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    ico = _STATIC / "favicon.ico"
    if ico.exists():
        return FileResponse(str(ico))
    from fastapi.responses import Response
    return Response(status_code=204)

@app.get("/site", include_in_schema=False)
@app.get("/", include_in_schema=False, response_model=None)
def serve_frontend():
    """Serve o catálogo web."""
    idx = _STATIC / "index.html"
    if idx.exists():
        return FileResponse(
            str(idx), media_type="text/html",
            headers={"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache"}
        )
    return {"status": "ok", "produtos": _count_produtos(), "medidas": _count_medidas()}

@app.get("/robots.txt", include_in_schema=False)
def robots():
    return FileResponse(str(_STATIC / "robots.txt"), media_type="text/plain")

@app.get("/sitemap.xml", include_in_schema=False)
def sitemap():
    """Sitemap dinâmico com medidas reais do banco."""
    from database import get_conn, DB_PATH
    conn = get_conn(DB_PATH)
    try:
        cur = conn.execute("""
            SELECT DISTINCT p.medida
            FROM produto p
            JOIN estoque e ON e.cod_item = p.cod_item
            WHERE e.qtd > 0 AND p.medida IS NOT NULL
              AND e.data_extracao = (SELECT MAX(data_extracao) FROM estoque)
            ORDER BY p.medida
            LIMIT 500
        """)
        medidas = [r[0] for r in cur.fetchall()]
    except Exception:
        medidas = []
    finally:
        conn.close()

    base = "https://catalogo.redefox.com.br"
    today = date.today().isoformat()
    filiais = ["porto-velho", "manaus", "ji-parana", "ariquemes", "cacoal", "vilhena", "parintins", "xapuri"]

    urls = [
        f"  <url><loc>{base}/</loc><lastmod>{today}</lastmod><changefreq>daily</changefreq><priority>1.0</priority></url>",
    ]
    for filial in filiais:
        urls.append(f"  <url><loc>{base}/?filial={filial}</loc><lastmod>{today}</lastmod><changefreq>daily</changefreq><priority>0.8</priority></url>")
    for medida in medidas:
        import urllib.parse
        slug = urllib.parse.quote(medida, safe="")
        urls.append(f"  <url><loc>{base}/?medida={slug}</loc><lastmod>{today}</lastmod><changefreq>weekly</changefreq><priority>0.7</priority></url>")

    xml = '<?xml version="1.0" encoding="UTF-8"?>\n'
    xml += '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"\n'
    xml += '        xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"\n'
    xml += '        xsi:schemaLocation="http://www.sitemaps.org/schemas/sitemap/0.9 http://www.sitemaps.org/schemas/sitemap/0.9/sitemap.xsd">\n'
    xml += "\n".join(urls)
    xml += "\n</urlset>"

    from fastapi.responses import Response
    return Response(content=xml, media_type="application/xml")

@app.get("/privacidade", include_in_schema=False)
def privacidade():
    return FileResponse(str(_STATIC / "privacidade.html"), media_type="text/html")

@app.get("/termos", include_in_schema=False)
def termos():
    return FileResponse(str(_STATIC / "termos.html"), media_type="text/html")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _conn():
    conn = get_conn(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS eventos (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            tipo        TEXT NOT NULL,
            medida      TEXT,
            filial      TEXT,
            produto_id  TEXT,
            produto_nm  TEXT,
            resultados  INTEGER,
            ip          TEXT,
            cidade_ip   TEXT,
            dispositivo TEXT,
            sessao_id   TEXT,
            criado_em   TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ev_tipo ON eventos(tipo)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ev_medida ON eventos(medida)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ev_criado ON eventos(criado_em)")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS leads (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            nome        TEXT NOT NULL,
            email       TEXT,
            telefone    TEXT,
            cidade      TEXT,
            filial_int  TEXT,
            interesse   TEXT,
            origem      TEXT DEFAULT 'catalogo',
            aceita_email INTEGER DEFAULT 1,
            criado_em   TEXT
        )
    """)
    conn.commit()
    return conn


def _row_to_dict(row) -> dict:
    return dict(row) if row else {}


def _rows_to_list(rows) -> list:
    return [dict(r) for r in rows]


def _whatsapp_link(telefone: str, mensagem: str) -> str:
    """Gera link wa.me com mensagem pré-preenchida."""
    import urllib.parse
    numero = "".join(c for c in telefone if c.isdigit())
    if not numero.startswith("55"):
        numero = "55" + numero
    return f"https://wa.me/{numero}?text={urllib.parse.quote(mensagem)}"


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/api/status", tags=["Sistema"])
def health():
    conn = _conn()
    n_prod = conn.execute("SELECT COUNT(*) FROM produto").fetchone()[0]
    n_est  = conn.execute("SELECT COUNT(*) FROM estoque").fetchone()[0]
    ultima = conn.execute("SELECT MAX(data_extracao) FROM extracao_log").fetchone()[0]
    conn.close()
    return {
        "status": "ok",
        "produtos": n_prod,
        "registros_estoque": n_est,
        "ultima_extracao": ultima,
    }

def _count_produtos():
    try:
        conn = _conn(); n = conn.execute("SELECT COUNT(*) FROM produto").fetchone()[0]; conn.close(); return n
    except: return 0

def _count_medidas():
    try:
        conn = _conn(); n = conn.execute("SELECT COUNT(DISTINCT medida) FROM produto").fetchone()[0]; conn.close(); return n
    except: return 0


# ---------------------------------------------------------------------------
# Filiais
# ---------------------------------------------------------------------------

@app.get("/filiais", tags=["Filiais"])
def listar_filiais():
    conn = _conn()
    rows = conn.execute(
        "SELECT codigo AS cod, nome_display, uf, cidade, whatsapp FROM filial WHERE ativa=1 ORDER BY uf, nome_display"
    ).fetchall()
    conn.close()
    return _rows_to_list(rows)


# ---------------------------------------------------------------------------
# Medidas disponíveis
# ---------------------------------------------------------------------------

@app.get("/medidas", tags=["Catálogo"])
def listar_medidas(
    categoria: Optional[str] = Query(None, description="car | truck | agricola | industrial"),
    filial: Optional[str] = Query(None, description="MATRIZ | ARIQUEMES | ..."),
    busca: Optional[str] = Query(None, description="prefixo para autocomplete, ex: 185"),
    limite: int = Query(200, le=500),
):
    """Lista todas as medidas com estoque > 0. Com `busca`, retorna formato para autocomplete."""
    conn = _conn()
    where = ["p.medida IS NOT NULL", "e.qtd > 0"]
    params: list = []

    if categoria:
        where.append("p.categoria = ?")
        params.append(categoria.lower())
    if filial:
        where.append("e.filial = ?")
        params.append(filial.upper())
    if busca:
        import re as _re
        b = busca.upper().strip()
        aro = _re.match(r'^(?:ARO\s*)?(\d{2})$', b)
        if aro:
            where.append("p.medida LIKE ?")
            params.append(f"%R{aro.group(1)}%")
        else:
            where.append("p.medida LIKE ?")
            params.append(f"%{b}%")

    sql = f"""
        WITH ultima_data AS (
            SELECT cod_item, filial, MAX(data_extracao) AS max_data
            FROM estoque GROUP BY cod_item, filial
        ),
        estoque_atual AS (
            SELECT e.cod_item, e.filial, e.qtd
            FROM estoque e
            JOIN ultima_data ud ON ud.cod_item = e.cod_item
                AND ud.filial = e.filial AND e.data_extracao = ud.max_data
        )
        SELECT p.medida, p.categoria, p.aro, COUNT(DISTINCT p.cod_item) n_produtos,
               COUNT(DISTINCT e.filial) n_filiais, SUM(e.qtd) total
        FROM produto p
        JOIN estoque_atual e ON e.cod_item = p.cod_item
        WHERE {' AND '.join(where)}
        GROUP BY p.medida, p.categoria, p.aro
        ORDER BY total DESC, p.medida
        LIMIT ?
    """
    rows = conn.execute(sql, params + [limite]).fetchall()
    conn.close()
    result = _rows_to_list(rows)
    return {"medidas": result} if busca else result


# ---------------------------------------------------------------------------
# Busca de produtos
# ---------------------------------------------------------------------------

@app.get("/busca", tags=["Catálogo"])
def buscar_produtos(
    medida: Optional[str]    = Query(None, description="ex: 185/65R15"),
    categoria: Optional[str] = Query(None, description="car | truck | agricola | industrial | camara"),
    marca: Optional[str]     = Query(None),
    filial: Optional[str]    = Query(None, description="MATRIZ | ARIQUEMES | ..."),
    com_estoque: bool        = Query(True, description="apenas produtos com estoque > 0"),
    limite: int              = Query(50, le=200),
    offset: int              = Query(0, ge=0),
):
    """
    Busca produtos por medida, categoria, marca ou filial.
    Retorna lista com estoque atual por filial.
    """
    conn = _conn()
    where = ["1=1"]
    params: list = []

    if medida:
        m = medida.upper().strip()
        # "ARO 14" | "ARO14" | "R14" | "14" → LIKE '%R14%'
        import re as _re
        aro = _re.match(r'^(?:ARO\s*)?(\d{2})$', m)
        if aro:
            where.append("p.medida LIKE ?")
            params.append(f"%R{aro.group(1)}%")
        elif '/' in m or 'R' in m:
            # medida completa ou parcial — tenta exato primeiro, senão LIKE
            where.append("(p.medida = ? OR p.medida LIKE ?)")
            params.extend([m, f"%{m}%"])
        else:
            where.append("p.medida LIKE ?")
            params.append(f"%{m}%")
    if categoria:
        where.append("p.categoria = ?")
        params.append(categoria.lower())
    if marca:
        where.append("p.marca LIKE ?")
        params.append(f"%{marca.upper()}%")

    estoque_join = "LEFT JOIN" if not com_estoque else "JOIN"
    estoque_where = ""
    filial_params = []

    if com_estoque:
        estoque_where = "AND e.qtd > 0 AND e.filial != 'DESCONHECIDA'"
    if filial:
        estoque_where += " AND e.filial = ?"
        filial_params.append(filial.upper())

    # CTE pré-calcula a data mais recente por (cod_item, filial) — evita subquery correlacionada
    sql = f"""
        WITH ultima_data AS (
            SELECT cod_item, filial, MAX(data_extracao) AS max_data
            FROM estoque
            GROUP BY cod_item, filial
        ),
        estoque_atual AS (
            SELECT e.cod_item, e.filial, e.qtd, e.custo
            FROM estoque e
            JOIN ultima_data ud ON ud.cod_item = e.cod_item
                AND ud.filial = e.filial
                AND e.data_extracao = ud.max_data
        )
        SELECT
            p.cod_item, p.cod_fabricacao, p.nome, p.marca, p.medida,
            p.largura, p.perfil, p.aro, p.categoria, p.tipo_banda,
            p.indice_carga, p.codigo_vel, p.nome_modelo, p.foto_url,
            GROUP_CONCAT(DISTINCT e.filial) filiais_com_estoque,
            SUM(e.qtd) total_estoque,
            MIN(e.custo) custo_min, MAX(e.custo) custo_max
        FROM produto p
        {estoque_join} estoque_atual e ON e.cod_item = p.cod_item
            {estoque_where}
        WHERE {' AND '.join(where)}
        GROUP BY p.cod_item
        ORDER BY total_estoque DESC NULLS LAST, p.nome
        LIMIT ? OFFSET ?
    """
    rows = conn.execute(sql, params + filial_params + [limite * 3, offset]).fetchall()
    conn.close()
    resultado = _rows_to_list(rows)

    # Deserializa GROUP_CONCAT para lista
    for r in resultado:
        fe = r.get("filiais_com_estoque")
        r["filiais_com_estoque"] = [f for f in (fe.split(",") if fe else []) if f != "DESCONHECIDA"]

    # Deduplica por nome+medida — mantém o com maior estoque total
    seen: dict[str, dict] = {}
    for r in resultado:
        key = (r.get("nome", "").upper().strip(), r.get("medida", ""))
        if key not in seen or (r.get("total_estoque") or 0) > (seen[key].get("total_estoque") or 0):
            seen[key] = r
    resultado = list(seen.values())[:limite]

    return {"produtos": resultado, "total": len(resultado), "offset": offset}


# ---------------------------------------------------------------------------
# Produto — detalhe completo
# ---------------------------------------------------------------------------

@app.get("/produto/{cod_item}", tags=["Catálogo"])
def detalhe_produto(cod_item: str):
    """Retorna o produto com todo o histórico de estoque por filial."""
    conn = _conn()
    prod = conn.execute(
        "SELECT * FROM produto WHERE cod_item = ?", (cod_item,)
    ).fetchone()
    if not prod:
        raise HTTPException(404, f"Produto '{cod_item}' não encontrado")

    estoque = conn.execute("""
        SELECT filial, uf, qtd, custo, data_extracao
        FROM estoque
        WHERE cod_item = ?
        ORDER BY data_extracao DESC, filial
    """, (cod_item,)).fetchall()

    precos = conn.execute("""
        SELECT filial, preco_tabela, fonte, data_referencia
        FROM preco WHERE cod_item = ?
        ORDER BY data_referencia DESC
    """, (cod_item,)).fetchall()

    conn.close()
    return {
        **_row_to_dict(prod),
        "estoque": _rows_to_list(estoque),
        "precos": _rows_to_list(precos),
    }


# ---------------------------------------------------------------------------
# Disponibilidade
# ---------------------------------------------------------------------------

@app.get("/disponibilidade/{cod_item}", tags=["Catálogo"])
def disponibilidade(cod_item: str):
    """Retorna estoque ATUAL (última extração) em cada filial."""
    conn = _conn()
    rows = conn.execute("""
        WITH ultima_data AS (
            SELECT filial, MAX(data_extracao) AS max_data
            FROM estoque WHERE cod_item = ?
            GROUP BY filial
        )
        SELECT e.filial, f.nome_display, f.uf, f.cidade, f.whatsapp,
               e.qtd, e.custo, e.data_extracao
        FROM estoque e
        JOIN ultima_data ud ON ud.filial = e.filial AND e.data_extracao = ud.max_data
        LEFT JOIN filial f ON f.codigo = e.filial
        WHERE e.cod_item = ? AND e.filial != 'DESCONHECIDA'
        ORDER BY e.qtd DESC
    """, (cod_item, cod_item)).fetchall()

    if not rows:
        conn.close()
        return {"cod_item": cod_item, "filiais": []}

    prod_nome_row = conn.execute("SELECT nome FROM produto WHERE cod_item=?", (cod_item,)).fetchone()
    conn.close()
    prod_nome = prod_nome_row[0] if prod_nome_row else cod_item
    resultado = _rows_to_list(rows)
    for r in resultado:
        r["nome_filial"] = r.pop("nome_display", None)
        if r.get("whatsapp") and r.get("qtd", 0) > 0:
            msg = (
                f"Olá! Tenho interesse no pneu {prod_nome}. "
                f"Vi no site que a filial {r.get('nome_filial', r['filial'])} tem {int(r['qtd'])} unidade(s)."
            )
            r["whatsapp_link"] = _whatsapp_link(r["whatsapp"], msg)
    return {"cod_item": cod_item, "nome": prod_nome, "filiais": resultado}


# ---------------------------------------------------------------------------
# Cotação / Lead
# ---------------------------------------------------------------------------

class LeadRequest(BaseModel):
    nome:         str
    email:        Optional[str] = None
    telefone:     Optional[str] = None
    cidade:       Optional[str] = None
    filial_int:   Optional[str] = None
    interesse:    Optional[str] = None
    aceita_email: bool = True
    origem:       str = "catalogo"

@app.post("/leads", tags=["Marketing"])
def capturar_lead(req: LeadRequest, request: Request):
    """Salva lead de e-mail marketing no banco e envia e-mail de boas-vindas."""
    _rate_limit(request)
    from datetime import datetime
    conn = _conn()
    conn.execute("""
        INSERT INTO leads (nome, email, telefone, cidade, filial_int, interesse, aceita_email, origem, criado_em)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        req.nome, req.email, req.telefone, req.cidade,
        req.filial_int, req.interesse,
        1 if req.aceita_email else 0,
        req.origem,
        datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ))
    conn.commit()
    conn.close()

    if req.email and req.aceita_email:
        try:
            from email_utils import boas_vindas
            boas_vindas(req.nome, req.email)
        except Exception:
            pass  # não bloqueia o cadastro se o e-mail falhar

    return {"ok": True, "mensagem": "Cadastro realizado! Em breve entraremos em contato."}

class EventoRequest(BaseModel):
    tipo:       str                    # busca | wa_click | modal_view | lead_form
    medida:     Optional[str] = None
    filial:     Optional[str] = None
    produto_id: Optional[str] = None
    produto_nm: Optional[str] = None
    resultados: Optional[int] = None
    sessao_id:  Optional[str] = None

@app.post("/eventos", tags=["Analytics"], status_code=201)
def registrar_evento(req: EventoRequest, request: "Request"):
    from datetime import datetime
    import re
    ip_raw = request.headers.get("x-forwarded-for", request.client.host or "")
    ip = ip_raw.split(",")[0].strip()
    ua  = request.headers.get("user-agent", "")
    if "Mobile" in ua or "Android" in ua or "iPhone" in ua:
        dispositivo = "mobile"
    elif "Tablet" in ua or "iPad" in ua:
        dispositivo = "tablet"
    else:
        dispositivo = "desktop"

    cidade_ip = None
    try:
        import urllib.request as _ur, json as _j
        if ip and not ip.startswith(("127.", "192.168.", "10.", "::1")):
            with _ur.urlopen(f"http://ip-api.com/json/{ip}?fields=city&lang=pt-BR", timeout=2) as r:
                cidade_ip = _j.loads(r.read()).get("city")
    except Exception:
        pass

    conn = _conn()
    conn.execute("""
        INSERT INTO eventos (tipo, medida, filial, produto_id, produto_nm, resultados,
                             ip, cidade_ip, dispositivo, sessao_id, criado_em)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
    """, (
        req.tipo, req.medida, req.filial, req.produto_id, req.produto_nm,
        req.resultados, ip, cidade_ip, dispositivo, req.sessao_id,
        datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ))
    conn.commit()
    conn.close()
    return {"ok": True}

@app.get("/admin/analytics", tags=["Analytics"])
def analytics(token: str = Query(...), dias: int = Query(30, le=365)):
    admin_token = os.environ.get("FOX_ADMIN_TOKEN", "fox2024")
    if token != admin_token:
        raise HTTPException(403, "Token inválido")
    conn = _conn()
    desde = f"datetime('now', '-{dias} days')"

    top_buscas = _rows_to_list(conn.execute(f"""
        SELECT medida, COUNT(*) as total, AVG(resultados) as media_resultados
        FROM eventos WHERE tipo='busca' AND medida IS NOT NULL
          AND criado_em >= {desde}
        GROUP BY medida ORDER BY total DESC LIMIT 20
    """).fetchall())

    top_produtos = _rows_to_list(conn.execute(f"""
        SELECT produto_nm, produto_id, COUNT(*) as views
        FROM eventos WHERE tipo='modal_view' AND produto_nm IS NOT NULL
          AND criado_em >= {desde}
        GROUP BY produto_id ORDER BY views DESC LIMIT 15
    """).fetchall())

    wa_clicks = _rows_to_list(conn.execute(f"""
        SELECT produto_nm, filial, COUNT(*) as clicks
        FROM eventos WHERE tipo='wa_click' AND criado_em >= {desde}
        GROUP BY produto_id, filial ORDER BY clicks DESC LIMIT 15
    """).fetchall())

    por_cidade = _rows_to_list(conn.execute(f"""
        SELECT cidade_ip as cidade, COUNT(*) as visitas
        FROM eventos WHERE cidade_ip IS NOT NULL AND criado_em >= {desde}
        GROUP BY cidade_ip ORDER BY visitas DESC LIMIT 10
    """).fetchall())

    por_dispositivo = _rows_to_list(conn.execute(f"""
        SELECT dispositivo, COUNT(*) as total
        FROM eventos WHERE criado_em >= {desde}
        GROUP BY dispositivo ORDER BY total DESC
    """).fetchall())

    por_hora = _rows_to_list(conn.execute(f"""
        SELECT CAST(strftime('%H', criado_em) AS INTEGER) as hora, COUNT(*) as eventos
        FROM eventos WHERE criado_em >= {desde}
        GROUP BY hora ORDER BY hora
    """).fetchall())

    totais = dict(conn.execute(f"""
        SELECT
          COUNT(*) as total,
          SUM(CASE WHEN tipo='busca' THEN 1 ELSE 0 END) as buscas,
          SUM(CASE WHEN tipo='modal_view' THEN 1 ELSE 0 END) as views,
          SUM(CASE WHEN tipo='wa_click' THEN 1 ELSE 0 END) as wa_clicks
        FROM eventos WHERE criado_em >= {desde}
    """).fetchone())

    conn.close()
    return {
        "dias": dias,
        "totais": totais,
        "top_buscas": top_buscas,
        "top_produtos": top_produtos,
        "wa_clicks": wa_clicks,
        "por_cidade": por_cidade,
        "por_dispositivo": por_dispositivo,
        "por_hora": por_hora,
    }

@app.get("/admin", tags=["Marketing"], include_in_schema=False)
def admin_panel():
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/static/admin.html")

@app.get("/admin/leads", tags=["Marketing"])
def listar_leads(token: str = Query(...), limit: int = Query(100, le=500)):
    """Lista leads capturados (requer token admin)."""
    admin_token = os.environ.get("FOX_ADMIN_TOKEN", "fox2024")
    if token != admin_token:
        raise HTTPException(403, "Token inválido")
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM leads ORDER BY criado_em DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return {"leads": _rows_to_list(rows), "total": len(_rows_to_list(rows))}


@app.get("/admin/config", tags=["Admin"])
def get_config(token: str = Query(...)):
    """Retorna todas as configurações editáveis."""
    if token != os.environ.get("FOX_ADMIN_TOKEN", "fox2024"):
        raise HTTPException(403, "Token inválido")
    conn = _conn()
    rows = conn.execute("SELECT chave, valor, descricao FROM config ORDER BY chave").fetchall()
    conn.close()
    return {r["chave"]: {"valor": r["valor"], "descricao": r["descricao"]} for r in rows}


class ConfigSaveRequest(BaseModel):
    token: str
    dados: dict  # {chave: valor}

@app.post("/admin/config", tags=["Admin"])
def save_config(req: ConfigSaveRequest):
    """Salva uma ou mais chaves de configuração."""
    if req.token != os.environ.get("FOX_ADMIN_TOKEN", "fox2024"):
        raise HTTPException(403, "Token inválido")
    conn = _conn()
    from datetime import datetime
    agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for chave, valor in req.dados.items():
        conn.execute(
            "UPDATE config SET valor=?, atualizado_em=? WHERE chave=?",
            (str(valor), agora, chave)
        )
    conn.commit()
    conn.close()
    return {"ok": True, "atualizadas": len(req.dados)}


class CotacaoRequest(BaseModel):
    nome_cliente:     Optional[str] = None
    nome:             Optional[str] = None   # alias frontend
    telefone:         str
    email:            Optional[str] = None
    medida_buscada:   Optional[str] = None
    medida:           Optional[str] = None   # alias frontend
    cod_item:         Optional[str] = None
    veiculo:          Optional[str] = None
    filial_interesse: Optional[str] = None
    filial_id:        Optional[str] = None   # alias frontend
    itens:            Optional[list] = None


@app.post("/cotacao", tags=["Cotação"], status_code=201)
def registrar_cotacao(req: CotacaoRequest, request: Request):
    """Registra um lead de cotação vindo do site."""
    _rate_limit(request)
    conn = _conn()
    nome = req.nome_cliente or req.nome
    medida = req.medida_buscada or req.medida
    filial = req.filial_interesse or req.filial_id
    cur = conn.execute("""
        INSERT INTO lead(nome_cliente, telefone, medida_buscada, veiculo,
                         filial_interesse, itens_json, origem)
        VALUES (?,?,?,?,?,?,?)
    """, (
        nome, req.telefone, medida, req.veiculo,
        filial, json.dumps(req.itens or []), "web",
    ))
    lead_id = cur.lastrowid
    conn.commit()

    # Gera link WhatsApp para a filial escolhida ou principal
    filial_row = conn.execute(
        "SELECT whatsapp, nome_display FROM filial WHERE codigo = ? AND ativa = 1",
        (filial or "MATRIZ",),
    ).fetchone()
    conn.close()

    whatsapp_link = None
    if filial_row and filial_row["whatsapp"]:
        partes = []
        if nome:
            partes.append(f"Olá! Meu nome é {nome}.")
        if medida:
            partes.append(f"Tenho interesse na medida {medida}.")
        if req.veiculo:
            partes.append(f"Veículo: {req.veiculo}.")
        if filial:
            partes.append(f"Prefiro a filial {filial_row['nome_display']}.")
        partes.append("Poderia me passar disponibilidade e preço?")
        whatsapp_link = _whatsapp_link(filial_row["whatsapp"], " ".join(partes))

    # E-mail de confirmação para o cliente
    if req.email:
        try:
            from email_utils import confirmacao_cotacao
            confirmacao_cotacao(
                nome=nome or "",
                email=req.email,
                medida=medida or "",
                filial_nome=filial_row["nome_display"] if filial_row else "",
                wa_link=whatsapp_link or "",
            )
        except Exception:
            pass

    return {"id": lead_id, "whatsapp_link": whatsapp_link}


@app.get("/cotacao/{lead_id}", tags=["Cotação"])
def consultar_cotacao(lead_id: int):
    conn = _conn()
    row = conn.execute("SELECT * FROM lead WHERE id = ?", (lead_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "Cotação não encontrada")
    r = _row_to_dict(row)
    if r.get("itens_json"):
        try:
            r["itens"] = json.loads(r["itens_json"])
        except Exception:
            r["itens"] = []
    return r


# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Chat RAG — Llama
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    pergunta: str
    session_id: str = "web"
    stream: bool = False


@app.get("/chat/status", tags=["Chat"])
def chat_status():
    """Verifica se a integração de IA (Groq) está configurada."""
    ok, msg = ollama_ok()
    return {"ok": ok, "mensagem": msg, "modelo": LLAMA_MODEL}


_FILIAL_NOME = {
    "MATRIZ": "Fox Pneus Matriz (Manaus)",
    "ARIQUEMES": "Fox Pneus Ariquemes",
    "JI-PARANA": "Fox Pneus Ji-Paraná",
    "CACOAL": "Fox Pneus Cacoal",
    "C.AUTO PVH": "Fox Pneus Porto Velho",
    "C.AUTO VLH": "Fox Pneus Vilhena",
    "PARINTINS": "Fox Pneus Parintins",
    "XAPURI": "Fox Pneus Xapuri",
}

def _resumo_natural(intencao: dict, ctx: dict) -> str:
    """Transforma o resumo técnico do SQL em linguagem natural amigável."""
    dados = ctx.get("dados", [])
    intt  = intencao.get("intencao", "geral")

    if not ctx.get("resumo") and not dados:
        return "Poxa, não encontrei nenhum resultado para essa consulta agora. Tente buscar pelo catálogo ou fale com nossa equipe pelo WhatsApp! 💬"

    if intt == "busca_medida" and dados:
        medida   = intencao.get("medida", "")
        filiais  = list({d["filial"] for d in dados if d.get("filial") and d["filial"] != "DESCONHECIDA"})
        marcas   = list({d["marca"]  for d in dados if d.get("marca")})[:4]
        f_nomes  = [_FILIAL_NOME.get(f, f) for f in filiais[:4]]
        qtd_op   = len({d.get("cod_item") for d in dados})
        label    = medida if not medida.startswith("ARO") else f"aro {medida[3:]}"
        txt = f"✅ Temos pneus {label} em estoque! Encontrei **{qtd_op} opções** disponíveis"
        if f_nomes:
            txt += f" em: {', '.join(f_nomes)}"
            if len(filiais) > 4:
                txt += f" e mais {len(filiais)-4} filial(is)"
        txt += "."
        if marcas:
            txt += f"\n\nMarcas disponíveis: {', '.join(marcas)}."
        txt += "\n\nQuer uma cotação? Me passa seu nome e WhatsApp que nossa equipe entra em contato rapidinho! 🛞"
        return txt

    if intt == "busca_filial" and dados:
        filial = _FILIAL_NOME.get(intencao.get("filial",""), intencao.get("filial",""))
        total  = sum(d.get("produtos",0) for d in dados)
        txt = f"📍 A {filial} tem **{total} produtos** em estoque agora."
        cats = [f"{d['categoria']}: {d['produtos']} itens" for d in dados[:4] if d.get("categoria")]
        if cats:
            txt += f"\n\n{chr(10).join(cats)}"
        txt += "\n\nQuer buscar uma medida específica? É só digitar aqui! 😊"
        return txt

    if intt == "busca_veiculo" and dados:
        veiculo = intencao.get("veiculo","").title()
        medidas = list({d.get("medida","") for d in dados if d.get("medida")})[:5]
        txt = f"🛞 Para o **{veiculo}**, as medidas recomendadas são: {', '.join(medidas)}."
        txt += "\n\nTodas com estoque disponível! Quer que eu verifique uma filial específica?"
        return txt

    if intt == "busca_marca" and dados:
        marca = intencao.get("marca","").title()
        qtd   = len({d.get("cod_item") for d in dados})
        txt = f"✅ Temos **{qtd} produtos {marca}** no estoque. Quer filtrar por alguma medida ou filial?"
        return txt

    # fallback genérico
    return ctx.get("resumo") or "Não encontrei o que você procura agora. Fale com nossa equipe pelo WhatsApp! 💬"


@app.post("/chat", tags=["Chat"])
def chat(req: ChatRequest):
    """
    Recebe uma pergunta e retorna resposta do assistente Fox Pneus.
    Com stream=true retorna SSE (text/event-stream), token a token.
    """
    from fastapi.responses import StreamingResponse as _SR
    ok, msg = ollama_ok()

    # Modo degradado (sem Groq)
    if not ok:
        from chat_intencoes import classificar_intencao, gerar_contexto_sql
        conn = get_conn(DB_PATH)
        intencao = classificar_intencao(req.pergunta)
        ctx = gerar_contexto_sql(intencao, conn)
        conn.close()
        resposta = _resumo_natural(intencao, ctx)
        if req.stream:
            def _deg():
                import json as _j
                yield f"data: {_j.dumps({'token': resposta})}\n\n"
                yield "data: [DONE]\n\n"
            return _SR(_deg(), media_type="text/event-stream")
        return {"resposta": resposta, "modo": "degradado_sem_llm", "aviso": msg}

    # Modo streaming SSE
    if req.stream:
        def _sse():
            import json as _j
            # Ping imediato para o fetch() resolver antes do Ollama começar
            yield ": ping\n\n"
            try:
                gen = chat_responder(req.pergunta, session_id=req.session_id, stream=True)
                for tok in gen:
                    yield f"data: {_j.dumps({'token': tok})}\n\n"
            except Exception as e:
                yield f"data: {_j.dumps({'erro': str(e)})}\n\n"
            yield "data: [DONE]\n\n"
        return _SR(_sse(), media_type="text/event-stream",
                   headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    # Modo normal (resposta completa)
    try:
        resposta = chat_responder(req.pergunta, session_id=req.session_id, stream=False)
        return {"resposta": resposta, "modo": "llm", "modelo": LLAMA_MODEL}
    except ConnectionError as e:
        raise HTTPException(503, f"Groq indisponível: {e}")


@app.delete("/chat/historico/{session_id}", tags=["Chat"])
def apagar_historico(session_id: str):
    """Limpa o histórico de uma sessão de chat."""
    limpar_historico(session_id)
    return {"ok": True, "session_id": session_id}


@app.post("/admin/recarregar", tags=["Admin"])
def recarregar_estoque(token: str = Query(..., description="Token de autorização")):
    """Recarrega todos os CSVs de estoque no banco."""
    admin_token = os.environ.get("FOX_ADMIN_TOKEN", "fox2024")
    if token != admin_token:
        raise HTTPException(403, "Token inválido")
    carregar_tudo()
    conn = _conn()
    n = conn.execute("SELECT COUNT(*) FROM produto").fetchone()[0]
    ultima = conn.execute("SELECT MAX(data_extracao) FROM extracao_log").fetchone()[0]
    conn.close()
    return {"status": "ok", "produtos": n, "ultima_extracao": ultima}


# ---------------------------------------------------------------------------
# Busca por veículo (stub — será expandido quando tiver base de compatibilidade)
# ---------------------------------------------------------------------------

@app.get("/veiculo", tags=["Catálogo"])
def buscar_por_veiculo(
    marca:  Optional[str] = Query(None, description="ex: TOYOTA"),
    modelo: Optional[str] = Query(None, description="ex: HILUX"),
    ano:    Optional[int] = Query(None),
):
    """
    Retorna medidas compatíveis com o veículo.
    Aceita só 'modelo' para busca livre, e fallback na base local do chat_intencoes.
    """
    from chat_intencoes import VEICULOS_BASE
    conn = _conn()
    modelo_str = (modelo or "").strip()
    marca_str = (marca or "").strip()

    where = []
    params: list = []
    if marca_str:
        where.append("UPPER(veiculo_marca) LIKE ?")
        params.append(f"%{marca_str.upper()}%")
    if modelo_str:
        where.append("UPPER(veiculo_modelo) LIKE ?")
        params.append(f"%{modelo_str.upper()}%")
    if ano:
        where.append("(ano_inicio IS NULL OR ano_inicio <= ?)")
        where.append("(ano_fim IS NULL OR ano_fim >= ?)")
        params += [ano, ano]

    medidas_rows = []
    if where:
        medidas_rows = conn.execute(f"""
            SELECT DISTINCT medida, posicao, ano_inicio, ano_fim
            FROM compatibilidade
            WHERE {' AND '.join(where)}
            ORDER BY medida
        """, params).fetchall()

    # Fallback: tabela local do classificador de intenção
    medidas_local = []
    if not medidas_rows and modelo_str:
        termo = modelo_str.lower()
        for (nome_v, _), meds in VEICULOS_BASE.items():
            if nome_v in termo or termo in nome_v:
                medidas_local = meds
                break

    medidas = [r["medida"] for r in medidas_rows] if medidas_rows else medidas_local

    disponibilidade = []
    for med in medidas:
        n = conn.execute("""
            SELECT COUNT(DISTINCT p.cod_item) FROM produto p
            JOIN estoque e ON e.cod_item = p.cod_item AND e.qtd > 0
            WHERE p.medida = ?
        """, (med,)).fetchone()[0]
        disponibilidade.append({"medida": med, "produtos_em_estoque": n})

    conn.close()
    nome_v = " ".join(filter(None, [marca_str.upper() if marca_str else None, modelo_str.upper() if modelo_str else None]))
    return {
        "veiculo": nome_v + (f" {ano}" if ano else ""),
        "medidas": [m["medida"] for m in disponibilidade],
        "disponibilidade": disponibilidade,
        "nota": "Base de compatibilidade veicular em construção." if not disponibilidade else None,
    }
