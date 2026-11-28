---
name: specboard
description: Cria e mantém o painel de validação e arquitetura técnica (SpecBoard v2) para projetos conduzidos por agentes de IA (incluindo pesquisa científica), com telas Agora, Projeto (fluxograma expansível), Revisão contextual (servidor local/SSH) e aba Agente. Separa execução do agente de aprovação humana, aplica políticas configuráveis por projeto e vincula aprovações ao SHA-256 dos bytes das evidências.
---

# specboard (v2) — painel de validação e arquitetura para projetos com agentes

## Princípios

1. **Executado ≠ verificado.** O agente só leva uma etapa até `executado`. Aprovar (`verificado`), marcar leitura (`revisado`), pedir correção (`pedir_correcao`) e alterar política são atos humanos gravados em `.specboard/verificacoes.jsonl` (pelo painel `serve` ou terminal).
2. **Política configurável por projeto.** Escolha na criação (`init --politica`): `acompanhamento_livre`, `so_marcos` (com marcos granulares em módulos ou etapas) ou `por_etapa`. Alterações posteriores são explícitas e auditadas.
3. **Integridade por conteúdo.** Cada decisão vincula-se ao SHA-256 dos bytes dos arquivos locais de evidência, ao critério/contrato e à revisão da etapa. Substituir um arquivo no mesmo caminho expira automaticamente a aprovação.
4. **Visão unificada sem repetição.** As abas **Agora**, **Projeto** (fluxograma expansível) e **Agente** (Learn/Guard/Review/Score) leem a mesma fonte de dados.
5. **Regra de Texto Didático Obrigatório em TODOS os cards (Home, Blocos/Módulos, Etapas e Revisão).** Todo texto visível no painel é escrito para o **revisor humano**, não para o terminal nem para o `git log`:
   - **Títulos (`titulo` de módulos e etapas):** nomeie claramente o objetivo ou entrega em português simples. **Proibido** usar apelidos internos não explicados (`Frente C`, `Ciclo 1`, `Gate A`, `Fase III`) ou códigos crípticos (`D50`, `D28`, `doc 13`). Para referenciar outro item, use sempre o ID do próprio SpecBoard (ex.: `M4.5`).
   - **Resumo da entrega (`afirmacao` / `resumo_didatico`):** siga os **3 Pilares** em 1–3 frases claras: **(1) O quê** foi definido/construído/analisado, **(2) Qual é a regra ou resultado concreto** (números, critério ou conclusão compreensível sem abrir código) e **(3) Por que importa / o que destrava**.
   - **Como conferir (`verificacao`):** diga ao humano **qual documento, figura ou tabela abrir** e **qual fato concreto confirma a aprovação**. **Nunca** instrua o revisor a comparar hashes/commits Git ou executar scripts `.py` como instrução principal.
   - **Objetivo do bloco (`objetivo`/`responde`) e card da Home (`projeto.atividade_agente.resumo`):** mesma linguagem humana direta, sem jargão técnico.
   - **Proibido em todos os cards visíveis:** nomes de scripts/configs (`.py`, `.yaml`, `.json`, `.sh`), hashes Git (`3dba70d`), termos Git (`commit`, `commits`, `PR #...`), flags CLI (`--doc`), identificadores `snake_case` e códigos/apelidos internos sem explicação (`D50`, `D28`, `doc 13`, `Frente C`). **Mova toda a rastreabilidade técnica para `detalhes_tecnicos` e `evidencia`.**
   - *Exemplo RUIM (reprovado em `validate --estrito`):*
     - `titulo`: `"Frente C: critério de esfoliação pré-registrado (D50)"`
     - `afirmacao`: `"Critério D50 registrado (3dba70d) antes da análise; implementado em analyze_md_d47.py com testes."`
     - `verificacao`: `"Comparar a data/commit de D50 com os commits das análises da Frente C (todos posteriores)."`
   - *Exemplo BOM (aprovado em `validate --estrito`):*
     - `titulo`: `"Critério objetivo de esfoliação pré-registrado antes das análises"`
     - `afirmacao`: `"Definimos e travamos previamente a regra numérica que identifica separação entre camadas nas simulações, antes de analisar qualquer trajetória. Os testes automáticos confirmaram que o cálculo aplica exatamente essa regra, evitando viés na leitura dos resultados."`
     - `verificacao`: `"Abrir o documento de decisões (DECISOES.md) e conferir se a regra de esfoliação (limiar e tempo mínimo) está registrada com data anterior ao início das análises."`
     - `detalhes_tecnicos`: `"Pré-registro D50 (commit 3dba70d, Frente C); cálculo e testes implementados em analyze_md_d47.py."`

