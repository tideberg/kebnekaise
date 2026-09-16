# Kebnekaise

Lokal temperatur- och CO₂-historik för kontoret. Tio mätpunkter, en tydligt märkt
simulering och samma lagring/analys när verkliga sensorer ansluts.

Koden publiceras under [MIT-licensen](LICENSE). Alla rumsnamn, volymer,
beläggningar och mätvärden i repot är syntetiska exempel; verkliga
miljökonfigurationer och data ska hållas utanför versionshanteringen.

**M1 är körbar på den här datorn.** Python 3.11+ och dess standardbibliotek är
hela körmiljön. Ingen `pip install`, npm, Docker, molntjänst eller extern
JavaScript behövs. `just` är en valfri kommandogenväg. Det här är ett Git-repo;
lokala databaser, exporter, backuper, credentials och miljöspecifika
installationsfiler ska ligga utanför versionshanteringen.

Matter-stöd för en Pi-pilot finns i repot, med automatisk start av enbart
insamling och daglig backup. Dashboarden startas tidsbegränsat vid behov och
nås endast genom en lokal SSH-tunnel. Sensorvärden och Matter-kontrollerns
identitet är miljöspecifika och
ska hållas utanför repot. Se [Pi: installation och SSH](docs/PI-SETUP.md) för
den generella anslutnings- och driftguiden.

## Starta

```sh
cd /path/to/kebnekaise
just demo
```

