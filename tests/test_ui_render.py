import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TEMPLATE = REPO / "specboard" / "assets" / "painel_template.html"
CD_HTML = REPO / "examples" / "carbon_dots" / ".specboard" / "painel.html"
LEGACY_HTML = REPO / "examples" / "painel_completo.html"


class TestUIRenderAndSyntax(unittest.TestCase):
    def test_template_and_generated_js_syntax_valid(self):
        """Verifica com Node.js (se disponível) que o JS embutido no template e nos painéis gerados não tem erro de sintaxe."""
        node = shutil.which("node")
        for html_file in (TEMPLATE, CD_HTML, LEGACY_HTML):
            text = html_file.read_text(encoding="utf-8")
            m = re.search(r"<script>(.*)</script>", text, flags=re.DOTALL)
            self.assertIsNotNone(m, f"Bloco <script> ausente em {html_file}")
            js = m.group(1)
            if node:
                with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8", delete=False) as tf:
                    tf.write(js)
                    tmp_path = Path(tf.name)
                try:
                    res = subprocess.run([node, "--check", str(tmp_path)], capture_output=True, text=True, check=False)
                    self.assertEqual(res.returncode, 0, f"Erro JS em {html_file}: {res.stderr}")
                finally:
                    tmp_path.unlink(missing_ok=True)

    def test_ui_elements_for_all_four_views_present(self):
        """A1, A4, A9: Confirma navegação Agora/Projeto/Agente, revisão em 4 passos, mobile vertical com setas e volta mapa<->Agente."""
        html = TEMPLATE.read_text(encoding="utf-8")
        # 3 abas principais
        self.assertIn('data-tab="agora"', html)
        self.assertIn('data-tab="projeto"', html)
        self.assertIn('data-tab="agente"', html)
        # 4 passos ordenados da Revisão
        self.assertIn("1. O que foi entregue", html)
        self.assertIn("2. Critério de verificação e contrato", html)
        self.assertIn("3. Evidência", html)
        self.assertIn("4. Decisão e efeito nas etapas dependentes", html)
        # Botões de decisão
        self.assertIn("Aprovar entrega", html)
        self.assertIn("Pedir correção", html)
        self.assertIn("Deixar para depois", html)
        # Ida e volta mapa <-> Agente
        self.assertIn("data-goto-agent", html)
        self.assertIn("btn-agent-back", html)
        self.assertIn("Voltar à etapa no Projeto", html)
        # Mobile preserva setas verticais (não esconde com display:none!)
        self.assertNotIn("svg.edges{display:none}", html)
        self.assertIn("flex-direction:column", html)
        # "sem registro" explícito para telemetria ausente
        self.assertIn("sem registro", html)
        # Painel Carbon Dots contém dados reais injetados
        cd_text = CD_HTML.read_text(encoding="utf-8")
        self.assertIn("estabilidade_cd_400k.png", cd_text)
        self.assertIn("pubchem-mcp", cd_text)


if __name__ == "__main__":
    unittest.main()
