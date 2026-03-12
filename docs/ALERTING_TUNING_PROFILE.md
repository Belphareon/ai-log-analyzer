# Alerting Tuning Profile (SIT/UAT)

Tento profil je urceny pro snizeni spamu pri zachovani signalu o novych nebo eskalujicich problemech.

## Doporucene hodnoty

- MAX_PEAK_ALERTS_PER_WINDOW=3
- ALERT_DIGEST_ENABLED=true
- ALERT_COOLDOWN_MIN=45
- ALERT_HEARTBEAT_MIN=120
- ALERT_MIN_DELTA_PCT=30
- ALERT_CONTINUATION_LOOKBACK_MIN=60

## Chovani

- Jeden digest email za 15m okno (pokud jsou alerty k odeslani).
- Pokracujici peak bez materialni zmeny se potlaci.
- Znovu se posila pri:
  - zmene trendu,
  - zmene error_count >= ALERT_MIN_DELTA_PCT,
  - nove aplikaci/namespace,
  - heartbeat intervalu.

## Rychly tuning

- Mene emailu:
  - zvys ALERT_COOLDOWN_MIN na 60-90
  - zvys ALERT_MIN_DELTA_PCT na 40-50
  - zvys ALERT_HEARTBEAT_MIN na 180

- Vice citlive alerty:
  - sniz ALERT_COOLDOWN_MIN na 30
  - sniz ALERT_MIN_DELTA_PCT na 20
  - sniz ALERT_HEARTBEAT_MIN na 60

## Poznamka

Pokud chces fallback na puvodni styl (email per peak), nastav ALERT_DIGEST_ENABLED=false.
