---
title: "Historicky replay peaku vyzaduje DB autoritu"
date: 2026-09-22
category: architecture
component: ai-log-analyzer
tags: [peak-detection, historical-replay, postgresql, baseline, fail-closed]
file_type: rules
---

# Historicky replay peaku vyzaduje DB autoritu

## Kontext

Read-only historical replay muze z Elasticsearchu potvrdit uplnost vstupu, ale sam o sobe nemuze potvrdit rozhodnuti peak detectoru. Pri realnych windows mel ES `expected == fetched`, zatimco lokalni PostgreSQL pristup selhal na LDAP autentizaci a `pg_hba.conf` pravidle.

## Pravidlo

1. Historicky replay musi pouzit stejne 15min UTC okno jako authoritative fact tables. Vyžaduje `--dry-run`, timezone-aware konec zarovnany na 15 minut a `window_minutes=15`.
2. Raw ES count je pouze vstupni evidence. Peak verdict vyzaduje kompatibilni Pxx/CAP snapshot a zero-inclusive `(namespace, fingerprint)` baseline z DB.
3. Kdyz nelze inicializovat `PeakDetector` z DB, regular phase i backfill musi skoncit chybou pred spustenim pipeline. EWMA ani jiny legacy fallback nesmi vydat spike verdict.
4. Kdyz selze pouze nacitani namespace/fingerprint baseline, volume gate muze bezet, ale family ownership se musi fail-closed potlacit. Neprirazovat namespace peak rutinni nebo neoverene family.
5. Chyba DB autorizace znamena, ze vysledek replay je neznamy. Nesmi se vydavat za negativni detekci ani za realny prod/nprod algoritmicky vysledek.

## Kontrolni postup

1. Spustit replay pres skutecny `regular_phase` entrypoint v autorizovanem runtime/Kubernetes prostredi.
2. Overit complete fetch (`expected == fetched`) a DB-backed threshold snapshot i baseline loading.
3. Teprve potom reportovat detector decision a jeho threshold evidence.
4. Pred image buildem spustit plnou test suite. Pokud chybi verejne API registry (`update_and_save` nebo `merge_enrichment_and_save`), jde o samostatny release blocker; neobchazet ho dry-run replayem.