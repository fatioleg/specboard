#!/usr/bin/env python3
"""Núcleo de domínio do SpecBoard v2.

Sem dependências externas (Python 3 stdlib puro).
Responsável por:
  - leitura e escrita de estado.json, verificacoes.jsonl, execucoes.jsonl e visita.json
  - fingerprint criptográfico v2 (SHA-256 dos bytes locais + critério/contrato + metadados)
    com retrocompatibilidade para verificações legadas v1
  - avaliação cronológica do status efetivo (última decisão vence, histórico preservado)
  - motor das três políticas de aprovação (acompanhamento_livre, so_marcos, por_etapa)
    com marcos granulares em módulos e/ou etapas
  - fila priorizada com ordenação natural
  - situação atual (Agora), mudanças desde a última visita e pacote de contexto limpo (Agente)
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

STATUS_AGENTE = {"pendente", "em_curso", "executado", "bloqueado"}
IMPACTOS = {"alto": 0, "medio": 1, "baixo": 2}
POLITICAS = {"acompanhamento_livre", "so_marcos", "por_etapa"}
CANAIS_REGISTRO = {"painel", "terminal", "ambos"}
TIPOS_COMPONENTE = {"skill", "local_tool", "mcp_tool"}
NATUREZAS_GUARDRAIL = {"codigo", "instrucao"}
PREFIXOS_REMOTOS = ("http://", "https://", "s3://", "gs://", "ssh://", "ftp://", "doi:")

_CHUNK_SIZE = 65536


def agora_str(com_segundos: bool = False) -> str:
    fmt = "%Y-%m-%d %H:%M:%S" if com_segundos else "%Y-%m-%d %H:%M"
    return datetime.now().strftime(fmt)


def paths(base: str | Path) -> dict[str, Path]:
    root = Path(base).resolve()
    d = root / ".specboard"
    return {
        "root": root,
        "dir": d,
        "estado": d / "estado.json",
        "verificacoes": d / "verificacoes.jsonl",
        "execucoes": d / "execucoes.jsonl",
        "visita": d / "visita.json",
        "hash_cache": d / ".hash_cache.json",
        "painel": d / "painel.html",
    }


def _ler_jsonl(p: Path) -> list[dict[str, Any]]:
    if not p.exists():
        return []
    itens: list[dict[str, Any]] = []
    for idx, ln in enumerate(p.read_text(encoding="utf-8").splitlines(), start=1):
        s = ln.strip()
        if not s:
            continue
        obj = json.loads(s)
        if "_seq" not in obj:
            obj["_seq"] = idx
        itens.append(obj)
    return itens


def load_all(base: str | Path) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any] | None]:
    ps = paths(base)
    if not ps["estado"].exists():
        raise FileNotFoundError(f"Não encontrei {ps['estado']}. Rode: python specboard.py init")
    estado = json.loads(ps["estado"].read_text(encoding="utf-8"))
    regs = _ler_jsonl(ps["verificacoes"])
    execs = _ler_jsonl(ps["execucoes"])
    visita = None
    if ps["visita"].exists():
        try:
            visita = json.loads(ps["visita"].read_text(encoding="utf-8"))
        except Exception:
            visita = None
    return estado, regs, execs, visita


def atomic_write_text(dest: Path, text: str) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{dest.name}.", suffix=".tmp", dir=str(dest.parent))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, dest)
    except Exception:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass
        raise


def append_jsonl(dest: Path, record: dict[str, Any]) -> dict[str, Any]:
    dest.parent.mkdir(parents=True, exist_ok=True)
    clean = {k: v for k, v in record.items() if not k.startswith("_")}
    line = json.dumps(clean, ensure_ascii=False) + "\n"
    with dest.open("a", encoding="utf-8", newline="\n") as f:
        f.write(line)
        f.flush()
        os.fsync(f.fileno())
    return clean


def save_estado(base: str | Path, estado: dict[str, Any]) -> None:
    ps = paths(base)
    estado.setdefault("projeto", {})["atualizado_em"] = agora_str()
    atomic_write_text(ps["estado"], json.dumps(estado, ensure_ascii=False, indent=2) + "\n")


def save_visita(base: str | Path, visita: dict[str, Any]) -> dict[str, Any]:
    ps = paths(base)
    visita = dict(visita)
    visita["registrada_em"] = agora_str(com_segundos=True)
    atomic_write_text(ps["visita"], json.dumps(visita, ensure_ascii=False, indent=2) + "\n")
    return visita


# ---------------------------------------------------------------------------
# Hashing & Evidência (v1 legado + v2 bytes reais)
# ---------------------------------------------------------------------------

def h(obj: Any, length: int = 12) -> str:
    return hashlib.sha256(json.dumps(obj, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:length]


def hash_contrato(mod: dict[str, Any]) -> str:
    c = {k: v for k, v in (mod.get("contrato") or {}).items() if k not in ("travado_em", "hash")}
    return h(c, 12)


def hash_etapa_v1(et: dict[str, Any]) -> str:
    """Hash legado v1 (somente strings do estado.json), preservado para compatibilidade."""
    return h({k: et.get(k) for k in ("titulo", "afirmacao", "verificacao", "evidencia")}, 12)


def _load_hash_cache(base: str | Path) -> dict[str, Any]:
    p = paths(base)["hash_cache"]
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_hash_cache(base: str | Path, cache: dict[str, Any]) -> None:
    try:
        p = paths(base)["hash_cache"]
        if p.parent.exists():
            atomic_write_text(p, json.dumps(cache, ensure_ascii=False))
    except Exception:
        pass


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(_CHUNK_SIZE)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _safe_resolve_local(root: Path, rel_ref: str) -> Path | None:
    cleaned = rel_ref.replace("\\", "/").strip()
    if not cleaned:
        return None
    candidate = Path(cleaned)
    if candidate.is_absolute():
        return None
    try:
        resolved = (root / candidate).resolve()
        resolved.relative_to(root)
        return resolved
    except Exception:
        return None


def _looks_like_path(ref: str) -> bool:
    s = ref.strip()
    if not s:
        return False
    if "/" in s or "\\" in s:
        return True
    # Tem extensão de arquivo plausível (ex.: tabela.csv, fig.png, report.md)
    if re.search(r"\.[A-Za-z0-9]{1,8}$", s):
        return True
    return False


def normalizar_evidencia_item(item: Any) -> dict[str, Any]:
    if isinstance(item, dict):
        ref = str(item.get("caminho") or item.get("ref") or item.get("url") or item.get("id") or "").strip()
        return {
            "id": item.get("id"),
            "ref": ref,
            "tipo_declarado": item.get("tipo"),
            "descricao": item.get("descricao", ""),
            "versao": item.get("versao") or item.get("etag") or item.get("commit_sha"),
            "sha256_esperado": item.get("sha256_esperado"),
            "obrigatoria": item.get("obrigatoria", True),
        }
    return {
        "id": None,
        "ref": str(item).strip(),
        "tipo_declarado": None,
        "descricao": "",
        "versao": None,
        "sha256_esperado": None,
        "obrigatoria": True,
    }


def inspecionar_evidencias(
    base: str | Path,
    evidencia_lista: list[Any] | None,
    *,
    strict: bool = False,
    cache: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    root = Path(base).resolve()
    resultados: list[dict[str, Any]] = []
    cache_dirty = False
    if cache is None and not strict:
        cache = _load_hash_cache(root)

    for raw in (evidencia_lista or []):
        info = normalizar_evidencia_item(raw)
        ref = info["ref"]
        lower = ref.lower()
        tipo_decl = info["tipo_declarado"]

        if tipo_decl == "remota" or any(lower.startswith(pref) for pref in PREFIXOS_REMOTOS):
            versao = info["versao"] or info["sha256_esperado"]
            resultados.append({
                "ref": ref,
                "id": info["id"],
                "descricao": info["descricao"],
                "tipo": "remota",
                "estado": "remota_versionada" if versao else "versao_indisponivel",
                "sha256": info["sha256_esperado"],
                "versao": versao,
                "bytes": None,
                "obrigatoria": info["obrigatoria"],
            })
            continue

        resolved = _safe_resolve_local(root, ref)
        is_path = tipo_decl == "arquivo_local" or _looks_like_path(ref) or (resolved is not None and resolved.exists())

        if not is_path:
            resultados.append({
                "ref": ref,
                "id": info["id"],
                "descricao": info["descricao"],
                "tipo": "referencia_logica",
                "estado": "sem_arquivo_local",
                "sha256": None,
                "versao": info["versao"],
                "bytes": None,
                "obrigatoria": False,
            })
            continue

        if resolved is None:
            resultados.append({
                "ref": ref,
                "id": info["id"],
                "descricao": info["descricao"],
                "tipo": "arquivo_local",
                "estado": "caminho_invalido",
                "sha256": None,
                "versao": None,
                "bytes": None,
                "obrigatoria": info["obrigatoria"],
            })
            continue

        if not resolved.exists() or not resolved.is_file():
            resultados.append({
                "ref": ref,
                "id": info["id"],
                "descricao": info["descricao"],
                "tipo": "arquivo_local",
                "estado": "ausente",
                "sha256": None,
                "versao": None,
                "bytes": None,
                "obrigatoria": info["obrigatoria"],
            })
            continue

        st = resolved.stat()
        rel_norm = resolved.relative_to(root).as_posix()
        digest = None
        if not strict and cache is not None:
            entry = cache.get(rel_norm)
            if entry and entry.get("size") == st.st_size and entry.get("mtime_ns") == st.st_mtime_ns:
                digest = entry.get("sha256")
        if not digest:
            digest = _sha256_file(resolved)
            if cache is not None:
                cache[rel_norm] = {"size": st.st_size, "mtime_ns": st.st_mtime_ns, "sha256": digest}
                cache_dirty = True

        ext = resolved.suffix.lower()
        midia = "imagem" if ext in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg") else (
            "tabela" if ext in (".csv", ".tsv") else (
                "markdown" if ext in (".md", ".markdown") else (
                    "json" if ext == ".json" else (
                        "texto" if ext in (".txt", ".log", ".yaml", ".yml", ".py", ".xyz", ".mdp", ".top") else "binario"
                    )
                )
            )
        )
        resultados.append({
            "ref": ref,
            "caminho_rel": rel_norm,
            "id": info["id"],
            "descricao": info["descricao"],
            "tipo": "arquivo_local",
            "midia": midia,
            "estado": "ok",
            "sha256": digest,
            "versao": info["versao"],
            "bytes": st.st_size,
            "mtime": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
            "obrigatoria": info["obrigatoria"],
        })

    if cache_dirty and cache is not None:
        _save_hash_cache(root, cache)
    return resultados


def snapshot_etapa(
    base: str | Path,
    mod: dict[str, Any],
    et: dict[str, Any],
    *,
    strict: bool = False,
    cache: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Calcula fingerprint composto v2 (metadados + critério/contrato + bytes das evidências)."""
    meta_obj = {
        "titulo": et.get("titulo"),
        "afirmacao": et.get("afirmacao"),
        "verificacao": et.get("verificacao"),
        "evidencia": et.get("evidencia"),
        "revisao_etapa": et.get("revisao_etapa"),
    }
    etapa_meta_hash = h(meta_obj, 16)
    contrato_norm = {k: v for k, v in (mod.get("contrato") or {}).items() if k not in ("travado_em", "hash")}
    criterio_obj = {
        "contrato": contrato_norm,
        "criterios_etapa": et.get("criterios") or [],
    }
    criterio_hash = h(criterio_obj, 16)
    evidencias = inspecionar_evidencias(base, et.get("evidencia") or [], strict=strict, cache=cache)
    evid_for_hash = [
        {
            "ref": ev["ref"],
            "tipo": ev["tipo"],
            "estado": ev["estado"],
            "sha256": ev.get("sha256"),
            "versao": ev.get("versao"),
        }
        for ev in evidencias
    ]
    fingerprint_total = h(
        {
            "v": 2,
            "etapa_meta_hash": etapa_meta_hash,
            "criterio_hash": criterio_hash,
            "evidencias": evid_for_hash,
        },
        16,
    )
    return {
        "schema_hash_v": 2,
        "etapa_meta_hash": etapa_meta_hash,
        "criterio_hash": criterio_hash,
        "hash_etapa_v1": hash_etapa_v1(et),
        "evidencias": evidencias,
        "fingerprint_total": fingerprint_total,
    }


