"""
Fox Pneus — Chat RAG com OpenRouter (Llama 3.1 / Qwen / etc.)
==============================================================
Responde perguntas sobre estoque, medidas e veículos usando dados do SQLite
como contexto dinâmico (RAG sem embeddings).

Quando o cliente confirma todos os dados (nome + WhatsApp + email),
o AI emite um sinal [[LEAD:{...}]] que o backend detecta para salvar
o lead e notificar o vendedor.

Configuração:
    FOX_GROQ_API_KEY   — chave da API (OpenRouter ou Groq)
    FOX_GROQ_MODEL     — modelo (padrão: meta-llama/llama-3.1-8b-instruct)
    FOX_AI_API_URL     — URL base (padrão: OpenRouter)
    FOX_MAX_TOKENS     — máximo de tokens na resposta (padrão: 512)
    FOX_TEMP           — temperature (padrão: 0.3)
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Iterator

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / ".env", override=False)
except ImportError:
    pass

from database import get_conn, DB_PATH
from chat_intencoes import classificar_intencao, gerar_contexto_sql, _PAT_MEDIDA, MARCAS, ALIASES_FILIAL as _ALIASES_FILIAL_HIST

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
GROQ_API_KEY = os.environ.get("FOX_GROQ_API_KEY", "").strip()
GROQ_MODEL   = os.environ.get("FOX_GROQ_MODEL", "meta-llama/llama-3.1-8b-instruct:free")
AI_API_URL   = os.environ.get("FOX_AI_API_URL", "https://openrouter.ai/api/v1/chat/completions")
MAX_TOKENS   = int(os.environ.get("FOX_MAX_TOKENS", "512"))
TEMPERATURE  = float(os.environ.get("FOX_TEMP", "0.3"))
LLAMA_MODEL  = GROQ_MODEL  # compatibilidade com api.py

_historico: dict[str, list[dict]] = {}

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------
_SYSTEM_PROMPT_BASE = """Você é o Foxinho, assistente de vendas da Fox Pneus — uma rede especializada em pneus com filiais em RO, AM e AC.

══ REGRA ABSOLUTA — NUNCA QUEBRE ══
Cite SOMENTE marcas, medidas e quantidades que estejam em [Dados do estoque] abaixo. Se não aparecer lá, não existe para você.
Se [Dados do estoque] disser "NÃO tem estoque" ou "NENHUMA FILIAL", informe isso claramente ao cliente e ofereça verificar outras medidas ou filiais. NUNCA invente produtos nem medidas que não estejam nos dados.

══ SEU OBJETIVO ══
1. Ajudar o cliente a encontrar o pneu certo.
2. Quando ele demonstrar interesse em comprar ou cotar, coletar: nome, WhatsApp e (opcionalmente) e-mail.
3. Confirmar os dados e emitir o sinal de lead.

══ TOM E ESTILO ══
- Português informal e acolhedor, como um vendedor experiente que realmente quer ajudar.
- Nunca robótico, nunca frio. Mostre que se importa com o problema do cliente.
- Sem "Claro!", "Ótimo!", "Certamente!" no início. Sem emojis.
- Respostas curtas. Máximo 3 blocos. Listas com * para medidas/marcas/filiais.
- **negrito** em medidas e marcas.

══ FLUXO DE ATENDIMENTO ══

ETAPA 1 — DESCOBERTA: Quando perguntarem por aro, medida ou veículo:
- Aro: Liste as MEDIDAS COMPLETAS disponíveis. Formato: **medida** — X opções. Pergunte qual interessa.
- Medida específica: Informe marcas e filiais com estoque. Pergunte se quer cotar.
- Filial: Informe disponibilidade. Nunca recuse.

ETAPA 2 — INTERESSE: Quando o cliente quiser saber preço ou comprar:
- Diga que o preço é passado pelo consultor.
- Pergunte de forma natural: "Posso passar seus dados pro nosso consultor te chamar?"

ETAPA 3 — CAPTAÇÃO (faça UMA pergunta por vez, não bombardeie):
- Primeiro: "Qual é o seu nome?"
- Depois: "E o WhatsApp para o consultor entrar em contato?"
- Por último: "Tem um e-mail? (opcional, mas ajuda a enviar a cotação)"

ETAPA 4 — CONFIRMAÇÃO: Repita os dados, mencione LGPD brevemente e confirme com o cliente.
Exemplo: "Vou passar pro nosso consultor: João Silva, WhatsApp (69) 99999-9999. Seus dados ficam protegidos e são usados só pra esse contato (LGPD). Confirma?"

ETAPA 5 — SINAL DE LEAD: Assim que o cliente confirmar (ou disser "sim", "pode", "isso", "correto"),
inclua EXATAMENTE ao final da sua resposta (sem mostrar ao cliente, em linha separada):
[[LEAD:{"nome":"NOME_DO_CLIENTE","whatsapp":"WHATSAPP","email":"EMAIL_OU_VAZIO","interesse":"MEDIDA_OU_DESCRICAO"}]]

