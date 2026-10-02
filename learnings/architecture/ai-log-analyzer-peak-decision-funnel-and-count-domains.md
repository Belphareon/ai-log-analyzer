---
title: "AI Log Analyzer: Peak decision funnel a count domains"
date: 2026-10-01
category: architecture
component: ai-log-analyzer
tags: [peak-detection, peak-episodes, namespace-coverage, notification-policy, delivery-audit, count-reconciliation, postgresql, km]
file_type: rules
---

# Peak alerty: oddeluj detection, policy a delivery

## Kontext

Po nasazeni `r97` prisel za priblizne 24 hodin jediny peak e-mail. Samotny pocet e-mailu vypadal jako selhani detectoru.

## Co fungovalo

Kombinace `km` logu a immutable PostgreSQL ledgeru ukazala cely funnel:

- 94 complete regular runu zpracovalo 13 135 ERROR radku,
- sest unikatnich `peak_identifier` vzniklo ve ctyrech oknech,
- jeden payload byl dorucen,
- pet payloadu bylo potlaceno jako `test_peak_suppressed:MochaXTestApp`,
- nebyl pouzit cooldown, top-N omission ani delivery failure.

Pri podobnem incidentu nikdy neodvozuj stav detectoru z poctu e-mailu. Pocitej oddelene namespace decisions, owner candidates, policy outcomes a delivery outcomes.

## Gotcha v namespace coverage

Sest `peak_identifier` nebyl pocet peaku v celem prostredi. `MONITORED_NAMESPACES`, fetch query a aktivni threshold snapshot obsahovaly pouze sest `dev/fat` namespaces. `sit/uat` detector vubec necetl, prestoze read-only ES agregace v nich potvrdila dalsi kandidaty.

Pri forenzice proto nejdrive over shodu namespace scope ve fetchi, baseline trainingu, threshold snapshotu a runtime workloadu. Count z ledgeru je uplny pouze vzhledem k tomuto scope.

## Navazujici okna jsou episode, ne sirsi bucket

Detekcni granularita zustava 15 minut. U `pcb-dev` se uzivatelskych 2 431 ERROR rozpadlo na `2 200 + 231`; u `pcb-ch-dev` se 836 rozpadlo na `344 + 492`. To je dukaz kontinuity problemu, ne duvod zavest 30min threshold.

Persistuj kazdy 15min namespace decision samostatne a propojuj ho do runtime `PeakEpisode` podle concrete cause evidence. Episode state se musi aktualizovat nezavisle na suppression nebo delivery, jinak dalsi okno ztrati informaci, ze jde o pokracovani stejneho problemu.

## Gotcha v `detection_events`

`build_detection_rows()` fan-outuje incident evidence pres vsechny `(bucket, namespace, fingerprint)` fact identity. Jedna `spike_p93_cap` evidence proto muze vytvorit vice DB radku a sloupec `namespace` muze obsahovat secondary namespace, zatimco skutecny signal namespace je v `evidence.details.namespace`.

V overenem obdobi bylo 10 `spike_p93_cap` radku, ale pouze sest unikatnich `peak_identifier`. Pro forenziku proto deduplikuj podle `evidence.details.peak_identifier`, ne podle poctu radku ani podle top-level `namespace`.

## Gotcha v count domains

Jeden alert obsahoval tri legitimni, ale nepojmenovane hodnoty:

- 431 namespace ERROR lines vyhodnocenych P94/CAP,
- 86 radku anomalniho owner fingerprintu v trigger namespace,
- 160 radku sirsiho problem/trace cluster payloadu.

Bez explicitnich fieldu vypadaji jako chyba scitani. Payload a renderer musi oddelit namespace signal, owner contribution, cause-family raw lines, correlated context a operation occurrences.

## Doporuceny postup

1. Over live image a joby pres `km`.
2. Z job logu ziskej `peaks_detected`, pocet clusteru a suppression reasons.
3. Z `analysis_runs` over complete windows a fetched count.
4. Z `notification_deliveries` seskup status, destination a provider message.
5. `spike_p93_cap` deduplikuj podle `peak_identifier`.
6. Threshold tuning delej az po replayi; nejdrive oprav decision observability a count contract.