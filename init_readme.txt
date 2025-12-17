jo jeste udelame jedno readme - jak zacit pouzivat ai-log analyzer, kde budou i prerekvizity:

Log Analyzer - how to implement

1) Zalozit tech usera pomoci smaxu
https://smax.kb.cz/saw/ess/offeringPage/85134

textove pole:"
Stručný popis
PAM - Správa technického účtu"

textove pole:"
Popis*

Prosím o vytvoření technického účtu v doméně DS
XX_<nazev>_ES_READ

volitelne -> Při vytváření prosím nastavit hodnotu mail na hodnoty @ds.kb.cz.
Nechci vytvářet email schránku v Exchange, ale pouze záznam v AD.

Description: Účet pro nahlizeni logu aplikace <moje_aplikace> (nastavuje se pak jinde)
Děkuji."

-> vysledek zaslany credentials na mail uzivatele

2) povoleni pristupu do ES pro vyse vytvoreneho tech usera
https://jira.kb.cz/browse/PSLAS-6038

textove pole:"
Ahoj,

prosim o povoleni pristupu technického uzivatele "XX_<nazev>_ES_READ" k indexum "cluster-app_<tvoje_app>*"...  z duvodu nacitani dat na analyzu logu.

Dekuji"

3) definovat variables + upravit pouzivani uctu, aby se dotahoval z cyberarku, ale to bude az v k8s, to z  localu resit nebudeme

4) upravit variables tak, aby to z nej scripty nacitaly (takze pocitat s jinymi indexy, nazvy apps ....)