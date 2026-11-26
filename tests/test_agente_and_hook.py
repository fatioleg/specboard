import json
import subprocess
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "specboard" / "scripts"))
import sb_core as core

HOOK = REPO / "specboard" / "scripts" / "block_verify_hook.py"
CD_DIR = REPO / "examples" / "carbon_dots"


class TestAgenteAndHook(unittest.TestCase):
    def test_carbon_dots_contexto_retomada_limpa(self):
        """A10: Retomada em sessão limpa devolve apenas protocolo, ref, janela e último ponto confirmado."""
        ctx = core.construir_contexto_limpo(CD_DIR, "M2.2")
        self.assertEqual(ctx["etapa"]["id"], "M2.2")
        self.assertEqual(ctx["contexto_duravel"]["protocolo"]["versao"], "v2.1")
        self.assertIn("5.0", ctx["contexto_duravel"]["janela_analise"])
        self.assertEqual(ctx["contexto_duravel"]["ultimo_ponto_confirmado"]["etapa"], "M1.1")
        refs = ctx["contexto_duravel"]["artefatos_referencia"]
        self.assertTrue(any(r["caminho"] == "data/core_ref.xyz" and r.get("sha256_atual") for r in refs))
        # Guardrails distinguem código vs instrução
        nats = {g["natureza"] for g in ctx["guardrails_ativos"]}
        self.assertEqual(nats, {"codigo", "instrucao"})

    def test_distincao_configurado_observado_e_sem_registro(self):
        """A11: Skill e script local aparecem observados; MCP opcional configurado sem telemetria mostra 'sem registro'."""
        estado, regs, execs, visita = core.load_all(CD_DIR)
        payload = core.construir_payload(CD_DIR, estado, regs, execs, visita)
        m22 = [e for m in payload["estado"]["modulos"] for e in m.get("etapas", []) if e["id"] == "M2.2"][0]
        comps = {c["nome"]: c for c in m22["_agente"]["componentes"]}

        self.assertEqual(comps["cd-rmsd-analysis"]["tipo"], "skill")
        self.assertEqual(comps["cd-rmsd-analysis"]["observado"]["estado"], "observado")

        self.assertEqual(comps["calc_rmsd.py"]["tipo"], "local_tool")
        self.assertEqual(comps["calc_rmsd.py"]["observado"]["estado"], "observado")

        self.assertEqual(comps["pubchem-mcp"]["tipo"], "mcp_tool")
        self.assertEqual(comps["pubchem-mcp"]["mcp_server"], "pubchem-reference")
        self.assertTrue(comps["pubchem-mcp"]["configurado"])
        self.assertEqual(comps["pubchem-mcp"]["observado"]["estado"], "sem_registro")
        self.assertEqual(comps["pubchem-mcp"]["observado"]["label"], "sem registro")

    def test_script_deterministico_carbon_dots_roda(self):
        res = subprocess.run(
            [sys.executable, str(CD_DIR / "scripts" / "calc_rmsd.py")],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("0.425", res.stdout)

    def test_hook_bloqueia_comandos_humanos_e_libera_comandos_agente(self):
        def run_hook(payload: dict) -> int:
            r = subprocess.run(
                [sys.executable, str(HOOK)],
                input=json.dumps(payload),
                text=True, capture_output=True, check=False,
            )
            return r.returncode

        # Deve bloquear (exit 2)
        self.assertEqual(run_hook({"tool_name": "Bash", "tool_input": {"command": "python specboard.py verify M2.3"}}), 2)
        self.assertEqual(run_hook({"tool_name": "PowerShell", "tool_input": {"command": "python specboard.py request-changes M2.3"}}), 2)
        self.assertEqual(run_hook({"tool_name": "Bash", "tool_input": {"command": "python specboard.py policy acompanhamento_livre -j x"}}), 2)
        self.assertEqual(run_hook({"tool_name": "Bash", "tool_input": {"command": "python specboard.py serve --port 8765"}}), 2)
        self.assertEqual(run_hook({"tool_name": "Bash", "tool_input": {"command": "curl -X POST http://127.0.0.1:8765/api/decisao"}}), 2)
        self.assertEqual(run_hook({"tool_name": "Write", "tool_input": {"file_path": "proj/.specboard/verificacoes.jsonl"}}), 2)

        # Deve liberar (exit 0)
        self.assertEqual(run_hook({"tool_name": "Bash", "tool_input": {"command": "python specboard.py validate"}}), 0)
        self.assertEqual(run_hook({"tool_name": "Bash", "tool_input": {"command": "python specboard.py gate M3.1"}}), 0)
        self.assertEqual(run_hook({"tool_name": "Bash", "tool_input": {"command": "python specboard.py context M2.2"}}), 0)
        self.assertEqual(run_hook({"tool_name": "Bash", "tool_input": {"command": "python specboard.py serve --readonly"}}), 0)


if __name__ == "__main__":
    unittest.main()
