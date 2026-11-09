"""
Fox Pneus — Busca automática de imagens de pneus (SEM API, SEM CADASTRO).

Fontes implementadas:
  XBRI        → raspa xbri.com.br/pneus?busca={modelo}  (SSR Next.js)
  BRIDGESTONE → CDN Scene7 scene7.com/is/image/bridgestone/bridgestone-{slug}-60-full-...
  FIRESTONE   → CDN firestone.com.br/content/dam/consumer/fst/shared/tires/{slug}/hero.jpg
  DUNLOP      → CDN firestone.com.br/content/dam/consumer/fst/shared/tires/{slug}/hero.jpg

Uso:
    python buscar_fotos.py                        # processa todos sem foto
    python buscar_fotos.py --marca BRIDGESTONE    # só uma marca
    python buscar_fotos.py --dry-run              # mostra sem salvar
    python buscar_fotos.py --limit 20             # processa até 20

Dependências:
    pip install requests
"""

import argparse
import re
import sqlite3
import time
import urllib.parse
from pathlib import Path

try:
    import requests
except ImportError:
    raise SystemExit("Instale:  pip install requests beautifulsoup4")

# ---------------------------------------------------------------------------

DB_PATH = Path(__file__).parent / "fox_catalog.db"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
}

SESSAO = requests.Session()
SESSAO.headers.update(HEADERS)

DELAY = 1.5   # segundos entre requisições para não sobrecarregar


# ---------------------------------------------------------------------------
# Utilitários
# ---------------------------------------------------------------------------

def _extrair_modelo_base(nome_modelo: str) -> str:
    """Remove sufixos promocionais e índice de carga/velocidade."""
    if not nome_modelo:
        return ""
    modelo = re.sub(
        r"\s*[-–—]\s*(PROMO[Ç\S]*|BLACK\s*(FRIDAY)?|\d+%|PROMO\b).*",
        "", nome_modelo, flags=re.I
    ).strip()
    modelo = re.sub(r"\s+\d{2,3}[A-Z](/\d{2,3}[A-Z])?\s*$", "", modelo).strip()
    return modelo


# ---------------------------------------------------------------------------
# Fonte 1 — XBRI (xbri.com.br)
# ---------------------------------------------------------------------------

def _nome_busca_xbri(modelo: str) -> str:
    """
    Extrai termo de busca do nome do modelo XBRI.
    'ECOLOGY 88H'            -> 'ECOLOGY'
    'FORZA F2 84T'           -> 'FORZA F2'
    'H/T FORZA HT2 102H'     -> 'FORZA HT2'
    'MUD FORZA M/T 2 120Q'   -> 'MUD FORZA'
    'SPORT+2 EXTRA LOAD 94W' -> 'SPORT+2'
    '+ BRUTUS T/A 107S'      -> 'BRUTUS'
    """
    base = _extrair_modelo_base(modelo)
    # Remove prefixos como "+", "H/T", "M/T" no início que não fazem parte do nome
    base = re.sub(r"^\s*\+\s*", "", base)   # remove "+" inicial
    # Quebra em tokens, remove índices de carga/velocidade e medidas (ex: 115/112Q, 88H, XL)
    tokens = base.split()
    nome_tokens = []
    for tok in tokens:
        # Para quando encontra token que é só número+letra (índice) ou medida com /
        if re.match(r"^\d+(/\d+)?[A-Z]{0,2}$", tok):
            break
        # "EXTRA" e "LOAD" são descritores que geralmente não fazem parte do slug
        if tok.upper() in {"EXTRA", "LOAD", "REINFORCED", "XL", "RF"}:
            break
        nome_tokens.append(tok)
    nome = " ".join(nome_tokens).strip()
    return nome if nome else base.split()[0] if base else ""


