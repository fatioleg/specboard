# Formato de `.specboard/estado.json` (v2 — retrocompatível com v1)

Leia este arquivo ao criar ou atualizar o estado de um projeto. Todos os campos introduzidos na v2 são **opcionais**, preservando 100% de compatibilidade com projetos legados (como `examples/estado_completo.json`).

## Projeto (`projeto`)

| Campo | Obrigatório | Nota |
|---|---|---|
| `projeto.nome` | sim | Nome curto do projeto. |
| `projeto.pergunta_central` | sim | A pergunta que o projeto responde, em uma frase. |
| `fases` | não | Fases em ordem no fluxograma do Projeto (ex.: `["Fase 1", "Fase 2", "Fase 3"]`). |
| `projeto.titulo` / `projeto.subtitulo` | não | Título principal e contexto no cabeçalho. |
| `projeto.politica_aprovacao` | não | `{ "modo": "so_marcos" \| "por_etapa" \| "acompanhamento_livre", "canal_padrao": "painel" \| "terminal" \| "ambos", "definida_em": "...", "definida_por": "..." }`. Sem ele, assume `por_etapa` (modo legado). |
| `projeto.atividade_agente` | não | `{ "estado": "executando" \| "aguardando_humano" \| "aguardando_correcao" \| "ocioso" \| "sem_dados", "etapa_id": "M2.2", "resumo": "...", "sessao_id": "...", "atualizado_em": "..." }`. Exibida separadamente dos bloqueios do sistema. |
| `projeto.voce_esta_aqui` | não | Override opcional do ID da etapa em destaque. |
| `projeto.pendencias_humanas` | não | Lista `{id, texto, bloqueia, modulo}` de decisões que só o humano pode tomar. |
| `projeto.comando_humano` | não | Prefixo do comando humano (ex.: com `ssh -t ...`), exibido no modo estático. |
| `projeto.limite_fila` | não | Tamanho da fila bloqueante acima do qual o sistema sinaliza parada em etapas de impacto alto (padrão `5`). |
| `projeto.fontes` | não | Documentos/specs de origem do estado. |

## Módulo (`modulos[]`)

| Campo | Nota |
|---|---|
| `id` | Curto e estável (`M0`, `M1`, `M2-B`). Nunca renumere. |
| `titulo`, `objetivo`, `fase` | Identificação e fase correspondente em `fases`. |
| `depende_de` | Lista de IDs de módulos dos quais este módulo depende. |
| `relacoes` | (opcional) Lista explícita `{ "para": "M3", "tipo": "bloqueante" \| "sequencia", "motivo": "..." }`. |
| `marco` | (opcional, booleano) Marca o módulo como ponto de controle na política `so_marcos` quando etapas individuais não declararem `marco`. |
| `resultado_final` | `true` no(s) módulo(s) que respondem à pergunta central. |
| `contrato` | `{pergunta, criterios_aceitacao, criterio_abandono, parametros, travado_em, hash}`. `travado_em` e `hash` só são escritos por `lock`/`amend`. |
| `etapas_estimadas` | Para módulos ainda não detalhados; entra no denominador honesto do progresso. |
| `etapas` | Lista de etapas (abaixo). |
| `emendas` | Escrito somente por `amend`. |
| `arquitetura_agente` | (opcional) Configuração técnica padrão herdada pelas etapas do módulo (ver [arquitetura-agente.md](arquitetura-agente.md)). |
| `responde`, `quando`, `registro`, `bloqueio` | Campos opcionais de contexto e bloqueio explícito. |

## Etapa (`etapas[]`)

| Campo | Nota |
|---|---|
| `id` | `<modulo>.<n>` (ex.: `M2.3`). Estável. |
| `titulo` | Nome claro da entrega. |
| `status` | Agente só usa: `pendente`, `em_curso`, `executado`, `bloqueado`. Estados humanos (`revisado`, `verificado`, `correcao_solicitada`) vêm exclusivamente de `.specboard/verificacoes.jsonl`. |
| `impacto` | `alto` / `medio` / `baixo`. |
| `revisao` | `completa` (padrão), `amostragem` (impacto baixo) ou `isenta`. |
| `marco` | (opcional, booleano) **Granularidade de marco:** `true` exige aprovação humana nesta etapa específica na política `so_marcos` para liberar dependentes. |
| `depende_de` | (opcional) Lista de IDs de etapas ou módulos dos quais esta etapa depende diretamente. |
| `afirmacao` | O que a etapa estabeleceu. Obrigatório para `executado`. |
| `verificacao` | Como o humano confere em poucos minutos. Obrigatório para `executado`. |
| `evidencia` | Lista de strings (legado) ou objetos `{id, caminho, tipo, descricao, versao, sha256_esperado, obrigatoria}`. Arquivos locais têm o SHA-256 dos bytes verificado em disco. |
| `criterios` | (opcional) Critérios específicos da etapa vinculados ao hash de decisão. |
| `arquitetura_agente` | (opcional) Configuração técnica da etapa para a aba **Agente** (ver [arquitetura-agente.md](arquitetura-agente.md)). |
| `data`, `descricao`, `bloqueio` | Metadados opcionais. |

## Arquivos auxiliares em `.specboard/`

| Arquivo | Quem escreve | Papel |
|---|---|---|
| `.specboard/estado.json` | Agente / plano | Estado estrutural, contratos, entregas e arquitetura técnica. |
| `.specboard/verificacoes.jsonl` | **Apenas humano** (painel `serve` ou CLI) | Ledger append-only de aprovações, revisões, pedidos de correção e mudanças de política, com hash SHA-256 dos bytes das evidências e do critério. |
| `.specboard/execucoes.jsonl` | Wrapper / telemetria | Observações reais de execução de skills, scripts locais e MCPs (formato compatível com OpenTelemetry `execute_tool`). |
| `.specboard/visita.json` | Painel (`serve`, gitignored) | Marcador local de última visita para calcular mudanças desde a última visita. |
| `.specboard/.hash_cache.json` | SpecBoard (gitignored) | Cache local `(size, mtime_ns) -> sha256` (sempre ignorado em gravações estritas de decisão). |
