#!/usr/bin/env python3
"""specboard — estado de projeto Spec-Driven Modular + painel de validação (v2).

Uso (rodar na raiz do projeto; Python 3 stdlib puro, funciona em PowerShell e Linux):
  python specboard.py init [--politica so_marcos|por_etapa|acompanhamento_livre]
  python specboard.py validate                 checa regras, contratos e evidências
  python specboard.py lock <MOD>               trava o contrato do módulo (pré-registro)
  python specboard.py amend <MOD> -j "..."     registra emenda em contrato travado
  python specboard.py queue                    fila priorizada de revisão
  python specboard.py build [--open]           gera .specboard/painel.html (snapshot offline)
  python specboard.py serve [--port 8765] [--open]  abre painel interativo com gravação local/SSH
  python specboard.py gate <ETAPA>             verifica se a etapa está liberada pela política
  python specboard.py context <ETAPA> [--json] monta contexto versionado para sessão limpa
  python specboard.py trace-tool <ETAPA> ...   registra uso observado de skill/tool/MCP (OTel)
  python specboard.py review <ETAPA>           HUMANO (terminal): marca como revisado
  python specboard.py verify <ETAPA>           HUMANO (terminal): marca como verificado
  python specboard.py request-changes <ETAPA>  HUMANO (terminal): pede correção com justificativa
  python specboard.py policy <MODO> -j "..."   HUMANO (terminal): altera política rastreavelmente
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import webbrowser
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import sb_core as core
import sb_server as srv

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

SKILL_DIR = SCRIPTS_DIR.parent
TEMPLATE = SKILL_DIR / "assets" / "painel_template.html"
EXEMPLO = SKILL_DIR / "assets" / "estado_exemplo.json"

# Re-exports compatíveis com v1
STATUS_AGENTE = core.STATUS_AGENTE
IMPACTOS = core.IMPACTOS
h = core.h
hash_contrato = core.hash_contrato
hash_etapa = core.hash_etapa_v1
etapas = core.iter_etapas


def paths(base):
    ps = core.paths(base)
    return ps["dir"], ps["estado"], ps["verificacoes"], ps["painel"]


def load(base):
    try:
        estado, regs, _, _ = core.load_all(base)
        return estado, regs
    except FileNotFoundError as exc:
        sys.exit(str(exc))


def save(base, estado):
    core.save_estado(base, estado)


def status_efetivo(et, regs, base=None, mod=None):
    return core.status_efetivo(et, regs, base=base, mod=mod)


def validar(estado, regs, base="."):
    return core.validar(base, estado, regs)


def resumo(estado, regs, base="."):
    payload = core.construir_payload(base, estado, regs)
    return payload["resumo"]


def fila(estado, regs, base="."):
    payload = core.construir_payload(base, estado, regs)
    return payload["fila"]


def _exigir_humano_interativo(permitir_nao_tty: bool = False) -> None:
    if os.environ.get("CLAUDECODE"):
        sys.exit("Recusado: este comando é exclusivo para uso humano fora de sessão de agente.")
    if not permitir_nao_tty and not sys.stdin.isatty():
        sys.exit("Recusado: este comando só roda em terminal interativo humano.")


def cmd_init(a) -> None:
    ps = core.paths(a.dir)
    if ps["estado"].exists():
        sys.exit(f"{ps['estado']} já existe.")
    ps["dir"].mkdir(parents=True, exist_ok=True)
    estado = json.loads(EXEMPLO.read_text(encoding="utf-8"))
    if a.politica:
        estado.setdefault("projeto", {})["politica_aprovacao"] = {
            "modo": a.politica,
            "canal_padrao": a.canal or "painel",
            "definida_em": core.agora_str(),
            "definida_por": "criação do projeto",
        }
    core.atomic_write_text(ps["estado"], json.dumps(estado, ensure_ascii=False, indent=2) + "\n")
    # Garante .gitignore local para artefatos descartáveis de sessão (.hash_cache.json, visita.json)
    gi = ps["dir"] / ".gitignore"
    if not gi.exists():
        gi.write_text(".hash_cache.json\nvisita.json\n", encoding="utf-8")
    pol_modo = (estado.get("projeto") or {}).get("politica_aprovacao", {}).get("modo", "so_marcos")
    print(f"Criado {ps['estado']} (política: {pol_modo}). Edite a partir do plano do projeto.")


def cmd_validate(a) -> None:
    try:
        estado, regs, _, _ = core.load_all(a.dir)
    except FileNotFoundError as exc:
        sys.exit(str(exc))
    erros, avisos = core.validar(a.dir, estado, regs)
    for x in avisos:
        print("AVISO:", x)
    for x in erros:
        print("ERRO: ", x)
    if erros:
        sys.exit(1)
    print("OK — estado válido.")


def achar_mod(estado, mid):
    for m in estado.get("modulos", []):
        if m["id"] == mid:
            return m
    sys.exit(f"Módulo {mid} não existe.")


def cmd_lock(a) -> None:
    estado, _ = load(a.dir)
    m = achar_mod(estado, a.modulo)
    c = m.setdefault("contrato", {})
    if c.get("hash"):
        sys.exit("Contrato já travado. Mudanças agora exigem 'amend'.")
    faltam = [k for k in ("pergunta", "criterios_aceitacao", "criterio_abandono") if not c.get(k)]
    if faltam:
        sys.exit(f"Contrato incompleto, falta: {', '.join(faltam)}")
    c["travado_em"] = core.agora_str()
    c["hash"] = core.hash_contrato(m)
    core.save_estado(a.dir, estado)
    print(f"{m['id']} travado (hash {c['hash']}).")


def cmd_amend(a) -> None:
    estado, _ = load(a.dir)
    m = achar_mod(estado, a.modulo)
    c = m.get("contrato") or {}
    if not c.get("hash"):
        sys.exit("Contrato não está travado; edite livremente.")
    novo = core.hash_contrato(m)
    if novo == c["hash"]:
        sys.exit("Nada mudou no contrato.")
    m.setdefault("emendas", []).append({
        "data": core.agora_str(),
        "hash_anterior": c["hash"],
        "hash_novo": novo,
        "justificativa": a.justificativa,
    })
    c["hash"] = novo
    core.save_estado(a.dir, estado)
    print(f"Emenda registrada em {m['id']}. Ela aparece em destaque no painel.")


def cmd_queue(a) -> None:
    try:
        estado, regs, execs, visita = core.load_all(a.dir)
    except FileNotFoundError as exc:
        sys.exit(str(exc))
    payload = core.construir_payload(a.dir, estado, regs, execs, visita)
    itens = payload["fila_todos"] if a.todas else payload["fila"]
    pol = payload["politica"]["modo"]
    print(f"Política ativa: {pol}")
    if not itens:
        if payload["fila_opcional"]:
            print(f"Fila bloqueante vazia ({len(payload['fila_opcional'])} entrega(s) opcional(is); use --todas para listar).")
        else:
            print("Fila vazia.")
        return
    for item in itens:
        tags = []
        if item["eh_marco"]:
            tags.append("MARCO")
        if item["exp"]:
            motivo = ", ".join(item["arquivos_alterados"] or item["exp_motivos"])
            tags.append(f"EXPIRADA: {motivo}" if motivo else "EXPIRADA")
        if item["reentregue"]:
            tags.append("REENTREGUE")
        if item["bloqueia_agora"]:
            tags.append("libera " + ",".join(x["id"] for x in item["bloqueia_agora"][:3]))
        extra = f" [{' | '.join(tags)}]" if tags else ""
        print(f"{item['id']:<10} {item['impacto']:<6} {item['status']:<10} {item['revisao']:<10} {item['titulo']}{extra}")


def cmd_humano(a, acao: str) -> None:
    _exigir_humano_interativo()
    try:
        estado, regs, _, _ = core.load_all(a.dir)
    except FileNotFoundError as exc:
        sys.exit(str(exc))
    alvo_pair = next(((m, e) for m, e in core.iter_etapas(estado) if e["id"] == a.etapa), None)
    if not alvo_pair:
        sys.exit(f"Etapa {a.etapa} não existe.")
    mod, alvo = alvo_pair
    snap = core.snapshot_etapa(a.dir, mod, alvo, strict=True)

    print(f"\n{alvo['id']} — {alvo['titulo']}")
    print(f"  Afirmação:   {alvo.get('afirmacao')}")
    print(f"  Verificação: {alvo.get('verificacao')}")
    if snap["evidencias"]:
        print("  Evidências:")
        for ev in snap["evidencias"]:
            sha_short = (ev.get("sha256") or "")[:12]
            print(f"    - {ev['ref']} [{ev['estado']}{(' · sha256:' + sha_short) if sha_short else ''}]")
    else:
        print("  Evidências:  (nenhuma)")
    print()

    if acao == "verificado":
        print("Verificado = você conferiu a evidência, não só leu o resumo.")
    elif acao == "pedir_correcao":
        print("Pedir correção = devolve a etapa ao agente com justificativa obrigatória.")

    if input(f"Digite o ID da etapa para confirmar '{acao}': ").strip() != alvo["id"]:
        sys.exit("Cancelado.")
    revisor = input("Seu nome/iniciais: ").strip()
    prompt_nota = "Justificativa da correção (obrigatória): " if acao == "pedir_correcao" else (
        "Nota (o que você conferiu): " if acao == "verificado" else "Nota (opcional): "
    )
    nota = input(prompt_nota).strip()
    if not revisor or (acao in ("verificado", "pedir_correcao") and not nota):
        sys.exit("Cancelado: revisor e nota/justificativa são obrigatórios no terminal.")

    try:
        core.registrar_decisao_humana(
            a.dir,
            etapa_id=alvo["id"],
            acao=acao,
            revisor=revisor,
            nota=nota,
            canal="terminal",
            observed_fingerprint=snap["fingerprint_total"],
        )
    except Exception as exc:
        sys.exit(f"Erro ao gravar decisão: {exc}")
    print(f"Registrado: {alvo['id']} ({acao}).")
    if a.build:
        cmd_build(argparse.Namespace(dir=a.dir, open=False))


def cmd_policy(a) -> None:
    _exigir_humano_interativo()
    revisor = input("Seu nome/iniciais para registrar mudança de política: ").strip()
    if not revisor:
        sys.exit("Cancelado: revisor é obrigatório.")
    try:
        reg = core.registrar_alteracao_politica(
            a.dir,
            novo_modo=a.modo,
            revisor=revisor,
            justificativa=a.justificativa,
            canal="terminal",
            canal_padrao=a.canal,
        )
    except Exception as exc:
        sys.exit(str(exc))
    print(f"Política alterada: {reg['modo_anterior']} -> {reg['modo']} (registrada em verificacoes.jsonl).")


def cmd_gate(a) -> None:
    try:
        res = core.avaliar_gate(a.dir, a.etapa)
    except (FileNotFoundError, KeyError) as exc:
        sys.exit(str(exc))
    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        if res["liberada"]:
            print(f"LIBERADA: {res['etapa']} (política: {res['politica']})")
        else:
            print(f"BLOQUEADA: {res['etapa']} (política: {res['politica']})")
            for b in res["bloqueios"]:
                print(f"  - [{b['tipo']}] {b['motivo']}")
    if not res["liberada"]:
        sys.exit(2)


def cmd_context(a) -> None:
    try:
        ctx = core.construir_contexto_limpo(a.dir, a.etapa)
    except (FileNotFoundError, KeyError) as exc:
        sys.exit(str(exc))
    if a.json:
        print(json.dumps(ctx, ensure_ascii=False, indent=2))
        return
    et = ctx["etapa"]
    dur = ctx["contexto_duravel"]
    print(f"=== Contexto mínimo para retomada limpa: {et['id']} ({et['titulo']}) ===")
    print(f"Projeto: {ctx['projeto']} | Fase: {et['fase']} | Política: {ctx['politica_aprovacao']}")
    if ctx["papel_agente"]:
        print(f"Papel do agente: {ctx['papel_agente']}")
    print(f"Objetivo: {dur['objetivo']}")
    if dur["protocolo"]:
        print(f"Protocolo: {json.dumps(dur['protocolo'], ensure_ascii=False)}")
    if dur["janela_analise"]:
        print(f"Janela de análise: {dur['janela_analise']}")
    if dur["decisoes_aceitas"]:
        print("Decisões aceitas:", "; ".join(str(d) for d in dur["decisoes_aceitas"]))
    if dur["ultimo_ponto_confirmado"]:
        print("Último ponto confirmado:", json.dumps(dur["ultimo_ponto_confirmado"], ensure_ascii=False))
    if dur["artefatos_referencia"]:
        print("Artefatos de referência:")
        for ref in dur["artefatos_referencia"]:
            sha = (ref.get("sha256_atual") or "")[:12]
            print(f"  - {ref.get('caminho') or ref.get('nome')} [{ref.get('estado_arquivo', '?')}{(' sha256:' + sha) if sha else ''}]")
    if ctx["componentes_esperados"]:
        print("Componentes:")
        for c in ctx["componentes_esperados"]:
            mcp = f" (MCP:{c['mcp_server']})" if c.get("mcp_server") else ""
            print(f"  - {c['nome']} [{c['tipo']}{mcp}] conf={c['configurado']} obs={c['observado']}")
    if ctx["guardrails_ativos"]:
        print("Guardrails:")
        for g in ctx["guardrails_ativos"]:
            print(f"  - [{g['natureza'].upper()}] {g['regra']} -> {g['se_falhar']}")
    if ctx["bloqueios_atuais"]:
        print("Bloqueios ativos:")
        for b in ctx["bloqueios_atuais"]:
            print(f"  - [{b['tipo']}] {b['motivo']}")


def cmd_trace_tool(a) -> None:
    ps = core.paths(a.dir)
    if not ps["estado"].exists():
        sys.exit(f"Não encontrei {ps['estado']}.")
    rec = {
        "etapa": a.etapa,
        "tool_name": a.tool,
        "gen_ai.tool.name": a.tool,
        "tool_type": a.type,
        "gen_ai.tool.type": "function" if a.type == "local_tool" else ("extension" if a.type == "mcp_tool" else "skill"),
        "mcp_server": a.mcp_server,
        "versao_origem": a.versao or "",
        "status": a.status,
        "duracao_ms": a.duracao_ms,
        "sessao_id": a.sessao or "",
        "observado_por": a.observado_por,
        "timestamp": core.agora_str(com_segundos=True),
    }
    core.append_jsonl(ps["execucoes"], rec)
    print(f"Telemetria registrada em {ps['execucoes']}: {a.etapa} -> {a.tool} ({a.type}, {a.status}).")


def cmd_build(a) -> None:
    try:
        estado, regs, execs, visita = core.load_all(a.dir)
    except FileNotFoundError as exc:
        sys.exit(str(exc))
    payload = core.construir_payload(a.dir, estado, regs, execs, visita, modo_servidor=False)
    html = TEMPLATE.read_text(encoding="utf-8").replace(
        "/*__DADOS__*/null",
        json.dumps(payload, ensure_ascii=False).replace("</", "<\\/"),
    )
    ps = core.paths(a.dir)
    core.atomic_write_text(ps["painel"], html)
    erros = payload["erros"]
    print(f"Painel gerado: {ps['painel']}" + (f"  ({len(erros)} erro(s) exibidos no topo)" if erros else ""))
    if a.open:
        webbrowser.open(ps["painel"].resolve().as_uri())


def cmd_serve(a) -> None:
    if not a.readonly and os.environ.get("CLAUDECODE"):
        sys.exit("Recusado: 'serve' com escrita só deve ser iniciado pelo humano. Use --readonly para inspeção.")
    ps = core.paths(a.dir)
    if not ps["estado"].exists():
        sys.exit(f"Não encontrei {ps['estado']}. Rode: python specboard.py init")
    server = srv.create_server(
        a.dir,
        TEMPLATE,
        host=a.host,
        port=a.port,
        readonly=a.readonly,
    )
    host, port = server.server_address[:2]
    url = f"http://{host}:{port}/"
    modo_txt = "SOMENTE LEITURA" if a.readonly else "INTERATIVO (gravação persistente ativa)"
    print(f"SpecBoard ativo em {url} [{modo_txt}]")
    print(f"Projeto: {ps['root']}")
    print("Para acesso remoto via SSH: ssh -L {p}:127.0.0.1:{p} usuario@servidor".format(p=port))
    print("Pressione Ctrl+C para encerrar.")
    if a.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServidor encerrado.")
    finally:
        server.server_close()


def main() -> None:
    p = argparse.ArgumentParser(description="specboard — painel de validação e arquitetura de projetos com agentes")
    p.add_argument("--dir", default=".", help="raiz do projeto")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_init = sub.add_parser("init")
    p_init.add_argument("--politica", choices=sorted(core.POLITICAS), default="so_marcos")
    p_init.add_argument("--canal", choices=sorted(core.CANAIS_REGISTRO), default="painel")

    sub.add_parser("validate")

    p_q = sub.add_parser("queue")
    p_q.add_argument("--todas", action="store_true", help="inclui etapas não bloqueantes/opcionais")

    p_b = sub.add_parser("build")
    p_b.add_argument("--open", action="store_true")

    p_s = sub.add_parser("serve")
    p_s.add_argument("--host", default="127.0.0.1")
    p_s.add_argument("--port", type=int, default=8765)
    p_s.add_argument("--open", action="store_true")
    p_s.add_argument("--readonly", action="store_true")

    sub.add_parser("lock").add_argument("modulo")

    p_am = sub.add_parser("amend")
    p_am.add_argument("modulo")
    p_am.add_argument("-j", "--justificativa", required=True)

    for n in ("review", "verify", "request-changes"):
        sp = sub.add_parser(n)
        sp.add_argument("etapa")
        sp.add_argument("--build", action="store_true", help="regenera painel.html após gravar")

    p_pol = sub.add_parser("policy")
    p_pol.add_argument("modo", choices=sorted(core.POLITICAS))
    p_pol.add_argument("-j", "--justificativa", required=True)
    p_pol.add_argument("--canal", choices=sorted(core.CANAIS_REGISTRO), default=None)

    p_gate = sub.add_parser("gate")
    p_gate.add_argument("etapa")
    p_gate.add_argument("--json", action="store_true")

    p_ctx = sub.add_parser("context")
    p_ctx.add_argument("etapa")
    p_ctx.add_argument("--json", action="store_true")

    p_tr = sub.add_parser("trace-tool")
    p_tr.add_argument("etapa")
    p_tr.add_argument("--tool", required=True, help="nome da skill, script ou ferramenta MCP")
    p_tr.add_argument("--type", choices=sorted(core.TIPOS_COMPONENTE), default="local_tool")
    p_tr.add_argument("--mcp-server", default=None)
    p_tr.add_argument("--versao", default="")
    p_tr.add_argument("--status", choices=("ok", "erro"), default="ok")
    p_tr.add_argument("--duracao-ms", type=int, default=0)
    p_tr.add_argument("--sessao", default="")
    p_tr.add_argument("--observado-por", default="wrapper")

    a = p.parse_args()
    handlers = {
        "init": cmd_init,
        "validate": cmd_validate,
        "lock": cmd_lock,
        "amend": cmd_amend,
        "queue": cmd_queue,
        "build": cmd_build,
        "serve": cmd_serve,
        "gate": cmd_gate,
        "context": cmd_context,
        "trace-tool": cmd_trace_tool,
        "policy": cmd_policy,
        "review": lambda args: cmd_humano(args, "revisado"),
        "verify": lambda args: cmd_humano(args, "verificado"),
        "request-changes": lambda args: cmd_humano(args, "pedir_correcao"),
    }
    handlers[a.cmd](a)


if __name__ == "__main__":
    main()
