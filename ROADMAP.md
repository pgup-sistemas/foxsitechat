# Fox Pneus — Catálogo Digital · Roadmap

> **Objetivo:** cliente pesquisa pneu por medida ou veículo, vê disponibilidade por filial, monta cotação e é direcionado para WhatsApp. Compra direta no futuro.

---

## Status atual (2026-10-29)

| Módulo | Arquivo | Status |
|--------|---------|--------|
| Parser de medida | `parser_medida.py` | ✅ 99.6% cobertura |
| Schema SQLite | `database.py` | ✅ 8 tabelas + 1 view |
| Loader CSV→SQLite | `carregar_estoque.py` | ✅ 9.952 registros carregados |
| FastAPI REST | `api.py` | ✅ 14 endpoints |
| Extração GoodData | `../scraping-estoque/extrair_estoque.py` | ✅ produção |
| Frontend (site) | — | 🔲 não iniciado |
| Compatibilidade veicular | — | 🔲 não iniciado |
| Chat Llama local | — | 🔲 planejado |
| Integração MOVERE API | — | ⏳ aguardando suporte |

---

## Fase 1 — Backend funcional ✅ (concluída)

### 1.1 Parser de medida
- [x] Regex para todos os formatos (radial car/truck, diagonal, agrícola, industrial, câmara, protetor)
- [x] Extração de campos: medida, aro, largura, perfil, categoria, tipo_banda, modelo
- [x] CLI: `python parser_medida.py estoque.csv` gera CSV enriquecido

### 1.2 Banco SQLite
- [x] Tabelas: `produto`, `estoque`, `filial`, `preco`, `compatibilidade`, `lead`, `extracao_log`
- [x] View `v_estoque_atual` (sempre busca a extração mais recente por filial)
- [x] 8 filiais pré-cadastradas

### 1.3 Loader
- [x] Carrega todos os CSVs de `scraping-estoque/output/`
- [x] Upsert de produto (não duplica, atualiza)
- [x] Detecção automática de filial e data pelo nome do arquivo
- [x] Log de extrações

### 1.4 API REST (FastAPI)
- [x] `GET /busca?medida=185/65R15` — busca por medida com estoque
- [x] `GET /busca?categoria=car&filial=MATRIZ` — filtros combinados
- [x] `GET /produto/{cod_item}` — detalhe com histórico de estoque
- [x] `GET /disponibilidade/{cod_item}` — estoque por filial + link WhatsApp
- [x] `GET /medidas` — lista todas as medidas em estoque
- [x] `GET /filiais` — lista filiais
- [x] `POST /cotacao` — registra lead + gera link WhatsApp
- [x] `GET /veiculo?marca=TOYOTA&modelo=HILUX` — stub para compatibilidade
- [x] `POST /admin/recarregar` — recarrega CSVs no banco
- [x] Docs automáticas: `http://localhost:8000/docs`

---

## Fase 2 — Qualidade dos dados 🔧 (próxima)

### 2.1 Preços de tabela
- [ ] Carregar `desconto_servicos_varejo_20261023.csv` na tabela `preco`
  - Colunas: `Cód Item`, `Preço tabela`, `Nome Estabelecimento`, `Date`
  - Script: `carregar_precos.py` (a criar)
- [ ] Expor preço no endpoint `/busca` e `/produto/{id}`

### 2.2 Deduplicação de estoque
- [ ] Os CSVs individuais por filial + `estoque_TODAS` causam duplicação
  - Solução: ao carregar, pular `estoque_TODAS` se filiais individuais já existirem na mesma data
  - Ou: adicionar constraint UNIQUE(cod_item, filial, data_extracao)

### 2.3 Filial "DESCONHECIDA"
- [ ] CSVs de cotação por UF (`estoque_cotacoes_uf_20261023.csv`) não têm filial
  - Mapear `UF Estabelecimento` (AM/RO/AC) para filial pelo campo existente
  - Ou marcar como `uf=AM/RO/AC` sem filial específica

### 2.4 Fotos dos produtos
- [ ] Adicionar coluna `foto_url` na tabela `produto`  ← já existe no schema
- [ ] Opção A: scraping de fotos por marca/modelo (Pirelli, Bridgestone, etc.)
- [ ] Opção B: upload manual por um admin no painel
- [ ] Opção C: foto genérica por categoria + marca

---

## Fase 3 — Frontend web 🌐

### 3.1 Busca por medida
```
/busca-medida → input: 185/65R15
             → grade de produtos com foto, marca, estoque por filial
             → botão "Quero este" → cotação WhatsApp
```
- [ ] Stack: HTML + Alpine.js (leve, sem build) ou Next.js
- [ ] Consumir `GET /busca?medida=` e `GET /disponibilidade/{cod_item}`
- [ ] Filtros: categoria, filial, marca, com_estoque

### 3.2 Busca por veículo
```
/busca-veiculo → marca → modelo → ano
              → medidas recomendadas → produtos em estoque
```
- [ ] Depende de 3.3 (base veicular)

### 3.3 Base de compatibilidade veicular
- [ ] Opção A: preencher manualmente (marca + modelo + medidas mais vendidas)
  - Foco inicial: Hilux, Ranger, S10, Strada, Saveiro, Uno, HB20, Gol
