#!/usr/bin/env python3
"""
FOX Analytics Engine — Extração de Estoque GoodData
Extrai dados de estoque de uma filial e salva em CSV para importação em outro sistema.

Uso:
    python extrair_estoque.py
    python extrair_estoque.py --filial MATRIZ
    python extrair_estoque.py --filial "C.AUTO PVH" --report 960907
    python extrair_estoque.py --todas-filiais
    python extrair_estoque.py --cada-filial

Reports disponíveis:
    916024  — Lista de Estoques (padrão)
    960907  — Estoques atacado vs varejo
    419305  — Detalhe estoque Reposição x Local
    774594  — Quantidade Estoque Ano/Mês
    37899   — Valor em Estoque
"""

import urllib.request, json, ssl, sys, time, csv, io, os
from datetime import date
from pathlib import Path

BASE      = "https://analytics.moveresoftware.com"
WS        = "uljodb77ez5d22jaim5mks2y36n5xvr4"
CTX       = ssl.create_default_context()

# Atributo de Estabelecimento/Filial no GoodData
OBJ_ESTAB = f"/gdc/md/{WS}/obj/1584"

# Mapeamento de filial → element id (usado no filtro)
FILIAIS = {
    "MATRIZ":    "/gdc/md/{WS}/obj/1583/elements?id=1",
    "ARIQUEMES": "/gdc/md/{WS}/obj/1583/elements?id=2",
    "JI-PARANA": "/gdc/md/{WS}/obj/1583/elements?id=3",
    "CACOAL":    "/gdc/md/{WS}/obj/1583/elements?id=4",
    "C.AUTO PVH":"/gdc/md/{WS}/obj/1583/elements?id=5",
    "C.AUTO VLH":"/gdc/md/{WS}/obj/1583/elements?id=6",
    "PARINTINS": "/gdc/md/{WS}/obj/1583/elements?id=7",
    "XAPURI":    "/gdc/md/{WS}/obj/1583/elements?id=8",
}

OUT_DIR = Path(__file__).resolve().parent / "output"


class GoodData:
    def __init__(self):
        self.sst = self.tt = None
        self.cookies = {}

    def _req(self, m, p, b=None, h={}, raw=False):
        hh = {"Content-Type": "application/json", "Accept": "application/json", **h}
        if self.cookies:
            hh["Cookie"] = "; ".join(f"{k}={v}" for k, v in self.cookies.items())
        req = urllib.request.Request(
            f"{BASE}{p}", json.dumps(b).encode() if b else None, hh, method=m
        )
        try:
            with urllib.request.urlopen(req, context=CTX, timeout=60) as r:
                for hdr in r.getheaders():
                    if hdr[0].lower() == "set-cookie":
                        pts = hdr[1].split(";")[0].split("=", 1)
                        if len(pts) == 2:
                            self.cookies[pts[0].strip()] = pts[1].strip()
                data = r.read()
                if raw:
                    return r.status, data
                text = data.decode()
                return r.status, json.loads(text) if text.strip() else {}
        except urllib.error.HTTPError as e:
            data = e.read()
            if raw:
                return e.code, data
            try:
                return e.code, json.loads(data.decode())
            except Exception:
                return e.code, {"raw": data.decode()[:300]}

    def login(self, email, pw):
        s, r = self._req("POST", "/gdc/account/login", {
            "postUserLogin": {"login": email, "password": pw, "remember": 0, "verify_level": 2}
        })
        if s not in (200, 201, 302):
            raise RuntimeError(f"Login falhou HTTP {s}: {r}")
        self.sst = r["userLogin"]["token"]
        s, r = self._req("GET", "/gdc/account/token", h={"X-GDC-AuthSST": self.sst})
        self.tt = r["userToken"]["token"]
        return self

    def _tt(self):
        return {"X-GDC-AuthTT": self.tt}

    def _refresh(self):
        s, r = self._req("GET", "/gdc/account/token", h={"X-GDC-AuthSST": self.sst})
        self.tt = r.get("userToken", {}).get("token", self.tt)

    def export(self, report_uri, filtros_extras=None):
        payload = {"report_req": {"report": report_uri}}
        if filtros_extras:
            payload["report_req"]["context"] = {"filters": filtros_extras}

        s, r = self._req("POST", f"/gdc/app/projects/{WS}/execute/raw/", b=payload, h=self._tt())
        if s == 401:
            self._refresh()
            s, r = self._req("POST", f"/gdc/app/projects/{WS}/execute/raw/", b=payload, h=self._tt())
        if s == 201:
            dl_uri = r.get("uri", "") if isinstance(r, dict) else ""
            if dl_uri:
                return self._download(dl_uri)
        if s == 202:
            poll = r.get("asyncTask", {}).get("link", {}).get("poll", "")
            if poll:
                return self._poll(poll)
        if s == 200:
            return 200, r if isinstance(r, bytes) else json.dumps(r).encode()
        return s, r

    def _download(self, uri, tries=20):
        for _ in range(tries):
            s, d = self._req("GET", uri, h=self._tt(), raw=True)
            if s == 200:
                return 200, d
            if s == 202:
                time.sleep(3)
                continue
            if isinstance(d, bytes):
                try:
                    j = json.loads(d.decode())
                    nu = j.get("uri", "")
                    if nu and nu != uri:
                        uri = nu
                        continue
                except Exception:
                    pass
            return s, d
        return 408, b"timeout"

    def _poll(self, uri, tries=20):
        for _ in range(tries):
            time.sleep(3)
            s, r = self._req("GET", uri, h=self._tt())
            if s == 200:
                return 200, r
            if s != 202:
                return s, r
        return 408, {}


