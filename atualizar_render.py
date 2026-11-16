#!/usr/bin/env python3
"""
Fox Pneus — Atualizar estoque no Render
========================================
Aciona a extração de dados do GoodData diretamente no servidor Render
e acompanha o progresso até concluir.

Uso:
    python atualizar_render.py
    python atualizar_render.py --url https://meu-app.onrender.com --token meutoken
"""

import sys
import time
import urllib.request
import json
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env", override=False)
except ImportError:
    pass

# Configurações — edite aqui ou defina no .env
RENDER_URL   = os.environ.get("FOX_RENDER_URL",  "https://foxsitechat.onrender.com")
ADMIN_TOKEN  = os.environ.get("FOX_ADMIN_TOKEN", "fox2024")

# Permite sobrescrever via argumento
for i, arg in enumerate(sys.argv[1:], 1):
    if arg == "--url"   and i < len(sys.argv): RENDER_URL  = sys.argv[i + 1]
    if arg == "--token" and i < len(sys.argv): ADMIN_TOKEN = sys.argv[i + 1]


def _get(path):
    url = f"{RENDER_URL.rstrip('/')}{path}"
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def _post(path):
    url = f"{RENDER_URL.rstrip('/')}{path}"
    req = urllib.request.Request(url, data=b"", method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def main():
    print(f"\n  Fox Pneus — Atualização de Estoque no Render")
    print(f"  Servidor: {RENDER_URL}\n")

    # 1. Aciona a atualização
    print("  Acionando extração do GoodData...")
    try:
        r = _post(f"/admin/atualizar-estoque?token={ADMIN_TOKEN}")
    except Exception as e:
        print(f"  ERRO ao acionar: {e}")
        sys.exit(1)

    if r.get("status") == "em_andamento":
        print("  Já está rodando. Acompanhando...")
    else:
        print(f"  Iniciado: {r.get('mensagem', '')}\n")

    # 2. Acompanha o progresso
    print("  Aguardando conclusão (pode levar 5–15 minutos)...")
    tentativas = 0
    ultimo_log = ""
    while True:
        time.sleep(10)
        tentativas += 1
        try:
            st = _get(f"/admin/status-atualizacao?token={ADMIN_TOKEN}")
        except Exception as e:
            print(f"  [{tentativas*10}s] Aguardando servidor... ({e})")
            continue

        log_atual = st.get("log", "")
        if log_atual != ultimo_log:
            print(f"  [{tentativas*10}s] {log_atual[:120]}")
            ultimo_log = log_atual

        if not st.get("rodando"):
            print(f"\n  Concluído em {tentativas*10}s")
            print(f"  Última execução: {st.get('ultima_execucao', 'desconhecida')}")
            print(f"\n  Log:\n{st.get('log', '')}\n")

            # Mostra contador atualizado
            try:
                status = _get("/api/status")
                print(f"  Produtos no banco: {status.get('produtos', '?')}")
                print(f"  Última extração:  {status.get('ultima_extracao', '?')}\n")
            except Exception:
                pass
            break

        if tentativas > 120:  # 20 minutos máximo
            print("  Timeout — verifique manualmente em /admin/status-atualizacao")
            break


if __name__ == "__main__":
    main()
