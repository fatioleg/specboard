import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "specboard" / "scripts"))
import sb_core as core


class TestCoreAndLegacy(unittest.TestCase):
    def test_legacy_estado_completo_compat(self):
        """A2: Projeto legado (estado_completo.json + verificacoes.jsonl v1) funciona sem quebrar."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sb_dir = root / ".specboard"
            sb_dir.mkdir()
            shutil.copy(REPO / "examples" / "estado_completo.json", sb_dir / "estado.json")
            estado, _, _, _ = core.load_all(root)

            # Simula verificação legada v1 (sem schema_hash_v nem evidencia_hashes)
            m0 = estado["modulos"][0]
            e01 = m0["etapas"][0]
            v1_hash = core.hash_etapa_v1(e01)
            (sb_dir / "verificacoes.jsonl").write_text(
                json.dumps({
                    "etapa": "M0.1",
                    "nivel": "verificado",
                    "revisor": "Fatio",
                    "nota": "Verificação antiga v1",
                    "data": "2026-09-12 10:00",
                    "hash_etapa": v1_hash,
                }) + "\n",
                encoding="utf-8",
            )

            estado, regs, execs, visita = core.load_all(root)
            payload = core.construir_payload(root, estado, regs, execs, visita)
            self.assertEqual(payload["erros"], [])
            self.assertTrue(payload["politica"]["legada"])
            self.assertEqual(payload["politica"]["modo"], "por_etapa")

            e01_out = payload["estado"]["modulos"][0]["etapas"][0]
            self.assertEqual(e01_out["_status"], "verificado")
            self.assertTrue(e01_out["_legada"])
            self.assertIsNone(e01_out["_exp"])

    def test_fila_vazia_e_mensagens_distintas(self):
        """A3: Fila vazia diferencia execução em curso, tudo verificado e falta de dados."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".specboard").mkdir()

            # Caso 1: execução em curso
            est_run = {
                "projeto": {"nome": "P", "pergunta_central": "Q?", "politica_aprovacao": {"modo": "por_etapa"}},
                "fases": ["F1"],
                "modulos": [{
                    "id": "M1", "titulo": "Mod 1", "fase": "F1", "depende_de": [], "resultado_final": True,
                    "etapas": [{"id": "M1.1", "titulo": "Rodando", "status": "em_curso", "impacto": "alto"}],
                }],
            }
            p1 = core.construir_payload(root, est_run, [])
            self.assertEqual(p1["fila"], [])
            self.assertEqual(p1["situacao_atual"]["proxima_acao"]["tipo"], "acompanhar")
            self.assertEqual(p1["situacao_atual"]["atividade_agente"]["estado"], "executando")
            self.assertEqual(p1["situacao_atual"]["atividade_agente"]["origem"], "reportado_pelo_agente")

            # Caso 2: falta de dados (apenas pendente sem execução)
            est_empty = {
                "projeto": {"nome": "P", "pergunta_central": "Q?", "politica_aprovacao": {"modo": "por_etapa"}},
                "fases": ["F1"],
                "modulos": [{
                    "id": "M1", "titulo": "Mod 1", "fase": "F1", "depende_de": [], "resultado_final": True,
                    "etapas": [{"id": "M1.1", "titulo": "Pendente", "status": "pendente", "impacto": "alto"}],
                }],
            }
            p2 = core.construir_payload(root, est_empty, [])
            self.assertEqual(p2["situacao_atual"]["proxima_acao"]["tipo"], "sem_dados")
            self.assertEqual(p2["situacao_atual"]["atividade_agente"]["estado"], "sem_dados")

            # Caso 3: tudo verificado
            (root / ".specboard" / "estado.json").write_text(json.dumps({
                "projeto": {"nome": "P", "pergunta_central": "Q?", "politica_aprovacao": {"modo": "por_etapa"}},
                "fases": ["F1"],
                "modulos": [{
                    "id": "M1", "titulo": "Mod 1", "fase": "F1", "depende_de": [], "resultado_final": True,
                    "etapas": [{"id": "M1.1", "titulo": "Feito", "status": "executado", "impacto": "alto",
                                "afirmacao": "ok", "verificacao": "ok", "evidencia": []}],
                }],
            }), encoding="utf-8")
            core.registrar_decisao_humana(root, etapa_id="M1.1", acao="verificado", revisor="F", nota="ok", canal="painel")
            e3, r3, _, _ = core.load_all(root)
            p3 = core.construir_payload(root, e3, r3)
            self.assertEqual(p3["fila"], [])
            self.assertEqual(p3["situacao_atual"]["proxima_acao"]["tipo"], "concluido")

    def test_stmod_nao_finge_em_curso_e_fila_ordem_natural(self):
        """Módulo com 1 executado + 1 pendente não vira 'em_curso'; M2.1 ordena antes de M10.1."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            est = {
                "projeto": {"nome": "P", "pergunta_central": "Q?", "politica_aprovacao": {"modo": "por_etapa"}},
                "fases": ["F1"],
                "modulos": [
                    {
                        "id": "M10", "titulo": "Mod 10", "fase": "F1", "depende_de": [],
                        "etapas": [
                            {"id": "M10.1", "titulo": "Dez", "status": "executado", "impacto": "alto",
                             "afirmacao": "a", "verificacao": "v", "evidencia": []},
                            {"id": "M10.2", "titulo": "Prox", "status": "pendente", "impacto": "medio"},
                        ],
                    },
                    {
                        "id": "M2", "titulo": "Mod 2", "fase": "F1", "depende_de": [], "resultado_final": False,
                        "etapas": [
                            {"id": "M2.1", "titulo": "Dois", "status": "executado", "impacto": "alto",
                             "afirmacao": "a", "verificacao": "v", "evidencia": []},
                        ],
                    },
                ],
            }
            p = core.construir_payload(root, est, [])
            m10 = p["estado"]["modulos"][0]
            self.assertEqual(m10["_status_mod"], "aguarda")
            # M10.1 bloqueia M10.2, então vem antes de M2.1 (que não bloqueia nada)
            self.assertEqual([x["id"] for x in p["fila"]], ["M10.1", "M2.1"])

            # Quando ambos têm mesma prioridade/bloqueio, desempate é por ordem natural numérica (M2.1 < M10.1)
            est["modulos"][1]["etapas"].append({"id": "M2.2", "titulo": "Prox2", "status": "pendente", "impacto": "medio"})
            p_eq = core.construir_payload(root, est, [])
            self.assertEqual([x["id"] for x in p_eq["fila"]], ["M2.1", "M10.1"])

    def test_mudancas_desde_ultima_visita(self):
        """Mudanças só reportam diff quando existe visita confiável gravada."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".specboard").mkdir()
            est = {
                "projeto": {"nome": "P", "pergunta_central": "Q?", "politica_aprovacao": {"modo": "por_etapa"}},
                "fases": ["F1"],
                "modulos": [{
                    "id": "M1", "titulo": "Mod 1", "fase": "F1", "depende_de": [], "resultado_final": True,
                    "etapas": [{"id": "M1.1", "titulo": "A", "status": "executado", "impacto": "alto",
                                "afirmacao": "a", "verificacao": "v", "evidencia": []}],
                }],
            }
            (root / ".specboard" / "estado.json").write_text(json.dumps(est), encoding="utf-8")
            p0 = core.construir_payload(root, est, [], [], None)
            self.assertFalse(p0["mudancas"]["referencia_confiavel"])

            visita = core.save_visita(root, {"event_ids": [ev["id"] for ev in p0["eventos"]]})
            p1 = core.construir_payload(root, est, [], [], visita)
            self.assertTrue(p1["mudancas"]["referencia_confiavel"])
            self.assertEqual(p1["mudancas"]["novos"], [])

            # Nova decisão cria evento novo
            core.registrar_decisao_humana(root, etapa_id="M1.1", acao="verificado", revisor="F", nota="ok", canal="painel")
            e2, r2, x2, v2 = core.load_all(root)
            p2 = core.construir_payload(root, e2, r2, x2, v2)
            self.assertGreaterEqual(len(p2["mudancas"]["novos"]), 1)


if __name__ == "__main__":
    unittest.main()
