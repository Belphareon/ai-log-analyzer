# r109: UTC slot P95/MAD, lokalni overeni

**Model 5.0 je implementovany lokalne, nikoli nasazeny nebo schvaleny pro nasazeni.**

Schvaleny klic: `namespace + den tydne UTC + hodina UTC + ctvrtina hodiny`. Kazdy slot ma vlastni P95/MAD. Skutecne nulove DB fakty jsou vzorky; chybejici nebo neuspesne behy se nedoplnuji nulami. Globalni CAP ani default 100 se nepouzivaji. Profil s 1-9 vzorky je `init`, od 10 je `mature`. `missing` je nevyhodnoceny slot bez nahradniho prahu a nesmi vyvolat recovery epizody.

## Implementace A Overeni

- Migrace 011 pridava samostatne slotove snapshoty a trvaly init/missing audit. Aplikovane migrace 000-010 zustaly beze zmen. Denni snapshot 4.1 je nekompatibilni, init guard vyzada trenovani noveho modelu.
- DB trener, init i tydenni CronJob pouzivaji 12 tydnu historie; pozadovany horizont pod 10 tydnu DB trener odmitne. Dostupna kratsi skutecna historie je povolena jako init. Zmensenim minima pod 10 nelze profil prohlasit za vyzraly.
- Zdrojovy i pripraveny nprod chart maji DB-only maintenance s 90denni retenci 15min faktu. Jde o konfiguraci, nikoli dukaz skutecneho stavu nprod. Firemni DB read-only pristup skoncil LDAP odmitnutim: stari a souvislost jeji historie zustavaji neoverene.
- Lokalni PostgreSQL 16 overil migrace, deset tydnu skutecnych faktu vcetne nul, oddeleni hodin, pouziti init, nepritomnost fallbacku, odmitnuti stareho denniho snapshotu a trvaly init/missing audit. Skutecny UTC detektor prosel i spike vetvi a payloadem s `CAP=None`.
- Puvodni slotovy checkpoint: **214 passed, 2 subtests passed**, bez skipped, vcetne sedmi PostgreSQL integraci. Po schvalenem oddeleni collectoru a DB reporteru je finalni sada **243 testu, 0 failures/errors/skipped**, vcetne nove migrace 012 a reportovaci integrace. Slotovy ES replay nebyl znovu collecten ani zmenen. Existujici deprecation warnings nejsou predmetem teto zmeny. Zdrojovy i pripraveny nprod Helm render a YAML/shell instalatoru prosly.
- Zadny commit, build, push, publikace image ani deployment v tomto kroku neprobehl. Tento ES volume replay neoveruje prirazeni priciny, epizody ani doruceni upozorneni.

## Zdroj A Interval

Aktualni [slotovy JSON](../reports/validation/r109-nprod-p95-utc-slot-24h-20261027.json) obsahuje vsech 8 064 profilu a 1 152 verdiktu. Jde o prepocet drive overenych ES poctu, ne novy fetch ani authoritative DB replay. [Puvodni ES replay](../reports/validation/r109-nprod-p95-24h-20261027-0800CET.json) a [historicky denni audit](../reports/validation/r109-nprod-p95-threshold-audit-20261027.json) jsou zdrojove podklady, nikoli vysledky soucasneho modelu. Zadny prikladovy radek nebyl oznacen jako potvrzeny false positive.

**Vyhodnoceni: 26.10.2026 08:00 az 27.10.2026 08:00 CET, konec vyloucen.** UTC `2026-10-26T07:00Z .. 2026-10-27T07:00Z`. Cas v seznamu je zacatek 15min okna v CET, UTC+1.

Archivovany ES dotaz pozadoval 4 tydny od `2026-09-28T07:00Z`; to neni nova DB konfigurace 12 tydnu. Pro slotovy ES prepocet je vyloucena prazdna historie pred prvnim dolozenym trenovacim ERROR `2026-10-13T10:15Z`. Posledni trenovaci okno je `2026-10-26T06:45Z`; holdout nevstupuje do trenovani. Histogramova nula uvnitr intervalu sama neprokazuje zdravy ingest. ES vzorky nejsou authoritative DB fakty.

