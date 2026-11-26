# Aba Agente — Arquitetura Técnica por Etapa

A aba **Agente** oferece a visão técnica do mesmo projeto descrito em `.specboard/estado.json`, inspirada nas camadas **Learn / Guard / Review / Score**, em engenharia de contexto para retomada limpa, avaliação de trajetórias e nas convenções semânticas do OpenTelemetry para chamadas de ferramentas (`execute_tool`) — sem exigir frameworks externos.

## Estrutura de `arquitetura_agente` (em módulo ou etapa)

```json
"arquitetura_agente": {
  "papel": "Analista de trajetórias MD (cálculo determinístico)",
  "contexto_duravel": {
    "objetivo": "Calcular RMSD do núcleo grafítico a 400 K.",
    "decisoes_aceitas": ["D-01: janela 5–10 ns", "D-02: unidades em Å"],
    "protocolo": {"nome": "protocolo-md-cd", "versao": "v2.1", "caminho": "reports/relatorio_m2.md"},
    "janela_analise": "5.0–10.0 ns",
    "artefatos_referencia": [
      {"nome": "Estrutura de referência", "caminho": "data/core_ref.xyz", "papel": "alinhamento"}
    ]
  },
  "contexto_execucao": {
    "fontes_carregadas": ["protocolo-md-cd v2.1", "data/core_ref.xyz", "contrato M2"],
    "fontes_omitidas": ["logs brutos da Fase 1"],
    "estrategia_retomada": "Rodar `python specboard.py context M2.2` ao iniciar sessão limpa."
  },
  "componentes": [
    {
      "id": "cd-rmsd-analysis",
      "nome": "cd-rmsd-analysis",
      "tipo": "skill",
      "versao_origem": "skills/cd-rmsd-analysis v1.2",
      "funcao": "Padroniza extração de janela e checagem de unidades.",
      "motivo_escolha": "Evita mistura Å/nm.",
      "planejado": true,
      "configurado": true
    },
    {
      "id": "calc_rmsd.py",
      "nome": "calc_rmsd.py",
      "tipo": "local_tool",
      "versao_origem": "scripts/calc_rmsd.py",
      "funcao": "Calcula estatísticas determinísticas de RMSD.",
      "planejado": true,
      "configurado": true
    },
    {
      "id": "pubchem-mcp",
      "nome": "pubchem-mcp",
      "tipo": "mcp_tool",
      "mcp_server": "pubchem-reference",
      "versao_origem": "mcp:pubchem-reference v0.4",
      "funcao": "Consulta externa opcional; usada só quando houver recurso externo pertinente.",
      "planejado": false,
      "configurado": true
    }
  ],
  "guardrails": [
    {
      "id": "G-01",
      "regra": "Conferir unidade em Angstrom (Å)",
      "natureza": "codigo",
      "onde_aplica": "scripts/calc_rmsd.py::analisar_rmsd",
      "verifica": "Existência de rmsd_core_angstrom",
      "se_falhar": "Aborta com exit 1"
    },
    {
      "id": "G-02",
      "regra": "Nunca editar dados originais",
      "natureza": "instrucao",
      "onde_aplica": "SKILL.md",
      "verifica": "Disciplina do agente",
      "se_falhar": "Detectado via divergência de SHA-256"
    }
  ],
  "linhagem": [
    {"etapa_fluxo": "Script local", "artefato": "scripts/calc_rmsd.py", "detalhe": "checagens determinísticas"},
    {"etapa_fluxo": "Resultado", "artefato": "data/rmsd_cd_400k.csv", "detalhe": "série temporal"},
    {"etapa_fluxo": "Evidência", "artefato": "figs/estabilidade_cd_400k.png", "detalhe": "figura revisada no marco"}
  ],
  "avaliacao": {
    "nota_separacao": "Avaliação técnica da arquitetura do agente ≠ validação científica pelo usuário.",
    "casos_referencia": [
      {
        "id": "EVAL-01",
        "titulo": "Rejeição de entrada em nm",
        "qualidade_resultado": "100% detecção",
        "trajetoria_ferramentas": "cd-rmsd-analysis → calc_rmsd.py",
        "tempo_ou_chamadas": "2 chamadas · 1.4 s",
        "status": "passou"
      }
    ]
  }
}
```

## Separação Planejado × Configurado × Observado

- **Planejado / Configurado:** vêm de `estado.json` (`componentes[]`).
- **Observado:** vem **exclusivamente** de `.specboard/execucoes.jsonl`, gravado via `python specboard.py trace-tool <ETAPA> --tool <NOME> --type skill|local_tool|mcp_tool [--mcp-server ...] [--duracao-ms ...]`.
- Quando não existe telemetria registrada para um componente, a interface exibe explicitamente **`sem registro`** — nunca infere uso a partir da configuração.

## Retomada em sessão limpa

Execute:

```bash
python specboard.py context <ETAPA>
# ou saída estruturada para outro agente:
python specboard.py context <ETAPA> --json
```

O comando monta somente o contexto durável versionado pertinente àquela etapa (protocolo, estrutura de referência com SHA-256 live, janela de análise, contrato do módulo, último ponto confirmado por humano e guardrails ativos), sem despejar fases ou logs irrelevantes na janela do modelo.
