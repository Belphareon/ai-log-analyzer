BASELINE_MEAN:

Z tabulky aggregation_data
Je to 7-denní rolling average pro konkrétní (den_týdne, hodina, čtvrt, namespace)
Příklad: Pondělí 10:00 pcb-dev-01-app → baseline = 50 (průměr všech pondělků 10:00 z posledních 7 dní, bez peaků!)
Stabilní, bezpečný, dlouhodobý
REFERENCE:

Z posledních 3 oken STEJNÝ den (-15, -30, -45 minut)
Příklad: Úterý 10:15 → reference = průměr(Úterý 10:00, 09:45, 09:30)
Počítá se z peak_raw_data (které OBSAHUJÍ JIŽ NAHRAZENÉ VALUES!)
Volatilní, může být vysoký pokud jsou poslední okna TAKÉ peaky!
RATIO:

ratio = original_value / reference
Příklad: 1000 / 50 = 20×
Znamená: "Kolik× vyšší než poslední 3 okna"
SPRÁVNÁ LOGIKA DETEKCE BY MĚLA BÝT:

Kde:

První podmínka: ratio >= baseline_mean * 3.0

Pokud je hodnota 3× vyšší než denní volatilita (baseline)
Volatilnější podmínka, reaguje na trend během dne
Druhá podmínka: value >= agregated_average * 2.5

Pokud je hodnota 2.5× vyšší než dlouhodobý průměr (z agregace)
Stabilnější podmínka, záchytná síť
CO BYLO ŠPATNĚ:

max_ratio_multiplier (5.0) - zbytečný, je to <= což je hloupost
dynamic_min_multiplier se počítá z 24h MAX - mělo by být z agregované tabulky (7-denní avg bez peaků!)
Replacement se dělá z REFERENCE - mělo by z BASELINE, protože reference může být vysoká
Chceš aby jsem to teď takto OPRAVIL?

Smazat max_ratio_multiplier - zůstane jenom ratio_multiplier: 3.0
dynamic_min_multiplier se počítá z aggregation_data.mean (ne z 24h raw)
Replacement = baseline_mean (ne reference)
Zaokrouhlovat na 2 desetinná místa
Je to správně?

pro BASELINE_MEAN:
"Je to 7-denní rolling average pro konkrétní (den_týdne, hodina, čtvrt, namespace)" do tabulky aggregation_data se maji neustale pridavat a aktualizovat dane hodnoty pro konkrétní (den_týdne, hodina, čtvrt, namespace) a ma tam byt s kazdym tydnem vice samplu ze kterych se pocita prumerna hodnota pro dane pole a neustale se aktualizuje podle novych nepeakovych hodnot, aneb kdyz je trend klesajici, ma klesat nebo naopak, jestli je to prumerna hodnota z poslednich 7 tydnu, tak to asi muze byt, to bude lepe reflektovat trend, ale dal bych vice, treba cap 10 samplů, tedy 10 tydnu
, to znamena Stabilní, bezpečný, dlouhodobý

První podmínka: ratio >= baseline_mean * 3.0

Pokud je hodnota 3× vyšší než denní volatilita (baseline)
Volatilnější podmínka, reaguje na trend během dne
Druhá podmínka: value >= agregated_average * 2.5
Pokud je hodnota 2.5× vyšší než dlouhodobý průměr (z agregace)
Stabilnější podmínka, záchytná síť
-> ano
dynamic_min_multiplier - jak se to pocitalo?
Replacement se dělá z REFERENCE - je OK, ale na zaklade nepeakovych hodnot... tzn jak bylo puvodne planovano, pokud je peak, dopocita se z prechozich hodnot

Skvělé, teď vidím jasně. Pojďme si to potvrdit krok za krokem, aby nebylo žádné zmátení:

BASELINE_MEAN ✅ Chápu:

7-denní rolling (nebo spíš 10 týdnů) průměr pro konkrétní kombinaci (den_týdne, hodina, čtvrt, namespace)
Ukládá se do aggregation_data a neustále se aktualizuje
Klíč: Počítá se POUZE z non-peak hodnot (pokud je to peak, nepadá do průměru)
Výsledek: Stabilní, bezpečný, dlouhodobý baseline
Dvě podmínky pro detekci:

Volatility threshold: ratio >= baseline_mean * 3.0 (jestli je trend daný den vysoký, reaguje na denní volatilitu)
Absolute threshold: value >= aggregation_data.mean * 2.5 (bezpečnostní síť - pokud je absolutně vysoká)
➡️ is_peak = (ratio >= 3.0) OR (value >= aggregation_data.mean * 2.5) ✅

