# Formato de `.specboard/estado.json`

Leia este arquivo ao criar ou converter o estado de um projeto.

## Projeto
| Campo | Obrigatório | Nota |
|---|---|---|
| `projeto.nome` | sim | |
| `projeto.pergunta_central` | sim | A pergunta que o projeto responde, em uma frase. Vem da deep-interview. |
| `fases` | não | Colunas do mapa, em ordem (ex.: Base, Frentes em paralelo, Consolidação, Resultado). |
| `projeto.titulo` / `projeto.subtitulo` | não | Título grande do painel e linha de contexto no topo. |
| `projeto.voce_esta_aqui` | não | ID da etapa a destacar. Sem ele: etapa `em_curso`, senão a próxima `pendente` de um módulo aberto no caminho até o resultado. |
| `projeto.pendencias_humanas` | não | Lista `{id, texto, bloqueia, modulo}`: decisões que só o usuário pode tomar. Entram em "O que falta" marcadas "você". |
| `projeto.glossario` | não | Lista de pares `[termo, explicação]` (siglas do projeto). Aparece em "Como ler este painel". |
| `projeto.comando_humano` | não | Prefixo real do comando humano (ex.: com `ssh -t ...`), mostrado na fila e em cada etapa. |
| `projeto.limite_fila` | não | Tamanho da fila acima do qual o agente não abre etapas de impacto alto (padrão 5). |
| `projeto.fontes` | não | De onde o estado foi convertido (specs, planos), mostrado no rodapé. |

## Módulo
| Campo | Nota |
|---|---|
| `id` | Curto e estável (M0, M1, M3-A...). Nunca renumere depois de criado. |
| `titulo`, `objetivo` | Texto curto. |
| `fase` | Deve estar em `fases`. |
| `depende_de` | Lista de IDs de módulos. |
| `resultado_final` | `true` no(s) módulo(s) que respondem a pergunta central. Define o "caminho até o resultado". |
| `contrato.pergunta` | O que o módulo responde. |
| `contrato.criterios_aceitacao` | Lista. Escritos ANTES de ver resultados. |
| `contrato.criterio_abandono` | O que faz o módulo ser abandonado ou o plano ser revisto. |
| `contrato.parametros` | Objeto livre com escolhas fixadas (métodos, limiares, versões). |
| `contrato.travado_em`, `contrato.hash` | Escritos só por `lock`/`amend`. Não edite. |
| `etapas_estimadas` | Para módulos ainda sem etapas: entra no denominador do progresso. |
| `etapas` | Lista de etapas (abaixo). |
| `emendas` | Escrito só por `amend`. |
| `responde` | (opcional) Que parte da pergunta central este módulo responde. Muito útil no detalhe. |
| `quando` | (opcional) Ex.: "fechado em 28/09". |
| `registro` | (opcional) Onde ficam os resultados (IDs de fatos, pastas de figuras). |
| `bloqueio` | (opcional) Motivo de bloqueio do módulo inteiro (ex.: decisão pendente do usuário). |

## Etapa
| Campo | Nota |
|---|---|
| `id` | `<modulo>.<n>` (M0.1). Estável. |
| `titulo` | |
| `status` | Agente só usa: `pendente`, `em_curso`, `executado`, `bloqueado`. |
| `impacto` | `alto` / `medio` / `baixo`: quanto esta etapa pode mudar a resposta à pergunta central. |
| `revisao` | `completa` (padrão) ou `amostragem` (só para impacto baixo). |
| `afirmacao` | O que a etapa afirma ter estabelecido. Obrigatório para `executado`. |
| `verificacao` | Como um humano confere isso em poucos minutos (arquivo, número, gráfico, comparação). Obrigatório para `executado`. |
| `evidencia` | IDs ou caminhos de artefatos que sustentam a afirmação. |
| `bloqueio` | (opcional) motivo, quando `status` = `bloqueado`. |
| `data` | (opcional) `AAAA-MM-DD` em que a etapa foi executada; alimenta a linha do tempo "O que já foi feito". |
| `descricao` | (opcional) O que a etapa vai fazer, para etapas ainda `pendente`/`em_curso` (aparece em "Você está aqui"). |
| `quem` | (opcional) Quem age a seguir, ex.: "agente escreve → você aprova". |

## Regras que o `validate` impõe
- `revisado`/`verificado` nunca aparecem no `estado.json`; vêm de `.specboard/verificacoes.jsonl`, escrito só pelo comando humano.
- Se `afirmacao`, `verificacao`, `evidencia` ou `titulo` de uma etapa mudarem depois de verificada, a verificação **expira** e a etapa volta à fila.
- Contrato travado alterado sem `amend` é erro.
- Dependência para módulo inexistente é erro.

## Boas e más `verificacao`
- Boa: "Abrir `out/resultados.csv`; a métrica X deve estar entre A e B e bater com a tabela de referência T2."
- Boa: "Rodar `pytest tests/test_parser.py`; os 12 testes passam."
- Má: "Verificar se está correto." (não diz o quê nem como)
- Má: "Revisar o código." (sem critério de aprovação)
