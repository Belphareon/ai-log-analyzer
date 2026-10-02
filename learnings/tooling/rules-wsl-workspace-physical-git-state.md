---
title: "WSL workspace: fyzický Git stav je autorita"
date: 2026-08-26
category: tooling
component: vscode-wsl
tags: [wsl, unc, git, terminal, tooling]
file_type: rules
---

# WSL workspace: fyzický Git stav je autorita

## Kontext

Při práci z VS Code nad UNC cestou do WSL proběhly některé editace úspěšně jen v editorovém filesystem overlay. `apply_patch` ohlásil smazání souborů, ale fyzický inode v `/home/jvsete/git/ai-log-analyzer` dál existoval a `git status` ho stále viděl. Současně terminál běžel jako `root`, takže `~` neukazovalo do repozitáře uživatele `jvsete`.

Paralelní příkazy odeslané přes terminálové nástroje navíc sdílely jednu persistentní shell session. Příkaz spuštěný během aktivního pytestu se smíchal s čekajícím vstupem a vytvořil v kořeni repozitáře nesmyslné soubory `()` a `t|pytest' || true`.

## Co nefungovalo

- Považovat úspěch UNC `apply_patch` za důkaz změny fyzického WSL souboru.
- Považovat `read_file` nebo editor diagnostics za důkaz, že dirty buffer byl uložen do fyzického WSL inode.
- Přepsat starší WSL soubor bez zachování novějšího dirty bufferu; tím by se ztratily obnovené checkpoint změny.
- Používat `~` v terminálu běžícím jako `root`; zapisuje pod `/root`, ne do `/home/jvsete`.
- Posílat terminálové tool calls paralelně nebo další příkaz před skutečným dokončením předchozího procesu.
- Po chybě shellového quotingu kontrolovat jen očekávaný soubor a ne celý `git status`.

## Pravidla pro příště

1. Pro tento repozitář používat explicitní `/home/jvsete/git/ai-log-analyzer`; nepoužívat `~`.
2. Po UNC editaci ověřit fyzický stav z WSL pomocí `git status --short`, `git diff` nebo explicitního filesystem checku. Editorový úspěch sám nestačí.
3. Terminálové příkazy spouštět sekvenčně. Další call neposílat, dokud předchozí sync příkaz skutečně nevrátil finální výstup; dlouhé procesy neparalelizovat v jedné persistentní session.
4. Po chybě quotingu okamžitě zkontrolovat `git status --short`, identifikovat artefakty přesným názvem a odstranit jen vlastní nově vytvořené soubory.
5. Cleanup ověřit dvěma způsoby: cílený filesystem count musí být nula a Git status už nesmí artefakty obsahovat.
6. Pokud `read_file` a WSL `stat`/`rg` ukazují rozdílný obsah, nejde automaticky o chybnou cestu: může existovat novější unsaved VS Code buffer. Nejdřív jej zachovat a dohledat podle unikátního markeru v `Code - Insiders/Backups/<workspace-id>/file/*`.
7. VS Code backup má na prvním řádku file URI a metadata. Před recovery ověřit přesné URI cílového WSL souboru, mtime, očekávané obsahové markery a zakončení dokumentu. První metadata řádek není součást souboru.
8. Recovery provést atomicky přes dočasný soubor ve stejném adresáři, normalizovat CRLF na LF a po zápisu porovnat SHA-256 normalizovaného backup obsahu s fyzickým souborem. Ověřit také `git status`, diagnostics a nulový počet dočasných souborů.

Příklad finální kontroly:

```bash
cd /home/jvsete/git/ai-log-analyzer
find . -maxdepth 1 -type f \( -name '()' -o -name 't*pytest*true' \) -print
git status --short
```