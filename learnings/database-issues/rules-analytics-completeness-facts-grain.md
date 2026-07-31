---
title: "Analytické trendy: úplnost, fakta a shodný grain"
date: 2026-07-31
category: database-issues
component: ai-log-analyzer
tags: [database, analytics, trends, idempotency, backfill, grafana]
file_type: rules
---

# Důvěryhodné trendy vyžadují ledger úplnosti a oddělená fakta

## Kontext

Review AI Log Analyzeru odhalilo, že existence jediného incidentního řádku byla používána jako důkaz dokončeného backfillu a že historický baseline četl hodnoty z anomaly tabulky. Současně se namespace-total P93 porovnávalo s per-fingerprint počtem.

## Zjištění

- `COUNT(*) > 0` není důkaz úplnosti dávky. Částečný zápis se pak může tvářit jako dokončený a další replay jej přeskočí.
- Tabulka detekovaných incidentů nebo anomálií není fact table. Obsahuje výběrová a odvozená data, takže z ní nelze korektně rekonstruovat nuly, chybějící okna ani běžný provoz.
- Threshold musí být trénován a vyhodnocován na stejné veličině, dimenzích a časovém grainu. Namespace-total baseline nelze porovnávat s per-fingerprint hodnotou.
- Nula je platné pozorování jen pro prokazatelně kompletní okno. Chybějící nebo neúplný běh musí zůstat mezerou.
- Historická analýza musí mít as-of cutoff; jinak backfill načte budoucí data a vznikne time leakage.

## Pravidlo pro příště

1. Zapisuj každý pokus do run ledgeru s `expected`, `fetched`, `processed` a `persisted` počty.
2. Označ run jako `complete` pouze ve stejné transakci, která commitne deterministické fact rows.
3. Stavěj trendy z husté 15min fact table a anomaly/detection rows drž odděleně.
4. Při návrhu detectoru napiš kontrakt `grain + dimensions + observed quantity` pro training i evaluation a automaticky ověř jejich shodu.
5. Reporty, registry a notifikace spouštěj až nad kompletním autoritativním runem.