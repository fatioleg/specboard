import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "specboard" / "scripts"))
import sb_core as core


def _setup_scientific_project(root: Path, politica: str) -> Path:
    (root / ".specboard").mkdir(parents=True, exist_ok=True)
    (root / "figs").mkdir(exist_ok=True)
    (root / "figs" / "rmsd.png").write_bytes(b"\x89PNG\r\n\x1a\nORIGINAL_BYTES_V1")
    estado = {
        "projeto": {
            "nome": "CD Test",
            "pergunta_central": "Estável a 400 K?",
            "politica_aprovacao": {"modo": politica, "canal_padrao": "painel"},
        },
        "fases": ["F2", "F3"],
        "modulos": [
            {
                "id": "M2", "titulo": "Estabilidade 400K", "fase": "F2", "depende_de": [], "marco": True,
                "contrato": {
                    "pergunta": "RMSD <= 0.80 A?",
                    "criterios_aceitacao": ["RMSD <= 0.80 A"],
                    "criterio_abandono": "RMSD > 1.20 A",
                    "parametros": {"T": 400},
                },
                "etapas": [
                    {"id": "M2.1", "titulo": "Preparo janela", "status": "executado", "impacto": "medio",
                     "marco": False, "afirmacao": "ok", "verificacao": "ok", "evidencia": []},
                    {"id": "M2.3", "titulo": "Marco figura estabilidade", "status": "executado", "impacto": "alto",
                     "marco": True, "depende_de": ["M2.1"],
                     "afirmacao": "RMSD 0.42 A", "verificacao": "Ver figura", "evidencia": ["figs/rmsd.png"]},
                ],
            },
            {
                "id": "M2-B", "titulo": "Paralelo IR 300K", "fase": "F2", "depende_de": [],
                "etapas": [
                    {"id": "M2-B.1", "titulo": "Espectro 300K", "status": "pendente", "impacto": "medio"},
                ],
            },
            {
                "id": "M3", "titulo": "Simulação 450K", "fase": "F3", "depende_de": ["M2"], "resultado_final": True,
                "etapas": [
                    {"id": "M3.1", "titulo": "MD 450K", "status": "pendente", "impacto": "alto"},
                ],
            },
        ],
    }
    # Trava contrato M2
    estado["modulos"][0]["contrato"]["travado_em"] = "2026-11-26 08:00"
    estado["modulos"][0]["contrato"]["hash"] = core.hash_contrato(estado["modulos"][0])
    (root / ".specboard" / "estado.json").write_text(json.dumps(estado, ensure_ascii=False, indent=2), encoding="utf-8")
    return root


