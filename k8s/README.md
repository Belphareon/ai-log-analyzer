# AI Log Analyzer Helm Chart

Tento chart vytvari kompletni runtime AI Log Analyzeru:

- pravidelny analyzator logu,
- backfill a publikaci reportu,
- prepocet peak thresholdu,
- jednorazovy init job,
- PVC, service account a Conjur-managed Secret.

Image se nastavuje v `values.yaml` pod `app.image`. Chart ani instalacni skript image nebuildi a nepushuji.

Databazove ucty jsou v `conjur.accounts.database.{d1,d2}` a `conjur.accounts.database_ddl.{d1,d2}`. Aktualni Secret mapuje aktivni D1 ucty; D2 je pripraven pro budouci dual-account prepinani.