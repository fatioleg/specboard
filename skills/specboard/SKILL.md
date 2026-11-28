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
5. **Resumo da entrega sempre didático.** O campo `afirmacao` (ou `resumo_didatico`) é escrito para o **revisor humano**, não para o terminal: explique em 1–3 frases claras **o que foi feito, por que importa e qual resultado prático foi obtido**. **Nunca** entregue uma lista críptica de arquivos `.py/.yaml`, flags (`--doc`), símbolos `snake_case` ou códigos internos sem contexto (`D28`, `doc 13`) como resumo principal — coloque esses itens em `detalhes_tecnicos` e `evidencia`.
   - *Evitar:* `"gerador.py, pré-registro params.yaml (D28), doc 13 (check_docs --doc 13 verde) e check_params.py alinhado a base_ff + custom_N (66/66 testes, 0 lacunas)."`
   - *Preferir:* `"Criamos o gerador dos modelos oxidados e validamos todos os parâmetros necessários para as simulações. As 66 checagens automáticas passaram sem nenhuma lacuna."` *(com scripts/flags/códigos movidos para `detalhes_tecnicos`)*.

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
- Rode `python SB validate && python SB build`.
- **Nunca** execute `review`, `verify`, `request-changes`, `policy`, `serve` (sem `--readonly`), nem toque em `.specboard/verificacoes.jsonl` ou `/api/decisao`.

### 4. Contratos e emendas
Antes dos resultados principais de um módulo, confirme o contrato com o usuário e rode `python SB lock <MOD>`. Qualquer mudança posterior exige `python SB amend <MOD> -j "motivo"`.
