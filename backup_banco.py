"""
Fox Pneus — Backup do banco SQLite.
Cria uma cópia compactada em backups/ e mantém os últimos 7 dias.

Uso:
    python backup_banco.py
"""
import shutil, sys, gzip
from datetime import datetime, timedelta
from pathlib import Path

BASE_DIR  = Path(__file__).resolve().parent
DB_PATH   = BASE_DIR / "fox_catalog.db"
BACKUP_DIR = BASE_DIR / "backups"
MANTER_DIAS = 7


def fazer_backup():
    if not DB_PATH.exists():
        print(f"[backup] Banco não encontrado: {DB_PATH}")
        sys.exit(1)

    BACKUP_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    dest  = BACKUP_DIR / f"fox_catalog_{stamp}.db.gz"

    # Compacta com gzip
    with open(DB_PATH, "rb") as f_in, gzip.open(dest, "wb") as f_out:
        shutil.copyfileobj(f_in, f_out)

    tam = dest.stat().st_size / 1024 / 1024
    print(f"[backup] {dest.name}  ({tam:.1f} MB)")

    # Remove backups antigos
    limite = datetime.now() - timedelta(days=MANTER_DIAS)
    removidos = 0
    for arq in BACKUP_DIR.glob("fox_catalog_*.db.gz"):
        try:
            data_arq = datetime.strptime(arq.stem[:15], "fox_catalog_%Y%m%d")
            if data_arq < limite:
                arq.unlink()
                removidos += 1
        except ValueError:
            pass

    if removidos:
        print(f"[backup] {removidos} backup(s) antigo(s) removido(s).")

    total = len(list(BACKUP_DIR.glob("fox_catalog_*.db.gz")))
    print(f"[backup] Total de backups: {total}")
    return dest


if __name__ == "__main__":
    fazer_backup()
