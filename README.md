# specboard

**Painel de validação e arquitetura para projetos conduzidos por agentes de IA (incluindo pesquisa científica).**
Converte a spec e o plano modular em `.specboard/estado.json` e entrega um painel interativo com **Agora**, **Projeto** (fluxograma expansível), **Revisão contextual** (figuras, tabelas e relatórios com decisão em um clique) e **Agente** (visão técnica Learn / Guard / Review / Score).

> *English summary:* Zero-dependency Python 3 stdlib dashboard and validation harness for agent-driven modular and scientific projects. Separates agent execution (`executado`) from human verification (`verificado`) or change requests (`pedir_correcao`), supports 3 configurable project approval policies (`acompanhamento_livre`, `so_marcos` with granular milestones, `por_etapa`), binds decisions to real file-byte SHA-256 hashes with TOCTOU (`HTTP 409`) protection, and includes a local/SSH review server plus an **Agente** technical view.

---

## O que há de novo na v2

1. **Tela inicial _Agora_ (leitura em poucos segundos):** separa claramente fase/marco atuais, atividade **reportada pelo agente**, **bloqueios impostos pelo sistema**, próxima ação humana em destaque, fila priorizada inline e mudanças desde a última visita.
2. **Aba _Projeto_ com fluxograma expansível:** começa em fases e marcos; 1º toque na fase desenha o subfluxograma inline; 1º toque no marco/etapa abre **Critério · Evidência · Decisão**; 2º toque recolhe preservando posição. No celular, reorganiza na vertical **com setas explícitas** (e opção de lista). Diferencia visualmente sequência de trabalho de dependência bloqueante.
3. **Revisão contextual no painel (`serve`) + túnel SSH:** abre direto da pendência na ordem **O que foi entregue → Critério → Evidência (PNG/SVG/CSV/Markdown inline) → Decisão** (`Aprovar`, `Pedir correção` com justificativa, `Deixar para depois`), mostrando o efeito sobre etapas dependentes e confirmando somente após gravação persistente.
4. **Política de aprovação por projeto + marcos granulares:** escolha entre `acompanhamento_livre`, `so_marcos` (marcos em módulos ou etapas individuais) e `por_etapa`, com alteração explícita e auditada no histórico e compatibilidade total com projetos legados.
5. **Rastreabilidade por hash dos bytes das evidências + proteção TOCTOU:** substituir o conteúdo de um arquivo no mesmo caminho muda o SHA-256 dos bytes e expira automaticamente a aprovação; se a evidência mudar entre abrir a revisão e clicar em Aprovar, o servidor retorna `HTTP 409 Conflict` e exige nova conferência.
6. **Aba _Agente_ (visão técnica do mesmo projeto):** salto bidirecional etapa ↔ configuração técnica em 4 blocos expansíveis — **Contexto e memória (Learn)** com retomada em sessão limpa (`context`), **Skills/Ferramentas/MCPs** distinguindo planejado × configurado × observado (`sem registro` quando sem telemetria), **Guardrails (Guard)** separando código vs. instrução, e **Revisão e avaliação (Review & Score)** mantendo avaliação do agente distinta da validação científica.

---

## Requisitos e Instalação

**Requisitos:** Python 3.11+ (testado em Python 3.13 no Windows e 3.12 no Linux). **Zero dependências externas.**

```powershell
git clone https://github.com/fatioleg/specboard.git
# Para Claude Code:
Copy-Item -Recurse specboard\specboard "$env:USERPROFILE\.claude\skills\"
```

O núcleo (`specboard/scripts/specboard.py`) é agnóstico de agente e funciona igualmente com Claude Code, Codex, Antigravity ou outros executores via `gate`, `context` e `trace-tool`.

---

## Uso rápido (tudo feito no painel)

```powershell
# 1. Criar estado inicial escolhendo a política de aprovação
python specboard/scripts/specboard.py init --politica so_marcos

# 2. Validar e gerar snapshot estático offline
python specboard/scripts/specboard.py validate
python specboard/scripts/specboard.py build

# 3. Abrir o painel interativo (revisão de figuras/CSV/MD + aprovação em 1 clique)
python specboard/scripts/specboard.py serve --port 8765 --open
```

### Projetos em máquina remota (SSH)

Rode o servidor no servidor remoto ligado apenas a `127.0.0.1` e abra um túnel SSH local:

```bash
ssh -L 8765:127.0.0.1:8765 usuario@servidor \
  "cd ~/meu-projeto && python3 ~/.local/share/specboard/scripts/specboard.py serve --port 8765"
```