class TestPolicyAndHashing(unittest.TestCase):
    def test_acompanhamento_livre_sem_autovalidacao(self):
        """A6: Em acompanhamento_livre nada bloqueia, mas executado continua ≠ verificado (0%)."""
        with tempfile.TemporaryDirectory() as tmp:
            root = _setup_scientific_project(Path(tmp), "acompanhamento_livre")
            gate_m3 = core.avaliar_gate(root, "M3.1")
            self.assertTrue(gate_m3["liberada"])
            e, r, x, v = core.load_all(root)
            p = core.construir_payload(root, e, r, x, v)
            self.assertEqual(p["resumo"]["verificadas"], 0)
            self.assertEqual(p["resumo"]["contagem"].get("executado"), 2)
            self.assertEqual(p["fila"], [])
            self.assertEqual(len(p["fila_opcional"]), 2)

    def test_so_marcos_bloqueia_somente_dependentes_do_marco(self):
        """A7: Em so_marcos, M2.3 não aprovado bloqueia M3.1, mas deixa ramo paralelo M2-B.1 livre; aprovar M2.3 libera M3.1."""
        with tempfile.TemporaryDirectory() as tmp:
            root = _setup_scientific_project(Path(tmp), "so_marcos")
            self.assertFalse(core.avaliar_gate(root, "M3.1")["liberada"])
            self.assertTrue(core.avaliar_gate(root, "M2-B.1")["liberada"])
            # M2.1 não é marco -> na fila principal só entra o marco M2.3
            e, r, x, v = core.load_all(root)
            p = core.construir_payload(root, e, r, x, v)
            self.assertEqual([i["id"] for i in p["fila"]], ["M2.3"])

            # Aprovar o marco M2.3 libera M3.1 imediatamente
            core.registrar_decisao_humana(root, etapa_id="M2.3", acao="verificado", revisor="Fatio", nota="ok", canal="painel")
            self.assertTrue(core.avaliar_gate(root, "M3.1")["liberada"])

    def test_alteracao_evidencia_mesmo_caminho_invalida_aprovacao(self):
        """A8a: Substituir bytes de figs/rmsd.png no mesmo caminho expira aprovação e devolve M2.3 à fila."""
        with tempfile.TemporaryDirectory() as tmp:
            root = _setup_scientific_project(Path(tmp), "so_marcos")
            core.registrar_decisao_humana(root, etapa_id="M2.3", acao="verificado", revisor="Fatio", nota="Figura v1 ok", canal="painel")
            self.assertTrue(core.avaliar_gate(root, "M3.1")["liberada"])

            # Reescreve arquivo NO MESMO CAMINHO sem alterar estado.json!
            (root / "figs" / "rmsd.png").write_bytes(b"\x89PNG\r\n\x1a\nALTERED_BYTES_V2")

            e, r, x, v = core.load_all(root)
            p = core.construir_payload(root, e, r, x, v)
            m23 = p["estado"]["modulos"][0]["etapas"][1]
            self.assertEqual(m23["_status"], "executado")
            self.assertEqual(m23["_exp"], "expirada")
            self.assertIn("evidencia_alterada", m23["_exp_motivos"])
            self.assertIn("figs/rmsd.png", m23["_arquivos_alterados"])
            # Devolveu à fila e rebloqueou M3.1!
            self.assertEqual([i["id"] for i in p["fila"]], ["M2.3"])
            self.assertFalse(core.avaliar_gate(root, "M3.1")["liberada"])
            # Histórico antigo preservado
            self.assertEqual(len(m23["_regs"]), 1)

    def test_emenda_de_contrato_expira_aprovacao_e_ultima_decisao_vence(self):
        """Alterar critério do contrato invalida aprovação; pedir correção posterior vence aprovação anterior."""
        with tempfile.TemporaryDirectory() as tmp:
            root = _setup_scientific_project(Path(tmp), "por_etapa")
            core.registrar_decisao_humana(root, etapa_id="M2.1", acao="verificado", revisor="F", nota="ok", canal="painel")
            core.registrar_decisao_humana(root, etapa_id="M2.3", acao="verificado", revisor="F", nota="ok", canal="painel")

            # Pedido de correção posterior sobre o mesmo snapshot deve vencer a aprovação anterior (corrige bug do any())
            core.registrar_decisao_humana(
                root, etapa_id="M2.3", acao="pedir_correcao", revisor="F",
                nota="Replotar com barras de erro", canal="painel",
            )
            e, r, x, v = core.load_all(root)
            p = core.construir_payload(root, e, r, x, v)
            m23 = p["estado"]["modulos"][0]["etapas"][1]
            self.assertEqual(m23["_status"], "correcao_solicitada")
            self.assertFalse(core.avaliar_gate(root, "M3.1")["liberada"])

            # Alteração de critério do contrato expira M2.1
            e["modulos"][0]["contrato"]["criterios_aceitacao"].append("Barras de erro obrigatórias")
            e["modulos"][0]["contrato"]["hash"] = core.hash_contrato(e["modulos"][0])
            core.save_estado(root, e)
            e2, r2, _, _ = core.load_all(root)
            p2 = core.construir_payload(root, e2, r2)
            m21 = p2["estado"]["modulos"][0]["etapas"][0]
            self.assertEqual(m21["_exp"], "expirada")
            self.assertIn("criterio_alterado", m21["_exp_motivos"])

    def test_alteracao_politica_rastreavel(self):
        """Mudança de política fica no histórico de verificacoes.jsonl e muda bloqueios."""
        with tempfile.TemporaryDirectory() as tmp:
            root = _setup_scientific_project(Path(tmp), "por_etapa")
            self.assertFalse(core.avaliar_gate(root, "M3.1")["liberada"])
            core.registrar_alteracao_politica(
                root, novo_modo="acompanhamento_livre", revisor="Fatio",
                justificativa="Fase exploratória inicial", canal="painel",
            )
            self.assertTrue(core.avaliar_gate(root, "M3.1")["liberada"])
            e, r, _, _ = core.load_all(root)
            pol = core.politica_efetiva(e, r)
            self.assertEqual(pol["modo"], "acompanhamento_livre")
            self.assertEqual(len(pol["historico"]), 1)
            self.assertEqual(pol["historico"][0]["modo_anterior"], "por_etapa")


if __name__ == "__main__":
    unittest.main()
