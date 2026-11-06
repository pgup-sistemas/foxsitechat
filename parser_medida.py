"""
Fox Pneus — Parser de Medida de Pneu
=====================================
Extrai campos estruturados a partir do nome livre do item vindo do GoodData/MOVERE.

Uso:
    from parser_medida import parse_item

    p = parse_item("185/65R15 LISO SETULA E-RACE RH05 88H")
    # → {
    #     "medida": "185/65R15",
    #     "largura": 185, "perfil": 65, "aro": 15,
    #     "categoria": "car",
    #     "tipo_banda": "liso",
    #     "indice_carga": "88",
    #     "codigo_velocidade": "H",
    #     "nome_modelo": "SETULA E-RACE RH05",
    #     "tipo_item": "pneu",
    # }

Também funciona como script:
    python parser_medida.py                    # roda testes internos
    python parser_medida.py estoque.csv        # parseia CSV e salva _parsed.csv
"""

import re
import csv
import sys
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Padrões de medida — ordem importa (mais específico primeiro)
# ---------------------------------------------------------------------------

# 1. Radial métrico carro/van/SUV  — 185/65R15, 235/50R19, 175/55R16
_PAT_RADIAL_CAR = re.compile(
    r"(\d{3})/(\d{2,3})R(\d{2}(?:\.\d)?)",
    re.IGNORECASE,
)

# 2. Radial truck — 1000R20, 1100R22, 295/80R22.5, 315/80R22.5, 13R22.5
_PAT_RADIAL_TRUCK_FRAC = re.compile(
    r"(\d{2,3})/(\d{2,3})R(\d{2}(?:\.\d)?)",
    re.IGNORECASE,
)
_PAT_RADIAL_TRUCK_PLAIN = re.compile(
    r"(\d{3,4})R(\d{2}(?:\.\d)?)",
    re.IGNORECASE,
)
_PAT_RADIAL_TRUCK_PLAIN2 = re.compile(
    r"(\d{2})R(\d{2}(?:\.\d)?)",
    re.IGNORECASE,
)

# 3. Diagonal clássico truck/ônibus — 1000-20, 1100-22, 750-16
_PAT_DIAG_TRUCK = re.compile(
    r"(\d{3,4})-(\d{2})",
    re.IGNORECASE,
)

# 4a. Agrícola diagonal — 14.9-28, 18.4-34, 12.4-36, 9.5-24, 8.25-15
_PAT_AGRI_DIAG = re.compile(
    r"(\d{1,3}\.\d{1,2})-(\d{2})",
    re.IGNORECASE,
)

# 4b. Agrícola fracionado com traço — 10.5/80-18, 12.5/80-18, 250/80-18
_PAT_AGRI_FRAC = re.compile(
    r"(\d{1,3}(?:\.\d{1,2})?)/(\d{2})-(\d{2})",
    re.IGNORECASE,
)

# 4c. Formato com L (load range) — 11L-15
_PAT_AGRI_L = re.compile(
    r"(\d{2,3})L-(\d{2})",
    re.IGNORECASE,
)

# 5. Agrícola radial moderno — 520/85R42, 380/90R46, 710/70R38
#    (coberto pelo _PAT_RADIAL_TRUCK_FRAC mas aro ≥ 28 → agrícola)

# 6. Industrial pequeno — 650-10, 600-9, 700-12, 750-15
_PAT_IND = re.compile(
    r"(\d{3})-(\d{1,2}(?:\.\d)?)",
    re.IGNORECASE,
)

# 6b. Industrial skid-steer — 400/60-15.5, 12-16.5, 10-16.5
_PAT_IND_SKID = re.compile(
    r"(\d{2,3}/\d{2}|\d{2})-(\d{2}\.\d)",
    re.IGNORECASE,
)

# 6c. Empilhadeira — 28X9-15, 6-12
_PAT_IND_FORK = re.compile(
    r"(\d{2,3})X(\d{1,2})-(\d{2})",
    re.IGNORECASE,
)

# 6d. Formato americano SUV/4x4 — 31X10.5R15, 33X12.5R18, 35X12.5R20
_PAT_AMERICANO = re.compile(
    r"(\d{2})X(\d{1,2}\.\d)R(\d{2})",
    re.IGNORECASE,
)