══ REGRAS DE NEGÓCIO ══
- PREÇOS: nunca informe. Diga "o preço é passado pelo nosso consultor".
- FILIAIS: use SOMENTE as de [Filiais cadastradas]. Nunca invente.
- MARCAS: cite SOMENTE as que apareçam nos dados.
- CONTATO: nunca invente telefone, WhatsApp ou endereço da empresa.
- DADOS EXATOS: nunca altere medidas. 175/75R13 não vira R14.
- SINAL: emita [[LEAD:...]] apenas uma vez, após confirmação explícita do cliente.
"""


def _get_listas_banco() -> tuple[str, str]:
    """Retorna (filiais, marcas) do banco para injetar no prompt."""
    filiais = ""
    marcas = ""
    try:
        conn = get_conn(DB_PATH)
        rows_f = conn.execute(
            "SELECT nome_display FROM filial ORDER BY nome_display"
        ).fetchall()
        if rows_f:
            filiais = "\n".join(f"* {r[0]}" for r in rows_f)

        rows_m = conn.execute(
            "SELECT DISTINCT marca FROM produto WHERE marca IS NOT NULL ORDER BY marca"
        ).fetchall()
        if rows_m:
            marcas = ", ".join(r[0] for r in rows_m)

        conn.close()
    except Exception:
        pass
    return filiais, marcas


def _build_system_prompt() -> str:
    filiais, marcas = _get_listas_banco()
    prompt = _SYSTEM_PROMPT_BASE
    if filiais:
        prompt += f"\n[Filiais cadastradas — USE SOMENTE ESTAS]\n{filiais}\n"
    if marcas:
        prompt += (
            f"\n[Marcas disponíveis no estoque — USE SOMENTE ESTAS]\n{marcas}\n"
            "\nNunca cite uma marca que não esteja nessa lista, mesmo que o cliente pergunte.\n"
        )
    return prompt


SYSTEM_PROMPT = _SYSTEM_PROMPT_BASE  # mantido para compatibilidade; use _build_system_prompt()

# ---------------------------------------------------------------------------
# Cliente Groq (HTTP direto, sem dependência extra)
# ---------------------------------------------------------------------------

def _groq_chat(mensagens: list[dict], stream: bool = False) -> str | Iterator[str]:
    import urllib.request

    if not GROQ_API_KEY:
        raise ConnectionError(
            "FOX_GROQ_API_KEY não configurada.\n"
            "Crie sua chave gratuita em: https://openrouter.ai/keys\n"
            "Depois adicione no .env: FOX_GROQ_API_KEY=sk-or-..."
        )

    payload = {
        "model": GROQ_MODEL,
        "messages": mensagens,
        "max_tokens": MAX_TOKENS,
        "temperature": TEMPERATURE,
        "stream": stream,
    }

    req = urllib.request.Request(
        AI_API_URL,
        data=json.dumps(payload).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "HTTP-Referer": "https://catalogo.redefox.com.br",
            "X-Title": "Fox Pneus",
        },
        method="POST",
    )

    if not stream:
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read())
                return data["choices"][0]["message"]["content"]
        except urllib.error.HTTPError as e:
            body = e.read().decode()
            raise ConnectionError(f"Groq API erro {e.code}: {body}")
        except Exception as e:
            raise ConnectionError(f"Groq indisponível: {e}")
    else:
        def _gen():
            with urllib.request.urlopen(req, timeout=60) as resp:
                for linha in resp:
                    linha = linha.decode().strip()
                    if not linha or linha == "data: [DONE]":
                        continue
                    if linha.startswith("data: "):
                        try:
                            chunk = json.loads(linha[6:])
                            token = chunk["choices"][0]["delta"].get("content", "")
                            if token:
                                yield token
                        except Exception:
                            continue
        return _gen()


# ---------------------------------------------------------------------------
# Verificação de saúde
# ---------------------------------------------------------------------------

def ollama_ok() -> tuple[bool, str]:
    """Verifica se a integração de IA está configurada."""
    if not GROQ_API_KEY:
        return False, "FOX_GROQ_API_KEY não configurada. Acesse openrouter.ai/keys"
    return True, f"Groq OK — modelo {GROQ_MODEL}"


# ---------------------------------------------------------------------------
# Função principal
# ---------------------------------------------------------------------------

def responder(
    pergunta: str,
    session_id: str = "default",
    stream: bool = False,
    usar_langchain: bool = False,
    debug: bool = False,
) -> str | Iterator[str]:
    conn = get_conn(DB_PATH)

    intencao = classificar_intencao(pergunta)

    if session_id not in _historico:
        _historico[session_id] = []
    intencao = _enriquecer_intencao(intencao, _historico[session_id])

    ctx = gerar_contexto_sql(intencao, conn)
    conn.close()

    if debug:
        print(f"\n[DEBUG] Intenção: {intencao['intencao']}")
        print(f"[DEBUG] Medida: {intencao.get('medida')}  Filial: {intencao.get('filial')}")
        print(f"[DEBUG] Resumo: {ctx['resumo']}")

    contexto_str = ""
    if ctx["resumo"]:
        contexto_str = f"[Dados atuais do estoque Fox Pneus]\n{ctx['resumo']}"
        if ctx["dados"]:
            amostra = ctx["dados"][:10]
            contexto_str += "\n\nDetalhes:\n" + json.dumps(amostra, ensure_ascii=False, indent=2)

    historico = _historico[session_id]
    msgs = [{"role": "system", "content": _build_system_prompt()}]
    for h in historico[-6:]:
        msgs.append(h)
    prompt_final = f"{contexto_str}\n\nPergunta: {pergunta}" if contexto_str else pergunta
    msgs.append({"role": "user", "content": prompt_final})

    if stream:
        def _stream_gen():
            tokens: list[str] = []
            try:
                for tok in _groq_chat(msgs, stream=True):
                    tokens.append(tok)
                    yield tok
            finally:
                resposta = "".join(tokens)
                if resposta:
                    historico.append({"role": "user",      "content": pergunta})
                    historico.append({"role": "assistant", "content": resposta})
                    if len(historico) > 40:
                        _historico[session_id] = historico[-40:]
        return _stream_gen()

    resposta = _groq_chat(msgs, stream=False)

    historico.append({"role": "user",      "content": pergunta})
    historico.append({"role": "assistant", "content": resposta})
    if len(historico) > 40:
        _historico[session_id] = historico[-40:]

    return resposta


def _enriquecer_intencao(intencao: dict, historico: list[dict]) -> dict:
    novo = dict(intencao)

    # Recupera medida do histórico quando não veio na mensagem atual
    if not novo.get("medida"):
        from chat_intencoes import _PAT_ARO as _PAT_ARO_HIST
        for msg in reversed(historico[-8:]):
            content = msg.get("content", "")
            m = _PAT_MEDIDA.search(content)
            if m:
                novo["medida"] = m.group(1).upper()
                if novo["intencao"] in ("busca_filial", "geral"):
                    novo["intencao"] = "busca_medida"
                if not novo.get("marca"):
                    cl = content.lower()
                    for mrc in MARCAS:
                        if mrc in cl:
                            novo["marca"] = mrc.upper()
                            break
                break
            a = _PAT_ARO_HIST.search(content)
            if a:
                novo["medida"] = f"ARO{a.group(1)}"
                if novo["intencao"] in ("busca_filial", "geral"):
                    novo["intencao"] = "busca_medida"
                break

    # Recupera filial do histórico quando não veio na mensagem atual
    if not novo.get("filial"):
        for msg in reversed(historico[-8:]):
            content = msg.get("content", "")
            cl = content.lower()
            for alias, cod in _ALIASES_FILIAL_HIST.items():
                if alias in cl:
                    novo["filial"] = cod
                    break
            if novo.get("filial"):
                break

    # Se tem medida E marca agora, busca por medida é mais específica
    if novo.get("medida") and novo.get("marca") and novo["intencao"] == "busca_marca":
        novo["intencao"] = "busca_medida"

    return novo


def limpar_historico(session_id: str = "default"):
    _historico.pop(session_id, None)


# ---------------------------------------------------------------------------
# Extração do sinal de lead
# ---------------------------------------------------------------------------

_PAT_LEAD = re.compile(r"\[\[LEAD:(\{[^}]+\})\]\]", re.DOTALL)


def extrair_lead(resposta: str) -> tuple[str, dict | None]:
    """Remove o sinal [[LEAD:{...}]] da resposta e retorna (texto_limpo, dados_lead)."""
    m = _PAT_LEAD.search(resposta)
    if not m:
        return resposta, None
    try:
        lead_data = json.loads(m.group(1))
    except json.JSONDecodeError:
        return resposta, None
    texto_limpo = _PAT_LEAD.sub("", resposta).strip()
    return texto_limpo, lead_data


# ---------------------------------------------------------------------------
# CLI interativo
# ---------------------------------------------------------------------------

def _cli():
    print("\n" + "="*60)
    print("  Fox Pneus — Chat Assistente (Groq / Llama 3.3)")
    print("="*60)

    ok, msg = ollama_ok()
    if not ok:
        print(f"\n  AVISO: {msg}\n")
        print("  Modo degradado: exibindo apenas o contexto SQL.\n")
    else:
        print(f"\n  {msg}\n")

    session = f"cli_{int(time.time())}"

    while True:
        try:
            pergunta = input("Você: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n  Até mais!")
            break

        if not pergunta:
            continue
        if pergunta.lower() in ("sair", "exit", "quit"):
            print("  Até mais!")
            break
        if pergunta.lower() == "limpar":
            limpar_historico(session)
            print("  Histórico limpo.\n")
            continue

        t0 = time.time()
        try:
            if ok:
                resp = responder(pergunta, session_id=session)
            else:
                conn = get_conn(DB_PATH)
                intencao = classificar_intencao(pergunta)
                ctx = gerar_contexto_sql(intencao, conn)
                conn.close()
                resp = ctx["resumo"] or "Nenhuma informação encontrada."
            print(f"\n  Fox: {resp}")
            print(f"  ({time.time()-t0:.1f}s)\n")
        except ConnectionError as e:
            print(f"\n  [Groq offline] {e}\n")
        except Exception as e:
            print(f"\n  [Erro] {e}\n")


if __name__ == "__main__":
    _cli()