**Vsech 8 064 profilu je init, zadny mature. Vsech 1 152 vyhodnocovanych oken pouziva jen jeden historicky vzorek.** Celkem 89 616 ERROR, 209 volume prekroceni v 76 ruznych casovych oknech. To nejsou 209 alertu: replay neaplikuje runtime minimum volume, family gate, epizody ani notifikacni politiku. Vyssi pocet oproti dennimu modelu neni meritko lepsi ani horsi precision/recall.

## Pokryti Vsech 12 Namespace

| Namespace | UTC slotu | ES vzorku | Z toho nuly | N na slot | ERROR v holdoutu | Prekroceni |
|---|---:|---:|---:|---:|---:|---:|
| pca-dev-01-app | 672 | 1235 | 944 | 1-2 | 742 | 10 |
| pca-fat-01-app | 672 | 1235 | 1234 | 1-2 | 0 | 0 |
| pca-sit-01-app | 672 | 1235 | 943 | 1-2 | 816 | 7 |
| pca-uat-01-app | 672 | 1235 | 1235 | 1-2 | 2 | 2 |
| pcb-ch-dev-01-app | 672 | 1235 | 863 | 1-2 | 3512 | 6 |
| pcb-ch-fat-01-app | 672 | 1235 | 1230 | 1-2 | 0 | 0 |
| pcb-ch-sit-01-app | 672 | 1235 | 589 | 1-2 | 32258 | 10 |
| pcb-ch-uat-01-app | 672 | 1235 | 1231 | 1-2 | 0 | 0 |
| pcb-dev-01-app | 672 | 1235 | 174 | 1-2 | 17055 | 48 |
| pcb-fat-01-app | 672 | 1235 | 188 | 1-2 | 11856 | 59 |
| pcb-sit-01-app | 672 | 1235 | 310 | 1-2 | 11960 | 31 |
| pcb-uat-01-app | 672 | 1235 | 190 | 1-2 | 11415 | 36 |

Tydenni pokryti je pro vsech 12 namespace stejne. Kazdy den ma 96 samostatnych profilu, ne jednu sloucenou denni populaci.

| UTC den | Slotu na NS | Pozorovani na NS | N na slot |
|---|---:|---:|---|
| Po | 96 | 124 | 1-2 |
| Ut | 96 | 151 | 1-2 |
| St | 96 | 192 | 2 |
| Ct | 96 | 192 | 2 |
| Pa | 96 | 192 | 2 |
| So | 96 | 192 | 2 |
| Ne | 96 | 192 | 2 |

## Presny Vypocet Tri Oken

Raw P95 je prvek serazenych vzorku slotu na indexu `min(floor(N * 0.95), N - 1)`, od nuly, bez interpolace. MAD je `median(abs(x - median))`; robustni strop je `median + 6 * 1.4826 * MAD`. Pri MAD=0 zustava strop maximum vzorku, nikoli median. Limit je `min(raw P95, strop)`; prekroceni je ostre `count > limit`. Zadny dalsi CAP se neaplikuje.

| Okno 26.10. CET | Namespace | UTC slot | Trenovaci vzorek 19.10. UTC | N | Median / MAD | P95 / strop / limit | Count | Verdikt |
|---|---|---|---|---:|---|---|---:|---|
| 11:00 | pcb-ch-sit-01-app | Po 10:00, Q0 | 10:00: 0 | 1 | 0 / 0 | 0 / 0 / 0 | 0 | init, neprekroceno |
| 13:00 | pcb-ch-sit-01-app | Po 12:00, Q0 | 12:00: 30 | 1 | 30 / 0 | 30 / 30 / 30 | 13095 | init, prekroceno |
| 08:15 | pcb-fat-01-app | Po 07:15, Q1 | 07:15: 3 | 1 | 3 / 0 | 3 / 3 / 3 | 87 | init, prekroceno |

Reference CHSIT 08:00-08:30 CET zustava: `13079 > 0` a `1259 > 9`, celkem 14 338 ERROR. Obe okna jsou volume prekroceni, nikoli timto potvrzene nove incidenty.

### Zmena Letniho Casu

UTC model neni model stejne mistni hodiny. Dne 19.10. platilo CEST (UTC+2), dne 26.10. CET (UTC+1). Dne 19.10. **13:00 mistniho casu** bylo `11:00Z` a melo 13 095 ERROR. Dne 26.10. **13:00 mistniho casu** je `12:00Z` a porovnava se se vzorkem 19.10. `12:00Z`, ktery mel 30 ERROR. To vysvetluje cast prekroceni pravidelnych spicek pres zmenu casu. Schvaleny UTC klic zustal zachovan; prechod na `Europe/Prague` by byl nove rozhodnuti, nikoli ticha oprava v tomto patchi.