def _carregar_credenciais():
    """Tenta carregar credenciais do deliver_config.json do pipeline de atribuição."""
    paths = [
        Path(__file__).resolve().parent.parent / "projetoAnaliseDados" / "pipelines" / "atribuicao" / "deliver_config.json",
        Path(__file__).resolve().parent / "config.json",
    ]
    for p in paths:
        if p.exists():
            try:
                cfg = json.loads(p.read_text(encoding="utf-8"))
                gd = cfg.get("gooddata", {})
                if gd.get("email") and gd.get("senha"):
                    return gd["email"], gd["senha"]
            except Exception:
                pass
    # fallback: variáveis de ambiente
    email = os.environ.get("FOX_GD_EMAIL", "")
    senha = os.environ.get("FOX_GD_SENHA", "")
    if email and senha:
        return email, senha
    # último recurso: input manual
    import getpass
    email = input("Email GoodData: ").strip()
    senha = getpass.getpass(f"Senha ({email}): ")
    return email, senha


def _descobrir_elements_filial(gd, filial_nome):
    """Busca o element ID correto para a filial no GoodData."""
    print(f"  Buscando element ID para filial '{filial_nome}'...", end=" ", flush=True)
    s, r = gd._req("GET", f"/gdc/md/{WS}/obj/1583/elements?limit=50", h=gd._tt())
    if s != 200:
        print(f"ERRO {s}")
        return None
    items = r.get("attributeElements", {}).get("elements", [])
    for item in items:
        title = item.get("title", "").upper().strip()
        if filial_nome.upper() in title or title in filial_nome.upper():
            uri = item.get("uri", "")
            print(f"ok → {uri}")
            return uri
    # tenta buscar com o nome exato
    s, r = gd._req("GET", f"/gdc/md/{WS}/obj/1583/elements?filter={filial_nome}&limit=20", h=gd._tt())
    if s == 200:
        items = r.get("attributeElements", {}).get("elements", [])
        for item in items:
            uri = item.get("uri", "")
            print(f"ok → {uri}")
            return uri
    print("não encontrado — exportando sem filtro de filial")
    return None


def extrair(report_id, filial=None, todas_filiais=False):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    email, senha = _carregar_credenciais()
    print(f"\n{'='*55}")
    print(f"  FOX Analytics Engine — Extração de Estoque")
    print(f"  Report: obj/{report_id}")
    print(f"  Filial: {filial or 'TODAS'}")
    print(f"  Data:   {date.today().strftime('%d/%m/%Y')}")
    print(f"{'='*55}\n")
    gd = GoodData()
    print("  Autenticando no GoodData...", end=" ", flush=True)
    gd.login(email, senha)
    print("ok")
    return _extrair_com_gd(gd, report_id, filial=filial, todas_filiais=todas_filiais)


