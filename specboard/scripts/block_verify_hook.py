#!/usr/bin/env python3
"""Hook PreToolUse do Claude Code (e compatíveis): impede o agente de se autovalidar.

Bloqueia (exit 2):
  - comandos shell que chamem `specboard ... review|verify|request-changes|policy`
  - comandos shell que iniciem `specboard ... serve` sem `--readonly`
  - chamadas HTTP diretas para `/api/decisao` ou `/api/politica`
  - qualquer referência ou escrita/edição em `.specboard/verificacoes.jsonl`
"""
import json
import re
import sys

try:
    sys.stderr.reconfigure(encoding="utf-8")  # acentos legíveis no Windows
except Exception:
    pass

try:
    dados = json.load(sys.stdin)
except Exception:
    sys.exit(0)

ferramenta = dados.get("tool_name", "")
entrada = dados.get("tool_input", {}) or {}

if ferramenta in ("Bash", "PowerShell"):
    cmd = entrada.get("command", "") or ""
    if (
        re.search(r"specboard(\.py)?\b.*\b(review|verify|request-changes|policy)\b", cmd)
        or (re.search(r"specboard(\.py)?\b.*\bserve\b", cmd) and "--readonly" not in cmd)
        or "verificacoes.jsonl" in cmd
        or "/api/decisao" in cmd
        or "/api/politica" in cmd
    ):
        print(
            "Bloqueado: decisão humana (revisão, aprovação, pedido de correção ou mudança de política) "
            "não pode ser executada pelo agente. Peça ao usuário para decidir pelo painel ou terminal.",
            file=sys.stderr,
        )
        sys.exit(2)

if ferramenta in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
    alvo = (entrada.get("file_path") or entrada.get("notebook_path") or "").replace("\\", "/")
    if alvo.endswith(".specboard/verificacoes.jsonl") or alvo.endswith("/verificacoes.jsonl"):
        print(
            "Bloqueado: verificacoes.jsonl só pode ser escrito por ação humana (painel ou CLI interativo).",
            file=sys.stderr,
        )
        sys.exit(2)

sys.exit(0)
