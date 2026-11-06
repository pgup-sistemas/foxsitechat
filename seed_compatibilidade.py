"""
Seed da tabela compatibilidade — veículo → medida(s) OEM.
Foco nos modelos mais vendidos no Brasil e comuns no Norte/Centro-Oeste.
Fonte: manuais de proprietário e catálogos Sindipneus / fabricantes.

Executar: python seed_compatibilidade.py
"""
from database import get_conn, DB_PATH

# (marca, modelo, ano_inicio, ano_fim, medidas_oe, posicao)
# medidas_oe: lista de medidas válidas para o modelo/período
DADOS = [
    # ── VOLKSWAGEN ──────────────────────────────────────────────────
    ("VOLKSWAGEN", "GOL",           2008, 2016, ["175/70R13", "175/65R14"], "todos"),
    ("VOLKSWAGEN", "GOL",           2017, None, ["175/65R14", "185/60R14"], "todos"),
    ("VOLKSWAGEN", "VOYAGE",        2008, None, ["175/65R14", "185/60R14"], "todos"),
    ("VOLKSWAGEN", "FOX",           2003, 2017, ["175/70R13", "175/65R14"], "todos"),
    ("VOLKSWAGEN", "UP",            2014, None, ["175/65R14", "185/60R14"], "todos"),
    ("VOLKSWAGEN", "POLO",          2018, None, ["195/55R16", "205/55R16"], "todos"),
    ("VOLKSWAGEN", "VIRTUS",        2018, None, ["195/55R16", "205/55R16"], "todos"),
    ("VOLKSWAGEN", "JETTA",         2011, 2018, ["205/55R16", "225/45R17"], "todos"),
    ("VOLKSWAGEN", "JETTA",         2019, None, ["205/55R16", "225/45R17"], "todos"),
    ("VOLKSWAGEN", "T-CROSS",       2019, None, ["195/60R16", "205/50R17"], "todos"),
    ("VOLKSWAGEN", "TIGUAN",        2017, None, ["215/55R17", "225/45R18"], "todos"),
    ("VOLKSWAGEN", "AMAROK",        2010, None, ["255/60R18", "265/60R18", "255/55R19"], "todos"),
    ("VOLKSWAGEN", "SAVEIRO",       2009, None, ["185/70R14", "195/65R15"], "todos"),
    ("VOLKSWAGEN", "KOMBI",         1999, 2013, ["185R14", "205/75R14"], "todos"),

    # ── FIAT ────────────────────────────────────────────────────────
    ("FIAT", "UNO",                 2010, None, ["175/70R13", "175/65R14"], "todos"),
    ("FIAT", "PALIO",               2000, 2017, ["175/70R13", "175/65R14"], "todos"),
    ("FIAT", "SIENA",               2000, 2017, ["175/70R13", "175/65R14"], "todos"),
    ("FIAT", "PUNTO",               2007, 2017, ["185/65R15", "195/55R15"], "todos"),
    ("FIAT", "BRAVO",               2010, 2015, ["195/55R16", "205/55R16"], "todos"),
    ("FIAT", "ARGO",                2017, None, ["175/65R14", "195/55R15", "195/60R16"], "todos"),
    ("FIAT", "CRONOS",              2018, None, ["185/65R15", "195/55R16"], "todos"),
    ("FIAT", "PULSE",               2021, None, ["195/60R16", "215/50R17"], "todos"),
    ("FIAT", "FASTBACK",            2022, None, ["215/50R17", "225/45R18"], "todos"),
    ("FIAT", "TORO",                2016, None, ["215/65R16", "225/50R18"], "todos"),
    ("FIAT", "STRADA",              2020, None, ["195/65R15", "205/60R16"], "todos"),
    ("FIAT", "DOBLO",               2010, None, ["195/65R15", "205/60R16"], "todos"),
    ("FIAT", "DUCATO",              2010, None, ["225/75R16", "215/75R16"], "todos"),

    # ── CHEVROLET ───────────────────────────────────────────────────
    ("CHEVROLET", "ONIX",           2013, 2019, ["185/65R15", "195/55R15"], "todos"),
    ("CHEVROLET", "ONIX",           2020, None, ["185/65R15", "195/55R16"], "todos"),
    ("CHEVROLET", "ONIX PLUS",      2020, None, ["195/55R16", "205/55R16"], "todos"),
    ("CHEVROLET", "PRISMA",         2013, 2020, ["185/65R15", "195/55R15"], "todos"),
    ("CHEVROLET", "SPIN",           2012, None, ["195/65R15", "185/65R15"], "todos"),
    ("CHEVROLET", "TRACKER",        2013, 2019, ["215/55R17", "225/50R17"], "todos"),
    ("CHEVROLET", "TRACKER",        2020, None, ["215/55R17", "225/45R18"], "todos"),
    ("CHEVROLET", "EQUINOX",        2017, None, ["225/55R18", "235/55R18"], "todos"),
    ("CHEVROLET", "S10",            2012, None, ["245/70R16", "265/60R18", "255/70R16"], "todos"),
    ("CHEVROLET", "TRAILBLAZER",    2012, None, ["265/65R17", "265/60R18"], "todos"),
    ("CHEVROLET", "MONTANA",        2023, None, ["205/60R16", "215/55R17"], "todos"),
    ("CHEVROLET", "CRUZE",          2012, None, ["205/55R16", "215/50R17"], "todos"),

    # ── HYUNDAI ─────────────────────────────────────────────────────
    ("HYUNDAI", "HB20",             2012, 2019, ["175/65R14", "185/60R15"], "todos"),
    ("HYUNDAI", "HB20",             2020, None, ["185/60R15", "195/55R16"], "todos"),
    ("HYUNDAI", "HB20S",            2013, 2019, ["175/65R14", "185/60R15"], "todos"),
    ("HYUNDAI", "CRETA",            2016, 2021, ["205/60R16", "215/55R17"], "todos"),
    ("HYUNDAI", "CRETA",            2022, None, ["215/55R17", "225/45R18"], "todos"),
    ("HYUNDAI", "TUCSON",           2016, None, ["215/60R17", "225/55R18"], "todos"),
    ("HYUNDAI", "IX35",             2010, 2017, ["215/60R17", "215/55R17"], "todos"),
    ("HYUNDAI", "SANTA FE",         2013, None, ["235/60R18", "235/55R19"], "todos"),

    # ── TOYOTA ──────────────────────────────────────────────────────
    ("TOYOTA", "COROLLA",           2008, 2014, ["195/65R15", "205/55R16"], "todos"),
    ("TOYOTA", "COROLLA",           2015, 2018, ["205/55R16", "215/45R17"], "todos"),
    ("TOYOTA", "COROLLA",           2019, None, ["215/45R17", "225/40R18"], "todos"),
    ("TOYOTA", "YARIS",             2018, None, ["185/60R15", "195/50R16"], "todos"),
    ("TOYOTA", "HILUX",             2005, 2015, ["265/65R17", "265/70R16"], "todos"),
    ("TOYOTA", "HILUX",             2016, None, ["265/60R18", "265/65R17"], "todos"),
    ("TOYOTA", "SW4",               2016, None, ["265/60R18", "265/65R17"], "todos"),
    ("TOYOTA", "RAV4",              2013, None, ["225/60R18", "235/55R18"], "todos"),
    ("TOYOTA", "CAMRY",             2012, None, ["215/55R17", "225/50R17"], "todos"),

    # ── HONDA ───────────────────────────────────────────────────────
    ("HONDA", "CIVIC",              2007, 2011, ["195/65R15", "205/55R16"], "todos"),
    ("HONDA", "CIVIC",              2012, 2016, ["205/55R16", "215/45R17"], "todos"),
    ("HONDA", "CIVIC",              2017, None, ["215/45R17", "235/40R18"], "todos"),
    ("HONDA", "FIT",                2009, 2014, ["185/55R16", "195/55R16"], "todos"),
    ("HONDA", "FIT",                2015, None, ["185/55R16", "195/55R16"], "todos"),
    ("HONDA", "HR-V",               2015, None, ["215/55R17", "225/45R18"], "todos"),
    ("HONDA", "CR-V",               2015, None, ["225/55R18", "235/55R18"], "todos"),
    ("HONDA", "WR-V",               2017, None, ["195/60R16", "205/55R16"], "todos"),

    # ── JEEP ────────────────────────────────────────────────────────
    ("JEEP", "RENEGADE",            2015, None, ["215/55R17", "225/45R18"], "todos"),
    ("JEEP", "COMPASS",             2017, None, ["225/60R18", "235/55R18"], "todos"),
    ("JEEP", "COMMANDER",           2021, None, ["225/60R18", "235/55R18"], "todos"),
    ("JEEP", "WRANGLER",            2010, None, ["255/75R17", "265/70R17", "255/70R18"], "todos"),

    # ── FORD ────────────────────────────────────────────────────────
    ("FORD", "KA",                  2015, 2021, ["175/65R14", "185/60R15"], "todos"),
    ("FORD", "ECOSPORT",            2013, None, ["195/65R15", "205/60R16", "215/55R17"], "todos"),
    ("FORD", "RANGER",              2012, None, ["245/70R16", "265/60R18", "265/65R17"], "todos"),
    ("FORD", "TERRITORY",           2020, None, ["225/55R18", "235/55R18"], "todos"),

    # ── NISSAN ──────────────────────────────────────────────────────
    ("NISSAN", "MARCH",             2011, 2018, ["175/65R14", "185/60R14"], "todos"),
    ("NISSAN", "VERSA",             2013, None, ["185/65R15", "195/55R16"], "todos"),
    ("NISSAN", "KICKS",             2016, None, ["205/60R16", "215/55R17"], "todos"),
    ("NISSAN", "FRONTIER",          2017, None, ["265/60R18", "265/65R17"], "todos"),
    ("NISSAN", "SENTRA",            2014, None, ["205/55R16", "215/50R17"], "todos"),

    # ── MITSUBISHI ──────────────────────────────────────────────────
    ("MITSUBISHI", "L200 TRITON",   2007, None, ["245/70R16", "265/60R18", "265/65R17"], "todos"),
    ("MITSUBISHI", "PAJERO SPORT",  2010, None, ["265/65R17", "265/60R18"], "todos"),
    ("MITSUBISHI", "OUTLANDER",     2010, None, ["225/55R18", "235/55R18"], "todos"),
    ("MITSUBISHI", "ECLIPSE CROSS", 2018, None, ["225/55R18", "235/55R18"], "todos"),
    ("MITSUBISHI", "ASX",           2012, None, ["215/60R17", "225/55R18"], "todos"),

    # ── RENAULT ─────────────────────────────────────────────────────
    ("RENAULT", "SANDERO",          2008, 2022, ["175/65R14", "185/65R15"], "todos"),
    ("RENAULT", "LOGAN",            2007, 2022, ["175/65R14", "185/65R15"], "todos"),
    ("RENAULT", "KWID",             2017, None, ["165/70R14", "175/60R15"], "todos"),
    ("RENAULT", "CAPTUR",           2017, None, ["205/60R16", "215/55R17"], "todos"),
    ("RENAULT", "DUSTER",           2012, None, ["215/65R16", "215/60R17"], "todos"),
    ("RENAULT", "OROCH",            2016, None, ["215/65R16", "205/60R16"], "todos"),

    # ── KIA ─────────────────────────────────────────────────────────
    ("KIA", "SPORTAGE",             2016, None, ["215/60R17", "225/55R18"], "todos"),
    ("KIA", "STINGER",              2018, None, ["225/40R19", "245/35R19"], "todos"),

    # ── SUBARU ──────────────────────────────────────────────────────
    ("SUBARU", "FORESTER",          2013, None, ["225/55R17", "225/60R17"], "todos"),
    ("SUBARU", "OUTBACK",           2015, None, ["225/55R18", "235/55R18"], "todos"),

    # ── LAND ROVER ──────────────────────────────────────────────────
    ("LAND ROVER", "DEFENDER",      2020, None, ["255/70R18", "265/65R18", "265/60R20"], "todos"),
    ("LAND ROVER", "DISCOVERY",     2010, None, ["255/55R19", "255/50R20"], "todos"),

    # ── ELÉTRICOS / HÍBRIDOS ────────────────────────────────────────
    ("BYD", "DOLPHIN",          2023, None, ["195/55R16", "205/50R17"], "todos"),
    ("BYD", "SEAL",             2023, None, ["235/45R18", "245/40R19"], "todos"),
    ("BYD", "ATTO 3",           2023, None, ["215/55R18", "235/50R18"], "todos"),
    ("BYD", "KING",             2024, None, ["245/50R20", "255/45R20"], "todos"),
    ("BYD", "TAN",              2023, None, ["245/45R20", "255/40R21"], "todos"),
    ("GWML", "ORA 03",          2023, None, ["195/55R16", "205/50R17"], "todos"),
    ("CAOA CHERY", "TIGGO 8 PRO E", 2023, None, ["235/55R18", "245/50R19"], "todos"),
    ("TOYOTA", "COROLLA CROSS", 2022, None, ["215/55R17", "225/45R18"], "todos"),
    ("TOYOTA", "CAMRY HYBRID",  2019, None, ["215/55R17", "225/45R17"], "todos"),
    ("HONDA", "ACCORD HYBRID",  2020, None, ["235/40R19", "245/35R19"], "todos"),
    ("VOLVO", "XC40 RECHARGE",  2021, None, ["235/50R19", "245/45R20"], "todos"),
    ("VOLVO", "C40 RECHARGE",   2022, None, ["235/50R19", "245/45R20"], "todos"),
    ("BMW", "IX3",              2021, None, ["215/55R18", "225/50R18"], "todos"),
    ("MERCEDES-BENZ", "EQA",    2022, None, ["235/50R18", "245/45R19"], "todos"),
    ("AUDI", "Q4 E-TRON",       2022, None, ["215/55R19", "235/50R20"], "todos"),
    ("VOLKSWAGEN", "ID.4",      2022, None, ["235/50R20", "255/45R20"], "todos"),

    # ── CAMINHONETES / SUV PESADO ────────────────────────────────────
    ("TOYOTA", "BANDEIRANTE",       1990, 2001, ["7.50R16", "205R16"], "todos"),
    ("FORD", "F250",                2000, None, ["245/75R16", "265/70R17"], "todos"),
    ("CHEVROLET", "D20",            1985, 1997, ["7.50R16", "7.00R16"], "todos"),

    # ── CAMINHÕES PESADOS (truck 22.5) ───────────────────────────────
    ("VOLVO", "FH",                 2000, None, ["295/80R22.5", "275/80R22.5"], "todos"),
    ("VOLVO", "FM",                 2000, None, ["295/80R22.5", "275/80R22.5"], "todos"),
    ("VOLVO", "FMX",                2010, None, ["295/80R22.5", "275/80R22.5"], "todos"),
    ("SCANIA", "R",                 2000, None, ["295/80R22.5", "275/80R22.5"], "todos"),
    ("SCANIA", "S",                 2016, None, ["295/80R22.5", "275/80R22.5"], "todos"),
    ("SCANIA", "G",                 2000, None, ["295/80R22.5", "275/80R22.5"], "todos"),
    ("SCANIA", "P",                 2000, None, ["295/80R22.5", "275/80R22.5"], "todos"),
    ("MERCEDES-BENZ", "ACTROS",     2000, None, ["295/80R22.5", "275/80R22.5"], "todos"),
    ("MERCEDES-BENZ", "AXOR",       2002, None, ["295/80R22.5", "275/80R22.5"], "todos"),
    ("MERCEDES-BENZ", "ATEGO",      2000, None, ["295/80R22.5", "275/80R22.5"], "todos"),
    ("IVECO", "STRALIS",            2003, None, ["295/80R22.5", "275/80R22.5"], "todos"),
    ("IVECO", "TRAKKER",            2004, None, ["295/80R22.5", "275/80R22.5"], "todos"),
    ("MAN", "TGX",                  2008, None, ["295/80R22.5", "275/80R22.5"], "todos"),
    ("MAN", "TGS",                  2008, None, ["295/80R22.5", "275/80R22.5"], "todos"),
    ("DAF", "XF",                   2002, None, ["295/80R22.5", "275/80R22.5"], "todos"),

    # ── CAMINHÕES MÉDIOS (aro 20 / convencionais) ────────────────────
    ("VOLKSWAGEN", "CONSTELLATION", 2005, None, ["295/80R22.5", "1000R20", "1000-20"], "todos"),
    ("VOLKSWAGEN", "WORKER",        2000, 2013, ["1000R20", "1000-20"], "todos"),
    ("VOLKSWAGEN", "DELIVERY",      2007, None, ["215/75R17.5", "225/75R17.5"], "todos"),
    ("FORD", "CARGO",               2000, None, ["295/80R22.5", "1000R20", "1000-20"], "todos"),
    ("MERCEDES-BENZ", "OF 1519",    2000, None, ["275/80R22.5", "295/80R22.5"], "todos"),
    ("MERCEDES-BENZ", "OF 1721",    2000, None, ["275/80R22.5", "295/80R22.5"], "todos"),
    ("IVECO", "EUROCARGO",          2000, None, ["275/80R22.5", "295/80R22.5"], "todos"),

    # ── ÔNIBUS ───────────────────────────────────────────────────────
    ("MARCOPOLO", "PARADISO",       2000, None, ["295/80R22.5", "275/80R22.5"], "todos"),
    ("MARCOPOLO", "VIAGGIO",        2000, None, ["295/80R22.5", "275/80R22.5"], "todos"),
    ("BUSSCAR", "EL BUS",          2000, None, ["295/80R22.5", "275/80R22.5"], "todos"),
    ("CAIO", "APACHE",              2000, None, ["275/80R22.5", "295/80R22.5"], "todos"),

    # ── TRATORES / CONSTRUÇÃO (aro 20 convencional) ──────────────────
    ("MASSEY FERGUSON", "MF 290",   1990, None, ["1100R20", "1100-20"], "todos"),
    ("NEW HOLLAND", "TL 75",        2000, None, ["1100R20", "1100-20"], "todos"),
]


def seed():
    conn = get_conn(DB_PATH)
    conn.execute("DELETE FROM compatibilidade")  # limpa antes de re-inserir

    total = 0
    for marca, modelo, ano_i, ano_f, medidas, posicao in DADOS:
        for medida in medidas:
            conn.execute(
                """INSERT INTO compatibilidade(medida, veiculo_marca, veiculo_modelo,
                   ano_inicio, ano_fim, posicao, fonte)
                   VALUES (?, ?, ?, ?, ?, ?, 'oem_manual')""",
                (medida, marca, modelo, ano_i, ano_f, posicao),
            )
            total += 1

    conn.commit()
    n_modelos = len({(m, mo) for m, mo, *_ in DADOS})
    print(f"Seed concluído: {total} registros | {n_modelos} modelos de veículos")

    # Mostra amostra
    rows = conn.execute(
        "SELECT veiculo_marca, veiculo_modelo, medida FROM compatibilidade LIMIT 5"
    ).fetchall()
    for r in rows:
        print(f"  {r['veiculo_marca']} {r['veiculo_modelo']} → {r['medida']}")
    conn.close()


if __name__ == "__main__":
    seed()
