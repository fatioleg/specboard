#!/usr/bin/env python3
"""Servidor HTTP local leve do SpecBoard (Python 3 stdlib puro).

Fornece o canal principal interativo para revisar evidências (figuras, tabelas CSV,
relatórios Markdown) e gravar decisões humanas com persistência confirmada em
.specboard/verificacoes.jsonl, tanto localmente (127.0.0.1) quanto em servidores
remotos via túnel SSH (`ssh -L 8765:127.0.0.1:8765 ...`).
"""
from __future__ import annotations

import csv
import io
import json
import mimetypes
import secrets
import threading
import urllib.parse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import sb_core as core

MAX_TEXT_PREVIEW_BYTES = 262_144  # 256 KB
MAX_CSV_ROWS = 200
MAX_BODY_BYTES = 1_048_576  # 1 MB

IMAGE_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
}


class SpecboardHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True

    def __init__(
        self,
        server_address: tuple[str, int],
        base_dir: Path,
        template_path: Path,
        *,
        readonly: bool = False,
        token: str | None = None,
    ):
        self.base_dir = Path(base_dir).resolve()
        self.template_path = Path(template_path).resolve()
        self.readonly = bool(readonly)
        self.session_token = token or secrets.token_urlsafe(32)
        self.write_lock = threading.Lock()
        super().__init__(server_address, SpecboardHandler)