Replacement:

Z REFERENCE je OK
ALE: REFERENCE se počítá z posledních 3 non-peak hodnot, ne z jakýchkoli hodnot!
To je ten problém - pokud jsou v těch 3 okénkách peak hodnoty, reference je znehodnocená
Teď otázka: dynamic_min_multiplier: 2.5 - co to přesně bylo?

Myslím, že to bylo původně fallback, když nebyl baseline dostupný? Nebo to bylo na něco jiného?

Podle mě by mělo být:

Pokud ratio >= 3.0 → je to peak
Pokud value >= aggregation_data.mean * 2.5 → je to peak
Nic víc, nic míň

Klíč: Počítá se POUZE z non-peak hodnot (pokud je to peak, nepadá do průměru) - ano ale aby se nestalo, ze se sejde ve stejne konkrétní kombinaci (den_týdne, hodina, čtvrt, namespace) ze tam budou chybet data, chtelo by to peakove hodnoty nahradit stejnou referencni hodnotou jako se uz pouziva, protoze kdyby byly peakove hodnoty, umi byt extremni, prumer by sel hodne nahoru, kdyz by byly peakove hodnoty vynechany, tak bude dost prazdnych oken
-Absolute threshold: - ma byt prumerna konstanta pro konkrétní kombinaci (den_týdne, hodina, čtvrt, namespace) - abychom spravne zvolili multiplayer, tak mi ukaz pro konkrétní kombinaci (den_týdne, hodina, čtvrt, pro kazdne NS vzorky po 2 hodinach, tzn prumer z peak data raw bude stacit (ze kterych se to pocita)
takze hodiny 1,3,5,7,9,11,13,15,17,19,21,23 prumer z nekolika hodnot (mame mit 4) pro kazde NS, at mam prehled

a ano ➡️ is_peak = (ratio >= 3.0) OR (value >= aggregation_data.mean * 2.5) ✅

"ALE: REFERENCE se počítá z posledních 3 non-peak hodnot, ne z jakýchkoli hodnot!
To je ten problém - pokud jsou v těch 3 okénkách peak hodnoty, reference je znehodnocená"
co je tohle za blbost? pokud se reference pocita z non-peak hodnot, tak pokud jsou v těch 3 okénkách peak hodnoty, maji byt nahrazeny tedy jsou non-peak a reference nemuze byt znehodnocena

Máš samozřejmě pravdu! Omlouvám se za zmätení.

Pojďme jasně:

BASELINE_MEAN:

Počítá se z non-peak hodnot = pokud je to peak, NAHRADÍ se referenční hodnotou
Takže máme data, jen s korektivou
Non-peak hodnoty padnou do baseline, peaky (s replacement) také padnou, jen korrigované ✅
REFERENCE:

Počítá se z posledních 3 non-peak hodnot
Pokud jsou v těch 3 okénkách peaky → jsou NAHRAZENY (máme replacement_value)
Takže reference je VŽDY z korrigovaných hodnot (replacement_value pokud existuje, jinak original_value)
Reference nemůže být znehodnocena, protože peaky jsou nahrazeny! ✅


jeste ti do detailu vysvetlim:
"REFERENCE:
Počítá se z posledních 3 non-peak hodnot
Pokud jsou v těch 3 okénkách peaky → jsou NAHRAZENY (máme replacement_value)"
-> Počítá se z posledních 3 non-peak hodnot tzn nemuzou byt v tech oknech peaky, pokud tam byly, jsou uz nahrazeny!
respektive pokud se najde peak, ihned se nahradi replacement_value, ktera se pouzije jako reference tak i pro BASELINE_MEAN
Takže reference je VŽDY z original_value pokud nebyla detekovana jako peak a pokud byla detekovana jako peak, tak je manisto ni korrigovana hodnota - replacement_value

Perfektně chápám! ✅

REFERENCE = posledních 3 non-peak hodnoty = vždy korrigovaná:

Pokud to nebylo peak → original_value
Pokud to BYLO peak → replacement_value (místo original_value)
→ Reference je VŽDY správně korrigovaná
BASELINE_MEAN = všechny non-peak hodnoty = vždy korrigovaná:

Stejná logika - peaky jsou nahrazeny replacement_value
Počítá se z korrigovaných dat
Replacement_value se tedy používá na dvou místech:

Jako REFERENCE pro ratio výpočet
Padá do BASELINE_MEAN (budoucí detekce)
