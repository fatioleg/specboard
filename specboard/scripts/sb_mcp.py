#!/usr/bin/env python3
"""Servidor MCP stdio do SpecBoard (Python 3 stdlib puro, zero dependências externas).

Compatível com Claude Code, OpenAI Codex e Google Antigravity.
Expõe SOMENTE ferramentas seguras para agentes (leitura, gate, contexto limpo,
validação, build offline, telemetria e mapa do harness).

REGRA DE SEGURANÇA (ZERO AUTOVALIDAÇÃO):
  Nenhuma ferramenta MCP pode gravar em `.specboard/verificacoes.jsonl`, aprovar
  etapas ou alterar a política de aprovação. Decisões humanas acontecem apenas
  pelo painel web (`specboard serve`) ou pelo terminal humano.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import sb_core as core  # noqa: E402

SERVER_INFO = {
    "name": "specboard",
    "version": "2.4.0",
}
SUPPORTED_PROTOCOL = "2024-11-05"
TEMPLATE_PATH = SCRIPTS_DIR.parent / "assets" / "painel_template.html"

TOOLS: list[dict[str, Any]] = [
    {
        "name": "specboard_status",
        "description": (
            "Retorna o resumo atual do projeto SpecBoard: fase atual, progresso verificado pelo humano, "
            "política ativa, fila pendente de aprovação e bloqueios do sistema."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "dir": {"type": "string", "description": "Diretório raiz do projeto (contendo .specboard/). Padrão: diretório atual."},
            },
        },
    },
    {
        "name": "specboard_queue",
        "description": "Lista a fila priorizada de entregas aguardando decisão humana.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "dir": {"type": "string", "description": "Diretório raiz do projeto. Padrão: diretório atual."},
                "todas": {"type": "boolean", "description": "Se true, inclui também etapas não bloqueantes na política atual."},
            },
        },
    },
    {
        "name": "specboard_gate",
        "description": (
            "Verifica deterministicamente se uma etapa está liberada para execução pela política de aprovação "
            "ou bloqueada aguardando decisão humana / pré-requisito."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["etapa_id"],
            "properties": {
                "dir": {"type": "string", "description": "Diretório raiz do projeto. Padrão: diretório atual."},
                "etapa_id": {"type": "string", "description": "ID da etapa (ex.: M2.3)."},
            },
        },
    },
    {
        "name": "specboard_context",
        "description": "Monta o pacote mínimo versionado de contexto para retomar uma etapa em sessão limpa.",
        "inputSchema": {
            "type": "object",
            "required": ["etapa_id"],
            "properties": {
                "dir": {"type": "string", "description": "Diretório raiz do projeto. Padrão: diretório atual."},
                "etapa_id": {"type": "string", "description": "ID da etapa (ex.: M2.2)."},
            },
        },
    },
    {
        "name": "specboard_validate",
        "description": (
            "Valida .specboard/estado.json, contratos travados, presença das evidências e a Regra de Texto Didático "
            "Obrigatório em TODOS os cards (títulos, resumo da entrega, como conferir, blocos e atividade na Home)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "dir": {"type": "string", "description": "Diretório raiz do projeto. Padrão: diretório atual."},
                "estrito": {
                    "type": "boolean",
                    "description": "Se true, reprova (valido=false) qualquer card (Home, módulo ou etapa) com texto técnico pouco didático.",
                },
            },
        },
    },
    {
        "name": "specboard_build",
        "description": "Gera o snapshot estático offline .specboard/painel.html (somente leitura).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "dir": {"type": "string", "description": "Diretório raiz do projeto. Padrão: diretório atual."},
            },
        },
    },
    {
        "name": "specboard_harness",
        "description": (
            "Retorna o mapa completo do harness do projeto: skills, servidores MCP, scripts locais, "
            "hooks/guardrails em código, orientações em texto, papéis e fluxo de fases/marcos."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "dir": {"type": "string", "description": "Diretório raiz do projeto. Padrão: diretório atual."},
            },
        },
    },
    {
        "name": "specboard_trace_tool",
        "description": "Registra uso observado de uma skill, script local ou MCP em .specboard/execucoes.jsonl (compatível com OTel).",
        "inputSchema": {
            "type": "object",
            "required": ["etapa_id", "tool"],
            "properties": {
                "dir": {"type": "string", "description": "Diretório raiz do projeto. Padrão: diretório atual."},
                "etapa_id": {"type": "string", "description": "ID da etapa."},
                "tool": {"type": "string", "description": "Nome da skill, script ou ferramenta MCP."},
                "tool_type": {
                    "type": "string",
                    "enum": ["local_tool", "mcp_tool", "skill"],
                    "description": "Categoria da ferramenta (padrão: local_tool).",
                },
                "mcp_server": {"type": "string", "description": "Nome do servidor MCP (opcional)."},
                "status": {"type": "string", "enum": ["ok", "erro"], "description": "Resultado (padrão: ok)."},
                "duracao_ms": {"type": "integer", "description": "Duração em milissegundos (opcional)."},
            },
        },
    },
    {
        "name": "specboard_bugs",
        "description": (
            "Lista bugs, problemas de UX e sugestões de melhoria reportados pelos usuários em .specboard/bugs.jsonl "
            "para que o agente possa diagnosticar e corrigir o projeto ou o painel."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "dir": {"type": "string", "description": "Diretório raiz do projeto. Padrão: diretório atual."},
                "status": {
                    "type": "string",
                    "enum": ["aberto", "em_analise", "resolvido", "descartado"],
                    "description": "Filtrar opcionalmente por status.",
                },
            },
        },
    },
    {
        "name": "specboard_bug_update",
        "description": (
            "Atualiza o status e registra o diagnóstico/solução de um agente em um bug reportado (em .specboard/bugs.jsonl). "
            "Não altera aprovações humanas nem verificacoes.jsonl."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["bug_id", "status"],
            "properties": {
                "dir": {"type": "string", "description": "Diretório raiz do projeto. Padrão: diretório atual."},
                "bug_id": {"type": "string", "description": "ID do bug (ex.: BUG-001)."},
                "status": {
                    "type": "string",
                    "enum": ["aberto", "em_analise", "resolvido", "descartado"],
                    "description": "Novo status do bug.",
                },
                "analise_agente": {"type": "string", "description": "Diagnóstico, causa raiz ou resumo da correção feita pelo agente."},
                "atualizado_por": {"type": "string", "description": "Identificação do agente (padrão: agente)."},
            },
        },
    },
]


def _resolve_dir(args: dict[str, Any]) -> Path:
    raw = (args.get("dir") or os.environ.get("SPECBOARD_DIR") or ".").strip()
    return Path(raw).expanduser().resolve()


def call_tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
    base = _resolve_dir(args)
    if name == "specboard_status":
        estado, regs, execs, visita = core.load_all(base)
        pay = core.construir_payload(base, estado, regs, execs, visita)
        return {
            "projeto": (pay["estado"].get("projeto") or {}).get("nome"),
            "politica": pay["politica"],
            "resumo": pay["resumo"],
            "situacao_atual": pay["situacao_atual"],
            "fila_pendentes": len(pay["fila"]),
            "resumos_pouco_didaticos": pay["resumos_pouco_didaticos"],
            "cards_pouco_didaticos": pay["cards_pouco_didaticos"],
            "erros": pay["erros"],
            "avisos": pay["avisos"],
        }
    if name == "specboard_queue":
        estado, regs, execs, visita = core.load_all(base)
        pay = core.construir_payload(base, estado, regs, execs, visita)
        itens = pay["fila_todos"] if args.get("todas") else pay["fila"]
        return {
            "politica": pay["politica"]["modo"],
            "total": len(itens),
            "itens": itens,
        }
    if name == "specboard_gate":
        etapa_id = str(args.get("etapa_id") or "").strip()
        if not etapa_id:
            raise ValueError("Parâmetro obrigatório ausente: etapa_id")
        return core.avaliar_gate(base, etapa_id)
    if name == "specboard_context":
        etapa_id = str(args.get("etapa_id") or "").strip()
        if not etapa_id:
            raise ValueError("Parâmetro obrigatório ausente: etapa_id")
        return core.construir_contexto_limpo(base, etapa_id)
    if name == "specboard_validate":
        estado, regs, execs, visita = core.load_all(base)
        estrito = bool(args.get("estrito", False))
        erros, avisos = core.validar(base, estado, regs, estrito_didatico=estrito)
        pay = core.construir_payload(base, estado, regs, execs, visita)
        return {
            "valido": len(erros) == 0,
            "estrito_didatico": estrito,
            "erros": erros,
            "avisos": avisos,
            "resumos_pouco_didaticos": pay["resumos_pouco_didaticos"],
            "cards_pouco_didaticos": pay["cards_pouco_didaticos"],
            "regra_resumo_didatico": core.REGRA_RESUMO_DIDATICO,
        }
    if name == "specboard_build":
        estado, regs, execs, visita = core.load_all(base)
        pay = core.construir_payload(base, estado, regs, execs, visita, modo_servidor=False)
        html = TEMPLATE_PATH.read_text(encoding="utf-8").replace(
            "/*__DADOS__*/null",
            json.dumps(pay, ensure_ascii=False).replace("</", "<\\/"),
        )
        ps = core.paths(base)
        core.atomic_write_text(ps["painel"], html)
        return {
            "painel": str(ps["painel"]),
            "erros": pay["erros"],
            "dica_interativo": f"Para aprovar/decidir no painel, o humano deve rodar: python specboard.py --dir \"{base}\" serve --open",
        }
    if name == "specboard_harness":
        estado, regs, execs, visita = core.load_all(base)
        pay = core.construir_payload(base, estado, regs, execs, visita)
        return pay["harness_resumo"]
    if name == "specboard_trace_tool":
        etapa_id = str(args.get("etapa_id") or "").strip()
        tool = str(args.get("tool") or "").strip()
        if not etapa_id or not tool:
            raise ValueError("Parâmetros obrigatórios ausentes: etapa_id e tool")
        ttype = str(args.get("tool_type") or "local_tool")
        rec = {
            "etapa": etapa_id,
            "tool_name": tool,
            "gen_ai.tool.name": tool,
            "tool_type": ttype,
            "gen_ai.tool.type": "function" if ttype == "local_tool" else ("extension" if ttype == "mcp_tool" else "skill"),
            "mcp_server": args.get("mcp_server") or None,
            "status": str(args.get("status") or "ok"),
            "duracao_ms": args.get("duracao_ms"),
            "observado_por": "mcp",
            "timestamp": core.agora_str(com_segundos=True),
        }
        ps = core.paths(base)
        if not ps["estado"].exists():
            raise FileNotFoundError(f"Não encontrei {ps['estado']}.")
        core.append_jsonl(ps["execucoes"], rec)
        return {"registrado": True, "arquivo": str(ps["execucoes"]), "evento": rec}
    if name == "specboard_bugs":
        bugs = core.listar_bugs(base)
        st_filter = (args.get("status") or "").strip()
        if st_filter:
            bugs = [b for b in bugs if b.get("status") == st_filter]
        return {"total": len(bugs), "bugs": bugs}
    if name == "specboard_bug_update":
        upd = core.atualizar_bug(
            base,
            bug_id=str(args.get("bug_id") or ""),
            status=str(args.get("status") or ""),
            analise_agente=str(args.get("analise_agente") or ""),
            atualizado_por=str(args.get("atualizado_por") or "agente"),
        )
        return {"atualizado": True, "evento": upd}

    raise KeyError(f"Ferramenta desconhecida: {name}")


def handle_request(req: dict[str, Any]) -> dict[str, Any] | None:
    method = req.get("method")
    req_id = req.get("id")
    params = req.get("params") or {}

    # Notificações JSON-RPC não têm resposta
    if req_id is None and method and method.startswith("notifications/"):
        return None

    if method == "initialize":
        client_proto = params.get("protocolVersion") or SUPPORTED_PROTOCOL
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": client_proto,
                "capabilities": {"tools": {}},
                "serverInfo": SERVER_INFO,
            },
        }
    if method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}}
    if method == "tools/call":
        tname = params.get("name", "")
        targs = params.get("arguments") or {}
        try:
            data = call_tool(tname, targs)
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False, indent=2)}],
                    "isError": False,
                },
            }
        except Exception as exc:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": f"Erro em {tname}: {exc}"}],
                    "isError": True,
                },
            }

    if req_id is None:
        return None
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"Método não suportado: {method}"},
    }


def _read_message(stream) -> tuple[dict[str, Any] | None, str]:
    """Suporta tanto JSON-RPC delimitado por linha quanto framing Content-Length (LSP/MCP)."""
    first = stream.readline()
    if not first:
        return None, "jsonl"
    line = first.decode("utf-8", errors="replace").strip()
    if not line:
        return _read_message(stream)
    if line.startswith("{"):
        return json.loads(line), "jsonl"
    headers: dict[str, str] = {}
    while line:
        if ":" in line:
            k, v = line.split(":", 1)
            headers[k.strip().lower()] = v.strip()
        nxt = stream.readline()
        if not nxt:
            return None, "lsp"
        line = nxt.decode("utf-8", errors="replace").strip()
    length = int(headers.get("content-length", "0"))
    if length <= 0:
        return None, "lsp"
    body = stream.read(length)
    return json.loads(body.decode("utf-8")), "lsp"


def _write_message(stream, msg: dict[str, Any], mode: str) -> None:
    raw = json.dumps(msg, ensure_ascii=False).encode("utf-8")
    if mode == "lsp":
        header = f"Content-Length: {len(raw)}\r\n\r\n".encode("ascii")
        stream.write(header + raw)
    else:
        stream.write(raw + b"\n")
    stream.flush()


def main() -> None:
    inp = sys.stdin.buffer
    out = sys.stdout.buffer
    while True:
        try:
            req, mode = _read_message(inp)
        except Exception:
            break
        if req is None:
            break
        resp = handle_request(req)
        if resp is not None:
            _write_message(out, resp, mode)


if __name__ == "__main__":
    main()
