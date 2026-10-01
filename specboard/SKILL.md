---
name: specboard
description: Cria e mantém um painel de validação (HTML) para qualquer projeto em Spec-Driven Development modular, a partir da deep-interview e do plano do oh-my-claudecode (OMC) ou de qualquer spec/plano existente. Converte o plano em módulos, contratos pré-registrados e etapas com afirmação, verificação e evidência, e separa o que o agente executou do que o humano verificou. Use sempre que o usuário quiser acompanhar, rastrear, visualizar ou validar o andamento de um projeto modular, pedir um "mapa dos módulos", "painel", "dashboard de progresso", "fila de revisão", ou terminar um planejamento e quiser começar a execução — mesmo que não diga "specboard".
---

# specboard — painel de validação para projetos modulares

## Por que existe
Em projetos com agentes, o gargalo é a validação humana, não a execução. Este painel
existe para mostrar **o que ainda falta você conferir**, não para celebrar etapas feitas.
Três ideias guiam tudo:

1. **Executado ≠ verificado.** O agente só chega até `executado`. `revisado` e `verificado`
   são atos humanos, registrados por comando interativo em `.specboard/verificacoes.jsonl`.
2. **Denominador honesto.** O progresso conta todas as etapas planejadas, inclusive as
   estimativas de módulos ainda sem contrato. Uma barra quase cheia que ignora o que não
   começou é autoengano.
3. **Pré-registro.** Critérios de aceitação e de abandono são escritos e travados antes de
   ver resultados. Mudança posterior vira emenda visível, nunca edição silenciosa.

O painel é sempre **gerado** a partir de `.specboard/estado.json`. Nunca edite o HTML.

## Arquivos da skill
- `scripts/specboard.py` — CLI: `init`, `validate`, `lock`, `amend`, `queue`, `build`, e os
  comandos humanos `review`/`verify`. Python 3 puro, sem dependências; roda em PowerShell.
- `scripts/block_verify_hook.py` — hook PreToolUse que impede o agente de se autovalidar.
- `assets/painel_template.html` — template do painel (não editar por projeto).
- `assets/estado_exemplo.json` — esqueleto inicial.
- `references/formato-estado.md` — **leia antes de escrever o estado.json**: todos os campos e regras.

Abaixo, `SB` = caminho absoluto de `scripts/specboard.py` desta skill. Resolva-o uma vez
(ex.: `~/.claude/skills/specboard/scripts/specboard.py`) e use o caminho real nos comandos.

## Fluxo

### 1. Montar o estado a partir do plano
1. Procure os artefatos do planejamento. Com OMC, eles costumam estar em `.omc/` (specs da
   deep-interview e planos). Se não achar, ou se houver mais de um candidato, pergunte ao
   usuário qual arquivo é a spec e qual é o plano. Não invente um plano.
2. Rode `python SB init` na raiz do projeto.
3. Leia `references/formato-estado.md` e preencha `.specboard/estado.json`:
   - `pergunta_central`: a pergunta que a deep-interview estabeleceu, em uma frase.
   - Um módulo por unidade de entrega do plano, com `depende_de` e `fase`.
   - Marque `resultado_final: true` no módulo que responde a pergunta central.
   - Módulos que o plano detalha recebem `etapas`; os demais recebem só `etapas_estimadas`.
   - Para cada etapa, defina `impacto` pensando na pergunta central: o que, se estiver
     errado, muda a resposta? Isso é `alto`. Seja parcimonioso: se tudo é alto, nada é.
   - Painel didático: preencha também os campos opcionais (`responde`, `data`, `descricao`,
     `quem`, `registro`, `glossario`, `pendencias_humanas`). Sem eles o mapa funciona, mas
     perde a linha do tempo, o "você está aqui" explicado e a tradução das siglas.
   - Contratos: copie da spec os critérios de aceitação. Se a spec não tiver
     `criterio_abandono`, **pergunte ao usuário** em vez de inventar.
4. `python SB validate` até passar; depois `python SB build --open`.
5. Mostre ao usuário o painel e liste explicitamente as suposições que você fez ao converter
   o plano (módulos agrupados, impactos atribuídos, estimativas). Ele aprova ou corrige.

### 2. Instalar a proteção (uma vez por projeto)
Adicione ao `.claude/settings.json` do projeto (crie se não existir; mescle se existir),
usando o caminho absoluto real do hook:

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

Crie também `.specboard/COMANDOS.txt` com os comandos humanos já com o caminho real, para o
usuário copiar no terminal dele:
`python "<SB>" queue`, `python "<SB>" review M0.1`, `python "<SB>" verify M0.1`, `python "<SB>" build --open`.

Seja franco com o usuário: o hook e a exigência de terminal interativo evitam
autovalidação **acidental**. Um agente determinado ainda poderia contornar editando
arquivos por outros meios; a defesa final é o `git diff` de `.specboard/` na revisão.

### 3. Durante a execução (a cada etapa)
- Ao começar uma etapa: `status: em_curso`.
- Ao terminar: `status: executado`, com `afirmacao`, `verificacao` e `evidencia` preenchidos.
  A `verificacao` deve permitir ao humano conferir em poucos minutos; veja exemplos no
  arquivo de referência.
- Se travar: `status: bloqueado` e `bloqueio` com o motivo.
- Depois de qualquer mudança: `python SB validate && python SB build`.
- **Nunca** escreva `revisado`/`verificado`, nunca toque em `verificacoes.jsonl`, nunca rode
  `review`/`verify`. Quando houver itens na fila, diga ao usuário quais rodar, em ordem de
  impacto, e pare de abrir etapas novas de impacto alto se a fila já tiver mais de ~5 itens
  aguardando: produzir mais do que o humano consegue validar só aumenta o acúmulo.

### 4. Antes de ver resultados de um módulo
Antes de rodar a etapa que produz o resultado principal de um módulo, confirme com o usuário
que o contrato está completo e rode `python SB lock <MOD>`. Se depois for necessário mudar
critérios, edite o contrato e rode `python SB amend <MOD> -j "motivo"`. Nunca altere um
contrato travado sem emenda.

## Acompanhamento ao vivo
Abra `.specboard/painel.html` com `#live` no final do endereço (ou clique em "ativar ao
vivo"): a página recarrega a cada 10 s e reflete cada `build`. Não há animação de propósito:
o painel serve para decidir o que conferir, não para assistir ao agente trabalhar.

## O que não fazer
- Não crie painéis específicos por projeto nem edite o template para um projeto só. Se o
  formato não comporta um projeto, proponha mudança no template ao usuário.
- Não marque o progresso pelo que o agente executou.
- Não preencha critério de abandono, pergunta central ou impacto alto sem base na spec ou
  na confirmação do usuário.