# ---------------------------------------------------------------------------
# Helpers de grafo, ordem natural e políticas
# ---------------------------------------------------------------------------

def natural_key(text: str) -> list[tuple[int, Any]]:
    parts = re.split(r"(\d+)", str(text or ""))
    out: list[tuple[int, Any]] = []
    for p in parts:
        if not p:
            continue
        if p.isdigit():
            out.append((0, int(p)))
        else:
            out.append((1, p.lower()))
    return out


def iter_etapas(estado: dict[str, Any]):
    for m in estado.get("modulos", []):
        for e in m.get("etapas", []):
            yield m, e


def politica_efetiva(estado: dict[str, Any], regs: list[dict[str, Any]]) -> dict[str, Any]:
    """Resolve política ativa: última alteração humana registrada em verificacoes.jsonl > estado.json > legado."""
    p = estado.get("projeto") or {}
    base_pol = p.get("politica_aprovacao")
    historico: list[dict[str, Any]] = []

    if isinstance(base_pol, dict) and base_pol.get("modo") in POLITICAS:
        atual = {
            "modo": base_pol["modo"],
            "canal_padrao": base_pol.get("canal_padrao", "painel"),
            "definida_em": base_pol.get("definida_em") or p.get("atualizado_em") or "",
            "definida_por": base_pol.get("definida_por") or "criação do projeto",
            "legada": False,
        }
    elif isinstance(base_pol, str) and base_pol in POLITICAS:
        atual = {
            "modo": base_pol,
            "canal_padrao": "painel",
            "definida_em": p.get("atualizado_em") or "",
            "definida_por": "criação do projeto",
            "legada": False,
        }
    else:
        atual = {
            "modo": "por_etapa",
            "canal_padrao": "ambos",
            "definida_em": "",
            "definida_por": "compatibilidade legada",
            "legada": True,
        }

    for r in regs:
        if r.get("tipo") == "alterar_politica" and r.get("modo") in POLITICAS:
            historico.append({
                "modo_anterior": r.get("modo_anterior"),
                "modo": r.get("modo"),
                "canal_padrao": r.get("canal_padrao", atual["canal_padrao"]),
                "revisor": r.get("revisor", ""),
                "justificativa": r.get("justificativa", ""),
                "data": r.get("data", ""),
                "canal": r.get("canal", "terminal"),
            })
            atual = {
                "modo": r["modo"],
                "canal_padrao": r.get("canal_padrao", atual["canal_padrao"]),
                "definida_em": r.get("data", ""),
                "definida_por": r.get("revisor", ""),
                "legada": False,
            }

    atual["historico"] = historico
    return atual


def eh_marco_etapa(mod: dict[str, Any], et: dict[str, Any]) -> bool:
    """Granularidade de marco: etapa explícita tem precedência; caso contrário herda módulo marco na última etapa."""
    if "marco" in et and et["marco"] is not None:
        return bool(et["marco"])
    if mod.get("marco"):
        ets = mod.get("etapas") or []
        if any(e.get("marco") is True for e in ets):
            return False
        return bool(ets) and ets[-1].get("id") == et.get("id")
    return False


def eh_marco_modulo(mod: dict[str, Any]) -> bool:
    if mod.get("marco"):
        return True
    return any(e.get("marco") is True for e in (mod.get("etapas") or []))


def _decisoes_etapa(et_id: str, regs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for r in regs if r.get("tipo") != "alterar_politica" and r.get("etapa") == et_id]