Depois abra `http://127.0.0.1:8765/` no navegador local: você revisa figuras, tabelas e relatórios diretamente do servidor remoto e grava decisões atomicamente em `.specboard/verificacoes.jsonl` no servidor, sem copiar HTML manualmente.

---

## Comandos da CLI

| Comando | Quem roda | O que faz |
|---|---|---|
| `python SB init [--politica ...]` | agente / humano | cria `.specboard/estado.json` e `.specboard/.gitignore` |
| `python SB validate` | agente / ambos | valida schema, contratos travados e presença de evidências |
| `python SB build [--open]` | ambos | gera `.specboard/painel.html` (snapshot offline read-only) |
| `python SB serve [--port 8765] [--open]` | **humano** | sobe servidor local `127.0.0.1` para revisão e gravação no painel |
| `python SB queue [--todas]` | ambos | lista fila priorizada (bloqueantes, expiradas, impacto, ordem natural) |
| `python SB gate <ETAPA> [--json]` | agente / executor | checa se etapa está liberada (`exit 0`) ou bloqueada (`exit 2`) |
| `python SB context <ETAPA> [--json]` | agente / ambos | monta pacote mínimo versionado para retomada em sessão limpa |
| `python SB trace-tool <ETAPA> --tool ...` | wrapper / telemetria | registra uso observado (compatível com OTel `execute_tool`) |
| `python SB lock <MOD>` / `amend <MOD> -j "..."` | agente com aval | trava contrato e registra emendas visíveis |
| `python SB verify\|review\|request-changes <ETAPA>` | **só humano** | alternativa em terminal interativo ao painel |
| `python SB policy <MODO> -j "..."` | **só humano** | altera política de aprovação com justificativa auditável |

---

## Políticas de aprovação

| Política | Bloqueio de avanço | Executado ≠ verificado | Uso típico |
|---|---|---|---|
| `acompanhamento_livre` | Nenhum bloqueio automático | **Sempre mantido** (0% verificado até ação humana) | Exploração inicial e prototipagem |
| `so_marcos` | Apenas marcos designados (`marco: true` em etapa ou módulo) bloqueiam dependentes; ramos paralelos seguem livres | **Sempre mantido** | Projetos científicos em fases (ex.: validar estabilidade estrutural antes de simulações caras) |
| `por_etapa` | Cada etapa sujeita ao fluxo exige conferência antes de liberar dependentes; módulos independentes seguem livres | **Sempre mantido** | Auditoria passo a passo e compatibilidade legada |

---

## Exemplos incluídos e testes

- **Exemplo científico v2 (`examples/carbon_dots/`):** estabilidade estrutural de *carbon dots* a 400 K com política `so_marcos`, marco granular `M2.3` (figura PNG + tabela CSV + relatório Markdown), ramo paralelo desbloqueado `M2-B`, aba **Agente** completa em `M2.2` (skill + script local observados e MCP opcional exibindo `sem registro`).
  ```powershell
  python specboard/scripts/specboard.py --dir examples/carbon_dots serve --open
  ```
- **Exemplo legado v1 (`examples/estado_completo.json`):** preservado intacto como fixture de regressão para garantir compatibilidade com projetos antigos.

Para rodar toda a suíte automatizada (Python stdlib `unittest`):

```powershell
python -m unittest discover -s tests -v
```

---

## Estrutura do repositório

```text
specboard/
├── SKILL.md
├── scripts/
│   ├── specboard.py           CLI unificado
│   ├── sb_core.py             domínio, hashing v2 (SHA-256 bytes), políticas, fila, contexto
│   ├── sb_server.py           servidor local/SSH (ThreadingHTTPServer 127.0.0.1)
│   └── block_verify_hook.py   hook PreToolUse contra autovalidação
├── assets/
│   ├── painel_template.html   interface única (Agora, Projeto, Revisão, Agente)
│   └── estado_exemplo.json    esqueleto inicial v2
└── references/
    ├── formato-estado.md      schema completo v2 + compatibilidade legada
    └── arquitetura-agente.md  guia da aba Agente (Learn/Guard/Review/Score)
examples/
├── estado_completo.json       fixture legada v1 preservada intacta
├── painel_completo.html       painel v2 gerado sobre o exemplo legado
└── carbon_dots/               exemplo científico v2 com PNG, CSV, MD, script e telemetria
tests/                         testes unitários e de integração (core, políticas, TOCTOU, server, hook, UI)
```

## Licença

[Apache License 2.0](LICENSE).