Öppna **[http://127.0.0.1:8840](http://127.0.0.1:8840)**. `Ctrl-C` stoppar
insamling och dashboard. Databasen finns kvar. Nästa start återanvänder den.
Stängd webbläsare stoppar inte insamlingen; sovande dator gör det.

Utan Just:

```sh
python3 -m kebnekaise seed --days 28
python3 -m kebnekaise run
```

`seed` lägger till historik och skriver aldrig över en befintlig tidsstämpel.
Det får bara köras med demokonfigurationen. Vanlig `run` fyller inte igen
databortfall retroaktivt.

## Prova M1

1. Växla mellan CO₂ och temperatur, 24 timmar/7 dagar/28 dagar och egen period.
2. Slå på/av vardagar 08–17. Klockslag för analysen är Europe/Stockholm.
3. Välj **Nordost 3**: modellen innehåller återkommande sämre ventilation.
4. Jämför **Sydväst 3 · fönster** och **Sydväst 3 · inre del** i temperaturvyn.
5. Välj **Luncharean**: lunch, fika och onsdagspresentationer ger olika förlopp.
6. Välj **Nordost 5**, en vardag cirka 13:00: ett simulerat avbrott ger sämre täckning.
7. Notera en upplevelse i dashboarden. Händelsen sparas lokalt med tid och plats.
8. Välj källan **Verkliga · Matter** eller **Verkliga · HA** i demon: vyn ska visa att verkliga data saknas.

Detta är modellerade exempel, **inte belägg för hur ert kontor fungerar**.
Modellen är inte kalibrerad mot ALPSTUGA eller en uppmätt planritning.

## Kommandon

```sh
just                           # hela listan med beskrivningar
just test                      # statistik, lagring, HTTP-säkerhet och adaptertest
just check                     # databasens integritet och antal värden per källa
just seed 7                    # lägg till sju dagars syntetisk historik
just run                       # insamling + lokal dashboard, utan seed
just view                      # enbart dashboard
just report                    # exports/rapport.md, vald periods statistik
just export                    # exports/readings.csv, samtliga råvärden
just backup                    # exports/backup.sqlite3, konsistent backup
just note warm sw-3a 'Varmt efter lunch'
just hil-demo                  # NE-1 via mock-HA, övriga nio via simulator
just pi-check                  # lokal, skrivskyddad inventering inför Pi-installation
```

Export, rapport och manuell backup vägrar skriva över en existerande målfil.
Ange ett nytt filnamn, till exempel `just report exports/rapport-2026-09-15.md`.
Databas, exporter, tokens, lokala konfigurationer och byggartefakter är Git-ignorerade.

HIL-demon kör två lokala processer och öppnas på
[127.0.0.1:8842](http://127.0.0.1:8842). Den testar HA:s REST-format och hela
insamlingskedjan, **inte radio, Matter-parning eller en riktig Home Assistant**.
Källan heter `mock` och kan aldrig misstas för `ha` i databasen. Se
[HIL och första sensorn](docs/HIL.md) för separata felfall och verklig inkoppling.

## Från demo till verklig mätning

| Miljö | Konfiguration | Databas | Källor |
|---|---|---|---|
| M1, komplett demo | `config/demo.json` | `data/demo.sqlite3` | 10 simulation |
| Adaptertest | `config/hil.json` | `data/hil.sqlite3` | 1 mock + 9 simulation |
| Importerad tidsserie | `config/replay.json` | `data/replay.sqlite3` | replay |
| Matter-pilot | kopia av `config/matter-pilot.example.json` | på Pi: `/var/lib/kebnekaise/pilot.sqlite3` | matter |
| Målmiljö | kopia av `config/office.example.json` | `data/office.sqlite3` | ha, matter eller disabled |

Office-exemplet har avsiktligt alla mätpunkter **disabled** tills verkliga
entity-id:n är identifierade. Byt en mätpunkt till `ha` och ange dess två
entity-id:n. Kör sedan:

```sh
just run config/local-office.json data/office.sqlite3
```

HA-token läses ur miljövariabel, aldrig från webbläsaren. Vid nätverksanslutning
till HA krävs verifierad HTTPS eller en SSH-tunnel till loopback. Konfiguration
och databas måste ha samma läge: en demodatabas kan inte bli produktionsdatabas.

## Design och drift

- [Koncept, mätplatser och milstolpar](docs/CONCEPT.md)
- [Systemdesign, datamodell och beräkningar](docs/DESIGN.md)
- [Pi-installation, Home Assistant och drift](docs/OPERATIONS.md)
- [Matter-adaptern: avläsning, tidsmärkning och drift](docs/MATTER-COLLECTION.md)
- [Förstudie: lättare Matter-lösning för Pi 3 utan Home Assistant](docs/MATTER-LITE.md)
- [Simulering, HIL och första riktiga sensorn](docs/HIL.md)
- [Säkerhetsarkitektur och integrationsunderlag](docs/SECURITY.md)
- [Rapportera säkerhetsproblem](SECURITY.md)
- [Verifierade källor och kvarstående osäkerheter](docs/SOURCES.md)
- [M1-verifiering](docs/M1-VERIFICATION.md)

**Hårdvaruspår:** återanvänd en kompatibel Apple TV/HomePod som Thread Border
Router om en sådan finns. Annars är Home Assistant Connect ZBT-2 i Thread-läge
vårt förstahandsval. ZBT-2 är en USB-radio; Home Assistant + OpenThread Border
Router behövs också. Apple TV kan sköta Thread utan en egen tvOS-app.

**Plattform:** Pi OS Lite räcker för loggern. Home Assistant OS på en Pi 4/5 eller
mini-PC är det enklaste *officiellt stödda* Matter-spåret. För samma dator med
HA OS finns en förberedd, portlös logger-app under `deploy/ha-app`; den ger
dagliga SQLite-kopior som kan öppnas i dashboarden på din dator. Linux med
systemd ger även en tidsbegränsad dashboard via SSH-tunnel vid behov. Den
faktiska hårdvaran,
värdnamnet och provdriften dokumenteras lokalt per installation. HA-appens
container är ännu inte verifierad.

Dashboarden och Matter-serverns administrations-API binder enbart
**127.0.0.1**. De saknar publiceringsläge. Matter- och
nätverksverifiering görs i målmiljön; nätverksnamn, adresser och mätdata ska inte
skrivas in i detta repo.
