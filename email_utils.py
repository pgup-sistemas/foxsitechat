"""
Fox Pneus — Utilitários de e-mail transacional.
Usado pela API para enviar boas-vindas ao lead e confirmação de cotação.
"""
import os, smtplib, threading
from email.message import EmailMessage
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env", override=False)
except ImportError:
    pass


def _db_config() -> dict:
    """Lê configurações da tabela config do banco. Retorna {} se falhar."""
    try:
        from database import get_conn, DB_PATH
        conn = get_conn(DB_PATH)
        rows = conn.execute("SELECT chave, valor FROM config").fetchall()
        conn.close()
        return {r[0]: r[1] for r in rows}
    except Exception:
        return {}


def _empresa(chave: str, fallback: str = "") -> str:
    """Busca valor de config no banco; fallback para env ou valor fixo."""
    cfg = _db_config()
    return cfg.get(chave) or os.environ.get(f"FOX_{chave.upper()}", fallback)


def _cfg():
    return {
        "host": os.environ.get("FOX_SMTP_HOST", "smtp.gmail.com"),
        "port": int(os.environ.get("FOX_SMTP_PORT", "587")),
        "user": os.environ.get("FOX_SMTP_USER", "").strip(),
        "pwd":  os.environ.get("FOX_SMTP_PASS", "").strip(),
        "from": os.environ.get("FOX_ALERT_EMAIL_FROM", "").strip(),
    }


def _enviar(para: str, assunto: str, html: str, texto: str) -> None:
    cfg = _cfg()
    if not cfg["user"] or not cfg["pwd"] or not para:
        return

    msg = EmailMessage()
    msg["Subject"] = assunto
    msg["From"]    = f"Fox Pneus <{cfg['from'] or cfg['user']}>"
    msg["To"]      = para
    msg.set_content(texto)
    msg.add_alternative(html, subtype="html")

    with smtplib.SMTP(cfg["host"], cfg["port"], timeout=30) as s:
        s.ehlo(); s.starttls(); s.login(cfg["user"], cfg["pwd"])
        s.send_message(msg)


def enviar_async(para: str, assunto: str, html: str, texto: str) -> None:
    """Envia em thread separada para não bloquear a resposta da API."""
    if not para:
        return
    t = threading.Thread(target=_enviar, args=(para, assunto, html, texto), daemon=True)
    t.start()


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------

def boas_vindas(nome: str, email: str) -> None:
    emp_nome    = _empresa("empresa_nome",        "Fox Pneus")
    emp_slogan  = _empresa("empresa_slogan",      "Pneus em RO, AM e AC")
    emp_site    = _empresa("empresa_site",        "https://catalogo.redefox.com.br")
    emp_wa      = _empresa("empresa_whatsapp",    "5569992323013")
    emp_wa_fmt  = _empresa("empresa_whatsapp_fmt","(69) 99232-3013")
    emp_filiais = _empresa("empresa_filiais",     "Porto Velho · Ji-Paraná · Ariquemes · Cacoal · Vilhena · Manaus · Parintins · Xapuri")
    emp_email   = _empresa("empresa_email",       "")

    nome_fmt = nome.strip().split()[0].capitalize()
    assunto  = f"Bem-vindo(a) à {emp_nome}! 🦊"

    html = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#111;font-family:Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#111;">
    <tr><td align="center" style="padding:32px 16px;">
      <table width="600" cellpadding="0" cellspacing="0"
             style="background:#1a1a1a;border-radius:12px;overflow:hidden;max-width:600px;">

        <tr>
          <td style="background:#c0392b;padding:28px 32px;text-align:center;">
            <h1 style="margin:0;color:#fff;font-size:28px;font-weight:900;
                       letter-spacing:2px;text-transform:uppercase;">{emp_nome.upper()}</h1>
            <p style="margin:4px 0 0;color:#ffcccc;font-size:13px;">{emp_slogan}</p>
          </td>
        </tr>

        <tr>
          <td style="padding:32px 32px 24px;">
            <h2 style="margin:0 0 12px;color:#fff;font-size:22px;">Olá, {nome_fmt}! 👋</h2>
            <p style="margin:0 0 16px;color:#ccc;font-size:15px;line-height:1.6;">
              Obrigado por se cadastrar no catálogo digital da
              <strong style="color:#e74c3c;">{emp_nome}</strong>.
              A partir de agora você receberá em primeira mão:
            </p>
            <ul style="margin:0 0 20px;padding-left:20px;color:#ccc;font-size:15px;line-height:2;">
              <li>Promoções exclusivas de pneus</li>
              <li>Ofertas por filial</li>
              <li>Lançamentos e novas marcas</li>
            </ul>
            <table cellpadding="0" cellspacing="0">
              <tr>
                <td style="background:#c0392b;border-radius:6px;">
                  <a href="{emp_site}"
                     style="display:inline-block;padding:14px 28px;color:#fff;
                            font-size:15px;font-weight:700;text-decoration:none;letter-spacing:1px;">
                    Ver Catálogo →
                  </a>
                </td>
              </tr>
            </table>
          </td>
        </tr>

        <tr>
          <td style="padding:0 32px 24px;">
            <p style="margin:0 0 8px;color:#888;font-size:12px;text-transform:uppercase;letter-spacing:1px;">
              Nossas filiais</p>
            <p style="margin:0;color:#aaa;font-size:13px;line-height:1.8;">{emp_filiais}</p>
          </td>
        </tr>

        <tr>
          <td style="padding:0 32px 32px;">
            <p style="margin:0;color:#888;font-size:13px;line-height:1.6;">
              Precisa de atendimento rápido? Fale pelo WhatsApp:
              <a href="https://wa.me/{emp_wa}"
                 style="color:#e74c3c;text-decoration:none;font-weight:700;">{emp_wa_fmt}</a>
            </p>
          </td>
        </tr>

        <tr>
          <td style="background:#111;padding:16px 32px;border-top:1px solid #222;">
            <p style="margin:0;color:#555;font-size:11px;text-align:center;line-height:1.6;">
              {emp_nome} · <a href="{emp_site}/politica" style="color:#555;">Política de Privacidade</a><br>
              Você recebeu este e-mail por se cadastrar em {emp_site.replace('https://','').replace('http://','')}
            </p>
          </td>
        </tr>

      </table>
    </td></tr>
  </table>