def _extrair_com_gd(gd, report_id, filial=None, todas_filiais=False):
    """Executa a extração usando uma instância GoodData já autenticada."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    report_uri = f"/gdc/md/{WS}/obj/{report_id}"
    filtros = []

    if filial and not todas_filiais:
        elem_uri = _descobrir_elements_filial(gd, filial)
        if elem_uri:
            filtros.append({
                "uri": OBJ_ESTAB,
                "constraint": {"type": "list", "elements": [elem_uri]}
            })

    sufixo_filial = filial.replace(" ", "_").replace(".", "") if filial else "TODAS"
    nome_arq = f"estoque_{sufixo_filial}_{date.today().strftime('%Y%m%d')}.csv"
    out_path = OUT_DIR / nome_arq

    print(f"  Exportando report obj/{report_id}...", end=" ", flush=True)
    s, data = gd.export(report_uri, filtros_extras=filtros if filtros else None)

    if s == 200 and isinstance(data, bytes):
        linhas_total = max(0, data.count(b"\n") - 1)
        print(f"ok  {linhas_total:,} linhas totais")

        # Filtro local por filial se coluna Nome Estabelecimento existir
        if filial and not todas_filiais:
            text = data.decode("utf-8-sig", errors="replace")
            reader = csv.DictReader(io.StringIO(text))
            rows = list(reader)
            fieldnames = reader.fieldnames or []
            col_estab = next((c for c in fieldnames if "estabelecimento" in c.lower() or "loja" in c.lower()), None)
            if col_estab:
                filtradas = [r for r in rows if filial.upper() in r.get(col_estab, "").upper()]
                print(f"  Filtro '{filial}': {len(filtradas):,} de {len(rows):,} linhas")
                buf = io.StringIO()
                w = csv.DictWriter(buf, fieldnames=fieldnames, quoting=csv.QUOTE_ALL)
                w.writeheader()
                w.writerows(filtradas)
                data = buf.getvalue().encode("utf-8")

        out_path.write_bytes(data)
        linhas_final = max(0, data.count(b"\n") - 1)
        print(f"\n  Salvo em: {out_path}")
        print(f"  Linhas:   {linhas_final:,}")
        print(f"  Tamanho:  {out_path.stat().st_size / 1024:.1f} KB\n")
        return out_path
    else:
        print(f"\n  ERRO HTTP {s}: {str(data)[:200]}")
        sys.exit(1)


def main():
    report_id    = 916024   # Lista de Estoques (padrão)
    filial       = "MATRIZ"
    todas        = False
    cada         = False

    for i, arg in enumerate(sys.argv[1:]):
        if arg == "--filial" and i + 2 <= len(sys.argv) - 1:
            filial = sys.argv[i + 2]
        elif arg == "--report" and i + 2 <= len(sys.argv) - 1:
            report_id = int(sys.argv[i + 2])
        elif arg == "--todas-filiais":
            todas = True
            filial = None
        elif arg == "--cada-filial":
            cada = True

    if cada:
        email, senha = _carregar_credenciais()
        gd = GoodData()
        print("  Autenticando no GoodData...", end=" ", flush=True)
        gd.login(email, senha)
        print("ok\n")
        resultados = []
        for nome_filial in FILIAIS:
            print(f"\n{'-'*55}")
            print(f"  Filial: {nome_filial}")
            print(f"{'-'*55}")
            try:
                path = _extrair_com_gd(gd, report_id, filial=nome_filial)
                resultados.append((nome_filial, path, None))
            except Exception as e:
                print(f"  ERRO: {e}")
                resultados.append((nome_filial, None, str(e)))
        print(f"\n{'='*55}")
        print("  Resumo:")
        for nome, path, erro in resultados:
            if path:
                print(f"  ✓ {nome:15s} → {path.name}")
            else:
                print(f"  ✗ {nome:15s} → ERRO: {erro}")
        print(f"{'='*55}\n")
    else:
        extrair(report_id, filial=filial, todas_filiais=todas)


if __name__ == "__main__":
    main()