## Kompletni Seznam Prekroceni

Vsechny radky maji `profile=init`, `N=1`; globalni CAP neni. ID `SLOT-*` jsou jen odkazy pro rucni kontrolu, ne FP/TP stitky. Count a limit jsou ERROR lines za 15 minut.

| ID | Zacatek CET | Namespace | Count | Slot limit |
|---|---|---|---:|---:|
| SLOT-001 | 26.10. 08:00 | pcb-ch-dev-01-app | 21 | 0 |
| SLOT-002 | 26.10. 08:00 | pcb-ch-sit-01-app | 13079 | 0 |
| SLOT-003 | 26.10. 08:00 | pcb-fat-01-app | 56 | 2 |
| SLOT-004 | 26.10. 08:00 | pcb-sit-01-app | 231 | 12 |
| SLOT-005 | 26.10. 08:00 | pcb-uat-01-app | 56 | 42 |
| SLOT-006 | 26.10. 08:15 | pcb-ch-sit-01-app | 1259 | 9 |
| SLOT-007 | 26.10. 08:15 | pcb-dev-01-app | 148 | 92 |
| SLOT-008 | 26.10. 08:15 | pcb-fat-01-app | 87 | 3 |
| SLOT-009 | 26.10. 08:15 | pcb-sit-01-app | 44 | 17 |
| SLOT-010 | 26.10. 08:15 | pcb-uat-01-app | 87 | 45 |
| SLOT-011 | 26.10. 08:30 | pcb-fat-01-app | 21 | 1 |
| SLOT-012 | 26.10. 08:30 | pcb-sit-01-app | 166 | 35 |
| SLOT-013 | 26.10. 08:45 | pcb-dev-01-app | 344 | 238 |
| SLOT-014 | 26.10. 08:45 | pcb-sit-01-app | 76 | 8 |
| SLOT-015 | 26.10. 09:00 | pcb-fat-01-app | 62 | 2 |
| SLOT-016 | 26.10. 09:00 | pcb-uat-01-app | 62 | 54 |
| SLOT-017 | 26.10. 09:15 | pcb-fat-01-app | 75 | 3 |
| SLOT-018 | 26.10. 09:30 | pcb-ch-dev-01-app | 461 | 51 |
| SLOT-019 | 26.10. 09:30 | pcb-dev-01-app | 2885 | 95 |
| SLOT-020 | 26.10. 09:30 | pcb-fat-01-app | 21 | 1 |
| SLOT-021 | 26.10. 09:30 | pcb-sit-01-app | 14 | 11 |
| SLOT-022 | 26.10. 09:45 | pcb-ch-dev-01-app | 492 | 0 |
| SLOT-023 | 26.10. 09:45 | pcb-dev-01-app | 236 | 27 |
| SLOT-024 | 26.10. 09:45 | pcb-sit-01-app | 16 | 8 |
| SLOT-025 | 26.10. 10:00 | pcb-ch-dev-01-app | 184 | 0 |
| SLOT-026 | 26.10. 10:00 | pcb-dev-01-app | 57 | 38 |
| SLOT-027 | 26.10. 10:00 | pcb-fat-01-app | 67 | 3 |
| SLOT-028 | 26.10. 10:00 | pcb-sit-01-app | 28 | 20 |
| SLOT-029 | 26.10. 10:00 | pcb-uat-01-app | 62 | 55 |
| SLOT-030 | 26.10. 10:15 | pcb-ch-dev-01-app | 505 | 79 |
| SLOT-031 | 26.10. 10:15 | pcb-dev-01-app | 705 | 106 |
| SLOT-032 | 26.10. 10:15 | pcb-fat-01-app | 75 | 3 |
| SLOT-033 | 26.10. 10:30 | pcb-ch-dev-01-app | 32 | 0 |
| SLOT-034 | 26.10. 10:30 | pcb-dev-01-app | 56 | 35 |
| SLOT-035 | 26.10. 10:30 | pcb-fat-01-app | 21 | 1 |
| SLOT-036 | 26.10. 10:30 | pcb-sit-01-app | 14 | 6 |
| SLOT-037 | 26.10. 10:45 | pca-dev-01-app | 6 | 0 |
| SLOT-038 | 26.10. 10:45 | pcb-dev-01-app | 42 | 15 |
| SLOT-039 | 26.10. 10:45 | pcb-sit-01-app | 16 | 8 |
| SLOT-040 | 26.10. 11:00 | pca-dev-01-app | 45 | 29 |
| SLOT-041 | 26.10. 11:00 | pcb-dev-01-app | 77 | 25 |
| SLOT-042 | 26.10. 11:00 | pcb-fat-01-app | 82 | 2 |
| SLOT-043 | 26.10. 11:00 | pcb-sit-01-app | 48 | 13 |
| SLOT-044 | 26.10. 11:00 | pcb-uat-01-app | 82 | 42 |
| SLOT-045 | 26.10. 11:15 | pcb-fat-01-app | 75 | 3 |
| SLOT-046 | 26.10. 11:30 | pcb-fat-01-app | 47 | 1 |
| SLOT-047 | 26.10. 12:00 | pca-dev-01-app | 52 | 29 |
| SLOT-048 | 26.10. 12:00 | pcb-dev-01-app | 45 | 42 |
| SLOT-049 | 26.10. 12:00 | pcb-fat-01-app | 62 | 2 |
| SLOT-050 | 26.10. 12:00 | pcb-uat-01-app | 62 | 59 |
| SLOT-051 | 26.10. 12:15 | pca-dev-01-app | 13 | 0 |
| SLOT-052 | 26.10. 12:15 | pca-sit-01-app | 5 | 0 |
| SLOT-053 | 26.10. 12:15 | pcb-dev-01-app | 101 | 99 |
| SLOT-054 | 26.10. 12:15 | pcb-fat-01-app | 79 | 3 |
| SLOT-055 | 26.10. 12:30 | pca-dev-01-app | 5 | 0 |
| SLOT-056 | 26.10. 12:30 | pcb-dev-01-app | 214 | 35 |
| SLOT-057 | 26.10. 12:30 | pcb-fat-01-app | 21 | 1 |
| SLOT-058 | 26.10. 12:45 | pca-dev-01-app | 6 | 0 |
| SLOT-059 | 26.10. 12:45 | pca-sit-01-app | 6 | 0 |
| SLOT-060 | 26.10. 12:45 | pcb-dev-01-app | 45 | 25 |
| SLOT-061 | 26.10. 12:45 | pcb-fat-01-app | 70 | 1 |
| SLOT-062 | 26.10. 13:00 | pca-dev-01-app | 52 | 29 |
| SLOT-063 | 26.10. 13:00 | pca-sit-01-app | 29 | 0 |
| SLOT-064 | 26.10. 13:00 | pcb-ch-sit-01-app | 13095 | 30 |
| SLOT-065 | 26.10. 13:00 | pcb-dev-01-app | 49 | 42 |
| SLOT-066 | 26.10. 13:00 | pcb-fat-01-app | 66 | 2 |
| SLOT-067 | 26.10. 13:00 | pcb-sit-01-app | 232 | 17 |
| SLOT-068 | 26.10. 13:15 | pcb-ch-sit-01-app | 1262 | 93 |
| SLOT-069 | 26.10. 13:15 | pcb-fat-01-app | 74 | 3 |
| SLOT-070 | 26.10. 13:30 | pcb-dev-01-app | 47 | 35 |
| SLOT-071 | 26.10. 13:30 | pcb-fat-01-app | 21 | 1 |
| SLOT-072 | 26.10. 13:45 | pcb-dev-01-app | 331 | 15 |
| SLOT-073 | 26.10. 13:45 | pcb-sit-01-app | 190 | 164 |
| SLOT-074 | 26.10. 14:00 | pcb-dev-01-app | 186 | 37 |
| SLOT-075 | 26.10. 14:00 | pcb-fat-01-app | 61 | 2 |
| SLOT-076 | 26.10. 14:00 | pcb-uat-01-app | 61 | 54 |
| SLOT-077 | 26.10. 14:15 | pcb-dev-01-app | 204 | 94 |
| SLOT-078 | 26.10. 14:15 | pcb-fat-01-app | 74 | 3 |
| SLOT-079 | 26.10. 14:30 | pcb-fat-01-app | 21 | 3 |
| SLOT-080 | 26.10. 14:45 | pcb-ch-sit-01-app | 119 | 0 |
| SLOT-081 | 26.10. 14:45 | pcb-dev-01-app | 305 | 15 |
| SLOT-082 | 26.10. 14:45 | pcb-fat-01-app | 5 | 1 |
| SLOT-083 | 26.10. 14:45 | pcb-sit-01-app | 84 | 0 |
| SLOT-084 | 26.10. 14:45 | pcb-uat-01-app | 5 | 1 |
| SLOT-085 | 26.10. 15:00 | pcb-ch-sit-01-app | 99 | 4 |
| SLOT-086 | 26.10. 15:00 | pcb-dev-01-app | 45 | 37 |
| SLOT-087 | 26.10. 15:00 | pcb-fat-01-app | 61 | 2 |
| SLOT-088 | 26.10. 15:00 | pcb-sit-01-app | 56 | 35 |
| SLOT-089 | 26.10. 15:00 | pcb-uat-01-app | 61 | 54 |
| SLOT-090 | 26.10. 15:15 | pcb-ch-sit-01-app | 247 | 26 |
| SLOT-091 | 26.10. 15:15 | pcb-dev-01-app | 270 | 95 |
| SLOT-092 | 26.10. 15:15 | pcb-fat-01-app | 74 | 3 |
| SLOT-093 | 26.10. 15:15 | pcb-sit-01-app | 146 | 49 |
| SLOT-094 | 26.10. 15:30 | pcb-ch-sit-01-app | 323 | 79 |
| SLOT-095 | 26.10. 15:30 | pcb-dev-01-app | 6470 | 35 |
| SLOT-096 | 26.10. 15:30 | pcb-fat-01-app | 7941 | 1 |
| SLOT-097 | 26.10. 15:30 | pcb-sit-01-app | 6289 | 6 |
| SLOT-098 | 26.10. 15:30 | pcb-uat-01-app | 7711 | 11 |
| SLOT-099 | 26.10. 15:45 | pcb-dev-01-app | 45 | 19 |
| SLOT-100 | 26.10. 15:45 | pcb-sit-01-app | 2 | 0 |
| SLOT-101 | 26.10. 15:45 | pcb-uat-01-app | 2 | 1 |
| SLOT-102 | 26.10. 16:00 | pcb-dev-01-app | 45 | 37 |
| SLOT-103 | 26.10. 16:00 | pcb-fat-01-app | 61 | 2 |
| SLOT-104 | 26.10. 16:00 | pcb-sit-01-app | 40 | 18 |
| SLOT-105 | 26.10. 16:00 | pcb-uat-01-app | 61 | 54 |
| SLOT-106 | 26.10. 16:15 | pcb-dev-01-app | 167 | 94 |
| SLOT-107 | 26.10. 16:15 | pcb-fat-01-app | 74 | 3 |
| SLOT-108 | 26.10. 16:30 | pcb-dev-01-app | 105 | 35 |
| SLOT-109 | 26.10. 16:30 | pcb-fat-01-app | 63 | 1 |
| SLOT-110 | 26.10. 16:30 | pcb-sit-01-app | 164 | 6 |
| SLOT-111 | 26.10. 16:30 | pcb-uat-01-app | 53 | 11 |
| SLOT-112 | 26.10. 16:45 | pcb-ch-sit-01-app | 19 | 0 |
| SLOT-113 | 26.10. 16:45 | pcb-dev-01-app | 105 | 15 |
| SLOT-114 | 26.10. 16:45 | pcb-fat-01-app | 90 | 1 |
| SLOT-115 | 26.10. 16:45 | pcb-sit-01-app | 75 | 0 |
| SLOT-116 | 26.10. 16:45 | pcb-uat-01-app | 90 | 1 |
| SLOT-117 | 26.10. 17:00 | pcb-dev-01-app | 45 | 37 |
| SLOT-118 | 26.10. 17:00 | pcb-fat-01-app | 61 | 2 |
| SLOT-119 | 26.10. 17:00 | pcb-sit-01-app | 20 | 12 |
| SLOT-120 | 26.10. 17:15 | pcb-fat-01-app | 74 | 3 |
| SLOT-121 | 26.10. 17:30 | pcb-fat-01-app | 21 | 1 |
| SLOT-122 | 26.10. 18:00 | pcb-dev-01-app | 54 | 37 |
| SLOT-123 | 26.10. 18:00 | pcb-fat-01-app | 61 | 2 |
| SLOT-124 | 26.10. 18:00 | pcb-sit-01-app | 70 | 12 |
| SLOT-125 | 26.10. 18:00 | pcb-uat-01-app | 66 | 54 |
| SLOT-126 | 26.10. 18:15 | pcb-fat-01-app | 74 | 3 |
| SLOT-127 | 26.10. 18:30 | pcb-fat-01-app | 21 | 1 |
| SLOT-128 | 26.10. 19:00 | pcb-dev-01-app | 45 | 31 |
| SLOT-129 | 26.10. 19:00 | pcb-fat-01-app | 61 | 2 |
| SLOT-130 | 26.10. 19:00 | pcb-sit-01-app | 20 | 12 |
| SLOT-131 | 26.10. 19:00 | pcb-uat-01-app | 61 | 48 |
| SLOT-132 | 26.10. 19:15 | pcb-dev-01-app | 94 | 82 |
| SLOT-133 | 26.10. 19:15 | pcb-fat-01-app | 74 | 3 |
| SLOT-134 | 26.10. 19:15 | pcb-uat-01-app | 74 | 62 |
| SLOT-135 | 26.10. 19:30 | pcb-fat-01-app | 21 | 1 |
| SLOT-136 | 26.10. 19:30 | pcb-uat-01-app | 11 | 6 |
| SLOT-137 | 26.10. 20:00 | pcb-dev-01-app | 45 | 25 |
| SLOT-138 | 26.10. 20:00 | pcb-fat-01-app | 61 | 2 |
| SLOT-139 | 26.10. 20:00 | pcb-sit-01-app | 20 | 12 |
| SLOT-140 | 26.10. 20:00 | pcb-uat-01-app | 61 | 42 |
| SLOT-141 | 26.10. 20:15 | pcb-dev-01-app | 94 | 22 |
| SLOT-142 | 26.10. 20:15 | pcb-fat-01-app | 74 | 3 |
| SLOT-143 | 26.10. 20:15 | pcb-sit-01-app | 5 | 4 |
| SLOT-144 | 26.10. 20:15 | pcb-uat-01-app | 74 | 2 |
| SLOT-145 | 26.10. 20:30 | pcb-fat-01-app | 21 | 1 |
| SLOT-146 | 26.10. 20:30 | pcb-sit-01-app | 7 | 6 |
| SLOT-147 | 26.10. 20:45 | pcb-dev-01-app | 15 | 14 |
| SLOT-148 | 26.10. 21:00 | pcb-dev-01-app | 37 | 24 |
| SLOT-149 | 26.10. 21:00 | pcb-fat-01-app | 53 | 2 |
| SLOT-150 | 26.10. 21:00 | pcb-uat-01-app | 53 | 42 |
| SLOT-151 | 26.10. 21:15 | pcb-dev-01-app | 94 | 36 |
| SLOT-152 | 26.10. 21:15 | pcb-fat-01-app | 74 | 3 |
| SLOT-153 | 26.10. 21:15 | pcb-uat-01-app | 74 | 2 |
| SLOT-154 | 26.10. 21:30 | pcb-fat-01-app | 21 | 1 |
| SLOT-155 | 26.10. 21:45 | pca-sit-01-app | 12 | 0 |
| SLOT-156 | 26.10. 21:45 | pcb-dev-01-app | 15 | 14 |
| SLOT-157 | 26.10. 22:00 | pcb-dev-01-app | 37 | 24 |
| SLOT-158 | 26.10. 22:00 | pcb-fat-01-app | 53 | 2 |
| SLOT-159 | 26.10. 22:00 | pcb-uat-01-app | 53 | 42 |
| SLOT-160 | 26.10. 22:15 | pcb-dev-01-app | 101 | 22 |
| SLOT-161 | 26.10. 22:15 | pcb-fat-01-app | 74 | 3 |
| SLOT-162 | 26.10. 22:15 | pcb-uat-01-app | 74 | 2 |
| SLOT-163 | 26.10. 22:30 | pca-uat-01-app | 1 | 0 |
| SLOT-164 | 26.10. 22:30 | pcb-fat-01-app | 21 | 1 |
| SLOT-165 | 26.10. 22:45 | pca-sit-01-app | 19 | 0 |
| SLOT-166 | 26.10. 22:45 | pcb-dev-01-app | 15 | 14 |
| SLOT-167 | 26.10. 23:00 | pca-uat-01-app | 1 | 0 |
| SLOT-168 | 26.10. 23:00 | pcb-dev-01-app | 37 | 34 |
| SLOT-169 | 26.10. 23:00 | pcb-fat-01-app | 53 | 2 |
| SLOT-170 | 26.10. 23:00 | pcb-uat-01-app | 53 | 42 |
| SLOT-171 | 26.10. 23:15 | pcb-fat-01-app | 74 | 3 |
| SLOT-172 | 26.10. 23:30 | pcb-fat-01-app | 21 | 1 |
| SLOT-173 | 27.10. 00:00 | pcb-fat-01-app | 47 | 7 |
| SLOT-174 | 27.10. 00:00 | pcb-sit-01-app | 28 | 12 |
| SLOT-175 | 27.10. 00:00 | pcb-uat-01-app | 47 | 37 |
| SLOT-176 | 27.10. 00:15 | pcb-fat-01-app | 81 | 40 |
| SLOT-177 | 27.10. 00:30 | pca-sit-01-app | 40 | 35 |
| SLOT-178 | 27.10. 00:30 | pcb-dev-01-app | 117 | 73 |
| SLOT-179 | 27.10. 00:30 | pcb-fat-01-app | 103 | 101 |
| SLOT-180 | 27.10. 00:30 | pcb-sit-01-app | 104 | 6 |
| SLOT-181 | 27.10. 00:30 | pcb-uat-01-app | 95 | 11 |
| SLOT-182 | 27.10. 01:00 | pcb-fat-01-app | 53 | 51 |
| SLOT-183 | 27.10. 01:00 | pcb-sit-01-app | 34 | 2 |
| SLOT-184 | 27.10. 01:00 | pcb-uat-01-app | 53 | 34 |
| SLOT-185 | 27.10. 01:15 | pca-dev-01-app | 23 | 0 |
| SLOT-186 | 27.10. 01:15 | pcb-dev-01-app | 99 | 95 |
| SLOT-187 | 27.10. 01:15 | pcb-uat-01-app | 75 | 74 |
| SLOT-188 | 27.10. 02:15 | pcb-dev-01-app | 95 | 65 |
| SLOT-189 | 27.10. 02:15 | pcb-fat-01-app | 75 | 39 |
| SLOT-190 | 27.10. 02:15 | pcb-uat-01-app | 75 | 38 |
| SLOT-191 | 27.10. 02:30 | pcb-ch-sit-01-app | 79 | 0 |
| SLOT-192 | 27.10. 02:45 | pcb-dev-01-app | 15 | 14 |
| SLOT-193 | 27.10. 03:15 | pcb-uat-01-app | 75 | 74 |
| SLOT-194 | 27.10. 03:45 | pca-sit-01-app | 29 | 0 |
| SLOT-195 | 27.10. 03:45 | pcb-sit-01-app | 5 | 0 |
| SLOT-196 | 27.10. 04:00 | pcb-dev-01-app | 36 | 28 |
| SLOT-197 | 27.10. 04:00 | pcb-fat-01-app | 58 | 42 |
| SLOT-198 | 27.10. 04:00 | pcb-uat-01-app | 56 | 42 |
| SLOT-199 | 27.10. 04:15 | pca-dev-01-app | 23 | 0 |
| SLOT-200 | 27.10. 05:15 | pcb-dev-01-app | 101 | 95 |
| SLOT-201 | 27.10. 05:15 | pcb-fat-01-app | 81 | 75 |
| SLOT-202 | 27.10. 05:15 | pcb-uat-01-app | 81 | 74 |
| SLOT-203 | 27.10. 06:00 | pcb-dev-01-app | 48 | 37 |
| SLOT-204 | 27.10. 06:00 | pcb-fat-01-app | 63 | 54 |
| SLOT-205 | 27.10. 06:00 | pcb-uat-01-app | 64 | 58 |
| SLOT-206 | 27.10. 06:15 | pca-dev-01-app | 12 | 0 |
| SLOT-207 | 27.10. 06:15 | pcb-uat-01-app | 75 | 74 |
| SLOT-208 | 27.10. 07:00 | pcb-sit-01-app | 314 | 226 |
| SLOT-209 | 27.10. 07:15 | pcb-uat-01-app | 75 | 74 |
