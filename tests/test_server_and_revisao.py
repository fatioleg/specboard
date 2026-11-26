import json
import shutil
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "specboard" / "scripts"))
import sb_core as core
import sb_server as srv


class TestServerAndRevisao(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "cd"
        shutil.copytree(REPO / "examples" / "carbon_dots", self.root)
        self.token = "test-session-token-123"
        self.server = srv.create_server(
            self.root,
            REPO / "specboard" / "assets" / "painel_template.html",
            host="127.0.0.1",
            port=0,
            readonly=False,
            token=self.token,
        )
        self.port = self.server.server_address[1]
        self.base_url = f"http://127.0.0.1:{self.port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def _get(self, path: str):
        req = urllib.request.Request(self.base_url + path)
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, resp.headers, resp.read()
        except urllib.error.HTTPError as err:
            return err.code, err.headers, err.read()

    def _post(self, path: str, body: dict, token: str | None = None):
        raw = json.dumps(body).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if token is not None:
            headers["X-Specboard-Token"] = token
        req = urllib.request.Request(self.base_url + path, data=raw, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as err:
            return err.code, json.loads(err.read().decode("utf-8"))

    def test_evidencias_png_csv_md_e_bloqueio_path_traversal(self):
        """A4: Servidor entrega PNG, tabela CSV estruturada, relatório MD e bloqueia '..'."""
        st, hdrs, png_bytes = self._get("/api/evidencia?ref=figs/estabilidade_cd_400k.png")
        self.assertEqual(st, 200)
        self.assertEqual(hdrs.get("Content-Type"), "image/png")
        self.assertTrue(png_bytes.startswith(b"\x89PNG"))

        st, _, csv_raw = self._get("/api/evidencia?ref=data/rmsd_cd_400k.csv")
        self.assertEqual(st, 200)
        csv_json = json.loads(csv_raw.decode("utf-8"))
        self.assertEqual(csv_json["midia"], "tabela")
        self.assertIn("rmsd_core_angstrom", csv_json["headers"])
        self.assertEqual(len(csv_json["rows"]), 11)

        st, _, md_raw = self._get("/api/evidencia?ref=reports/relatorio_m2.md")
        self.assertEqual(st, 200)
        md_json = json.loads(md_raw.decode("utf-8"))
        self.assertEqual(md_json["midia"], "markdown")
        self.assertIn("0.425", md_json["conteudo"])

        # Path traversal bloqueado com 403
        st, _, _ = self._get("/api/evidencia?ref=../../README.md")
        self.assertEqual(st, 403)

    def test_decisao_persistida_e_protecao_csrf(self):
        """A5: Decisão sem token retorna 403; com token persiste em disco e sobrevive recarregamento."""
        st_no_tok, _ = self._post("/api/decisao", {"etapa_id": "M2.3", "acao": "verificado", "revisor": "F", "nota": "ok"})
        self.assertEqual(st_no_tok, 403)

        st, _, raw = self._get("/api/estado")
        self.assertEqual(st, 200)
        estado_api = json.loads(raw.decode("utf-8"))
        m23 = [e for m in estado_api["estado"]["modulos"] for e in m.get("etapas", []) if e["id"] == "M2.3"][0]
        fp = m23["_snapshot"]["fingerprint_total"]

        # Pedir correção sem justificativa falha (400)
        st_bad, _ = self._post("/api/decisao", {
            "etapa_id": "M2.3", "acao": "pedir_correcao", "revisor": "Fatio", "nota": "", "observed_fingerprint": fp,
        }, token=self.token)
        self.assertEqual(st_bad, 400)

        # Aprovar com sucesso (200)
        st_ok, res_ok = self._post("/api/decisao", {
            "etapa_id": "M2.3", "acao": "verificado", "revisor": "Fatio", "nota": "Figura e CSV conferidos", "observed_fingerprint": fp,
        }, token=self.token)
        self.assertEqual(st_ok, 200)
        self.assertTrue(res_ok["ok"])

        # Recarregar via GET /api/estado confirma persistência e desbloqueio de M3
        st2, _, raw2 = self._get("/api/estado")
        self.assertEqual(st2, 200)
        reloaded = json.loads(raw2.decode("utf-8"))
        m23_after = [e for m in reloaded["estado"]["modulos"] for e in m.get("etapas", []) if e["id"] == "M2.3"][0]
        self.assertEqual(m23_after["_status"], "verificado")
        self.assertTrue(core.avaliar_gate(self.root, "M3.1")["liberada"])

    def test_toctou_conflito_409_quando_evidencia_muda_durante_revisao(self):
        """A8b: Se a figura mudar entre abrir Revisão e clicar Aprovar, servidor retorna 409 e não grava."""
        _, _, raw = self._get("/api/estado")
        estado_api = json.loads(raw.decode("utf-8"))
        m23 = [e for m in estado_api["estado"]["modulos"] for e in m.get("etapas", []) if e["id"] == "M2.3"][0]
        fp_abertura = m23["_snapshot"]["fingerprint_total"]

        # Simula agente alterando a figura enquanto o usuário está revisando
        fig = self.root / "figs" / "estabilidade_cd_400k.png"
        fig.write_bytes(fig.read_bytes() + b"MODIFIED")

        st, body = self._post("/api/decisao", {
            "etapa_id": "M2.3",
            "acao": "verificado",
            "revisor": "Fatio",
            "nota": "Tentativa com snapshot antigo",
            "observed_fingerprint": fp_abertura,
        }, token=self.token)
        self.assertEqual(st, 409)
        self.assertTrue(body.get("conflito"))
        # Garante que NÃO aprovou M2.3
        self.assertFalse(core.avaliar_gate(self.root, "M3.1")["liberada"])

    def test_alterar_politica_e_visita_pelo_painel(self):
        """Política e marcador de visita funcionam 100% pelo painel."""
        st, body = self._post("/api/politica", {
            "modo": "acompanhamento_livre", "revisor": "Fatio", "justificativa": "Teste livre",
        }, token=self.token)
        self.assertEqual(st, 200)
        self.assertEqual(body["payload"]["politica"]["modo"], "acompanhamento_livre")

        st_v, body_v = self._post("/api/visita", {"revisor": "Fatio"}, token=self.token)
        self.assertEqual(st_v, 200)
        self.assertTrue(body_v["payload"]["mudancas"]["referencia_confiavel"])
        self.assertEqual(body_v["payload"]["mudancas"]["novos"], [])

    def test_acoes_diretas_aguardar_bloquear_desbloquear_e_lock(self):
        """Botões diretos: aguardar_decisao, bloquear, desbloquear e travar contrato funcionam no painel."""
        # Aguardar decisão em M2.3
        st1, b1 = self._post("/api/decisao", {
            "etapa_id": "M2.3", "acao": "aguardar_decisao", "revisor": "Fatio", "nota": "Aguardando reunião",
        }, token=self.token)
        self.assertEqual(st1, 200)
        m23 = [e for m in b1["payload"]["estado"]["modulos"] for e in m.get("etapas", []) if e["id"] == "M2.3"][0]
        self.assertEqual(m23["_status"], "aguardando_decisao")

        # Bloquear manualmente sem motivo falha (400)
        st_bad, _ = self._post("/api/decisao", {
            "etapa_id": "M2.3", "acao": "bloquear", "revisor": "Fatio", "nota": "",
        }, token=self.token)
        self.assertEqual(st_bad, 400)

        # Bloquear manualmente com motivo -> status bloqueado
        st2, b2 = self._post("/api/decisao", {
            "etapa_id": "M2.3", "acao": "bloquear", "revisor": "Fatio", "nota": "Aguardar nova rodada",
        }, token=self.token)
        self.assertEqual(st2, 200)
        m23_b = [e for m in b2["payload"]["estado"]["modulos"] for e in m.get("etapas", []) if e["id"] == "M2.3"][0]
        self.assertEqual(m23_b["_status"], "bloqueado")

        # Desbloquear -> volta para executado
        st3, b3 = self._post("/api/decisao", {
            "etapa_id": "M2.3", "acao": "desbloquear", "revisor": "Fatio", "nota": "Retomado",
        }, token=self.token)
        self.assertEqual(st3, 200)
        m23_u = [e for m in b3["payload"]["estado"]["modulos"] for e in m.get("etapas", []) if e["id"] == "M2.3"][0]
        self.assertEqual(m23_u["_status"], "executado")


if __name__ == "__main__":
    unittest.main()