def _buscar_xbri(modelo: str) -> str | None:
    """
    Raspa xbri.com.br buscando pelo modelo e retorna a URL da imagem CDN.
    O site retorna HTML com SSR (Next.js), então as URLs já vêm no HTML.
    """
    modelo_base = _extrair_modelo_base(modelo)
    if not modelo_base:
        return None

    nome_busca = _nome_busca_xbri(modelo)
    # Gera termos de busca com fallback progressivo (remove última palavra até achar)
    palavras = nome_busca.split()
    termos = [" ".join(palavras[:n]) for n in range(len(palavras), 0, -1)]

    SESSAO.headers["Referer"] = "https://xbri.com.br/"
    for termo in termos:
        url = f"https://xbri.com.br/pneus?busca={urllib.parse.quote(termo)}"
        try:
            r = SESSAO.get(url, timeout=15)
            if not r.ok:
                continue

            cdn_matches = re.findall(
                r'cdn\.pneufree\.com\.br/CMS/images/ModelosPneu/(XBRI-[^/"\'\\]+)/shopping\.jpg',
                r.text
            )
            if cdn_matches:
                slug = cdn_matches[0]
                return f"https://cdn.pneufree.com.br/CMS/images/ModelosPneu/{slug}/shopping.jpg"

            # Fallback via next/image URL encoded
            next_imgs = re.findall(r'/_next/image\?url=([^"&\s]+)', r.text)
            for encoded in next_imgs:
                decoded = urllib.parse.unquote(encoded)
                if "pneufree" in decoded and "shopping" in decoded and "XBRI" in decoded:
                    return decoded

        except Exception as e:
            print(f"    [XBRI erro: {e}]")
            break

        time.sleep(0.5)   # pausa entre tentativas do mesmo produto

    return None


# ---------------------------------------------------------------------------
# Fonte 2 — Bridgestone (CDN Scene7, público sem autenticação)
# ---------------------------------------------------------------------------

def _slug_simples(modelo: str) -> str:
    """'ALENZA 001' → 'alenza-001', 'ALENZA 001 96H BL' → 'alenza-001'"""
    base = _extrair_modelo_base(modelo)
    # Remove prefixo "+" (marcador de promoção na base de dados)
    base = re.sub(r"^\s*\+\s*", "", base)
    # Remove índices de carga/velocidade que podem aparecer antes de BL/RFT
    base = re.sub(r"\s+\d{2,3}[A-Z](/\d{2,3}[A-Z])?\s*", " ", base).strip()
    # Remove sufixos de equipamento: BL, RFT, NRFT, XL, RF, LT, EL, TOYOTA
    base = re.sub(r"\b(BL|RFT|NRFT|XL|RF|LT|EL|TOYOTA)\b", "", base, flags=re.I).strip()
    # Limpa espaços duplos
    base = re.sub(r"\s+", " ", base).strip()
    return re.sub(r"[\s_]+", "-", base.lower())


def _buscar_bridgestone(modelo: str) -> str | None:
    slug = _slug_simples(modelo)
    if not slug:
        return None
    # Padrão Scene7 Bridgestone: retorna 403 se não achar (não é auth)
    base_url = "https://s7d1.scene7.com/is/image/bridgestone"
    candidatos = [
        f"{base_url}/bridgestone-{slug}-60-full-web-global-consumer?fmt=jpg&wid=400",
        # Variação sem número separado por hífen adicional
        f"{base_url}/bridgestone-{slug.replace('-', '')}-60-full-web-global-consumer?fmt=jpg&wid=400",
    ]
    for url in candidatos:
        try:
            r = SESSAO.head(url, timeout=8, allow_redirects=True)
            if r.status_code == 200:
                return url
        except Exception:
            pass
    return None


# ---------------------------------------------------------------------------
# Fonte 3 — Firestone e Dunlop (CDN firestone.com.br/content/dam)
# ---------------------------------------------------------------------------

# Slugs confirmados ou derivados do catálogo firestone.com.br
_FIRESTONE_OVERRIDES: dict[str, str] = {
    "F-700": "f--700",         # duplo hífen por causa do traço no nome
    "F-700 PLUS": "f--700-plus",
    "F-1000": "f--1000",
    "F-1000 PLUS": "f--1000-plus",
}

def _buscar_firestone_dunlop(modelo: str) -> str | None:
    base = _extrair_modelo_base(modelo)
    # Verifica override manual primeiro
    slug = _FIRESTONE_OVERRIDES.get(base.upper(), _slug_simples(modelo))
    if not slug:
        return None
    # Firestone content/dam – retorna 404 se não existir
    for path in [
        f"https://www.firestone.com.br/content/dam/consumer/fst/shared/tires/{slug}/hero.jpg",
        f"https://www.firestone.com.br/content/dam/consumer/fst/la/tires/{slug}/hero.jpg",
    ]:
        try:
            r = SESSAO.head(path, timeout=8, allow_redirects=True)
            if r.status_code == 200:
                return path
        except Exception:
            pass
    return None


