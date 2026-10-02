---
title: "Alerting: oddělit volume gate, příčinu a business dopad"
date: 2026-08-25
category: architecture
component: ai-log-analyzer
tags: [alerting, elasticsearch, trace-analysis, thresholds, reporting]
file_type: rules
---

# Alerting: oddělit volume gate, příčinu a business dopad

## Kontext

Produkční 15min digest seskupoval ERROR logy podle obecných exception classes a stejný počet opakoval jako Errors, Root cause a Behavior. Forenzní analýza okna 25. 8. 2026 ukázala `393` ERROR řádků, ale jen `100` unikátních traced operations. Dominantní konkrétní family vytvořila `200` řádků z `40` operací.

## Co nefunguje

- `ServiceBusinessException` ani jiná wrapper class není stabilní identita problému. Jedna class zahrnovala několik nezávislých business příčin.
- Raw ERROR lines nejsou business impact. Jedna operace vytvářela 5 až 11 řádků napříč root a downstream službami.
- Signal-first výběr zprávy může označit downstream HTTP wrapper za root cause a přehlédnout dřívější DB/concurrency exception.
- Sloučení secondary problem payloadu do primary payloadu sečte counts a scope, ale ponechá vysvětlení primary problému. Výsledek pak nelze auditně reconciliovat.
- Current-window evidence a historical Known Error behavior se nesmí vykreslovat pod jedním neoznačeným countem.

## Osvědčený kontrakt

Detekci a diagnózu držet jako samostatné fáze:

1. Namespace Pxx/CAP je pouze volume gate: „je celkový ERROR provoz neobvyklý?“
2. Operation/cause analysis říká: „co přesně zvýšení tvoří?“
3. Notification policy rozhoduje: „je to actionable a komu to patří?“

Primary impact unit:

```text
operation_occurrence = trace_id + root_span_or_request_boundary
```

Cause identity:

```text
cause_signature = root_app + canonical_cause + operation + outward_status
```

V reportu vždy zobrazit dvě pojmenované metriky:

- unique operations,
- raw ERROR lines a amplification `raw lines / operations`.

## Forenzní postup

1. Použít half-open UTC okno a complete PIT/search-after fetch; při `expected != fetched` report nevydat.
2. Seskupit eventy na operation occurrences, dlouhé trace segmentovat podle request boundary nebo time gapu.
3. Eventům přidělit role `concrete cause`, `wrapper`, `transport symptom`, `business outcome`.
4. Root cause rankovat podle span ancestry, upstream pozice, event role a specificity, ne pouze podle klíčových slov ve zprávě.
5. Pro representative trace načíst INFO/WARN kontext. Například `result=CANCELLED` změnil interpretaci HTTP 400 z incidentu na pravděpodobný expected outcome nebo contract mismatch.
6. Threshold důvod číst z uložených `detection_events`: evaluated namespace total, Pxx, CAP, effective threshold, snapshot ID a population semantics.
7. Před renderem vynutit reconciliation:

```text
sum(family raw lines) + excluded/untraced = fetched ERROR lines
representative trace belongs to displayed family and scope
current counts are never mixed with historical counts
```

## Span-aware operation counting

`trace_id` není vždy operation ID. Dlouhá session trace může obsahovat několik nezávislých requestů, proto se operation count nesmí automaticky rovnat počtu trace IDs.

Ověřený rozhodovací strom:

1. Zachovat `span_id` a `parent_span_id` od ES fetch přes SQLite spill až do `TraceEvent`.
2. Pokud každý ERROR event vede úplnou ancestry cestou k explicitnímu parentless root span, rozdělit timeline podle rootu. Každý segment se klasifikuje samostatně a context z jiného rootu se nesmí kopírovat.
3. Pokud span data chybí, použít `trace_id` fallback jen pro ohraničenou trace. Aktuální default je maximálně 100 ERROR eventů a 15 minut; oba limity jsou konfigurovatelné.
4. Pokud je ancestry částečná, konfliktní, cyklická, timeline capnutá nebo má více nedokazatelných request boundaries, vrátit `unique_operations = NULL`, `method = unavailable`, `confidence = low` a konkrétní reason.
5. Vždy reconciliovat `sum(segment ERROR lines) == trace raw ERROR lines`. Bez této rovnice segmentaci nepoužít.

Persistence musí držet operation count odděleně od trace evidence. Platí `unique_operations >= len(trace_ids)`, nikoli rovnost; dvě root-span operace mohou mít stejné session `trace_id`.

Alert payload smí převzít autoritativní run-level cause families jen při současné přesné shodě množiny trace IDs a raw ERROR countu. Jinak ponechá lokální family a nesmí připojit evidence z jiného alert clusteru.

## CAP lifecycle poznatek

Init trainer a weekly CronJob nejsou duplicitní detektory. Init vytváří bootstrap snapshot po backfillu, CronJob obnovuje rolling snapshot a regular jobs poslední complete snapshot jen čtou. Init má threshold přepočítat pouze při chybějícím nebo nekompatibilním snapshotu, případně po explicitním force flagu.

Vyřazení nul před P93 obvykle threshold zvýší, protože jde o percentile aktivních oken. Nejde o způsob, jak zvýšit citlivost. Population semantics musí být verzované a zobrazené v alertu.

## Kde je detail

Kompletní evidence, sample reporty a implementační fáze jsou v `plans/002_operator-centered-alert-and-wiki-reporting.md`.