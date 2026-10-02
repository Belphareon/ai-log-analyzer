---
title: "CDC: forenzní důkaz hot loopu frontových eventů"
date: 2026-09-25
category: architecture
component: ai-log-analyzer
tags: [elasticsearch, cdc, queue, lifecycle, trace-analysis, root-cause]
file_type: rules
---

# CDC: forenzní důkaz hot loopu frontových eventů

## Kontext

V produkčním okně 2026-09-25 01:10-01:35 CEST bylo pro topic
`cluster-k8s_prod_0927-in` přes milion logů. Incident nebyl vysvětlitelný
samotným OOM ani `Thread pool exhausted`; rozhodující evidence byla v INFO
workflow zprávách `bl-pcb-client-rainbow-status-v1`.

## Ověřený postup

1. Převést lokální interval na half-open UTC interval a pro prod topic použít
   `https://elasticsearch.kb.cz:9500`.
2. Přes PIT + `search_after` ověřit úplnost a nad všemi levely seřadit přímá ES
   pole `application.name`, `kubernetes.pod.name`, `traceId` a `level`.
   V tomto indexu nepoužívat příponu `.keyword`; agregace by vrátila falešně
   pouze `missing`.
3. Pro dominantní trace stáhnout raw INFO/WARN lifecycle zprávy a z nich
   extrahovat `queueEventId`, entitu, event type, `createdAt`, `delayedTo`,
   přechod stavu, predecessor IDs a pod.
4. Na každý predecessor ID dotáhnout jeho vlastní timeline. Root cause je
   prokázaná teprve tehdy, když závislost, state transition a ukončovací
   podmínka tvoří úplný řetězec.

## Prokázaný mechanismus

`CLIENT_CARDS_MIGRATION` 6467528 byl od 01:18:01 do 01:20:22 zpracován
972x a 971x vrácen `PROCESSING -> REGISTERED`. Při každém pokusu nalezl dva
starší re-registrované `CLIENT_MIGRATION` eventy 6467677 a 6467678. Návrat byl
explicitně `without delaying`, ale `delayedTo` zůstal v minulosti. Scheduler jej
proto ihned znovu vybral.

Predecessory byly vloženy v 01:10:22, nesly však historický
`createdAt=2026-05-07`; dokončily se v 01:20:22 a karta poté okamžitě přešla do
`COMPLETED`. Dva pody hot loop zesílily, ale nebyly jeho příčinou.

## Pravidla pro analyzer

- ERROR peak je volume gate, ne dostatečný diagnostický vstup.
- Lifecycle probe musí běžet nezávisle na ERROR fetchi; INFO-only hot loop se
   jinak ukončí jako `no_data` dřív, než může vzniknout evidence.
- Pro queue incidenty si analyzer musí selektivně dotáhnout INFO/WARN context.
- Neodvozovat lifecycle z fingerprintu. Parsovat stabilní message patterns do
  queue timeline a grafu závislostí mezi eventy.
- Detekovat opakovaný `PROCESSING -> REGISTERED` s `without delaying` a
  `delayedTo <= observed_at`; uvést pokusy, délku, rychlost, pody,
  predecessor IDs a exact evidence messages.
- Více podů hlásit jako amplifikátor až po prokázání lifecycle smyčky, ne jako
  automatickou root cause.

## Kontrakty implementace

- Samostatný `fetch_lifecycle_context()` musí používat PIT + `search_after` a
   vlastní `LifecycleFetchStats`. Úplnost se ověřuje pro každý původní scope i
   dotahovaný predecessor; cap, timeout nebo `expected != fetched` znamená, že
   nevznikne high-confidence incident ani alert.
- Identita queue eventu není samotné `queueEventId`. Použít alespoň
   `topic + namespace + queueEventId`; trace ID je pouze evidence, protože
   predecessor může být v jiné trace. Fetch musí zahrnout `topic`,
   `kubernetes.pod.name` a pokud je dostupné také ES `_id` pro deduplikaci.
- `WorkflowIncident` držet mimo ERROR/fingerprint model a před notifikací jej
   uložit do vlastního run ledgeru s query scope, pattern version,
   expected/fetched/processed počty, confidence a odkazy na evidence. To umožní
   audit, replay, deduplikaci i trendování bez zneužití ERROR-only persistence.
- Akceptační sada musí obsahovat INFO-only loop, stejný `queueEventId` v jiném
   scope, predecessor v jiné trace, neuspořádané a duplicitní dokumenty,
   benign retry s budoucím `delayedTo`, multi-pod amplifikaci a neúplný fetch.