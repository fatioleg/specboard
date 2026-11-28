# SpecBoard — Regras do Plugin

Quando o plugin **SpecBoard** estiver ativo em um projeto contendo `.specboard/estado.json`:

1. **Zero autovalidação:** nunca aprove, revise, peça correção ou altere a política de aprovação em nome do humano. Nunca escreva em `.specboard/verificacoes.jsonl` nem inicie `specboard serve` sem `--readonly`.
2. **Consulte o gate antes de avançar:** use a ferramenta MCP `specboard_gate` (ou `python specboard.py gate <ETAPA>`) antes de iniciar uma etapa dependente.
3. **Retomada limpa:** use `specboard_context` para carregar apenas protocolo, referências e contrato da etapa ativa sem arrastar histórico irrelevante.
4. **Telemetria honesta:** registre ferramentas usadas via `specboard_trace_tool` e nunca marque uma etapa como verificada sem aprovação humana explícita.
5. **Rebuild após mudanças:** ao atualizar `.specboard/estado.json`, rode `specboard_validate` e `specboard_build` para manter `.specboard/painel.html` sincronizado.
6. **Regra de Texto Didático Obrigatório em TODOS os cards (Home, Blocos, Etapas e Revisão):** escreva `titulo`, `objetivo`, `projeto.atividade_agente.resumo`, `afirmacao` (ou `resumo_didatico`) e `verificacao` (*Como conferir*) em português claro para o revisor humano — explicando **o quê foi feito**, **qual a regra ou resultado concreto** e **por que importa / qual evidência abrir para conferir**. **Proibido em qualquer card visível:** nomes de scripts (`.py`/`.yaml`/`.json`), hashes ou termos Git (`3dba70d`, `commit`, `commits`), flags (`--flag`), identificadores `snake_case` e códigos/apelidos internos sem explicação (`D50`, `D28`, `doc 13`, `Frente C`, `Ciclo 1`, `Gate A`, `Fase III`). Use sempre IDs do SpecBoard (ex.: `M4.5`), mova toda a rastreabilidade técnica para `detalhes_tecnicos` / `evidencia` e valide sempre com `specboard_validate(estrito=true)` ou `python specboard.py validate --estrito`.
