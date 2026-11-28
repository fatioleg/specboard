import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "specboard" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import sb_core as core  # noqa: E402
import sb_mcp as mcp  # noqa: E402


def _make_project(tmp: Path, etapa_extra: dict) -> Path:
    sb = tmp / ".specboard"
    sb.mkdir(parents=True, exist_ok=True)
    ev = tmp / "relatorio.md"
    ev.write_text("# Relatório\n66/66 testes aprovados.\n", encoding="utf-8")
    etapa = {
        "id": "M1.1",
        "titulo": "Modelos oxidados e parâmetros validados",
        "status": "executado",
        "impacto": "alto",
        "revisao": "completa",
        "marco": True,
        "verificacao": "Abrir relatorio.md e conferir que todas as 66 verificações passaram.",
        "evidencia": ["relatorio.md"],
    }
    etapa.update(etapa_extra)
    estado = {
        "projeto": {
            "nome": "Teste Didático",
            "pergunta_central": "Os modelos oxidados atendem aos critérios de validação?",
            "politica_aprovacao": {"modo": "so_marcos", "canal_padrao": "painel"},
        },
        "fases": ["Fase 1"],
        "modulos": [
            {
                "id": "M1",
                "titulo": "Parâmetros e modelos",
                "fase": "Fase 1",
                "objetivo": "Validar os parâmetros dos modelos.",
                "depende_de": [],
                "resultado_final": True,
                "marco": True,
                "contrato": {},
                "etapas": [etapa],
            }
        ],
    }
    (sb / "estado.json").write_text(json.dumps(estado, ensure_ascii=False, indent=2), encoding="utf-8")
    return tmp