</body>
</html>"""

    texto = (
        f"Olá, {nome_fmt}!\n\n"
        f"Obrigado por se cadastrar no catálogo digital da {emp_nome}.\n"
        "A partir de agora você receberá promoções exclusivas e novidades.\n\n"
        f"Acesse: {emp_site}\n\n"
        f"Filiais: {emp_filiais}\n\n"
        f"WhatsApp: {emp_wa_fmt}\n\n"
        f"{emp_nome}"
    )

    enviar_async(email, assunto, html, texto)


def confirmacao_cotacao(nome: str, email: str, medida: str = "", filial_nome: str = "",
                        wa_link: str = "") -> None:
    if not email:
        return
    emp_nome   = _empresa("empresa_nome",    "Fox Pneus")
    emp_site   = _empresa("empresa_site",    "https://catalogo.redefox.com.br")
    emp_wa     = _empresa("empresa_whatsapp","5569992323013")
    emp_wa_fmt = _empresa("empresa_whatsapp_fmt", "(69) 99232-3013")

    nome_fmt = nome.strip().split()[0].capitalize() if nome else "Cliente"
    assunto  = f"{emp_nome} — Recebemos sua solicitação de cotação"
    detalhe  = f"<li>Medida: <strong>{medida}</strong></li>" if medida else ""
    detalhe += f"<li>Filial: <strong>{filial_nome}</strong></li>" if filial_nome else ""
    botao_wa = f"""<table cellpadding="0" cellspacing="0"><tr>
      <td style="background:#25d366;border-radius:6px;">
        <a href="{wa_link}" style="display:inline-block;padding:12px 24px;color:#fff;
           font-size:14px;font-weight:700;text-decoration:none;">💬 Falar pelo WhatsApp</a>
      </td></tr></table>""" if wa_link else ""

    html = f"""<!DOCTYPE html><html lang="pt-BR">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#111;font-family:Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#111;">
  <tr><td align="center" style="padding:32px 16px;">
    <table width="600" cellpadding="0" cellspacing="0"
           style="background:#1a1a1a;border-radius:12px;overflow:hidden;max-width:600px;">
      <tr><td style="background:#c0392b;padding:24px 32px;text-align:center;">
        <h1 style="margin:0;color:#fff;font-size:26px;font-weight:900;letter-spacing:2px;text-transform:uppercase;">
          {emp_nome.upper()}</h1>
      </td></tr>
      <tr><td style="padding:28px 32px 24px;">
        <h2 style="margin:0 0 12px;color:#fff;font-size:20px;">Olá, {nome_fmt}! ✅</h2>
        <p style="margin:0 0 16px;color:#ccc;font-size:15px;line-height:1.6;">
          Recebemos sua solicitação de cotação. Nossa equipe entrará em contato em breve.
        </p>
        {"<ul style='margin:0 0 20px;padding-left:20px;color:#ccc;font-size:14px;line-height:2;'>" + detalhe + "</ul>" if detalhe else ""}
        <p style="margin:0 0 20px;color:#ccc;font-size:14px;line-height:1.6;">
          Ou fale agora com um de nossos atendentes:
        </p>
        {botao_wa or f'<p style="margin:0;"><a href="https://wa.me/{emp_wa}" style="color:#25d366;font-weight:700;">{emp_wa_fmt}</a></p>'}
      </td></tr>
      <tr><td style="background:#111;padding:14px 32px;border-top:1px solid #222;">
        <p style="margin:0;color:#555;font-size:11px;text-align:center;">
          {emp_nome} · <a href="{emp_site}" style="color:#555;">{emp_site.replace('https://','')}</a>
        </p>
      </td></tr>
    </table>
  </td></tr>
