#!/usr/bin/env python3
"""Hook PreToolUse multi-plataforma (Claude Code, OpenAI Codex e Google Antigravity).

Impede que qualquer agente se autovalide:
  - comandos shell chamando `specboard ... review|verify|request-changes|policy`
  - comandos shell iniciando `specboard ... serve` sem `--readonly`
  - chamadas diretas para `/api/decisao` ou `/api/politica`
  - escrita ou edição direta em `.specboard/verificacoes.jsonl`
"""
from __future__ import annotations

import json
import re
import sys

try:
    sys.stderr.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def _deny(reason: str, is_antigravity: bool) -> None:
    if is_antigravity:
        print(json.dumps({"decision": "deny", "reason": reason}, ensure_ascii=False))
        sys.exit(0)
    print(reason, file=sys.stderr)
    sys.exit(2)


def _allow(is_antigravity: bool) -> None:
    if is_antigravity:
        print(json.dumps({"decision": "allow"}))
    sys.exit(0)


def main() -> None:
    try:
        dados = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    # Detecta contrato Antigravity (camelCase hookEventName / toolCall) vs Claude/Codex (tool_name / tool_input)
    is_agy = "toolCall" in dados or "hookEventName" in dados
    if is_agy:
        tc = dados.get("toolCall") or {}
        ferramenta = str(tc.get("name") or "")
        entrada = tc.get("args") or {}
    else:
        ferramenta = str(dados.get("tool_name") or "")
        entrada = dados.get("tool_input") or {}
    if not isinstance(entrada, dict):
        entrada = {"input": str(entrada)}

    fname_low = ferramenta.lower()
    if fname_low in ("bash", "powershell", "run_command", "shell", "exec_command"):
        cmd = str(entrada.get("command") or entrada.get("CommandLine") or entrada.get("cmd") or "")
        if (
            re.search(r"specboard(\.py)?\b.*\b(review|verify|request-changes|policy)\b", cmd)
            or (re.search(r"specboard(\.py)?\b.*\bserve\b", cmd) and "--readonly" not in cmd)
            or "verificacoes.jsonl" in cmd
            or "/api/decisao" in cmd
            or "/api/politica" in cmd
        ):
            _deny(
                "Bloqueado: decisão humana (revisão, aprovação, pedido de correção ou mudança de política) "
                "não pode ser executada pelo agente. Peça ao usuário para decidir pelo painel ou terminal.",
                is_agy,
            )

    if fname_low in ("write", "edit", "multiedit", "notebookedit", "write_file", "edit_file", "apply_patch"):
        candidatos = [
            str(entrada.get("file_path") or ""),
            str(entrada.get("notebook_path") or ""),
            str(entrada.get("Path") or ""),
            str(entrada.get("path") or ""),
            str(entrada.get("input") or ""),
        ]
        blob = " ".join(candidatos).replace("\\", "/")
        if re.search(r"(^|[\s/\"'])(\.specboard/)?verificacoes\.jsonl\b", blob):
            _deny(
                "Bloqueado: verificacoes.jsonl só pode ser escrito por ação humana (painel ou CLI interativo).",
                is_agy,
            )

    _allow(is_agy)


if __name__ == "__main__":
    main()