# 7. Câmara — CAMARA 16, CAMARA 20, CAMARA ARO 18, CAMARA AR..., CAMARA DE AR..., CÂMARA...
_PAT_CAMARA = re.compile(
    r"^C[AÂ]MARA(?:\s+(?:DE\s+)?AR(?:O)?)?\s+(?:FR[-\s])?(\d{1,2})(?!\.\d*[/-])",
    re.IGNORECASE,
)

# 8. Protetor — PROTETOR 16, PROTETOR 22, PROTETOR ARO 20, PROTETOR CAMARA AR PNEU ARO 20
_PAT_PROTETOR = re.compile(
    r"^PROTETOR\s+(?:(?:CAMARA\s+)?(?:AR\s+)?(?:PNEU\s+)?(?:ARO\s+))?(\d{1,2})(?!\.\d*[/-])",
    re.IGNORECASE,
)

# Índice de carga + código de velocidade no final da string
_PAT_CARGA_VEL = re.compile(
    r"\b(\d{2,3})([A-Z]{1,2})\b",
    re.IGNORECASE,
)

# Tipo de banda
_BANDA_LISO = re.compile(r"\bLISO\b", re.IGNORECASE)
_BANDA_MISTO = re.compile(r"\bMISTO\b|\bA/T\b|\bA\+T\b", re.IGNORECASE)
_BANDA_BORR = re.compile(r"\bBORRACHUDO\b|\bBOR\b|\bTG\d+\b", re.IGNORECASE)
_BANDA_ROD = re.compile(r"\bROD\b|\bRODOVIÁR", re.IGNORECASE)

# Marcas comuns — para extrair o modelo removendo marca e medida
_MARCAS = {
    "PIRELLI", "BRIDGESTONE", "MICHELIN", "GOODYEAR", "DUNLOP", "CONTINENTAL",
    "FIRESTONE", "HANKOOK", "YOKOHAMA", "TOYO", "KUMHO", "NEXEN", "FALKEN",
    "NITTO", "COOPER", "BF GOODRICH", "MAXXIS", "PETLAS",
    "XBRI", "SUNSET", "ROTALLA", "LING LONG", "ROUTEWAY", "CROSSWIND",
    "ANTEO", "MARTE", "CENTAURO", "MAGNUM", "DURABLE", "JAPURA",
    "ECOBOR", "IRBOFLEX", "RS", "PIRELLI", "ECOPIA",
    "SETULA", "FUZION", "FORZA", "FORTE", "MASTER",
    "FORMULA", "SESTANTE", "AMANDA",
}