</table>
</body></html>"""

    texto = (
        f"Olá, {nome_fmt}!\n\n"
        f"Recebemos sua solicitação de cotação na {emp_nome}.\n"
        f"{'Medida: ' + medida + chr(10) if medida else ''}"
        f"{'Filial: ' + filial_nome + chr(10) if filial_nome else ''}"
        f"\nNossa equipe entrará em contato em breve.\n"
        f"WhatsApp: {emp_wa_fmt}\n\n{emp_nome}"
    )
    enviar_async(email, assunto, html, texto)


def notificar_vendedor_lead(nome: str, whatsapp: str, email: str = "", interesse: str = "") -> None:
    """Envia e-mail interno ao vendedor quando o chat captura um lead."""
    cfg = _cfg()
    destino = cfg.get("alert_email") or os.environ.get("FOX_ALERT_EMAIL", "")
    if not destino:
        return

    emp_nome = _empresa("empresa_nome", "Fox Pneus")
    emp_wa   = _empresa("empresa_whatsapp", "5569992323013")
    wa_link  = f"https://wa.me/55{whatsapp.replace(' ','').replace('(','').replace(')','').replace('-','')}" if whatsapp else ""

    assunto = f"[{emp_nome}] Novo lead pelo chat — {nome}"
    linhas_detalhe = ""
    if interesse:
        linhas_detalhe += f"<li><strong>Interesse:</strong> {interesse}</li>"
    if email:
        linhas_detalhe += f"<li><strong>E-mail:</strong> {email}</li>"

    botao = (
        f'<a href="{wa_link}" style="display:inline-block;background:#25d366;color:#fff;'
        f'font-weight:700;padding:12px 24px;border-radius:6px;text-decoration:none;font-size:14px;">'
        f'💬 Chamar no WhatsApp</a>'
    ) if wa_link else ""

    html = f"""<!DOCTYPE html><html lang="pt-BR">
<head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:#111;font-family:Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#111;">
  <tr><td align="center" style="padding:32px 16px;">
    <table width="560" cellpadding="0" cellspacing="0"
           style="background:#1a1a1a;border-radius:12px;overflow:hidden;max-width:560px;">
      <tr><td style="background:#c0392b;padding:20px 28px;">
        <h1 style="margin:0;color:#fff;font-size:20px;font-weight:900;letter-spacing:1px;text-transform:uppercase;">
          {emp_nome} — Novo Lead (Chat IA)</h1>
      </td></tr>
      <tr><td style="padding:24px 28px;">
        <p style="margin:0 0 16px;color:#ccc;font-size:15px;">
          Um cliente deixou os dados pelo chat assistente:
        </p>
        <ul style="margin:0 0 20px;padding-left:20px;color:#ccc;font-size:14px;line-height:2;">
          <li><strong>Nome:</strong> {nome}</li>
          <li><strong>WhatsApp:</strong> {whatsapp}</li>
          {linhas_detalhe}
        </ul>
        {botao}
        <p style="margin:20px 0 0;color:#666;font-size:12px;">
          Dados coletados com consentimento via chat. Protegidos conforme a LGPD.
        </p>
      </td></tr>
    </table>
  </td></tr>
</table>
</body></html>"""

    texto = (
        f"Novo lead pelo chat — {emp_nome}\n\n"
        f"Nome: {nome}\nWhatsApp: {whatsapp}\n"
        f"{'Interesse: ' + interesse + chr(10) if interesse else ''}"
        f"{'E-mail: ' + email + chr(10) if email else ''}"
        f"\nAcesse: {wa_link}"
    )
    enviar_async(destino, assunto, html, texto)