# ---------------------------------------------------------------------------
# Orquestrador — adicione novos scrapers aqui
# ---------------------------------------------------------------------------

SCRAPERS: dict[str, callable] = {
    "XBRI": _buscar_xbri,
    "BRIDGESTONE": _buscar_bridgestone,
    "FIRESTONE": _buscar_firestone_dunlop,
    "DUNLOP": _buscar_firestone_dunlop,
}


def buscar_imagem(marca: str, modelo: str, _medida: str) -> tuple[str | None, str]:
    """Tenta cada scraper disponível para a marca. Retorna (url, fonte)."""
    marca_up = marca.upper().strip()
    scraper = SCRAPERS.get(marca_up)
    if scraper:
        url = scraper(modelo)
        if url:
            return url, marca_up
    return None, ""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def processar(
    marca_filtro: str | None = None,
    dry_run: bool = False,
    limit: int | None = None,
):
    conn = sqlite3.connect(DB_PATH)

    where = "marca IS NOT NULL AND (foto_url IS NULL OR foto_url = '')"
    params: list = []
    if marca_filtro:
        where += " AND UPPER(marca) = ?"
        params.append(marca_filtro.upper())
    else:
        # Sem filtro: processa apenas marcas que têm scraper
        marcas_com_scraper = "', '".join(SCRAPERS.keys())
        where += f" AND UPPER(marca) IN ('{marcas_com_scraper}')"

    sql = (
        f"SELECT cod_item, marca, nome_modelo, medida FROM produto "
        f"WHERE {where} AND categoria IN ('car','suv','van','truck') "
        f"ORDER BY marca, nome_modelo"
    )
    if limit:
        sql += f" LIMIT {int(limit)}"

    rows = conn.execute(sql, params).fetchall()
    total = len(rows)
    marcas_disponiveis = list(SCRAPERS.keys())
    print(f"\nMarcas com scraper: {', '.join(marcas_disponiveis)}")
    print(f"{total} produtos para processar\n", flush=True)

    atualizados = 0
    por_fonte: dict[str, int] = {}
    nao_encontrados: list[str] = []

    for i, (cod, marca, nome_modelo, medida) in enumerate(rows, 1):
        print(f"[{i}/{total}] {marca} | {nome_modelo} | {medida}", flush=True)

        url, fonte = buscar_imagem(marca, nome_modelo or "", medida or "")

        if url:
            print(f"    OK [{fonte}]  {url[:90]}", flush=True)
            if not dry_run:
                conn.execute(
                    "UPDATE produto SET foto_url=? WHERE cod_item=?",
                    (url, cod),
                )
                conn.commit()
            atualizados += 1
            por_fonte[fonte] = por_fonte.get(fonte, 0) + 1
        else:
            print("    NAO encontrou", flush=True)
            nao_encontrados.append(f"{marca} | {nome_modelo} | {medida}")

        time.sleep(DELAY)

    conn.close()

    print(f"\n{'=' * 55}")
    print(f"Resultado: {atualizados}/{total} atualizados" +
          (" (dry-run, nada salvo)" if dry_run else ""))
    for fonte, qtd in por_fonte.items():
        print(f"  {fonte}: {qtd}")

    if nao_encontrados:
        print(f"\nNao encontrados ({len(nao_encontrados)}):")
        for item in nao_encontrados[:20]:
            print(f"  - {item}")


if __name__ == "__main__":
    p = argparse.ArgumentParser(
        description="Popula foto_url usando scrapers de sites publicos"
    )
    p.add_argument("--marca", default=None,
                   help=f"Filtrar por marca. Disponiveis: {', '.join(SCRAPERS.keys())}")
    p.add_argument("--dry-run", action="store_true", help="Mostra sem salvar no banco")
    p.add_argument("--limit", type=int, default=None, help="Limitar nro de produtos")
    args = p.parse_args()
    processar(args.marca, args.dry_run, args.limit)
