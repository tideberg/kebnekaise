# Koncept: förstå kontorets inomhusklimat

Målet är jämförbart underlag för återkommande upplevelser av värme, kyla och
instängd luft. Mätningar ska hjälpa oss att undersöka orsaker och utvärdera
åtgärder. En avvikande upplevelse blir inte ogiltig för att lufttemperaturen
ligger inom ett valt intervall.

Mätplanen nedan är ett syntetiskt designexempel. Områden, rumsvolymer,
beläggning och placeringar beskriver inte en viss arbetsplats.

## Mätplan

| Område | Rum | Mätpunkter | ID |
|---|---:|---:|---|
| Nordost | 5 | 5 | ne-1 … ne-5 |
| Sydväst, två mindre rum | 2 | 2 | sw-1, sw-2 |
| Sydväst, stort rum | 1 | 2 | sw-3a, sw-3b |
| Lunch/fika/presentationer | 1 | 1 | lunch |
| **Totalt** | **9** | **10** | |

Room-id och placeringens id är separata: sw-3a och sw-3b tillhör samma rum.
Rumsnamn, volymer och beläggning i konfigurationen är tills vidare antaganden.
Byt till arbetsplatsens faktiska benämningar när placeringarna bestäms.

ALPSTUGA mäter enligt IKEA CO₂, PM2,5, temperatur och luftfuktighet och använder
Matter over Thread. M1 lagrar de två efterfrågade storheterna temperatur och CO₂.
Luftfuktighet och partiklar kan läggas till senare om de behövs. USB-C-kabel och
laddare ingår inte. Produktpriset kontrollerades till 299 kr den 14 september
2026: tio sensorer blir **2 990 kr inklusive moms**, plus strömförsörjning,
eventuell Thread-radio, Pi-nätdel och lagring. [IKEA](https://www.ikea.com/se/sv/p/alpstuga-luftkvalitetsmaetare-smart-50604187/)

En lämplig införandeordning är att prova en sensor innan resterande beställs.
Då verifieras temperatur/CO₂-entiteter, rapporteringstakt, återanslutning och
avvikelse mot ett referensinstrument.

## Vad vi vill kunna se

- Dygns- och veckomönster: när startar och slutar avvikelserna?
- Skillnad mellan nordost och sydväst samt de två delarna av stora rummet.
- Lunch/fika/presentationers mönster och återhämtningen efteråt.
- Observationer vid en konkret tidpunkt: varmt, kallt, instängd luft, vädring.
- Före/efter en ventilationsändring, med motsvarande tider och verksamhet.
- Datatäckning och fel: vad vet vi faktiskt, och var saknas underlag?

Samla minst några normala arbetsveckor före slutsatser; längre historik behövs
för säsongsmönster. Jämför med liknande väder och användning. Den nuvarande
simulatorn täcker vardagsmönster; den innehåller ingen validerad årsmodell.

## Referenser och placering

Dashboardens 1 000 ppm är en analysreferens för att uppmärksamma ventilation,
inte ett larm för akut fara eller ett bevis på komplett luftkvalitet. Folkhälso-
myndighetens vägledning använder nivån som en möjlig indikation på behov av
ytterligare kontroll. [Vägledning](https://www.folkhalsomyndigheten.se/regler-och-tillsyn/tillsynsvagledning-och-stod/halsoskydd-vagledning-och-tillsyn/vagledning-om-ventilation/)

Vi visar 20–24 °C som redigerbart analysintervall. Arbetsmiljöverket anger
normalt 20–24 °C vintertid och 20–26 °C sommartid vid lätt, stillasittande arbete,
men bedömningen beror på flera faktorer. ALPSTUGA mäter inte operativ temperatur,
drag eller strålning från ett kallt fönster.
[Termiskt klimat](https://www.av.se/inomhusmiljo/temperatur-och-termiskt-klimat-pa-arbetsplatsen/bedom-det-termiska-klimatet/)

Placera stabilt vid representativ vistelse-/andningshöjd, med luft runt sensorn,
bort från direkt sol, element, varm elektronik, tilluftsdon och direkt utandning.
Dokumentera höjd, avstånd, ungefärligt område och sensorns serienummer. Prova två
lägen i luncharean om ett enda värde inte är representativt. HSE beskriver
praktiska begränsningar och placering för CO₂-mätning.
[CO₂-monitorer](https://www.hse.gov.uk/ventilation/using-co2-monitors.htm)

Samplacera sensorerna före utrullning och jämför över minst ett normalt dygn.
Dokumentera individuella avvikelser; ändra inte råvärden eller en kalibrerings-
inställning utan verifierad metod för aktuell firmware. Temperatur nära sensorns
elektronik och möjlig CO₂-baslinjekalibrering ska utvärderas praktiskt.

## Milstolpar och godkännandekriterier

| Milstolpe | Leverans | När den kan godkännas |
|---|---|---|
| **M1 – denna dator** | Simulering, DB, UI, rapport/export, backup, adapter och mock-HA, runbooks | Reproducerbar start; 10 punkter; verifierade luckor och källor; tester och granskad UI |
| **M2 – Pi** | Valt OS, nyckelbaserad adminåtkomst, tidsynk, automatisk start, lagring och backup | En omstart och minst 24 h simulering på Pi; återläst backup; inga publika dashboardportar |
| **M3 – en sensor** | ALPSTUGA, border router, Matter-kontroller och entity-mappning | 48–72 h logging; både storheter; dokumenterad rapportering; ström-/nätbortfall och återkomst; referensjämförelse |
| **M4 – målmiljön** | Tio märkta placeringar och driftrutin | Alla riktiga punkter; minst fem arbetsdagar med överenskommen täckning; återläst extern backup; kontaktperson och nätåtkomst fastställda |

Täckningsmål vid M3/M4: preliminärt minst 95 % under arbetstid, bedömt med
**verifierad** rapporteringsfrekvens och åldersgräns. En 60-sekunders poll är inte
ett löfte om en ny fysisk mätning varje minut. Det är en hypotes att dessa
konsumentsensorer är tillräckliga för trendmätning; M3 prövar den.
