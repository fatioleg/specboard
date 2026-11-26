# Relatório de Estabilidade Estrutural — Carbon Dots (400 K)

## Resumo da entrega (Marco M2.3)

- **Protocolo:** `protocolo-md-cd` v2.1 (janela equilibrada `5–10 ns`)
- **RMSD médio do núcleo grafítico (5–10 ns):** `0.425 Å` (máximo `0.440 Å`, critério pré-registrado `<= 0.80 Å`)
- **RMSD da borda funcionalizada (5–10 ns):** `1.155 Å` (oscilação esperada sem reconstrução)
- **Integridade de anéis aromáticos:** `100%` preservada em todos os quadros da janela

## Checagens determinísticas executadas (`scripts/calc_rmsd.py`)

- **Unidades:** confirmado `Å` em todas as entradas (sem mistura com `nm`).
- **Seleção de átomos:** máscara de núcleo validada contra `data/core_ref.xyz`.
- **Integridade de entradas:** arquivos conferidos por SHA-256 antes do cálculo.

## Decisão aguardada

Aprovar este marco libera a **Fase 3 (`M3` — Simulação em 450 K)**. O ramo paralelo `M2-B` (espectroscopia vibracional a 300 K) é independente e não está bloqueado por este marco.
