#!/usr/bin/env python3
"""Script local determinístico de exemplo para checagem de RMSD em carbon dots.

Checagens impostas por código (guardrails):
  1. Unidades explícitas em Angstrom (rejeita colunas em nm sem conversão)
  2. Integridade da estrutura de referência (XYZ válido)
  3. Validação da janela de análise (5–10 ns) contra limiar pré-registrado (0.80 Å)
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path


def validar_xyz(path: Path) -> int:
    linhas = [ln.strip() for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    n_atoms = int(linhas[0])
    coords = linhas[2:]
    if len(coords) != n_atoms:
        raise ValueError(f"Máscara/XYZ inconsistente: esperado {n_atoms} átomos, encontrado {len(coords)}.")
    return n_atoms


def analisar_rmsd(csv_path: Path, janela_inicio: float = 5.0, limite_angstrom: float = 0.80) -> dict:
    with csv_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if "rmsd_core_angstrom" not in (reader.fieldnames or []):
            raise ValueError("Coluna 'rmsd_core_angstrom' ausente — verifique unidades (Å vs nm).")
        vals = []
        for row in reader:
            t = float(row["time_ns"])
            if t >= janela_inicio:
                vals.append(float(row["rmsd_core_angstrom"]))
    if not vals:
        raise ValueError("Janela de análise vazia.")
    media = sum(vals) / len(vals)
    maximo = max(vals)
    return {
        "n_pontos": len(vals),
        "media_angstrom": round(media, 4),
        "maximo_angstrom": round(maximo, 4),
        "aprovado_limiar": maximo <= limite_angstrom,
    }


if __name__ == "__main__":
    base = Path(__file__).resolve().parent.parent
    n = validar_xyz(base / "data" / "core_ref.xyz")
    res = analisar_rmsd(base / "data" / "rmsd_cd_400k.csv")
    print(f"OK | átomos núcleo={n} | janela 5-10 ns: média={res['media_angstrom']} Å, máx={res['maximo_angstrom']} Å | critério={res['aprovado_limiar']}")
    sys.exit(0 if res["aprovado_limiar"] else 1)