class SpecboardHandler(BaseHTTPRequestHandler):
    server: SpecboardHTTPServer

    def log_message(self, format: str, *args: Any) -> None:
        # Silencioso por padrão em testes; pode ser inspecionado se necessário
        return

    def _send_bytes(
        self,
        status: int,
        data: bytes,
        content_type: str,
        *,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if extra_headers:
            for k, v in extra_headers.items():
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _send_json(self, status: int, obj: dict[str, Any]) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self._send_bytes(status, body, "application/json; charset=utf-8")

    def _check_origin_and_token(self) -> tuple[bool, str]:
        if self.server.readonly:
            return False, "Servidor iniciado em modo somente leitura (--readonly)."
        token = self.headers.get("X-Specboard-Token", "")
        if not secrets.compare_digest(token, self.server.session_token):
            return False, "Token de sessão ausente ou inválido."
        origin = self.headers.get("Origin")
        if origin:
            parsed = urllib.parse.urlparse(origin)
            if parsed.hostname not in ("127.0.0.1", "localhost", "::1"):
                return False, f"Origem não autorizada: {origin}"
        return True, ""

    def _read_json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > MAX_BODY_BYTES:
            raise ValueError("Corpo da requisição inválido ou grande demais.")
        raw = self.rfile.read(length)
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Payload JSON deve ser um objeto.")
        return data

    def _render_html(self) -> bytes:
        estado, regs, execs, visita = core.load_all(self.server.base_dir)
        payload = core.construir_payload(
            self.server.base_dir,
            estado,
            regs,
            execs,
            visita,
            modo_servidor=True,
        )
        payload["servidor"] = {
            "readonly": self.server.readonly,
            "token": "" if self.server.readonly else self.server.session_token,
        }
        tpl = self.server.template_path.read_text(encoding="utf-8")
        html = tpl.replace(
            "/*__DADOS__*/null",
            json.dumps(payload, ensure_ascii=False).replace("</", "<\\/"),
        )
        return html.encode("utf-8")

    def _serve_evidencia(self, query: dict[str, list[str]]) -> None:
        ref = (query.get("ref") or [""])[0]
        raw_mode = (query.get("raw") or ["0"])[0] == "1"
        resolved = core._safe_resolve_local(self.server.base_dir, ref)
        if resolved is None:
            self._send_json(HTTPStatus.FORBIDDEN, {"erro": "Caminho fora da raiz do projeto não permitido."})
            return
        if not resolved.exists() or not resolved.is_file():
            self._send_json(HTTPStatus.NOT_FOUND, {"erro": f"Arquivo de evidência não encontrado: {ref}"})
            return

        ext = resolved.suffix.lower()
        st = resolved.stat()
        sha = core._sha256_file(resolved)

        if raw_mode or ext in IMAGE_MIME:
            mime = IMAGE_MIME.get(ext) or mimetypes.guess_type(str(resolved))[0] or "application/octet-stream"
            data = resolved.read_bytes()
            self._send_bytes(
                HTTPStatus.OK,
                data,
                mime,
                extra_headers={
                    "Content-Security-Policy": "default-src 'none'; sandbox",
                    "X-Specboard-SHA256": sha,
                },
            )
            return

        # Pré-visualização estruturada (CSV/TSV, Markdown, JSON ou texto) com limite seguro
        truncated = st.st_size > MAX_TEXT_PREVIEW_BYTES
        with resolved.open("rb") as f:
            raw_bytes = f.read(MAX_TEXT_PREVIEW_BYTES)
        try:
            text = raw_bytes.decode("utf-8")
        except UnicodeDecodeError:
            text = raw_bytes.decode("latin-1", errors="replace")

        if ext in (".csv", ".tsv"):
            delim = "\t" if ext == ".tsv" else ","
            rows: list[list[str]] = []
            reader = csv.reader(io.StringIO(text), delimiter=delim)
            row_truncated = False
            for idx, row in enumerate(reader):
                if idx > MAX_CSV_ROWS:
                    row_truncated = True
                    break
                rows.append(row)
            self._send_json(HTTPStatus.OK, {
                "ref": ref,
                "midia": "tabela",
                "sha256": sha,
                "bytes": st.st_size,
                "headers": rows[0] if rows else [],
                "rows": rows[1:] if len(rows) > 1 else [],
                "truncado": truncated or row_truncated,
                "max_linhas": MAX_CSV_ROWS,
            })
            return

        midia = "markdown" if ext in (".md", ".markdown") else ("json" if ext == ".json" else "texto")
        self._send_json(HTTPStatus.OK, {
            "ref": ref,
            "midia": midia,
            "sha256": sha,
            "bytes": st.st_size,
            "conteudo": text,
            "truncado": truncated,
        })

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        try:
            if path in ("/", "/index.html", "/painel.html"):
                self._send_bytes(HTTPStatus.OK, self._render_html(), "text/html; charset=utf-8")
                return

            if path == "/favicon.ico":
                self._send_bytes(HTTPStatus.NO_CONTENT, b"", "image/x-icon")
                return

            if path == "/api/estado":
                estado, regs, execs, visita = core.load_all(self.server.base_dir)
                payload = core.construir_payload(
                    self.server.base_dir,
                    estado,
                    regs,
                    execs,
                    visita,
                    modo_servidor=True,
                )
                payload["servidor"] = {
                    "readonly": self.server.readonly,
                    "token": "" if self.server.readonly else self.server.session_token,
                }
                self._send_json(HTTPStatus.OK, payload)
                return

            if path == "/api/evidencia":
                self._serve_evidencia(query)
                return

            if path.startswith("/api/contexto/"):
                etapa_id = urllib.parse.unquote(path[len("/api/contexto/"):]).strip()
                ctx = core.construir_contexto_limpo(self.server.base_dir, etapa_id)
                self._send_json(HTTPStatus.OK, ctx)
                return

            self._send_json(HTTPStatus.NOT_FOUND, {"erro": "Rota não encontrada."})
        except FileNotFoundError as exc:
            self._send_json(HTTPStatus.NOT_FOUND, {"erro": str(exc)})
        except KeyError as exc:
            self._send_json(HTTPStatus.NOT_FOUND, {"erro": str(exc)})
        except Exception as exc:
            self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"erro": str(exc)})

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        ok, msg = self._check_origin_and_token()
        if not ok:
            self._send_json(HTTPStatus.FORBIDDEN, {"erro": msg})
            return

        try:
            body = self._read_json_body()
        except Exception as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {"erro": f"JSON inválido: {exc}"})
            return

        with self.server.write_lock:
            try:
                if path == "/api/decisao":
                    reg = core.registrar_decisao_humana(
                        self.server.base_dir,
                        etapa_id=str(body.get("etapa_id") or ""),
                        acao=str(body.get("acao") or ""),
                        revisor=str(body.get("revisor") or ""),
                        nota=str(body.get("nota") or ""),
                        canal="painel",
                        observed_fingerprint=body.get("observed_fingerprint"),
                        permitir_evidencia_ausente=bool(body.get("permitir_evidencia_ausente", False)),
                    )
                    estado, regs, execs, visita = core.load_all(self.server.base_dir)
                    payload = core.construir_payload(
                        self.server.base_dir,
                        estado,
                        regs,
                        execs,
                        visita,
                        modo_servidor=True,
                    )
                    payload["servidor"] = {
                        "readonly": self.server.readonly,
                        "token": self.server.session_token,
                    }
                    self._send_json(HTTPStatus.OK, {"ok": True, "registro": reg, "payload": payload})
                    return

                if path == "/api/politica":
                    reg = core.registrar_alteracao_politica(
                        self.server.base_dir,
                        novo_modo=str(body.get("modo") or ""),
                        revisor=str(body.get("revisor") or ""),
                        justificativa=str(body.get("justificativa") or ""),
                        canal="painel",
                        canal_padrao=body.get("canal_padrao"),
                    )
                    estado, regs, execs, visita = core.load_all(self.server.base_dir)
                    payload = core.construir_payload(
                        self.server.base_dir,
                        estado,
                        regs,
                        execs,
                        visita,
                        modo_servidor=True,
                    )
                    payload["servidor"] = {
                        "readonly": self.server.readonly,
                        "token": self.server.session_token,
                    }
                    self._send_json(HTTPStatus.OK, {"ok": True, "registro": reg, "payload": payload})
                    return

                if path == "/api/visita":
                    estado, regs, execs, visita_ant = core.load_all(self.server.base_dir)
                    payload_now = core.construir_payload(
                        self.server.base_dir,
                        estado,
                        regs,
                        execs,
                        visita_ant,
                        modo_servidor=True,
                    )
                    nova_visita = core.save_visita(
                        self.server.base_dir,
                        {
                            "event_ids": [ev["id"] for ev in payload_now["eventos"]],
                            "revisor": str(body.get("revisor") or ""),
                        },
                    )
                    payload_apos = core.construir_payload(
                        self.server.base_dir,
                        estado,
                        regs,
                        execs,
                        nova_visita,
                        modo_servidor=True,
                    )
                    payload_apos["servidor"] = {
                        "readonly": self.server.readonly,
                        "token": self.server.session_token,
                    }
                    self._send_json(HTTPStatus.OK, {"ok": True, "visita": nova_visita, "payload": payload_apos})
                    return

                if path == "/api/contrato/lock":
                    res_lock = core.travar_contrato_modulo(self.server.base_dir, str(body.get("modulo_id") or ""))
                    estado, regs, execs, visita = core.load_all(self.server.base_dir)
                    payload = core.construir_payload(
                        self.server.base_dir,
                        estado,
                        regs,
                        execs,
                        visita,
                        modo_servidor=True,
                    )
                    payload["servidor"] = {
                        "readonly": self.server.readonly,
                        "token": self.server.session_token,
                    }
                    self._send_json(HTTPStatus.OK, {"ok": True, "lock": res_lock, "payload": payload})
                    return

                self._send_json(HTTPStatus.NOT_FOUND, {"erro": "Rota não encontrada."})
            except RuntimeError as exc:
                if "CONFLITO_TOCTOU" in str(exc):
                    estado, regs, execs, visita = core.load_all(self.server.base_dir)
                    payload = core.construir_payload(
                        self.server.base_dir,
                        estado,
                        regs,
                        execs,
                        visita,
                        modo_servidor=True,
                    )
                    payload["servidor"] = {
                        "readonly": self.server.readonly,
                        "token": self.server.session_token,
                    }
                    self._send_json(
                        HTTPStatus.CONFLICT,
                        {"ok": False, "conflito": True, "erro": str(exc), "payload": payload},
                    )
                    return
                self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "erro": str(exc)})
            except KeyError as exc:
                self._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "erro": str(exc)})
            except ValueError as exc:
                self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "erro": str(exc)})
            except Exception as exc:
                self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"ok": False, "erro": str(exc)})


def create_server(
    base_dir: str | Path,
    template_path: str | Path,
    *,
    host: str = "127.0.0.1",
    port: int = 0,
    readonly: bool = False,
    token: str | None = None,
) -> SpecboardHTTPServer:
    return SpecboardHTTPServer(
        (host, port),
        Path(base_dir),
        Path(template_path),
        readonly=readonly,
        token=token,
    )