- [ ] Opção B: integrar tabela Sindipneus (formato CSV disponível)
- [ ] Opção C: usar LLM local (Llama) para sugestão de medida por veículo
  - Usuário digita "Hilux 2020" → Llama sugere medidas → API confirma estoque

### 3.4 Cotação / WhatsApp
- [ ] Formulário: nome, telefone, medida/veículo, filial preferida
- [ ] `POST /cotacao` → salva lead → retorna link `wa.me/...` pré-preenchido
- [ ] Painel simples de leads para vendedores (tabela + filtro por filial)

---

## Fase 4 — Atualização automática ⚙️

### 4.1 Scheduler diário
```
cron: 06:00 → python extrair_estoque.py --cada-filial
           → python carregar_estoque.py
```
- [ ] Windows Task Scheduler ou script `.bat`
- [ ] Ou: `python -m schedule` dentro de `scheduler.py`
- [ ] Notificação por e-mail se extração falhar

### 4.2 API de reload
- [ ] `POST /admin/recarregar` já existe  ← só falta conectar ao scheduler
- [ ] Adicionar autenticação real (JWT ou chave estática em .env)

---

## Fase 5 — Chat Llama local 🤖

> Responde perguntas sobre estoque, medidas e veículos usando os dados do SQLite como contexto.

### 5.1 Como funciona
O Llama **não é treinado** nos dados — ele é **alimentado em tempo real** com contexto via RAG (Retrieval-Augmented Generation):

```
Usuário: "Tem 185/65R15 na Matriz?"
    ↓
Sistema faz: SELECT * FROM v_estoque_atual WHERE medida='185/65R15' AND filial='MATRIZ'
    ↓
Monta prompt: "Dados de estoque: [resultado SQL]. Pergunta: [...]"
    ↓
Llama responde com linguagem natural
```

### 5.2 Para "treinar" o Llama nos dados
O Llama local (Ollama) suporta duas abordagens:

| Abordagem | O que é | Quando usar |
|-----------|---------|-------------|
| **RAG (contexto no prompt)** | Busca no SQLite e injeta no prompt | Dados mudam todo dia (estoque) |
| **Fine-tuning (GGUF/LoRA)** | Reajusta pesos do modelo com seus dados | Dados estáticos (catálogo, FAQs) |

**Recomendação:** RAG para estoque + fine-tuning só para linguagem da empresa (tom, termos técnicos, política de desconto).

### 5.3 Stack proposto
```
Ollama (llama3.2 local)
  + LangChain ou llama-index
  + SQLite como "knowledge base"
  + FastAPI: POST /chat {"pergunta": "..."}
```

### 5.4 Casos de uso do chat
- "Qual filial tem mais 1000R20 em estoque?"
- "Quais medidas de pneu servem no Fiat Strada 2019?"
- "Me mostra os pneus truck com mais de 50 unidades em Manaus"
- "Qual a medida mais vendida na Matriz?"
- "Tem pneu agrícola 14.9-28 disponível?"

### 5.5 Tarefas
- [ ] Instalar Ollama + llama3.2 (já feito segundo o usuário)
- [ ] Criar `chat.py`: endpoint POST /chat que:
  1. Classifica intenção (busca_medida | busca_filial | busca_veiculo | geral)
  2. Executa query SQL correspondente
  3. Injeta resultado no prompt do Llama
  4. Retorna resposta em linguagem natural
- [ ] Adicionar `GET /chat/historico` por sessão
- [ ] Conectar ao frontend (widget de chat flutuante)

---

## Fase 6 — MOVERE API ⏳ (bloqueado)

- [ ] Aguardar liberação de acesso pelo suporte
- [ ] Implementar `movere_connector.py`:
  - `GET /itens` — catálogo completo com fotos e descrições
  - `GET /estoque/{estabelecimento}` — estoque em tempo real
  - `GET /precos/{item}/{estabelecimento}` — preço oficial
- [ ] Substituir fonte de preços do GoodData pelo MOVERE
- [ ] Sincronização diária MOVERE → SQLite

---

## Fase 7 — Compra direta 💳 (futuro)

- [ ] Carrinho de compras
- [ ] Checkout com pagamento (PIX / boleto / cartão)
- [ ] Integração com MOVERE para baixa de estoque em tempo real
- [ ] Reserva de estoque (timeout de 30 min)
- [ ] NF-e automática

---

## Comandos rápidos

```bash
# Rodar a API
cd vendas-online-osn
uvicorn api:app --reload --port 8000

# Docs interativas
http://localhost:8000/docs

# Atualizar estoque manualmente
cd scraping-estoque
python extrair_estoque.py --cada-filial
cd ../vendas-online-osn
python carregar_estoque.py

# Recriar banco do zero
python database.py --reset
python carregar_estoque.py

# Testar parser
python parser_medida.py
python parser_medida.py ../scraping-estoque/output/estoque_TODAS_20261023.csv
```

---

## Arquitetura atual

```
GoodData (analytics.moveresoftware.com)
    │
    └── extrair_estoque.py ──→ output/*.csv
                                    │
                              carregar_estoque.py
                                    │
                              fox_catalog.db (SQLite)
                                    │
                    ┌───────────────┼────────────────┐
                    │               │                │
                  api.py        chat.py (futuro)   painel_leads (futuro)
                (FastAPI)       (Llama RAG)
                    │
               frontend web (fase 3)
                    │
               WhatsApp (cotação)
```
