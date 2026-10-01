#!/usr/bin/env python3
"""Hook PreToolUse do Claude Code: impede o agente de se autovalidar.

Bloqueia (exit 2):
  - comandos shell que chamem `specboard ... review|verify`
  - qualquer escrita/edição em .specboard/verificacoes.jsonl
"""
import json, re, sys

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
    cmd = entrada.get("command", "")
    if re.search(r"specboard(\.py)?\b.*\b(review|verify)\b", cmd) or "verificacoes.jsonl" in cmd:
        print("Bloqueado: revisão/verificação é ato humano. Peça ao usuário para rodar "
              "o comando no terminal dele.", file=sys.stderr)
        sys.exit(2)

if ferramenta in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
    alvo = (entrada.get("file_path") or entrada.get("notebook_path") or "").replace("\\", "/")
    if alvo.endswith(".specboard/verificacoes.jsonl"):
        print("Bloqueado: verificacoes.jsonl só é escrito pelo comando humano.", file=sys.stderr)
        sys.exit(2)

sys.exit(0)