def status_efetivo_detalhado(
    base: str | Path,
    mod: dict[str, Any],
    et: dict[str, Any],
    regs: list[dict[str, Any]],
    *,
    snap: dict[str, Any] | None = None,
    cache: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Avalia o status efetivo pela ÚLTIMA decisão cronológica, preservando todo o histórico."""
    if snap is None:
        snap = snapshot_etapa(base, mod, et, cache=cache)
    historico = _decisoes_etapa(et["id"], regs)
    st_agente = et.get("status", "pendente")

    if not historico:
        return {
            "status": st_agente,
            "exp": None,
            "exp_motivos": [],
            "arquivos_alterados": [],
            "legada": False,
            "reentregue": False,
            "ultima_decisao": None,
            "historico": [],
            "snapshot": snap,
        }

    ultima = historico[-1]
    acao = ultima.get("acao") or ultima.get("nivel")

    # Caso 0a: bloqueio explícito imposto pelo humano
    if acao == "bloquear":
        return {
            "status": "bloqueado",
            "exp": None,
            "exp_motivos": [],
            "arquivos_alterados": [],
            "legada": False,
            "reentregue": False,
            "bloqueio_humano": True,
            "ultima_decisao": ultima,
            "historico": historico,
            "snapshot": snap,
        }

    # Caso 0b: humano pausou explicitamente em "aguardando decisão"
    if acao == "aguardar_decisao":
        return {
            "status": "aguardando_decisao",
            "exp": None,
            "exp_motivos": [],
            "arquivos_alterados": [],
            "legada": False,
            "reentregue": False,
            "ultima_decisao": ultima,
            "historico": historico,
            "snapshot": snap,
        }

    # Caso 0c: humano desbloqueou / retomou a etapa para o estado do agente
    if acao == "desbloquear":
        return {
            "status": st_agente,
            "exp": None,
            "exp_motivos": [],
            "arquivos_alterados": [],
            "legada": False,
            "reentregue": False,
            "ultima_decisao": ultima,
            "historico": historico,
            "snapshot": snap,
        }

    # Caso 1: última decisão foi pedido de correção
    if acao in ("pedir_correcao", "correcao_solicitada"):
        fp_prev = ultima.get("fingerprint_total") or ultima.get("hash_etapa")
        fp_now = snap["fingerprint_total"] if ultima.get("fingerprint_total") else snap["hash_etapa_v1"]
        mudou = fp_prev != fp_now
        if st_agente == "em_curso":
            return {
                "status": "em_curso",
                "exp": None,
                "exp_motivos": [],
                "arquivos_alterados": [],
                "legada": False,
                "reentregue": False,
                "em_correcao": True,
                "ultima_decisao": ultima,
                "historico": historico,
                "snapshot": snap,
            }
        if st_agente == "executado" and mudou:
            return {
                "status": "executado",
                "exp": None,
                "exp_motivos": [],
                "arquivos_alterados": [],
                "legada": False,
                "reentregue": True,
                "ultima_decisao": ultima,
                "historico": historico,
                "snapshot": snap,
            }
        return {
            "status": "correcao_solicitada",
            "exp": None,
            "exp_motivos": [],
            "arquivos_alterados": [],
            "legada": False,
            "reentregue": False,
            "ultima_decisao": ultima,
            "historico": historico,
            "snapshot": snap,
        }

    # Caso 2: última decisão foi aprovação (verificado) ou leitura (revisado)
    if ultima.get("nivel") in ("verificado", "revisado"):
        # Se o agente explicitamente reabriu a etapa (em_curso ou pendente ou bloqueado), não tratar como verificada
        if st_agente in ("em_curso", "bloqueado", "pendente"):
            return {
                "status": st_agente,
                "exp": "expirada",
                "exp_motivos": ["etapa_reaberta"],
                "arquivos_alterados": [],
                "legada": ultima.get("schema_hash_v") != 2,
                "reentregue": False,
                "ultima_decisao": ultima,
                "historico": historico,
                "snapshot": snap,
            }

        # Registro v2 com fingerprint composto
        if ultima.get("schema_hash_v") == 2 or "fingerprint_total" in ultima:
            if ultima.get("fingerprint_total") == snap["fingerprint_total"]:
                return {
                    "status": ultima["nivel"],
                    "exp": None,
                    "exp_motivos": [],
                    "arquivos_alterados": [],
                    "legada": False,
                    "reentregue": False,
                    "ultima_decisao": ultima,
                    "historico": historico,
                    "snapshot": snap,
                }
            # Diagnosticar exatamente o que mudou
            motivos: list[str] = []
            alterados: list[str] = []
            if ultima.get("etapa_meta_hash") and ultima.get("etapa_meta_hash") != snap["etapa_meta_hash"]:
                motivos.append("etapa_alterada")
            if ultima.get("criterio_hash") and ultima.get("criterio_hash") != snap["criterio_hash"]:
                motivos.append("criterio_alterado")
            prev_evs = {ev.get("ref"): ev for ev in (ultima.get("evidencias") or [])}
            now_evs = {ev.get("ref"): ev for ev in snap["evidencias"]}
            for ref in sorted(set(prev_evs) | set(now_evs)):
                a = prev_evs.get(ref)
                b = now_evs.get(ref)
                if not a or not b:
                    alterados.append(ref)
                elif a.get("sha256") != b.get("sha256") or a.get("estado") != b.get("estado"):
                    alterados.append(ref)
            if alterados:
                motivos.append("evidencia_alterada")
            if not motivos:
                motivos.append("snapshot_alterado")
            return {
                "status": st_agente,
                "exp": "expirada",
                "exp_motivos": motivos,
                "arquivos_alterados": alterados,
                "legada": False,
                "reentregue": False,
                "ultima_decisao": ultima,
                "historico": historico,
                "snapshot": snap,
            }

        # Registro legado v1 (somente hash_etapa)
        if ultima.get("hash_etapa") == snap["hash_etapa_v1"]:
            return {
                "status": ultima["nivel"],
                "exp": None,
                "exp_motivos": [],
                "arquivos_alterados": [],
                "legada": True,
                "reentregue": False,
                "ultima_decisao": ultima,
                "historico": historico,
                "snapshot": snap,
            }
        return {
            "status": st_agente,
            "exp": "expirada",
            "exp_motivos": ["etapa_alterada"],
            "arquivos_alterados": [],
            "legada": True,
            "reentregue": False,
            "ultima_decisao": ultima,
            "historico": historico,
            "snapshot": snap,
        }

    return {
        "status": st_agente,
        "exp": None,
        "exp_motivos": [],
        "arquivos_alterados": [],
        "legada": False,
        "reentregue": False,
        "ultima_decisao": ultima,
        "historico": historico,
        "snapshot": snap,
    }


def status_efetivo(
    et: dict[str, Any],
    regs: list[dict[str, Any]],
    *,
    base: str | Path | None = None,
    mod: dict[str, Any] | None = None,
) -> tuple[str, str | None]:
    """Assinatura compatível com v1; usa v2 completo quando base/mod são fornecidos."""
    if base is not None and mod is not None:
        info = status_efetivo_detalhado(base, mod, et, regs)
        return info["status"], info["exp"]
    # Fallback puramente em memória
    info = status_efetivo_detalhado(Path("."), mod or {}, et, regs)
    return info["status"], info["exp"]


# ---------------------------------------------------------------------------
# Validação
# ---------------------------------------------------------------------------

def validar(base: str | Path, estado: dict[str, Any], regs: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    erros: list[str] = []
    avisos: list[str] = []
    p = estado.get("projeto") or {}
    if not p.get("pergunta_central"):
        erros.append("projeto.pergunta_central vazia: o painel precisa saber o que está sendo respondido.")

    pol = p.get("politica_aprovacao")
    if isinstance(pol, dict):
        if pol.get("modo") and pol["modo"] not in POLITICAS:
            erros.append(f"projeto.politica_aprovacao.modo inválido: '{pol['modo']}'.")
        if pol.get("canal_padrao") and pol["canal_padrao"] not in CANAIS_REGISTRO:
            erros.append(f"projeto.politica_aprovacao.canal_padrao inválido: '{pol['canal_padrao']}'.")
    elif isinstance(pol, str) and pol not in POLITICAS:
        erros.append(f"projeto.politica_aprovacao inválido: '{pol}'.")

    ids_mod = [m.get("id") for m in estado.get("modulos", [])]
    if len(ids_mod) != len(set(ids_mod)):
        erros.append("IDs de módulo duplicados.")
    if not any(m.get("resultado_final") for m in estado.get("modulos", [])):
        avisos.append("Nenhum módulo marcado com resultado_final: true.")

    todos_ids_etapa = {e.get("id") for _, e in iter_etapas(estado) if e.get("id")}
    vistos: set[str] = set()
    cache = _load_hash_cache(base)

    for m in estado.get("modulos", []):
        for dep in m.get("depende_de", []):
            if dep not in ids_mod:
                erros.append(f"{m['id']}: depende de módulo inexistente '{dep}'.")
        c = m.get("contrato") or {}
        if c.get("hash") and c["hash"] != hash_contrato(m):
            erros.append(f"{m['id']}: contrato travado foi alterado sem emenda. Rode: amend {m['id']} -j \"motivo\"")
        if not m.get("etapas") and not m.get("etapas_estimadas"):
            avisos.append(f"{m['id']}: sem etapas nem etapas_estimadas; fica fora do denominador.")
        for e in m.get("etapas", []):
            eid = e["id"]
            if eid in vistos:
                erros.append(f"Etapa duplicada: {eid}")
            vistos.add(eid)
            st = e.get("status", "pendente")
            if st not in STATUS_AGENTE:
                erros.append(
                    f"{eid}: status '{st}' inválido no estado.json. "
                    "'revisado'/'verificado' só existem via decisão humana."
                )
            if e.get("impacto") not in IMPACTOS:
                erros.append(f"{eid}: impacto deve ser alto/medio/baixo.")
            for dep in e.get("depende_de", []):
                if dep not in todos_ids_etapa and dep not in ids_mod:
                    erros.append(f"{eid}: depende de etapa/módulo inexistente '{dep}'.")
            if st == "executado" and not (e.get("afirmacao") and e.get("verificacao")):
                erros.append(f"{eid}: executado sem 'afirmacao' e 'verificacao' — nada a validar.")
            if st == "executado" and not e.get("evidencia"):
                avisos.append(f"{eid}: executado sem evidência apontada.")
            if st == "executado" and e.get("evidencia"):
                evs = inspecionar_evidencias(base, e.get("evidencia"), cache=cache)
                for ev in evs:
                    if ev["estado"] == "ausente":
                        avisos.append(f"{eid}: evidência local ausente no disco: '{ev['ref']}'.")
                    elif ev["estado"] == "caminho_invalido":
                        erros.append(f"{eid}: caminho de evidência fora da raiz do projeto: '{ev['ref']}'.")
            arq = e.get("arquitetura_agente")
            if isinstance(arq, dict):
                for comp in arq.get("componentes") or []:
                    if comp.get("tipo") and comp["tipo"] not in TIPOS_COMPONENTE:
                        erros.append(f"{eid}: componente '{comp.get('nome')}' com tipo inválido '{comp['tipo']}'.")
                for g in arq.get("guardrails") or []:
                    if g.get("natureza") and g["natureza"] not in NATUREZAS_GUARDRAIL:
                        erros.append(f"{eid}: guardrail '{g.get('regra')}' com natureza inválida '{g['natureza']}'.")

    return erros, avisos


# ---------------------------------------------------------------------------
# Grafo, Bloqueios, Fila, Situação Atual, Aba Agente e Payload Completo
# ---------------------------------------------------------------------------

def _ordem_e_rota(estado: dict[str, Any]) -> tuple[list[dict[str, Any]], set[str]]:
    mods = estado.get("modulos", [])
    by_id = {m["id"]: m for m in mods}
    vis: set[str] = set()
    ordem: list[dict[str, Any]] = []

    def go(mid: str) -> None:
        if mid in vis or mid not in by_id:
            return
        vis.add(mid)
        for dep in by_id[mid].get("depende_de", []):
            go(dep)
        ordem.append(by_id[mid])

    for m in mods:
        if m.get("resultado_final"):
            go(m["id"])
    for m in mods:
        go(m["id"])

    na_rota: set[str] = set()

    def go_rota(mid: str) -> None:
        if mid in na_rota or mid not in by_id:
            return
        na_rota.add(mid)
        for dep in by_id[mid].get("depende_de", []):
            go_rota(dep)

    for m in mods:
        if m.get("resultado_final"):
            go_rota(m["id"])

    return ordem, na_rota


def _merge_arquitetura_agente(
    mod: dict[str, Any],
    et: dict[str, Any],
    execs: list[dict[str, Any]],
    estado: dict[str, Any],
    base: str | Path,
    regs: list[dict[str, Any]],
    cache: dict[str, Any],
) -> dict[str, Any]:
    """Constrói visão técnica da etapa separando planejado, configurado e observado ('sem registro')."""
    mod_arq = mod.get("arquitetura_agente") or {}
    et_arq = et.get("arquitetura_agente") or {}
    merged = {
        "papel": et_arq.get("papel") or mod_arq.get("papel") or "",
        "contexto_duravel": dict(mod_arq.get("contexto_duravel") or {}),
        "contexto_execucao": dict(mod_arq.get("contexto_execucao") or {}),
        "componentes": [],
        "guardrails": [],
        "avaliacao": et_arq.get("avaliacao") or mod_arq.get("avaliacao") or {},
        "possui_definicao": bool(et_arq or mod_arq),
    }
    merged["contexto_duravel"].update(et_arq.get("contexto_duravel") or {})
    merged["contexto_execucao"].update(et_arq.get("contexto_execucao") or {})

    # Enriquecer hashes de artefatos de referência do contexto durável
    refs_in = merged["contexto_duravel"].get("artefatos_referencia") or []
    refs_out = []
    for ref in refs_in:
        if isinstance(ref, dict):
            item = dict(ref)
            caminho = item.get("caminho") or item.get("ref")
            if caminho:
                insp = inspecionar_evidencias(base, [caminho], cache=cache)
                if insp:
                    item["estado_arquivo"] = insp[0]["estado"]
                    item["sha256_atual"] = insp[0].get("sha256")
            refs_out.append(item)
        else:
            insp = inspecionar_evidencias(base, [str(ref)], cache=cache)
            refs_out.append({
                "nome": str(ref),
                "caminho": str(ref),
                "estado_arquivo": insp[0]["estado"] if insp else "desconhecido",
                "sha256_atual": insp[0].get("sha256") if insp else None,
            })
    if refs_out:
        merged["contexto_duravel"]["artefatos_referencia"] = refs_out

    # Telemetria observada da etapa (execucoes.jsonl)
    et_execs = [x for x in execs if x.get("etapa") == et["id"]]
    obs_by_name: dict[str, list[dict[str, Any]]] = {}
    for tr in et_execs:
        tname = tr.get("tool_name") or tr.get("gen_ai.tool.name") or tr.get("componente") or ""
        if tname:
            obs_by_name.setdefault(tname, []).append(tr)

    raw_comps = list(mod_arq.get("componentes") or []) + list(et_arq.get("componentes") or [])
    vistos_comp: set[str] = set()
    comps_out = []
    for c in raw_comps:
        nome = c.get("nome") or c.get("id") or ""
        if not nome or nome in vistos_comp:
            continue
        vistos_comp.add(nome)
        traces = obs_by_name.get(nome) or obs_by_name.get(c.get("id", "")) or []
        if traces:
            ultimo = traces[-1]
            dur_total = sum(int(t.get("duracao_ms") or 0) for t in traces)
            obs_info = {
                "estado": "observado",
                "label": f"observado ({len(traces)}x)",
                "chamadas": len(traces),
                "duracao_total_ms": dur_total,
                "ultimo_status": ultimo.get("status", "ok"),
                "ultima_em": ultimo.get("timestamp", ""),
                "observado_por": ultimo.get("observado_por", "telemetria"),
            }
        else:
            obs_info = {
                "estado": "sem_registro",
                "label": "sem registro",
                "chamadas": 0,
            }
        comps_out.append({
            "id": c.get("id") or nome,
            "nome": nome,
            "tipo": c.get("tipo", "local_tool"),
            "mcp_server": c.get("mcp_server"),
            "versao_origem": c.get("versao_origem") or c.get("versao") or "",
            "funcao": c.get("funcao") or "",
            "motivo_escolha": c.get("motivo_escolha") or "",
            "planejado": bool(c.get("planejado", True)),
            "configurado": bool(c.get("configurado", True)),
            "observado": obs_info,
        })

    # Incluir ferramentas observadas em execução que não estavam declaradas
    for tname, traces in obs_by_name.items():
        if tname in vistos_comp:
            continue
        ultimo = traces[-1]
        comps_out.append({
            "id": tname,
            "nome": tname,
            "tipo": ultimo.get("tool_type") or "local_tool",
            "mcp_server": ultimo.get("mcp_server"),
            "versao_origem": ultimo.get("versao_origem") or "observado em execução",
            "funcao": ultimo.get("funcao") or "Chamada registrada fora da lista planejada",
            "motivo_escolha": "",
            "planejado": False,
            "configurado": False,
            "observado": {
                "estado": "observado",
                "label": f"observado ({len(traces)}x)",
                "chamadas": len(traces),
                "duracao_total_ms": sum(int(t.get("duracao_ms") or 0) for t in traces),
                "ultimo_status": ultimo.get("status", "ok"),
                "ultima_em": ultimo.get("timestamp", ""),
                "observado_por": ultimo.get("observado_por", "telemetria"),
            },
        })
    merged["componentes"] = comps_out

    # Guardrails (separando código vs instrução)
    raw_guards = list(mod_arq.get("guardrails") or []) + list(et_arq.get("guardrails") or [])
    merged["guardrails"] = [
        {
            "id": g.get("id") or f"G-{i+1}",
            "regra": g.get("regra") or "",
            "natureza": g.get("natureza", "instrucao"),
            "onde_aplica": g.get("onde_aplica") or "",
            "verifica": g.get("verifica") or "",
            "se_falhar": g.get("se_falhar") or "",
            "referencia_codigo": g.get("referencia_codigo") or "",
        }
        for i, g in enumerate(raw_guards)
    ]

    # Ligação ponta a ponta (script -> resultado -> evidência)
    merged["linhagem"] = et_arq.get("linhagem") or []
    return merged


def construir_payload(
    base: str | Path,
    estado_raw: dict[str, Any],
    regs: list[dict[str, Any]],
    execs: list[dict[str, Any]] | None = None,
    visita: dict[str, Any] | None = None,
    *,
    modo_servidor: bool = False,
) -> dict[str, Any]:
    """Constrói o estado enriquecido usado igualmente por build, serve, queue e gate."""
    execs = execs or []
    estado = json.loads(json.dumps(estado_raw, ensure_ascii=False))
    root = Path(base).resolve()
    cache = _load_hash_cache(root)

    erros, avisos = validar(root, estado, regs)
    politica = politica_efetiva(estado, regs)
    modo_pol = politica["modo"]
    ordem, na_rota = _ordem_e_rota(estado)
    mods = estado.get("modulos", [])
    by_mod = {m["id"]: m for m in mods}

    # 1) Calcular status efetivo, snapshot e marco de cada etapa
    etapa_index: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    for m in mods:
        c = m.get("contrato") or {}
        m["_contrato_ok"] = not (c.get("hash") and c["hash"] != hash_contrato(m))
        m["_na_rota"] = m["id"] in na_rota
        m["_eh_marco"] = eh_marco_modulo(m)
        for e in m.get("etapas", []):
            det = status_efetivo_detalhado(root, m, e, regs, cache=cache)
            e["_status"] = det["status"]
            e["_status_agente"] = e.get("status", "pendente")
            e["_exp"] = det["exp"]
            e["_exp_motivos"] = det["exp_motivos"]
            e["_arquivos_alterados"] = det["arquivos_alterados"]
            e["_legada"] = det["legada"]
            e["_reentregue"] = det["reentregue"]
            e["_ultima_decisao"] = det["ultima_decisao"]
            e["_regs"] = det["historico"]
            e["_snapshot"] = det["snapshot"]
            e["_eh_marco"] = eh_marco_etapa(m, e)
            e["_modulo_id"] = m["id"]
            e["_agente"] = _merge_arquitetura_agente(m, e, execs, estado, root, regs, cache)
            etapa_index[e["id"]] = (m, e)

    # 2) Mapa de dependências e bloqueios impostos pelo sistema (conforme política)
    mod_bloqueadores: dict[str, list[dict[str, Any]]] = {m["id"]: [] for m in mods}
    etapa_bloqueadores: dict[str, list[dict[str, Any]]] = {eid: [] for eid in etapa_index}
    etapa_base_reaberta: dict[str, list[str]] = {eid: [] for eid in etapa_index}

    def _etapas_portao_modulo(m_dep: dict[str, Any]) -> list[dict[str, Any]]:
        ets = m_dep.get("etapas") or []
        if not ets:
            return []
        if modo_pol == "acompanhamento_livre":
            return [
                e for e in ets
                if e["_status"] == "bloqueado" and (e.get("_ultima_decisao") or {}).get("acao") == "bloquear"
            ]
        if modo_pol == "so_marcos":
            marcos = [e for e in ets if e["_eh_marco"]]
            if marcos:
                return marcos
            if m_dep.get("marco"):
                return ets
            return []
        # por_etapa
        return [e for e in ets if e.get("revisao") != "isenta"]

    # Bloqueios entre módulos e dentro de módulos
    for m in mods:
        mid = m["id"]
        if not m["_contrato_ok"]:
            mod_bloqueadores[mid].append({
                "tipo": "contrato_violado",
                "origem_id": mid,
                "motivo": f"Contrato travado de {mid} alterado sem emenda.",
            })
        if m.get("bloqueio"):
            mod_bloqueadores[mid].append({
                "tipo": "bloqueio_modulo",
                "origem_id": mid,
                "motivo": m["bloqueio"],
            })

        for dep_mid in m.get("depende_de", []):
            m_dep = by_mod.get(dep_mid)
            if not m_dep:
                continue
            portoes = _etapas_portao_modulo(m_dep)
            for ge in portoes:
                if ge["_status"] != "verificado":
                    motivo_extra = (
                        "verificação expirada" if ge["_exp"]
                        else ("correção solicitada" if ge["_status"] == "correcao_solicitada" else "aguarda aprovação humana")
                    )
                    mod_bloqueadores[mid].append({
                        "tipo": "marco_pendente" if ge["_eh_marco"] else "etapa_pendente",
                        "origem_id": ge["id"],
                        "modulo_origem": dep_mid,
                        "motivo": f"Depende de {ge['id']} ({ge['titulo']}): {motivo_extra}.",
                    })
            if not m_dep.get("etapas") and modo_pol != "acompanhamento_livre" and (modo_pol == "por_etapa" or m_dep.get("marco")):
                mod_bloqueadores[mid].append({
                    "tipo": "modulo_nao_detalhado",
                    "origem_id": dep_mid,
                    "modulo_origem": dep_mid,
                    "motivo": f"Módulo anterior {dep_mid} ainda não foi executado/verificado.",
                })

        # Bloqueios no nível de etapa (herda módulo + dependências diretas da etapa)
        ets = m.get("etapas") or []
        for idx, e in enumerate(ets):
            eid = e["id"]
            b_list = list(mod_bloqueadores[mid])
            if e["_status"] == "bloqueado":
                b_list.append({
                    "tipo": "bloqueio_etapa",
                    "origem_id": eid,
                    "motivo": e.get("bloqueio") or f"Etapa {eid} marcada como bloqueada.",
                })

            # Dependências explícitas da etapa ou sequência interna
            deps_et = e.get("depende_de")
            if deps_et is None:
                # Sequência interna padrão: olha etapas anteriores do mesmo módulo se forem marco (em so_marcos) ou qualquer anterior (em por_etapa)
                prev_candidates = ets[:idx]
            else:
                prev_candidates = []
                for d_ref in deps_et:
                    if d_ref in etapa_index:
                        prev_candidates.append(etapa_index[d_ref][1])
                    elif d_ref in by_mod:
                        prev_candidates.extend(_etapas_portao_modulo(by_mod[d_ref]))

            for pe in prev_candidates:
                if pe["id"] == eid:
                    continue
                if modo_pol == "acompanhamento_livre":
                    continue
                exige = (
                    (modo_pol == "so_marcos" and pe["_eh_marco"])
                    or (modo_pol == "por_etapa" and pe.get("revisao") != "isenta")
                )
                if not exige:
                    continue
                if pe["_status"] != "verificado":
                    # Se a etapa atual já foi executada antes da expiração/correção anterior -> sinaliza base reaberta
                    if e["_status"] in ("executado", "revisado", "verificado"):
                        if pe["_exp"] or pe["_status"] == "correcao_solicitada":
                            etapa_base_reaberta[eid].append(pe["id"])
                    else:
                        motivo_extra = (
                            "verificação expirada" if pe["_exp"]
                            else ("correção solicitada" if pe["_status"] == "correcao_solicitada" else "aguarda aprovação")
                        )
                        b_list.append({
                            "tipo": "marco_pendente" if pe["_eh_marco"] else "etapa_pendente",
                            "origem_id": pe["id"],
                            "modulo_origem": pe["_modulo_id"],
                            "motivo": f"Aguarda aprovação de {pe['id']} ({pe['titulo']}): {motivo_extra}.",
                        })

            # Deduplicar bloqueadores por (tipo, origem_id)
            vistos_b: set[tuple[str, str]] = set()
            dedup_b = []
            for b in b_list:
                key = (b["tipo"], b["origem_id"])
                if key not in vistos_b:
                    vistos_b.add(key)
                    dedup_b.append(b)
            etapa_bloqueadores[eid] = dedup_b
            e["_bloqueios_sistema"] = dedup_b
            e["_base_reaberta_por"] = etapa_base_reaberta[eid]

    # 3) Calcular impacto de aprovar / pedir correção em cada etapa (quem depende dela)
    bloqueia_map: dict[str, list[dict[str, str]]] = {eid: [] for eid in etapa_index}
    for m in mods:
        mid = m["id"]
        for b in mod_bloqueadores[mid]:
            orig = b.get("origem_id")
            if orig in bloqueia_map:
                bloqueia_map[orig].append({"tipo": "modulo", "id": mid, "titulo": m.get("titulo", mid)})
        for e in m.get("etapas", []):
            for b in e["_bloqueios_sistema"]:
                orig = b.get("origem_id")
                if orig in bloqueia_map and orig != e["id"]:
                    bloqueia_map[orig].append({"tipo": "etapa", "id": e["id"], "titulo": e.get("titulo", e["id"])})

    for eid, (m, e) in etapa_index.items():
        # Também listar dependentes estruturais mesmo que ainda não estejam bloqueados (ex.: modo livre ou módulo futuro)
        estruturais = list(bloqueia_map[eid])
        seen_dep = {(x["tipo"], x["id"]) for x in estruturais}
        for m2 in mods:
            if m["id"] in (m2.get("depende_de") or []) and ("modulo", m2["id"]) not in seen_dep:
                estruturais.append({"tipo": "modulo", "id": m2["id"], "titulo": m2.get("titulo", m2["id"])})
                seen_dep.add(("modulo", m2["id"]))
            for e2 in m2.get("etapas", []):
                if eid in (e2.get("depende_de") or []) and ("etapa", e2["id"]) not in seen_dep:
                    estruturais.append({"tipo": "etapa", "id": e2["id"], "titulo": e2.get("titulo", e2["id"])})
                    seen_dep.add(("etapa", e2["id"]))
        e["_libera"] = estruturais
        e["_bloqueia_agora"] = bloqueia_map[eid]

    # 4) Relações explícitas do mapa (sequência de trabalho vs dependência bloqueante)
    relacoes_mapa: list[dict[str, Any]] = []
    seen_rel: set[tuple[str, str]] = set()
    for m in mods:
        for rel in m.get("relacoes") or []:
            para = rel.get("para")
            if para in by_mod:
                tipo_rel = rel.get("tipo", "sequencia")
                relacoes_mapa.append({
                    "de": m["id"],
                    "para": para,
                    "tipo": tipo_rel,
                    "motivo": rel.get("motivo", ""),
                })
                seen_rel.add((m["id"], para))
    for m in mods:
        for dep in m.get("depende_de") or []:
            if dep in by_mod and (dep, m["id"]) not in seen_rel:
                dep_mod = by_mod[dep]
                eh_bloq = any(
                    b.get("modulo_origem") == dep or b.get("origem_id") == dep
                    for b in mod_bloqueadores[m["id"]]
                ) or (modo_pol == "so_marcos" and dep_mod["_eh_marco"]) or (modo_pol == "por_etapa")
                relacoes_mapa.append({
                    "de": dep,
                    "para": m["id"],
                    "tipo": "bloqueante" if eh_bloq else "sequencia",
                    "ativa": any(
                        b.get("modulo_origem") == dep or b.get("origem_id") == dep
                        for b in mod_bloqueadores[m["id"]]
                    ),
                    "motivo": "Dependência de marco/aprovação" if eh_bloq else "Sequência de trabalho",
                })
                seen_rel.add((dep, m["id"]))

    # 5) Status consolidado de módulo (corrigindo o bug v1 de 'em_curso' falso!)
    for m in mods:
        ets = m.get("etapas") or []
        ss = [e["_status"] for e in ets]
        m["_bloqueios_sistema"] = mod_bloqueadores[m["id"]]
        if not m["_contrato_ok"] or m.get("bloqueio") or "bloqueado" in ss or "correcao_solicitada" in ss:
            m["_status_mod"] = "bloqueado"
        elif mod_bloqueadores[m["id"]] and (not ss or all(s == "pendente" for s in ss)):
            m["_status_mod"] = "bloqueado"
        elif ss and all(s == "verificado" for s in ss):
            m["_status_mod"] = "verificado"
        elif "em_curso" in ss:
            m["_status_mod"] = "em_curso"
        elif any(s in ("executado", "revisado", "aguardando_decisao") for s in ss):
            m["_status_mod"] = "aguarda"
        elif any(s == "verificado" for s in ss):
            m["_status_mod"] = "parcial"
        else:
            m["_status_mod"] = "pendente"

    # 6) Resumo (denominador honesto: executado ≠ verificado em TODAS as políticas!)
    total = 0
    verificadas = 0
    estimado = False
    cont: dict[str, int] = {}
    for m in mods:
        if m.get("etapas"):
            total += len(m["etapas"])
        elif m.get("etapas_estimadas"):
            total += int(m["etapas_estimadas"])
            estimado = True
        for e in m.get("etapas", []):
            s = e["_status"]
            cont[s] = cont.get(s, 0) + 1
            if s == "verificado":
                verificadas += 1
    resumo_obj = {
        "total": total,
        "verificadas": verificadas,
        "estimado": estimado,
        "contagem": cont,
    }

    # 7) Fila priorizada (com ordenação natural e distinção bloqueante vs secundária)
    fila_todos = []
    for m, e in iter_etapas(estado):
        s = e["_status"]
        if s not in ("executado", "revisado", "aguardando_decisao"):
            continue
        bloqueia_algo = bool(e["_bloqueia_agora"])
        eh_bloq_pol = (
            modo_pol == "por_etapa"
            or (modo_pol == "so_marcos" and (e["_eh_marco"] or bloqueia_algo))
        )
        sort_tuple = (
            0 if s != "aguardando_decisao" else 1,
            0 if bloqueia_algo else 1,
            0 if eh_bloq_pol else 1,
            0 if e["_eh_marco"] else 1,
            0 if (e["_exp"] == "expirada" or e["_reentregue"]) else 1,
            0 if s == "executado" else 1,
            IMPACTOS.get(e.get("impacto"), 3),
            0 if (m.get("resultado_final") or m["_na_rota"]) else 1,
            natural_key(e["id"]),
        )
        fila_todos.append((
            sort_tuple,
            {
                "id": e["id"],
                "modulo_id": m["id"],
                "modulo_titulo": m.get("titulo", m["id"]),
                "fase": m.get("fase") or "—",
                "titulo": e.get("titulo", e["id"]),
                "impacto": e.get("impacto", "medio"),
                "status": s,
                "exp": e["_exp"],
                "exp_motivos": e["_exp_motivos"],
                "arquivos_alterados": e["_arquivos_alterados"],
                "reentregue": e["_reentregue"],
                "revisao": e.get("revisao", "completa"),
                "eh_marco": e["_eh_marco"],
                "bloqueante": eh_bloq_pol,
                "libera": e["_libera"],
                "bloqueia_agora": e["_bloqueia_agora"],
                "evidencia_ausente": any(ev["estado"] == "ausente" for ev in e["_snapshot"]["evidencias"]),
            },
        ))

    fila_todos.sort(key=lambda pair: pair[0])
    fila_lista = [item for _, item in fila_todos]
    fila_principal = [x for x in fila_lista if x["bloqueante"]] if modo_pol == "so_marcos" else (
        [] if modo_pol == "acompanhamento_livre" else fila_lista
    )
    fila_opcional = [x for x in fila_lista if not x["bloqueante"]] if modo_pol != "por_etapa" else []

    # 8) Bloqueios globais do sistema — AGRUPADOS POR CAUSA RAIZ (evita explosão N×M na UI!)
    p = estado.get("projeto") or {}
    lim_fila = int(p.get("limite_fila") or 5)
    bloqueios_sistema: list[dict[str, Any]] = []
    if modo_pol != "acompanhamento_livre" and len(fila_principal) > lim_fila:
        bloqueios_sistema.append({
            "tipo": "limite_fila",
            "origem": "sistema",
            "gravidade": "alta",
            "titulo": f"Limite da fila excedido ({len(fila_principal)} > {lim_fila})",
            "detalhe": "Reduza a fila antes de abrir novas etapas de impacto alto.",
            "retidos": [],
        })
    for m in mods:
        if not m["_contrato_ok"]:
            bloqueios_sistema.append({
                "tipo": "contrato_violado",
                "origem": "sistema",
                "gravidade": "alta",
                "alvo_id": m["id"],
                "origem_id": m["id"],
                "titulo": f"Contrato travado alterado sem emenda em {m['id']}",
                "detalhe": f"Registre emenda explícita em {m['id']} antes de prosseguir.",
                "retidos": [m["id"]],
            })

    # Agrupar bloqueadores de marcos/etapas por origem_id (1 linha por causa raiz!)
    por_origem: dict[str, dict[str, Any]] = {}
    for m in mods:
        for b in m["_bloqueios_sistema"]:
            if b["tipo"] in ("marco_pendente", "etapa_pendente"):
                oid = b["origem_id"]
                if oid not in por_origem:
                    orig_et = etapa_index.get(oid, (None, None))[1]
                    orig_tit = orig_et["titulo"] if orig_et else oid
                    orig_st = orig_et["_status"] if orig_et else "pendente"
                    por_origem[oid] = {
                        "tipo": b["tipo"],
                        "origem": "sistema",
                        "gravidade": "alta",
                        "origem_id": oid,
                        "status_origem": orig_st,
                        "titulo": f"{oid} — {orig_tit}",
                        "retidos": [],
                    }
                if m["id"] not in por_origem[oid]["retidos"]:
                    por_origem[oid]["retidos"].append(m["id"])

    fila_ids = {x["id"] for x in fila_principal}
    for oid, item in por_origem.items():
        st_o = item["status_origem"]
        # Etapas futuras 'pendente' são sequência planejada; itens já na fila principal não precisam duplicar aqui
        if st_o == "pendente" or oid in fila_ids:
            continue
        estado_txt = (
            "em andamento" if st_o == "em_curso"
            else ("pausada/bloqueada" if st_o == "bloqueado"
                  else ("em espera" if st_o == "aguardando_decisao"
                        else ("ajuste solicitado" if st_o == "correcao_solicitada"
                              else "aguarda sua aprovação")))
        )
        nomes_ret = [by_mod[rid].get("titulo", rid) if rid in by_mod else rid for rid in item["retidos"][:2]]
        extra_n = len(item["retidos"]) - len(nomes_ret)
        ret_str = ", ".join(nomes_ret) + (f" (+{extra_n})" if extra_n > 0 else "")
        item["detalhe"] = f"{estado_txt} · segura: {ret_str}"
        bloqueios_sistema.append(item)

    # Etapas explicitamente bloqueadas (por agente ou humano)
    for m, e in iter_etapas(estado):
        if e["_status"] == "bloqueado" and e["id"] not in por_origem:
            motivo_b = (
                (e.get("_ultima_decisao") or {}).get("nota")
                if (e.get("_ultima_decisao") or {}).get("acao") == "bloquear"
                else e.get("bloqueio")
            ) or "Etapa bloqueada."
            bloqueios_sistema.append({
                "tipo": "bloqueio_etapa",
                "origem": "humano" if (e.get("_ultima_decisao") or {}).get("acao") == "bloquear" else "sistema",
                "gravidade": "alta",
                "origem_id": e["id"],
                "status_origem": "bloqueado",
                "titulo": f"{e['id']} — {e['titulo']}",
                "detalhe": motivo_b,
                "retidos": [x["id"] for x in e.get("_libera", [])[:4]],
            })

    for ph in p.get("pendencias_humanas") or []:
        bloqueios_sistema.append({
            "tipo": "pendencia_humana",
            "origem": "humano",
            "gravidade": "media",
            "alvo_id": ph.get("modulo") or "",
            "titulo": f"{ph.get('id', 'Pendência')}: {ph.get('texto', '')}",
            "detalhe": f"Bloqueia {ph['bloqueia']}" if ph.get("bloqueia") else "Decisão humana pendente.",
            "retidos": [ph["bloqueia"]] if ph.get("bloqueia") else [],
        })

    # 9) Situação Atual para a tela "Agora" (fase, marco, atividade agente, bloqueio sistema, ação humana)
    todas_ord = [(m, e) for m in ordem for e in (m.get("etapas") or [])]
    em_curso = next(((m, e) for m, e in todas_ord if e["_status"] == "em_curso"), None)
    correcao = next(((m, e) for m, e in todas_ord if e["_status"] == "correcao_solicitada"), None)
    override = next(((m, e) for m, e in todas_ord if e["id"] == p.get("voce_esta_aqui")), None)
    prox_pend = next(
        ((m, e) for m, e in todas_ord if e["_status"] == "pendente" and not e["_bloqueios_sistema"]),
        None,
    ) or next(((m, e) for m, e in todas_ord if e["_status"] == "pendente"), None)

    item_foco_fila = fila_principal[0] if fila_principal else (fila_lista[0] if fila_lista else None)
    mod_foco = None
    et_foco = None
    if item_foco_fila:
        mod_foco, et_foco = etapa_index[item_foco_fila["id"]]
    elif override:
        mod_foco, et_foco = override
    elif em_curso:
        mod_foco, et_foco = em_curso
    elif correcao:
        mod_foco, et_foco = correcao
    elif prox_pend:
        mod_foco, et_foco = prox_pend
    elif ordem:
        mod_foco = ordem[0]

    # Atividade do agente (SEMPRE separada e marcada como reportada pelo agente)
    ativ_decl = p.get("atividade_agente") or {}
    if ativ_decl.get("estado"):
        atividade_agente = {
            "origem": "reportado_pelo_agente",
            "estado": ativ_decl["estado"],
            "etapa_id": ativ_decl.get("etapa_id") or (em_curso[1]["id"] if em_curso else None),
            "resumo": ativ_decl.get("resumo") or "",
            "sessao_id": ativ_decl.get("sessao_id") or "",
            "atualizado_em": ativ_decl.get("atualizado_em") or p.get("atualizado_em") or "",
        }
    elif em_curso:
        atividade_agente = {
            "origem": "reportado_pelo_agente",
            "estado": "executando",
            "etapa_id": em_curso[1]["id"],
            "resumo": f"Executando {em_curso[1]['id']} — {em_curso[1]['titulo']}",
            "sessao_id": "",
            "atualizado_em": p.get("atualizado_em") or "",
        }
    elif correcao:
        atividade_agente = {
            "origem": "reportado_pelo_agente",
            "estado": "aguardando_correcao",
            "etapa_id": correcao[1]["id"],
            "resumo": f"Correção solicitada em {correcao[1]['id']} — aguardando retomada pelo agente.",
            "sessao_id": "",
            "atualizado_em": p.get("atualizado_em") or "",
        }
    elif fila_principal:
        atividade_agente = {
            "origem": "reportado_pelo_agente",
            "estado": "aguardando_humano",
            "etapa_id": fila_principal[0]["id"],
            "resumo": "Nenhuma etapa em curso declarada; há entregas aguardando sua revisão.",
            "sessao_id": "",
            "atualizado_em": p.get("atualizado_em") or "",
        }
    else:
        atividade_agente = {
            "origem": "reportado_pelo_agente",
            "estado": "sem_dados",
            "etapa_id": None,
            "resumo": "O agente não reportou execução ativa no momento.",
            "sessao_id": "",
            "atualizado_em": p.get("atualizado_em") or "",
        }

    # Próxima ação humana principal (linguagem clara e direta)
    if fila_principal:
        top = fila_principal[0]
        mods_lib = [x["titulo"] for x in top["bloqueia_agora"] if x.get("tipo") == "modulo"]
        if not mods_lib:
            mods_lib = [x["titulo"] for x in top["bloqueia_agora"]]
        lib_txt = ", ".join(mods_lib[:2]) + (f" (+{len(mods_lib) - 2})" if len(mods_lib) > 2 else "")
        proxima_acao = {
            "tipo": "revisar",
            "etapa_id": top["id"],
            "modulo_id": top["modulo_id"],
            "titulo": top["titulo"],
            "detalhe": (
                "Os arquivos mudaram depois da última aprovação — vale conferir novamente." if top["exp"]
                else (f"Aprovar esta entrega libera: {lib_txt}." if lib_txt
                      else "Entrega pronta para sua conferência.")
            ),
            "cta_label": "Revisar evidências",
            "fila_count": len(fila_principal),
            "fila_total_count": len(fila_lista),
        }
    elif p.get("pendencias_humanas"):
        ph0 = p["pendencias_humanas"][0]
        proxima_acao = {
            "tipo": "resolver_pendencia",
            "etapa_id": None,
            "modulo_id": ph0.get("modulo"),
            "titulo": f"Decidir pendência {ph0.get('id', '')}: {ph0.get('texto', '')}",
            "detalhe": f"Desbloqueia {ph0['bloqueia']}" if ph0.get("bloqueia") else "Decisão necessária para destravar o plano.",
            "cta_label": "Ver no Projeto",
            "fila_count": 0,
            "fila_total_count": len(fila_lista),
        }
    elif modo_pol == "acompanhamento_livre" and fila_lista:
        top = fila_lista[0]
        proxima_acao = {
            "tipo": "revisar_opcional",
            "etapa_id": top["id"],
            "modulo_id": top["modulo_id"],
            "titulo": f"Revisão opcional: {top['id']} — {top['titulo']}",
            "detalhe": "Política em acompanhamento livre: o agente avança sem bloqueio, mas você pode validar evidências quando quiser.",
            "cta_label": "Conferir evidência",
            "fila_count": 0,
            "fila_total_count": len(fila_lista),
        }
    elif em_curso:
        proxima_acao = {
            "tipo": "acompanhar",
            "etapa_id": em_curso[1]["id"],
            "modulo_id": em_curso[0]["id"],
            "titulo": "Nenhuma ação humana pendente agora",
            "detalhe": f"Agente reportou execução em {em_curso[1]['id']} ({em_curso[1]['titulo']}).",
            "cta_label": "Ver etapa no Projeto",
            "fila_count": 0,
            "fila_total_count": 0,
        }
    elif total > 0 and verificadas == total:
        proxima_acao = {
            "tipo": "concluido",
            "etapa_id": None,
            "modulo_id": mod_foco["id"] if mod_foco else None,
            "titulo": "Todas as etapas planejadas foram verificadas",
            "detalhe": "Fila vazia e 100% do denominador validado por você.",
            "cta_label": "Explorar Projeto",
            "fila_count": 0,
            "fila_total_count": 0,
        }
    else:
        proxima_acao = {
            "tipo": "sem_dados",
            "etapa_id": et_foco["id"] if et_foco else None,
            "modulo_id": mod_foco["id"] if mod_foco else None,
            "titulo": "Nenhuma entrega aguardando você",
            "detalhe": "Fila vazia e sem execução ativa registrada no estado atual.",
            "cta_label": "Abrir mapa do Projeto",
            "fila_count": 0,
            "fila_total_count": 0,
        }

    # Marco atual em destaque
    marco_atual = None
    if et_foco and et_foco["_eh_marco"]:
        marco_atual = {
            "id": et_foco["id"],
            "modulo_id": mod_foco["id"],
            "titulo": et_foco["titulo"],
            "status": et_foco["_status"],
            "contrato_travado": bool((mod_foco.get("contrato") or {}).get("hash")),
        }
    elif mod_foco:
        m_et = next((e for e in (mod_foco.get("etapas") or []) if e["_eh_marco"]), None)
        marco_atual = {
            "id": m_et["id"] if m_et else mod_foco["id"],
            "modulo_id": mod_foco["id"],
            "titulo": m_et["titulo"] if m_et else mod_foco.get("titulo", mod_foco["id"]),
            "status": m_et["_status"] if m_et else mod_foco["_status_mod"],
            "contrato_travado": bool((mod_foco.get("contrato") or {}).get("hash")),
        }

    situacao_atual = {
        "fase_atual": mod_foco.get("fase") if mod_foco else "—",
        "modulo_atual_id": mod_foco["id"] if mod_foco else None,
        "modulo_atual_titulo": mod_foco.get("titulo") if mod_foco else None,
        "etapa_foco_id": et_foco["id"] if et_foco else None,
        "marco_atual": marco_atual,
        "atividade_agente": atividade_agente,
        "bloqueios_sistema": bloqueios_sistema,
        "proxima_acao": proxima_acao,
    }

    # 10) Eventos relevantes e mudanças desde a última visita
    eventos: list[dict[str, Any]] = []
    for m in mods:
        for em in m.get("emendas") or []:
            eventos.append({
                "id": f"amend:{m['id']}:{em.get('hash_novo', '')}",
                "tipo": "emenda",
                "data": em.get("data", ""),
                "alvo_id": m["id"],
                "texto": f"Emenda no contrato de {m['id']}: {em.get('justificativa', '')}",
            })
        for e in m.get("etapas", []):
            fp = e["_snapshot"]["fingerprint_total"]
            if e["_exp"] == "expirada":
                det_m = ", ".join(e["_arquivos_alterados"]) if e["_arquivos_alterados"] else ", ".join(e["_exp_motivos"])
                eventos.append({
                    "id": f"exp:{e['id']}:{fp}",
                    "tipo": "expirada",
                    "data": e.get("data") or p.get("atualizado_em") or "",
                    "alvo_id": e["id"],
                    "texto": f"{e['id']} voltou à fila — verificação expirada ({det_m}).",
                })
            elif e["_status"] in ("executado", "revisado"):
                eventos.append({
                    "id": f"exec:{e['id']}:{fp}",
                    "tipo": "entrega",
                    "data": e.get("data") or p.get("atualizado_em") or "",
                    "alvo_id": e["id"],
                    "texto": f"{e['id']} ({e['titulo']}) marcada como executada pelo agente.",
                })
            elif e["_status"] == "correcao_solicitada":
                u = e["_ultima_decisao"] or {}
                eventos.append({
                    "id": f"corr:{e['id']}:{u.get('_seq', '')}",
                    "tipo": "correcao",
                    "data": u.get("data", ""),
                    "alvo_id": e["id"],
                    "texto": f"Correção solicitada em {e['id']}: {u.get('nota') or u.get('justificativa') or ''}",
                })
    for r in regs:
        if r.get("tipo") == "alterar_politica":
            eventos.append({
                "id": f"pol:{r.get('_seq', '')}:{r.get('modo', '')}",
                "tipo": "politica",
                "data": r.get("data", ""),
                "alvo_id": "",
                "texto": f"Política alterada para '{r.get('modo')}' por {r.get('revisor', 'humano')}: {r.get('justificativa', '')}",
            })
        else:
            eventos.append({
                "id": f"dec:{r.get('_seq', '')}:{r.get('etapa', '')}:{r.get('nivel', r.get('acao', ''))}",
                "tipo": "decisao",
                "data": r.get("data", ""),
                "alvo_id": r.get("etapa", ""),
                "texto": f"{r.get('etapa')} marcada como {r.get('nivel') or r.get('acao')} por {r.get('revisor', 'humano')}.",
            })

    mudancas: dict[str, Any]
    if visita and isinstance(visita.get("event_ids"), list):
        vistos_ids = set(visita["event_ids"])
        novos = [ev for ev in eventos if ev["id"] not in vistos_ids]
        mudancas = {
            "referencia_confiavel": True,
            "referencia_em": visita.get("registrada_em", ""),
            "novos": novos,
        }
    else:
        mudancas = {
            "referencia_confiavel": False,
            "referencia_em": "",
            "novos": [],
        }

    return {
        "versao_schema": 2,
        "modo_servidor": modo_servidor,
        "estado": estado,
        "politica": politica,
        "resumo": resumo_obj,
        "situacao_atual": situacao_atual,
        "fila": fila_principal,
        "fila_todos": fila_lista,
        "fila_opcional": fila_opcional,
        "relacoes_mapa": relacoes_mapa,
        "eventos": eventos,
        "mudancas": mudancas,
        "erros": erros,
        "avisos": avisos,
        "gerado_em": agora_str(com_segundos=True),
    }


def avaliar_gate(base: str | Path, etapa_id: str) -> dict[str, Any]:
    """Verifica deterministicamente se uma etapa está liberada ou bloqueada para um executor."""
    estado, regs, execs, visita = load_all(base)
    payload = construir_payload(base, estado, regs, execs, visita)
    alvo = None
    for m in payload["estado"].get("modulos", []):
        for e in m.get("etapas", []):
            if e["id"] == etapa_id:
                alvo = (m, e)
                break
    if not alvo:
        raise KeyError(f"Etapa {etapa_id} não existe.")
    m, e = alvo
    bloqueios = list(e.get("_bloqueios_sistema") or [])
    pol = payload["politica"]["modo"]
    lim = int((payload["estado"].get("projeto") or {}).get("limite_fila") or 5)
    if pol != "acompanhamento_livre" and e.get("impacto") == "alto" and len(payload["fila"]) > lim:
        bloqueios.append({
            "tipo": "limite_fila",
            "origem_id": "fila",
            "motivo": f"Fila com {len(payload['fila'])} itens (> limite {lim}) impede abrir etapa de impacto alto.",
        })
    return {
        "etapa": etapa_id,
        "modulo": m["id"],
        "politica": pol,
        "liberada": len(bloqueios) == 0,
        "bloqueios": bloqueios,
    }


def construir_contexto_limpo(base: str | Path, etapa_id: str) -> dict[str, Any]:
    """Monta o pacote mínimo versionado para retomar a etapa em sessão limpa ou outro agente."""
    estado, regs, execs, visita = load_all(base)
    payload = construir_payload(base, estado, regs, execs, visita)
    alvo = None
    for m in payload["estado"].get("modulos", []):
        for e in m.get("etapas", []):
            if e["id"] == etapa_id:
                alvo = (m, e)
                break
    if not alvo:
        raise KeyError(f"Etapa {etapa_id} não existe.")
    m, e = alvo
    arq = e.get("_agente") or {}
    dur = arq.get("contexto_duravel") or {}
    exe = arq.get("contexto_execucao") or {}

    # Último ponto confirmado por humano antes desta etapa (no módulo ou dependências)
    dep_mods = set(m.get("depende_de") or []) | {m["id"]}
    confirmados = []
    for m2 in payload["estado"].get("modulos", []):
        if m2["id"] not in dep_mods:
            continue
        for e2 in m2.get("etapas", []):
            if e2["id"] == etapa_id:
                continue
            if e2["_status"] == "verificado":
                u = e2.get("_ultima_decisao") or {}
                confirmados.append({
                    "etapa": e2["id"],
                    "titulo": e2["titulo"],
                    "data": u.get("data", ""),
                    "revisor": u.get("revisor", ""),
                    "fingerprint": u.get("fingerprint_total") or u.get("hash_etapa", ""),
                })

    ultimo_confirmado = dur.get("ultimo_ponto_confirmado") or (confirmados[-1] if confirmados else None)
    return {
        "projeto": (payload["estado"].get("projeto") or {}).get("nome"),
        "pergunta_central": (payload["estado"].get("projeto") or {}).get("pergunta_central"),
        "politica_aprovacao": payload["politica"]["modo"],
        "etapa": {
            "id": e["id"],
            "titulo": e["titulo"],
            "modulo": m["id"],
            "fase": m.get("fase"),
            "status_atual": e["_status"],
            "eh_marco": e["_eh_marco"],
            "descricao": e.get("descricao") or "",
        },
        "papel_agente": arq.get("papel") or "",
        "contrato_modulo": {
            "travado_em": (m.get("contrato") or {}).get("travado_em"),
            "hash": (m.get("contrato") or {}).get("hash"),
            "criterios_aceitacao": (m.get("contrato") or {}).get("criterios_aceitacao") or [],
            "criterio_abandono": (m.get("contrato") or {}).get("criterio_abandono") or "",
        },
        "contexto_duravel": {
            "objetivo": dur.get("objetivo") or m.get("objetivo") or "",
            "decisoes_aceitas": dur.get("decisoes_aceitas") or [],
            "protocolo": dur.get("protocolo") or {},
            "janela_analise": dur.get("janela_analise") or "",
            "artefatos_referencia": dur.get("artefatos_referencia") or [],
            "ultimo_ponto_confirmado": ultimo_confirmado,
        },
        "contexto_execucao": {
            "fontes_carregadas": exe.get("fontes_carregadas") or [],
            "fontes_omitidas": exe.get("fontes_omitidas") or [],
            "estrategia_retomada": exe.get("estrategia_retomada") or (
                "Carregar apenas protocolo versionado, artefatos de referência, contrato do módulo e último ponto confirmado."
            ),
        },
        "componentes_esperados": [
            {
                "nome": c["nome"],
                "tipo": c["tipo"],
                "mcp_server": c.get("mcp_server"),
                "versao_origem": c.get("versao_origem"),
                "configurado": c.get("configurado"),
                "observado": c["observado"]["estado"],
            }
            for c in (arq.get("componentes") or [])
        ],
        "guardrails_ativos": arq.get("guardrails") or [],
        "bloqueios_atuais": e.get("_bloqueios_sistema") or [],
        "ultima_correcao": (
            e["_ultima_decisao"]
            if (e.get("_ultima_decisao") or {}).get("acao") == "pedir_correcao"
            else None
        ),
    }


def registrar_decisao_humana(
    base: str | Path,
    *,
    etapa_id: str,
    acao: str,
    revisor: str,
    nota: str,
    canal: str,
    observed_fingerprint: str | None = None,
    permitir_evidencia_ausente: bool = False,
) -> dict[str, Any]:
    """Grava decisão humana com checagem estrita de bytes (SHA-256) e proteção TOCTOU."""
    acoes_validas = ("verificado", "revisado", "pedir_correcao", "aguardar_decisao", "bloquear", "desbloquear")
    if acao not in acoes_validas:
        raise ValueError(f"Ação inválida: {acao}")
    revisor = (revisor or "").strip()
    nota = (nota or "").strip()
    if not revisor:
        raise ValueError("Nome ou iniciais do revisor são obrigatórios.")
    if acao == "pedir_correcao" and not nota:
        raise ValueError("Justificativa é obrigatória ao pedir correção.")
    if acao == "bloquear" and not nota:
        raise ValueError("Informe o motivo ao bloquear a etapa.")

    estado, regs, _, _ = load_all(base)
    alvo = next(((m, e) for m, e in iter_etapas(estado) if e["id"] == etapa_id), None)
    if not alvo:
        raise KeyError(f"Etapa {etapa_id} não existe.")
    mod, et = alvo

    # Recalcular snapshot ESTRITO direto do disco (sem cache!)
    snap = snapshot_etapa(base, mod, et, strict=True)

    # Proteção TOCTOU: ao aprovar ou revisar, se algo mudou entre abertura e gravação -> conflito!
    if acao in ("verificado", "revisado") and observed_fingerprint and observed_fingerprint != snap["fingerprint_total"]:
        raise RuntimeError(
            "CONFLITO_TOCTOU: a etapa ou o conteúdo de um arquivo de evidência mudou "
            "desde que você abriu a revisão. Recarregue e confira novamente."
        )

    # Em aprovação, impedir aprovar silenciosamente evidência obrigatória ausente
    if acao == "verificado" and not permitir_evidencia_ausente:
        ausentes = [ev["ref"] for ev in snap["evidencias"] if ev["estado"] == "ausente" and ev.get("obrigatoria", True)]
        if ausentes:
            raise ValueError(
                f"Evidência local ausente no disco ({', '.join(ausentes)}). "
                "Peça correção ou corrija o arquivo antes de aprovar."
            )

    nivel_map = {
        "verificado": "verificado",
        "revisado": "revisado",
        "pedir_correcao": "correcao_solicitada",
        "aguardar_decisao": "aguardando_decisao",
        "bloquear": "bloqueado",
        "desbloquear": "desbloqueado",
    }
    nivel = nivel_map[acao]
    registro = {
        "schema_hash_v": 2,
        "tipo": "decisao",
        "etapa": et["id"],
        "acao": acao,
        "nivel": nivel,
        "ator": "humano",
        "canal": canal,
        "revisor": revisor,
        "nota": nota,
        "data": agora_str(com_segundos=True),
        "hash_etapa": snap["hash_etapa_v1"],
        "etapa_meta_hash": snap["etapa_meta_hash"],
        "criterio_hash": snap["criterio_hash"],
        "fingerprint_total": snap["fingerprint_total"],
        "evidencias": [
            {
                "ref": ev["ref"],
                "tipo": ev["tipo"],
                "estado": ev["estado"],
                "sha256": ev.get("sha256"),
                "bytes": ev.get("bytes"),
                "versao": ev.get("versao"),
            }
            for ev in snap["evidencias"]
        ],
    }
    ps = paths(base)
    return append_jsonl(ps["verificacoes"], registro)


def travar_contrato_modulo(base: str | Path, modulo_id: str) -> dict[str, Any]:
    """Trava o contrato de um módulo (pré-registro) diretamente pelo painel ou CLI."""
    estado, _, _, _ = load_all(base)
    mod = next((m for m in estado.get("modulos", []) if m["id"] == modulo_id), None)
    if not mod:
        raise KeyError(f"Módulo {modulo_id} não existe.")
    c = mod.setdefault("contrato", {})
    if c.get("hash"):
        raise ValueError(f"Contrato de {modulo_id} já está travado.")
    faltam = [k for k in ("pergunta", "criterios_aceitacao", "criterio_abandono") if not c.get(k)]
    if faltam:
        raise ValueError(f"Contrato incompleto em {modulo_id}, falta: {', '.join(faltam)}")
    c["travado_em"] = agora_str()
    c["hash"] = hash_contrato(mod)
    save_estado(base, estado)
    return {"modulo": modulo_id, "travado_em": c["travado_em"], "hash": c["hash"]}


def registrar_alteracao_politica(
    base: str | Path,
    *,
    novo_modo: str,
    revisor: str,
    justificativa: str,
    canal: str,
    canal_padrao: str | None = None,
) -> dict[str, Any]:
    if novo_modo not in POLITICAS:
        raise ValueError(f"Política inválida: {novo_modo}. Use: {', '.join(sorted(POLITICAS))}")
    if canal_padrao and canal_padrao not in CANAIS_REGISTRO:
        raise ValueError(f"Canal inválido: {canal_padrao}.")
    revisor = (revisor or "").strip()
    justificativa = (justificativa or "").strip()
    if not revisor or not justificativa:
        raise ValueError("Revisor e justificativa são obrigatórios para alterar a política.")

    estado, regs, _, _ = load_all(base)
    pol_atual = politica_efetiva(estado, regs)
    reg = {
        "schema_hash_v": 2,
        "tipo": "alterar_politica",
        "ator": "humano",
        "canal": canal,
        "revisor": revisor,
        "justificativa": justificativa,
        "modo_anterior": pol_atual["modo"],
        "modo": novo_modo,
        "canal_padrao": canal_padrao or pol_atual["canal_padrao"],
        "data": agora_str(com_segundos=True),
    }
    ps = paths(base)
    return append_jsonl(ps["verificacoes"], reg)
