"""
Fox Pneus — Envia alerta de falha por e-mail.

Uso (chamado pelo bat em caso de erro):
    python alertar_falha.py "mensagem de erro" "caminho/do/log.txt"
"""
import os, sys, smtplib, socket
from email.message import EmailMessage
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env", override=False)
except ImportError:
    pass

TO      = os.environ.get("FOX_ALERT_EMAIL", "").strip()
FROM    = os.environ.get("FOX_ALERT_EMAIL_FROM", TO).strip()
HOST    = os.environ.get("FOX_SMTP_HOST", "smtp.gmail.com")
PORT    = int(os.environ.get("FOX_SMTP_PORT", "587"))
USER    = os.environ.get("FOX_SMTP_USER", "").strip()
PASS    = os.environ.get("FOX_SMTP_PASS", "").strip()


def enviar(assunto: str, corpo: str) -> None:
    if not TO or not USER or not PASS:
        print("[alerta] E-mail não configurado — ignorando.")
        return

    msg = EmailMessage()
    msg["Subject"] = assunto
    msg["From"]    = FROM or USER
    msg["To"]      = TO
    msg.set_content(corpo)

    with smtplib.SMTP(HOST, PORT, timeout=30) as s:
        s.ehlo()
        s.starttls()
        s.login(USER, PASS)
        s.send_message(msg)
    print(f"[alerta] E-mail enviado para {TO}")


if __name__ == "__main__":
    erro   = sys.argv[1] if len(sys.argv) > 1 else "Erro desconhecido"
    log_path = sys.argv[2] if len(sys.argv) > 2 else ""

    tail = ""
    if log_path and Path(log_path).exists():
        linhas = Path(log_path).read_text(encoding="utf-8", errors="replace").splitlines()
        tail = "\n".join(linhas[-30:])

    corpo = (
        f"Fox Pneus — falha na atualização de estoque\n"
        f"Host: {socket.gethostname()}\n"
        f"Erro: {erro}\n\n"
        f"Últimas linhas do log:\n{tail}\n"
    )
    try:
        enviar(f"[Fox Pneus] FALHA na atualização de estoque", corpo)
    except Exception as e:
        print(f"[alerta] Falha ao enviar e-mail: {e}")
        sys.exit(1)