class TestDidacticSummaryRule(unittest.TestCase):
    def test_detects_cryptic_jargon_summary_from_real_example(self):
        cryptic = (
            "cd_ox.py, pré-registro cd_ox.yaml (D28), doc 13 (check_docs --doc 13 verde) "
            "e check_ox_params.py alinhado a opls_base + custom_N (66/66 testes, 0 lacunas)."
        )
        res = core.avaliar_clareza_resumo({"afirmacao": cryptic})
        self.assertFalse(res["didatico"])
        self.assertGreaterEqual(len(res["sinais"]["arquivos"]), 3)
        self.assertIn("--doc", res["sinais"]["flags"])
        self.assertTrue(any(x in res["sinais"]["identificadores"] for x in ("opls_base", "custom_N", "check_docs")))
        self.assertTrue(any(x in res["sinais"]["codigos"] for x in ("D28", "doc 13")))
        self.assertTrue(res["motivos"])

    def test_accepts_didactic_summary_with_technical_details_separated(self):
        etapa = {
            "afirmacao": (
                "Criamos o gerador dos modelos oxidados e validamos todos os parâmetros necessários "
                "para as simulações. Todas as 66 verificações automáticas passaram sem nenhuma lacuna."
            ),
            "detalhes_tecnicos": (
                "cd_ox.py, pré-registro cd_ox.yaml (D28), doc 13 (check_docs --doc 13 verde) "
                "e check_ox_params.py alinhado a opls_base + custom_N (66/66 testes, 0 lacunas)."
            ),
        }
        res = core.avaliar_clareza_resumo(etapa)
        self.assertTrue(res["didatico"])
        self.assertEqual(res["motivos"], [])

    def test_validate_warns_by_default_and_fails_in_strict_mode(self):
        cryptic = (
            "cd_ox.py, pré-registro cd_ox.yaml (D28), doc 13 (check_docs --doc 13 verde) "
            "e check_ox_params.py alinhado a opls_base + custom_N (66/66 testes, 0 lacunas)."
        )
        with tempfile.TemporaryDirectory() as td:
            proj = _make_project(Path(td), {"afirmacao": cryptic})
            estado, regs, _, _ = core.load_all(proj)

            erros, avisos = core.validar(proj, estado, regs)
            self.assertEqual(erros, [])
            self.assertTrue(any("pouco didático" in a for a in avisos))

            erros_s, _ = core.validar(proj, estado, regs, estrito_didatico=True)
            self.assertTrue(any("pouco didático" in e for e in erros_s))

            # CLI validate --estrito deve sair com código 1
            cli = SCRIPTS / "specboard.py"
            p_soft = subprocess.run([sys.executable, str(cli), "--dir", str(proj), "validate"], capture_output=True, text=True)
            self.assertEqual(p_soft.returncode, 0)
            self.assertIn("AVISO:", p_soft.stdout)

            p_strict = subprocess.run([sys.executable, str(cli), "--dir", str(proj), "validate", "--estrito"], capture_output=True, text=True)
            self.assertEqual(p_strict.returncode, 1)
            self.assertIn("ERRO:", p_strict.stdout)

    def test_resumo_didatico_overrides_legacy_afirmacao_and_passes_strict(self):
        cryptic = (
            "cd_ox.py, pré-registro cd_ox.yaml (D28), doc 13 (check_docs --doc 13 verde) "
            "e check_ox_params.py alinhado a opls_base + custom_N (66/66 testes, 0 lacunas)."
        )
        clear = (
            "Implementamos a geração dos modelos oxidados e conferimos a consistência completa dos parâmetros. "
            "Todos os 66 testes automáticos passaram sem falhas."
        )
        with tempfile.TemporaryDirectory() as td:
            proj = _make_project(Path(td), {"afirmacao": cryptic, "resumo_didatico": clear})
            estado, regs, _, _ = core.load_all(proj)
            erros, avisos = core.validar(proj, estado, regs, estrito_didatico=True)
            self.assertEqual(erros, [])
            self.assertFalse(any("pouco didático" in a for a in avisos))

            pay = core.construir_payload(proj, estado, regs)
            self.assertEqual(pay["resumos_pouco_didaticos"], [])
            et = pay["estado"]["modulos"][0]["etapas"][0]
            self.assertEqual(et["_resumo_principal"], clear)
            self.assertTrue(et["_clareza_resumo"]["usa_resumo_didatico"])

    def test_mcp_validate_and_context_expose_didactic_rule(self):
        cryptic = "script_a.py, cfg.yaml (D28), check_docs --doc 13 e foo_bar alinhado."
        with tempfile.TemporaryDirectory() as td:
            proj = _make_project(Path(td), {"afirmacao": cryptic})
            out_strict = mcp.call_tool("specboard_validate", {"dir": str(proj), "estrito": True})
            self.assertFalse(out_strict["valido"])
            self.assertEqual(len(out_strict["resumos_pouco_didaticos"]), 1)
            self.assertIn("linguagem humana", out_strict["regra_resumo_didatico"])

            ctx = mcp.call_tool("specboard_context", {"dir": str(proj), "etapa_id": "M1.1"})
            self.assertIn("regra_resumo_didatico", ctx)
            self.assertIn("detalhes_tecnicos", ctx["regra_resumo_didatico"])

    def test_carbon_dots_example_passes_strict_didactic_validation(self):
        cd_dir = ROOT / "examples" / "carbon_dots"
        estado, regs, _, _ = core.load_all(cd_dir)
        erros, avisos = core.validar(cd_dir, estado, regs, estrito_didatico=True)
        self.assertEqual(erros, [], f"Erros inesperados em carbon_dots: {erros}")
        self.assertFalse(any("pouco didático" in a for a in avisos), f"Avisos didáticos em carbon_dots: {avisos}")

    def test_html_template_renders_didactic_controls_and_technical_fold(self):
        cryptic = "cd_ox.py, cd_ox.yaml (D28), check_docs --doc 13 e opls_base + custom_N."
        with tempfile.TemporaryDirectory() as td:
            proj = _make_project(Path(td), {"afirmacao": cryptic, "detalhes_tecnicos": "Comando: pytest -q (66/66)"})
            cli = SCRIPTS / "specboard.py"
            p = subprocess.run([sys.executable, str(cli), "--dir", str(proj), "build"], capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, p.stderr)
            html = (proj / ".specboard" / "painel.html").read_text(encoding="utf-8")
            self.assertIn("renderDeliverySummary", html)
            self.assertIn("Resumo muito técnico", html)
            self.assertIn("Detalhes técnicos", html)
            self.assertIn("data-copy-didactic", html)


if __name__ == "__main__":
    unittest.main()
