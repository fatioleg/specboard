"""Testes da área de Reporte de Bugs & Melhorias (core, HTTP API, MCP e templates GitHub)."""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "specboard" / "scripts"
TEMPLATE = REPO / "specboard" / "assets" / "painel_template.html"
sys.path.insert(0, str(SCRIPTS))

import sb_core as core  # noqa: E402
import sb_mcp as mcp  # noqa: E402
import sb_server as srv  # noqa: E402


class TestBugsSystem(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="sb_bugs_"))
        shutil.copytree(REPO / "examples" / "carbon_dots", self.tmp / "proj")
        self.proj = self.tmp / "proj"

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_core_and_mcp_bug_lifecycle(self) -> None:
        b = core.registrar_bug(
            self.proj,
            titulo="Caixa de critérios estreita no mapa",
            descricao="Texto quebrava em 3 colunas estreitas.",
            passos="Abrir Projeto -> clicar em M1.1",
            tipo="ux",
            severidade="alto",
            tela_origem="projeto",
            etapa_id="M1.1",
            tema="light",
            viewport="1440x880",
            reportado_por="Pesquisador",
        )
        self.assertEqual(b["id"], "BUG-001")
        self.assertEqual(b["status"], "aberto")

        # Agente lê bugs via MCP specboard_bugs
        r_list = mcp.handle_request({
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "specboard_bugs", "arguments": {"dir": str(self.proj), "status": "aberto"}},
        })
        self.assertFalse(r_list["result"]["isError"])
        data = json.loads(r_list["result"]["content"][0]["text"])
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["bugs"][0]["id"], "BUG-001")

        # Agente registra análise e marca como resolvido via MCP specboard_bug_update
        r_upd = mcp.handle_request({
            "jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {
                "name": "specboard_bug_update",
                "arguments": {
                    "dir": str(self.proj),
                    "bug_id": "BUG-001",
                    "status": "resolvido",
                    "analise_agente": "Substituído grid de 3 colunas por bloco em largura total.",
                    "atualizado_por": "agente-ux",
                },
            },
        })
        self.assertFalse(r_upd["result"]["isError"])
        bugs_after = core.listar_bugs(self.proj)
        self.assertEqual(bugs_after[0]["status"], "resolvido")
        self.assertIn("largura total", bugs_after[0]["analise_agente"])

    def test_server_bug_endpoints_with_csrf(self) -> None:
        server = srv.create_server(self.proj, TEMPLATE, host="127.0.0.1", port=0, readonly=False)
        host, port = server.server_address[:2]
        base_url = f"http://{host}:{port}"
        th = threading.Thread(target=server.serve_forever, daemon=True)
        th.start()
        try:
            # Sem token CSRF -> 403
            req_bad = urllib.request.Request(
                f"{base_url}/api/bug",
                data=json.dumps({"titulo": "Sem token"}).encode("utf-8"),
                headers={"Content-Type": "application/json", "Origin": base_url},
                method="POST",
            )
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req_bad)
            self.assertEqual(ctx.exception.code, 403)

            # Com token CSRF -> 200 e persistido em bugs.jsonl
            req_ok = urllib.request.Request(
                f"{base_url}/api/bug",
                data=json.dumps({
                    "titulo": "Botão Home visível em todas as telas",
                    "tipo": "melhoria",
                    "severidade": "baixo",
                    "tela_origem": "agora",
                    "tema": "dark",
                }).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Origin": base_url,
                    "X-Specboard-Token": server.session_token,
                },
                method="POST",
            )
            with urllib.request.urlopen(req_ok) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            self.assertTrue(body["ok"])
            self.assertEqual(body["bug"]["id"], "BUG-001")
            self.assertEqual(len(body["payload"]["bugs"]), 1)

            # Atualizar status via /api/bug/status
            req_st = urllib.request.Request(
                f"{base_url}/api/bug/status",
                data=json.dumps({"bug_id": "BUG-001", "status": "em_analise", "analise_agente": "Em revisão"}).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Origin": base_url,
                    "X-Specboard-Token": server.session_token,
                },
                method="POST",
            )
            with urllib.request.urlopen(req_st) as resp2:
                body2 = json.loads(resp2.read().decode("utf-8"))
            self.assertEqual(body2["payload"]["bugs"][0]["status"], "em_analise")
        finally:
            server.shutdown()
            server.server_close()

    def test_github_issue_templates_exist(self) -> None:
        self.assertTrue((REPO / ".github" / "ISSUE_TEMPLATE" / "bug_report.yml").is_file())
        self.assertTrue((REPO / ".github" / "ISSUE_TEMPLATE" / "feature_request.yml").is_file())


if __name__ == "__main__":
    unittest.main()