## Arquivos da skill

- `scripts/specboard.py` — CLI unificado (`init`, `validate`, `lock`, `amend`, `queue`, `build`, `serve`, `gate`, `context`, `trace-tool`, e comandos humanos `review`, `verify`, `request-changes`, `policy`). Python 3 stdlib puro.
- `scripts/sb_core.py` — motor de domínio, hashing v2, políticas e contexto limpo.
- `scripts/sb_server.py` — servidor local `127.0.0.1` (suporta túnel SSH) para revisão de figuras/CSV/MD e gravação confirmada.
- `scripts/block_verify_hook.py` — hook `PreToolUse` contra autovalidação.
- `assets/painel_template.html` — interface única (usada por `serve` e `build`).
- `references/formato-estado.md` e `references/arquitetura-agente.md` — leia antes de editar `.specboard/estado.json`.

Abaixo, `SB` = caminho absoluto de `scripts/specboard.py`.

## Fluxo operacional

### 1. Inicializar o projeto
1. Procure specs e planos existentes (ex.: `.omc/specs/`, `.omc/plans/`). Não invente critérios.
2. Pergunte ao usuário qual política de aprovação deseja (`so_marcos`, `por_etapa` ou `acompanhamento_livre`) e rode:
   `python SB init --politica <modo>`
3. Preencha `.specboard/estado.json` consultando `references/formato-estado.md` e `references/arquitetura-agente.md`:
   - `projeto.pergunta_central`, `projeto.atividade_agente`, `fases`, `modulos`, `etapas` e `marco: true` nos marcos granulares desejados.
   - `arquitetura_agente` nas etapas técnicas críticas (contexto durável vs. execução, skills/ferramentas locais/MCPs, guardrails por código vs. instrução, avaliação do agente separada da validação científica).
4. Rode `python SB validate && python SB build` e instrua o usuário a abrir o painel interativo com `python SB serve --open`.

### 2. Instalar proteção contra autovalidação
Adicione ao `.claude/settings.json` do projeto (ou equivalente do agente em uso):

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash|PowerShell|Write|Edit|MultiEdit",
        "hooks": [{ "type": "command", "command": "python \"<CAMINHO>/scripts/block_verify_hook.py\"" }]
      }
    ]
  }
}
```

### 3. Durante a execução (etapa a etapa)
- Antes de iniciar uma etapa, cheque o portão determinístico: `python SB gate <ETAPA>`. Se sair com código `2`, respeite o bloqueio e informe o usuário.
- Em sessão limpa ou troca de agente, reconstrua o contexto mínimo: `python SB context <ETAPA>`.
- Atualize `projeto.atividade_agente` e marque a etapa `em_curso` → `executado` com `afirmacao`, `verificacao` e `evidencia` (caminhos reais de figuras, tabelas e relatórios).
- Quando houver wrapper/telemetria de ferramentas, registre em `.specboard/execucoes.jsonl` com `python SB trace-tool ...` (nunca invente telemetria; sem registro deve permanecer `"sem registro"`).
- Rode `python SB validate --estrito && python SB build` (garante 0 erros e 0 cards pouco didáticos).
- **Nunca** execute `review`, `verify`, `request-changes`, `policy`, `serve` (sem `--readonly`), nem toque em `.specboard/verificacoes.jsonl` ou `/api/decisao`.

### 4. Contratos e emendas
Antes dos resultados principais de um módulo, confirme o contrato com o usuário e rode `python SB lock <MOD>`. Qualquer mudança posterior exige `python SB amend <MOD> -j "motivo"`.
