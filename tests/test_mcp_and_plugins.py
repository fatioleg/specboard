"""Testes do servidor MCP stdio (sb_mcp.py), manifests de marketplace e hook multi-plataforma."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "specboard" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import sb_mcp as mcp  # noqa: E402


class TestMcpAndPlugins(unittest.TestCase):
    def test_mcp_protocol_and_zero_self_validation(self) -> None:
        r_init = mcp.handle_request({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05"}})
        self.assertEqual(r_init["result"]["serverInfo"]["name"], "specboard")

        r_list = mcp.handle_request({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        names = {t["name"] for t in r_list["result"]["tools"]}
        self.assertIn("specboard_status", names)
        self.assertIn("specboard_gate", names)
        self.assertIn("specboard_harness", names)
        self.assertIn("specboard_context", names)
        # Garantia de segurança: nenhuma ferramenta MCP permite autovalidação
        for forbidden in ("verify", "approve", "policy", "review", "request_changes"):
            self.assertFalse(any(forbidden in n for n in names), f"Ferramenta proibida no MCP: {forbidden}")

        ex_dir = str(REPO / "examples" / "carbon_dots")
        r_st = mcp.handle_request({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "specboard_status", "arguments": {"dir": ex_dir}}})
        self.assertFalse(r_st["result"]["isError"])
        st_data = json.loads(r_st["result"]["content"][0]["text"])
        self.assertEqual(st_data["politica"]["modo"], "so_marcos")

        r_hr = mcp.handle_request({"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "specboard_harness", "arguments": {"dir": ex_dir}}})
        self.assertFalse(r_hr["result"]["isError"])
        hr_data = json.loads(r_hr["result"]["content"][0]["text"])
        self.assertGreaterEqual(hr_data["contadores"]["skills"], 1)
        self.assertGreaterEqual(hr_data["contadores"]["mcps"], 1)
        self.assertGreaterEqual(hr_data["contadores"]["hooks_codigo"], 1)

    def test_mcp_stdio_roundtrip_subprocess(self) -> None:
        req = json.dumps({"jsonrpc": "2.0", "id": 10, "method": "ping"}) + "\n"
        proc = subprocess.run(
            [sys.executable, str(SCRIPTS / "sb_mcp.py")],
            input=req,
            text=True,
            capture_output=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        resp = json.loads(proc.stdout.strip())
        self.assertEqual(resp["id"], 10)
        self.assertEqual(resp["result"], {})

    def test_hook_blocks_antigravity_and_codex_payloads(self) -> None:
        hook = str(SCRIPTS / "block_verify_hook.py")
        # Antigravity camelCase PreToolUse -> JSON decision: deny
        agy_payload = json.dumps({
            "hookEventName": "PreToolUse",
            "toolCall": {"name": "run_command", "args": {"CommandLine": "python specboard.py verify M1.1"}},
        })
        p1 = subprocess.run([sys.executable, hook], input=agy_payload, text=True, capture_output=True, check=False)
        self.assertEqual(p1.returncode, 0)
        out1 = json.loads(p1.stdout.strip())
        self.assertEqual(out1["decision"], "deny")

        # Antigravity write_file para verificacoes.jsonl -> deny
        agy_write = json.dumps({
            "hookEventName": "PreToolUse",
            "toolCall": {"name": "write_file", "args": {"Path": "/proj/.specboard/verificacoes.jsonl"}},
        })
        p2 = subprocess.run([sys.executable, hook], input=agy_write, text=True, capture_output=True, check=False)
        self.assertEqual(json.loads(p2.stdout.strip())["decision"], "deny")

        # Codex apply_patch para verificacoes.jsonl -> exit 2
        codex_patch = json.dumps({
            "tool_name": "apply_patch",
            "tool_input": {"input": "*** Update File: .specboard/verificacoes.jsonl\n+{}"},
        })
        p3 = subprocess.run([sys.executable, hook], input=codex_patch, text=True, capture_output=True, check=False)
        self.assertEqual(p3.returncode, 2)

    def test_all_marketplace_and_plugin_manifests_valid_json(self) -> None:
        expected = [
            "plugin.json",
            "mcp_config.json",
            ".mcp.json",
            "hooks.json",
            "hooks/hooks.claude.json",
            "hooks/hooks.codex.json",
            ".claude-plugin/plugin.json",
            ".claude-plugin/marketplace.json",
            ".codex-plugin/plugin.json",
            ".codex-plugin/mcp.json",
            ".agents/plugins/marketplace.json",
        ]
        for rel in expected:
            p = REPO / rel
            self.assertTrue(p.is_file(), f"Manifest ausente: {rel}")
            data = json.loads(p.read_text(encoding="utf-8"))
            self.assertIsInstance(data, dict, f"JSON inválido em {rel}")
        self.assertTrue((REPO / "skills" / "specboard" / "SKILL.md").is_file())
        self.assertTrue((REPO / "rules" / "AGENTS.md").is_file())


if __name__ == "__main__":
    unittest.main()