# Sufixos de especificação a ignorar na extração do modelo
_SUFIXOS = re.compile(
    r"\b(TL|TT|XL|M\+S|M&S|\d+PR|SL|C[1-9]|G\d|L\d|R-\d|SC|IF|PHP:\d+)\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Classificação de categoria por aro / largura / padrão
# ---------------------------------------------------------------------------

def _classificar_categoria(
    largura: Optional[int],
    perfil: Optional[int],
    aro: Optional[float],
    formato: str,
) -> str:
    """Retorna: car, van, truck, agricola, industrial, camara, protetor."""
    if formato in ("camara", "protetor"):
        return formato

    if aro is None:
        return "desconhecido"

    # Agrícola — aro ≥ 24 com largura tipicamente > 12 polegadas, ou formato diagonal agri
    if formato == "agri_diag":
        return "agricola"
    if formato == "radial_frac" and aro >= 28:
        return "agricola"

    # Industrial / empilhadeira — apenas formato explícito (650-10, 600-9)
    if formato == "ind":
        return "industrial"

    # Truck — aro ≥ 17.5, ou largura ≥ 700 (truck diagonal clássico)
    if formato in ("radial_truck_plain", "radial_truck_plain2"):
        return "truck"
    if formato == "diag_truck":
        # largura em mm (ex: 1000-20 → aro 20 → truck)
        if aro >= 19:
            return "truck"
        return "industrial"
    if formato == "radial_frac":
        if aro >= 17.5:
            return "truck"
        # 225/75R16C = van/utilitário
        if largura and largura >= 215 and aro == 16:
            return "van"

    # Car — aro 13-18, largura 155-275
    if formato == "radial_car":
        if aro <= 18 and largura and 155 <= largura <= 275:
            return "car"
        if aro >= 19:
            return "suv"

    return "car"


# ---------------------------------------------------------------------------
# Extrator principal
# ---------------------------------------------------------------------------

def parse_item(nome: str) -> dict:
    """
    Parseia o nome do item e retorna um dicionário com campos estruturados.
    Sempre retorna todas as chaves; None quando não aplicável.
    """
    nome = nome.strip()
    resultado = {
        "nome_original": nome,
        "medida": None,
        "largura": None,
        "perfil": None,
        "aro": None,
        "indice_carga": None,
        "codigo_velocidade": None,
        "categoria": None,
        "tipo_banda": None,
        "nome_modelo": None,
        "tipo_item": "pneu",
        "formato_medida": None,
    }

    nome_upper = nome.upper()

    # --- Câmara de ar ----------------------------------------------------------
    m = _PAT_CAMARA.match(nome_upper)
    if m:
        resultado.update({
            "medida": f"ARO {m.group(1)}",
            "aro": float(m.group(1)),
            "tipo_item": "camara",
            "categoria": "camara",
            "formato_medida": "camara",
        })
        return resultado

    # --- Protetor de câmara ----------------------------------------------------
    m = _PAT_PROTETOR.match(nome_upper)
    if m:
        resultado.update({
            "medida": f"ARO {m.group(1)}",
            "aro": float(m.group(1)),
            "tipo_item": "protetor",
            "categoria": "protetor",
            "formato_medida": "protetor",
        })
        return resultado

    # --- Radial carro (185/65R15) -----------------------------------------------
    m = _PAT_RADIAL_CAR.search(nome_upper)
    if m:
        larg, perf, aro_s = int(m.group(1)), int(m.group(2)), float(m.group(3))
        # Diferencia 185/65R15 (car) de 295/80R22.5 (truck)
        if aro_s <= 22 and larg >= 295:
            pass  # cai no próximo bloco
        elif aro_s <= 20 and larg <= 285:
            medida = f"{larg}/{perf}R{m.group(3)}"
            resultado.update({
                "medida": medida,
                "largura": larg,
                "perfil": perf,
                "aro": aro_s,
                "formato_medida": "radial_car",
                "categoria": _classificar_categoria(larg, perf, aro_s, "radial_car"),
            })
            _preencher_banda_modelo(resultado, nome_upper, medida)
            _preencher_carga_vel(resultado, nome_upper)
            return resultado

    # --- Radial truck fracionado (295/80R22.5, 315/80R22.5, 1000R/...) ---------
    m = _PAT_RADIAL_TRUCK_FRAC.search(nome_upper)
    if m:
        larg, perf, aro_s = int(m.group(1)), int(m.group(2)), float(m.group(3))
        medida = f"{larg}/{perf}R{m.group(3)}"
        resultado.update({
            "medida": medida,
            "largura": larg,
            "perfil": perf,
            "aro": aro_s,
            "formato_medida": "radial_frac",
            "categoria": _classificar_categoria(larg, perf, aro_s, "radial_frac"),
        })
        _preencher_banda_modelo(resultado, nome_upper, medida)
        _preencher_carga_vel(resultado, nome_upper)
        return resultado

    # --- Radial truck sem fração (900R20, 1000R20, 1100R22) --------------------
    m = _PAT_RADIAL_TRUCK_PLAIN.search(nome_upper)
    if m:
        larg, aro_s = int(m.group(1)), float(m.group(2))
        medida = f"{larg}R{m.group(2)}"
        resultado.update({
            "medida": medida,
            "largura": larg,
            "perfil": None,
            "aro": aro_s,
            "formato_medida": "radial_truck_plain",
            "categoria": "truck",
        })
        _preencher_banda_modelo(resultado, nome_upper, medida)
        _preencher_carga_vel(resultado, nome_upper)
        return resultado

    # --- Radial truck 2 dígitos (13R22.5) --------------------------------------
    m = _PAT_RADIAL_TRUCK_PLAIN2.search(nome_upper)
    if m:
        larg, aro_s = int(m.group(1)), float(m.group(2))
        if larg >= 11:  # 11R22.5, 13R22.5 — evita confundir com índice de carga
            medida = f"{larg}R{m.group(2)}"
            resultado.update({
                "medida": medida,
                "largura": larg,
                "perfil": None,
                "aro": aro_s,
                "formato_medida": "radial_truck_plain2",
                "categoria": "truck",
            })
            _preencher_banda_modelo(resultado, nome_upper, medida)
            _preencher_carga_vel(resultado, nome_upper)
            return resultado

    # --- Agrícola fracionado com traço (10.5/80-18, 12.5/80-18, 250/80-18) ----
    m = _PAT_AGRI_FRAC.search(nome_upper)
    if m:
        larg_s, perf_s, aro_s = m.group(1), m.group(2), float(m.group(3))
        medida = f"{larg_s}/{perf_s}-{int(aro_s):02d}"
        resultado.update({
            "medida": medida,
            "perfil": int(perf_s),
            "aro": aro_s,
            "formato_medida": "agri_frac",
            "categoria": "agricola",
        })
        _preencher_banda_modelo(resultado, nome_upper, medida)
        return resultado

    # --- Agrícola com load range L (11L-15) ------------------------------------
    m = _PAT_AGRI_L.search(nome_upper)
    if m:
        larg, aro_s = int(m.group(1)), float(m.group(2))
        medida = f"{larg}L-{int(aro_s):02d}"
        resultado.update({
            "medida": medida,
            "largura": larg,
            "aro": aro_s,
            "formato_medida": "agri_l",
            "categoria": "agricola",
        })
        _preencher_banda_modelo(resultado, nome_upper, medida)
        return resultado

    # --- Agrícola diagonal (14.9-28, 18.4-34, 9.5-24, 8.25-15) ---------------
    m = _PAT_AGRI_DIAG.search(nome_upper)
    if m:
        larg_s, aro_s = m.group(1), float(m.group(2))
        medida = f"{larg_s}-{m.group(2)}"
        resultado.update({
            "medida": medida,
            "largura": None,
            "perfil": None,
            "aro": aro_s,
            "formato_medida": "agri_diag",
            "categoria": "agricola",
        })
        _preencher_banda_modelo(resultado, nome_upper, medida)
        return resultado

    # --- Diagonal truck clássico (1000-20, 1100-22) ----------------------------
    m = _PAT_DIAG_TRUCK.search(nome_upper)
    if m:
        larg, aro = int(m.group(1)), float(m.group(2))
        medida = f"{larg}-{int(aro):02d}"
        resultado.update({
            "medida": medida,
            "largura": larg,
            "perfil": None,
            "aro": aro,
            "formato_medida": "diag_truck",
            "categoria": _classificar_categoria(larg, None, aro, "diag_truck"),
        })
        _preencher_banda_modelo(resultado, nome_upper, medida)
        return resultado

    # --- Industrial skid-steer (400/60-15.5, 12-16.5, 10-16.5) ---------------
    m = _PAT_IND_SKID.search(nome_upper)
    if m:
        larg_s, aro_s = m.group(1), float(m.group(2))
        medida = f"{larg_s}-{m.group(2)}"
        resultado.update({
            "medida": medida,
            "aro": aro_s,
            "formato_medida": "ind_skid",
            "categoria": "industrial",
        })
        _preencher_banda_modelo(resultado, nome_upper, medida)
        return resultado

    # --- Industrial empilhadeira (28X9-15) ------------------------------------
    m = _PAT_IND_FORK.search(nome_upper)
    if m:
        larg, sec, aro = int(m.group(1)), m.group(2), float(m.group(3))
        medida = f"{larg}X{sec}-{int(aro):02d}"
        resultado.update({
            "medida": medida,
            "largura": larg,
            "aro": aro,
            "formato_medida": "ind_fork",
            "categoria": "industrial",
        })
        _preencher_banda_modelo(resultado, nome_upper, medida)
        return resultado

    # --- Industrial pequeno (650-10, 600-9) ------------------------------------
    m = _PAT_IND.search(nome_upper)
    if m:
        larg, aro_s = int(m.group(1)), float(m.group(2))
        medida = f"{larg}-{m.group(2)}"
        resultado.update({
            "medida": medida,
            "largura": larg,
            "perfil": None,
            "aro": aro_s,
            "formato_medida": "ind",
            "categoria": "industrial",
        })
        _preencher_banda_modelo(resultado, nome_upper, medida)
        return resultado

    # --- Formato americano SUV/4x4 (31X10.5R15, 33X12.5R18) --------------------
    m = _PAT_AMERICANO.search(nome_upper)
    if m:
        altura, larg_s, aro_s = int(m.group(1)), m.group(2), float(m.group(3))
        medida = f"{altura}X{larg_s}R{int(aro_s)}"
        categoria = "suv" if aro_s <= 20 else "truck"
        resultado.update({
            "medida": medida,
            "largura": altura,  # altura total em polegadas
            "aro": aro_s,
            "formato_medida": "americano",
            "categoria": categoria,
        })
        _preencher_banda_modelo(resultado, nome_upper, medida)
        _preencher_carga_vel(resultado, nome_upper)
        return resultado

    # Não reconhecido
    resultado["categoria"] = "desconhecido"
    return resultado


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _preencher_banda_modelo(resultado: dict, nome_upper: str, medida: str):
    """Detecta tipo de banda e extrai nome do modelo."""
    # Borrachudo tem prioridade sobre misto (ex: "BOR MISTO" = banda borrachuda)
    if _BANDA_BORR.search(nome_upper):
        resultado["tipo_banda"] = "borrachudo"
    elif _BANDA_LISO.search(nome_upper):
        resultado["tipo_banda"] = "liso"
    elif _BANDA_ROD.search(nome_upper):
        resultado["tipo_banda"] = "rodoviario"
    elif _BANDA_MISTO.search(nome_upper):
        resultado["tipo_banda"] = "misto"

    # Remove medida + sufixos técnicos para isolar o nome do modelo
    modelo = nome_upper
    modelo = modelo.replace(medida.upper(), "").strip()
    modelo = _SUFIXOS.sub(" ", modelo)
    # Remove termos de banda
    for pat in (_BANDA_LISO, _BANDA_MISTO, _BANDA_BORR, _BANDA_ROD):
        modelo = pat.sub(" ", modelo)
    # Limpa espaços múltiplos
    modelo = re.sub(r"\s{2,}", " ", modelo).strip(" -/")
    if modelo:
        resultado["nome_modelo"] = modelo


def _preencher_carga_vel(resultado: dict, nome_upper: str):
    """Extrai índice de carga e código de velocidade (ex: 88H, 103W)."""
    for m in _PAT_CARGA_VEL.finditer(nome_upper):
        carga, vel = m.group(1), m.group(2).upper()
        # Códigos de velocidade válidos
        if vel in {"L","M","N","P","Q","R","S","T","U","H","V","W","Y","Z","ZR"}:
            carga_int = int(carga)
            if 60 <= carga_int <= 220:  # faixa realista
                resultado["indice_carga"] = carga
                resultado["codigo_velocidade"] = vel
                return


# ---------------------------------------------------------------------------
# CLI — parseia CSV
# ---------------------------------------------------------------------------

def _processar_csv(caminho_entrada: str):
    entrada = Path(caminho_entrada)
    saida = entrada.with_stem(entrada.stem + "_parsed")

    CAMPOS_SAIDA = [
        "medida", "largura", "perfil", "aro", "categoria",
        "tipo_banda", "indice_carga", "codigo_velocidade",
        "nome_modelo", "tipo_item", "formato_medida", "nome_original",
    ]

    total = ok = 0
    with open(entrada, encoding="utf-8-sig") as fi, \
         open(saida, "w", newline="", encoding="utf-8") as fo:

        reader = csv.DictReader(fi)
        campos_entrada = reader.fieldnames or []
        # Detecta coluna de nome do item
        col_nome = next(
            (c for c in campos_entrada if c.strip().lower() in ("item", "nome", "descrição", "descricao")),
            campos_entrada[0] if campos_entrada else "Item",
        )

        fieldnames = campos_entrada + [c for c in CAMPOS_SAIDA if c not in campos_entrada]
        writer = csv.DictWriter(fo, fieldnames=fieldnames, extrasaction="ignore", quoting=csv.QUOTE_ALL)
        writer.writeheader()

        for row in reader:
            total += 1
            nome = row.get(col_nome, "").strip()
            parsed = parse_item(nome)
            row.update(parsed)
            writer.writerow(row)
            if parsed["medida"]:
                ok += 1

    print(f"  Entrada:   {entrada}")
    print(f"  Saída:     {saida}")
    print(f"  Total:     {total:,} itens")
    print(f"  Parseados: {ok:,} ({ok/total*100:.1f}%)")
    print(f"  Sem medida:{total-ok:,}")


# ---------------------------------------------------------------------------
# Testes
# ---------------------------------------------------------------------------

CASOS_TESTE = [
    # (nome, medida_esperada, categoria_esperada, banda_esperada)
    ("185/65R15 LISO SETULA E-RACE RH05 88H",           "185/65R15",  "car",        "liso"),
    ("235/50R19 LISO SETULA S RACE RU01 103W XL",        "235/50R19",  "suv",        "liso"),
    ("175/75R14 MISTO A/T CROSSWIND 86T",                "175/75R14",  "car",        "misto"),
    ("265/60R18 MISTO A/T SETULA A-RACE AT08 110T",      "265/60R18",  "car",        "misto"),
    ("1000R20 LISO ROD FR01 146/143K TT",                "1000R20",    "truck",      "liso"),
    ("1100R22 BOR MISTO TG01 151/148K",                  "1100R22",    "truck",      "borrachudo"),
    ("1000-20 RT59 MARTE 16PR",                          "1000-20",    "truck",      None),
    ("1100-22 ANTEO AT59 BORRACHUDO 150/146J 16PR",      "1100-22",    "truck",      "borrachudo"),
    ("295/80R22.5 LISO ROD FG01 152/148K TL",            "295/80R22.5","truck",      "liso"),
    ("14.9-28 TM95 8PR",                                 "14.9-28",    "agricola",   None),
    ("520/85R42 PHP:85 157A8(157B)",                     "520/85R42",  "agricola",   None),
    ("380/90R46 AGRIFLEX+354 R-1W 175D TL",              "380/90R46",  "agricola",   None),
    ("650-10 CI84 10PR",                                 "650-10",     "industrial", None),
    ("700-12 CI84 12PR",                                 "700-12",     "industrial", None),
    ("13R22.5 TG01 TL 156/150K",                         "13R22.5",    "truck",      None),
    ("CAMARA 20 1000R20 V3-06-5",                        "ARO 20",     "camara",     None),
    ("PROTETOR 16 ECOBOR",                               "ARO 16",     "protetor",   None),
    ("PROTETOR 22 ECOBOR (PNEU 1100-22)",                "ARO 22",     "protetor",   None),
    ("31X10.5R15 MISTO A/T+ X-TREK A/T 109S LT",        "31X10.5R15", "suv",        "misto"),
    ("33X12.5R18 MISTO A/T+ BRUTUS T/A LT 10PR TL 118Q","33X12.5R18", "suv",        "misto"),
    ("35X12.5R20 MUD FORZA M/T2 LT 6PR",                "35X12.5R20", "suv",        None),
]


def _run_tests():
    print(f"\n{'='*65}")
    print("  Fox Pneus — Testes do Parser de Medida")
    print(f"{'='*65}\n")
    erros = 0
    for nome, med_esp, cat_esp, banda_esp in CASOS_TESTE:
        r = parse_item(nome)
        ok_med  = r["medida"]    == med_esp
        ok_cat  = r["categoria"] == cat_esp
        ok_banda = banda_esp is None or r["tipo_banda"] == banda_esp
        status = "OK" if (ok_med and ok_cat and ok_banda) else "XX"
        if status == "XX":
            erros += 1
        print(f"  {status} {nome[:52]:<52}")
        if not ok_med:
            print(f"      medida:    esperado={med_esp!r:20} obtido={r['medida']!r}")
        if not ok_cat:
            print(f"      categoria: esperado={cat_esp!r:20} obtido={r['categoria']!r}")
        if not ok_banda:
            print(f"      banda:     esperado={banda_esp!r:20} obtido={r['tipo_banda']!r}")
    print(f"\n  Resultado: {len(CASOS_TESTE)-erros}/{len(CASOS_TESTE)} ok")
    print(f"{'='*65}\n")
    return erros


if __name__ == "__main__":
    if len(sys.argv) > 1:
        _processar_csv(sys.argv[1])
    else:
        _run_tests()
