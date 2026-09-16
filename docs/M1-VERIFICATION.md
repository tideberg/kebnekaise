# M1-verifiering

Genomförd 15 september 2026 på utvecklingsdatorn, macOS/arm64,
Python 3.14.4, Just 1.58.0. Körmiljökravet är Python 3.11+ men en separat
3.11-körning och Pi-drift har inte gjorts. Docker användes inte.

## Resultat

| Kontroll | Resultat |
|---|---|
| `just test` | **33 tester passerar**, cirka 3,6 s; även Python-kompilering |
| `node --check kebnekaise/web/app.js` | Godkänd syntax; Node är endast ett utvecklingsverktyg |
| Demo, 28 dagar | Cirka 805 000 rader vid generering; tio platser och två storheter |
| SQLite integrity_check | `ok` för demo, HIL, återläst backup och replay |
| Full CSV-export → replay | **805 860 rader** återimporterade, enbart källa `replay` |
| Online-backup | Konsistent kopia skapad medan insamlingen körde |
| Överföringspaket | CSV och SHA-256-manifest skapade i ZIP; ingen uppladdning |
| Full HIL-start | Två lokala processer; NE-1 genom HA-adapter som `mock`, nio som `simulation` |
| Bortfallstest | HA otillgänglig → inga nya värden för den punkten; ingen simulator-fallback |
| Lyssningsadress | Egna servrar binder bara 127.0.0.1 |
| Webbläsare, desktop | Granskad layout; temperatur/CO₂, rumsval, tidsperiod och arbetstidsfilter |
| Verklig källa i ren demo | 0/10 platser med verkliga data; tom graf/statistik |
| Observation | Testobservation sparad via UI; klick öppnar rätt rum och tidsfönster |
| Smal vy, 390 px | Granskad graf och kontroller; ingen horisontell sidöverströmning |

Testerna täcker bland annat idempotens, atomiska importer även efter flera
skrivblock, fel enheter, NaN/framtida/stale-värden, separata källor, tidsviktad
statistik, saknad tid, sommar-/vintertid, read-only-läsning, insamlingslås,
backupåterställning och rotation, Host/Origin/CSRF samt begränsade HTTP-anrop.

Demoporten ändrades till **8840** för att undvika portnumret som ett annat
befintligt lokalt verktyg använde. Det verktyget ändrades inte.

## Lokala leverabler

- `data/demo.sqlite3`: körande demo, med fortsatt simulerad insamling.
- `data/hil.sqlite3`: programvarutest av blandad insamling.
- `data/replay.sqlite3`: hela CSV-exporten importerad som replay.
- `exports/M1-rapport.md`: analysrapport under arbetstid.
- `exports/M1-readings.csv`: råexporten som verifierades.
- `exports/M1-backup.sqlite3`: verifierad SQLite-kopia.
- `exports/M1-demo.zip`: överföringspaket med syntetiska data, uttrycklig source-filter.

Dessa data/artefakter är Git-ignorerade. Källkod, konfigurationsexempel,
Justfile, dokumentation och tester ingår i repot. Demons antal levande rader
ökar efter kontrollen. Ingen verklig kontorsmätning har gjorts.

## Kvar till senare milstolpar

M1 verifierar vår egen programvara och HA-REST-adaptern mot mock. Följande
kräver verklig miljö och har **inte** verifierats: Pi-installation/omstart/
strömförsörjning, systemd-härdning på Linux, byggd HA-app i Supervisor,
Matter/Thread-parning, firmware, sensornoggrannhet, rapporteringskadens,
Apple-TV-OTA, kontorets IPv6/mDNS och tio punkters radiotäckning. HA-appens
Python-image väljs och låses vid det faktiska byggsteget, inte med ett påhittat
digest i M1. Dagliga snapshots i HA OS-spåret är inte ett liveflöde till datorn.

Nästa test finns i [driftinstruktionerna](OPERATIONS.md) och
[HIL-planen](HIL.md). M2 börjar med identifiering av Pi-modell och val av OS.
