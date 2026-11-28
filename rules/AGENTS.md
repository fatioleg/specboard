# SpecBoard — Regras do Plugin

Quando o plugin **SpecBoard** estiver ativo em um projeto contendo `.specboard/estado.json`:

1. **Zero autovalidação:** nunca aprove, revise, peça correção ou altere a política de aprovação em nome do humano. Nunca escreva em `.specboard/verificacoes.jsonl` nem inicie `specboard serve` sem `--readonly`.
2. **Consulte o gate antes de avançar:** use a ferramenta MCP `specboard_gate` (ou `python specboard.py gate <ETAPA>`) antes de iniciar uma etapa dependente.
3. **Retomada limpa:** use `specboard_context` para carregar apenas protocolo, referências e contrato da etapa ativa sem arrastar histórico irrelevante.
4. **Telemetria honesta:** registre ferramentas usadas via `specboard_trace_tool` e nunca marque uma etapa como verificada sem aprovação humana explícita.
5. **Rebuild após mudanças:** ao atualizar `.specboard/estado.json`, rode `specboard_validate` e `specboard_build` para manter `.specboard/painel.html` sincronizado.
6. **Resumo da entrega sempre didático:** escreva `afirmacao` (ou `resumo_didatico`) em português claro explicando *o que foi feito, por que importa e qual resultado prático foi obtido*. Nunca despeje nomes de scripts (`.py`/`.yaml`), flags de terminal (`--flag`), identificadores `snake_case` ou códigos internos sem explicação (`D28`, `doc 13`) no resumo principal — coloque detalhes técnicos em `detalhes_tecnicos` e arquivos em `evidencia`. Valide com `specboard_validate(estrito=true)` ou `python specboard.py validate --estrito`.
