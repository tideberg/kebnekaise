# Insamling via Matter

Logger 0.2 läser den lokala `matter-server@1.4.0` via dess WebSocket-API,
schema 13. Servern sköter parning, Thread/IP och Matter; Python sköter validering,
SQLite och analys. Den redan installerade Node.js 24-körmiljön ger adaptern
WebSocket-stöd utan extra Python-paket eller egen WebSocket-implementation.

## Konfiguration och plats

`config/matter-pilot.example.json` beskriver en neutral pilot med exempelvärden.
Ersätt node-id, endpointmappning, placering och namn i en lokal konfiguration;
de värdena hör till just den parade kontrollern och ska inte checkas in.
Vid flytt mellan miljöer skapas en ny placeringsidentitet; historik från en
annan miljö ska inte blandas in. Riktiga rum kräver inga påhittade
rumsvolymer eller beläggningsparametrar.

`matter.url` måste vara `ws://127.0.0.1:PORT/ws`. `node_path` är en absolut
sökväg till Node.js 24. Varken Matter-kontrollerns nycklar eller parningskoden
finns i loggerkonfigurationen. Webbklienten får inte nodmappning eller
körmiljösökvägar från `/api/config`.

## Vad en rad betyder

- Varje minut öppnas en tidsbegränsad anslutning och ett `read_attribute` skickas
  per nod. Ett gemensamt tidsfönster på 15 sekunder begränsar hela omgången.
  Om transportprocessen låser sig avslutar Python den efter ytterligare 5 sekunder.
- Temperatur `endpoint/1026/0` är ett heltal i hundradels °C. CO₂ läses från
  `endpoint/1037/0`; i samma svar måste `endpoint/1037/8` vara heltalet `0` (ppm).
- Källan är `matter`, tidsstämpeltypen `matter_read_received`. `ts` avser när
  svaret togs emot, **inte sensorns interna tid för en fysisk mätning**.
  `received_at` är tidpunkten då loggern lämnar den validerade omgången till SQLite.
- Oförändrade värden från nya lyckade fjärrläsningar får nya avläsningstider.
  `get_nodes`, initiala tillståndsdumpar och oombedda attributnotiser används inte.
- Saknat värde, null, fel enhet, orimligt värde eller misslyckad läsning ger
  en lucka för berörd storhet och felstatus för mätpunkten. En giltig temperatur
  kan sparas även om CO₂ saknas. Inga cachevärden eller simulerade värden ersätter
  bortfall. Nästa minut görs ett nytt försök.

Pilotens `max_hold_seconds` är 120. Analysen håller senaste giltiga avläsning
högst så länge; därefter räknas tiden som saknad. Nulägeskortet visar även
insamlarens senaste felstatus. Piloten öppnas med 24 timmar, hela dygnet och
Matter-källan vald. Tiden före första avläsningen är tom och sänker täckningen.

SQLite-schema 2 lägger till `matter` i källkontrollen. Schema 1 migreras
transaktionellt med befintliga rader, metadata och konfigurationshistorik kvar.
Okända schemaversioner avvisas. Ta backup före uppgradering. En gammal version
av loggern ska inte användas för att skriva till schema 2.

## Pi-drift och export

Installera de tre drop-in-filerna under `deploy/systemd/pilot/` i respektive
`/etc/systemd/system/*.service.d/override.conf`. Lägg den granskade konfigurationen
i `/etc/kebnekaise/pilot.json` (root:kebnekaise, 0640). De väljer en ny
`/var/lib/kebnekaise/pilot.sqlite3` och dagsbackup i `backups-pilot/pilot-DATUM.sqlite3`.
Demo-konfiguration, databas och tidigare backuper behålls separat. Loggern
återförsöker själv när Matter-tjänsten återkommer; de två tjänsterna kan startas
om oberoende av varandra.

Den ordinarie loggern kör bara `collect`. Pilotens dashboard startas separat
med `kebnekaise-dashboard.service`, använder pilotdatabasen och stoppas efter
högst två timmar.

Kör på Pi:n från `/opt/kebnekaise`, med skrivbehörighet för målfilen:

```sh
sudo -u kebnekaise python3 -m kebnekaise \
  --config /etc/kebnekaise/pilot.json --db /var/lib/kebnekaise/pilot.sqlite3 check
sudo -u kebnekaise python3 -m kebnekaise \
  --config /etc/kebnekaise/pilot.json --db /var/lib/kebnekaise/pilot.sqlite3 \
  bundle --source matter --output /var/lib/kebnekaise/pilot-export.zip
```

Välj uttryckligen `--source matter` för pilotens bundle; äldre bundle-kommandon
har `ha` som standard. CSV-export har samtliga källor som standard och behåller
källnamn och tidsstämpeltyp. Filnamn som redan finns skrivs inte över.

Daglig backup använder SQLite:s backup-API och roterar sju markerade kopior
med samma prefix. Manuell extern kopia till Macen behövs fortfarande; timern
skriver på samma SD-kort. Matter-identiteten behöver sin separata, konsistenta
backup efter ändrad parning, se [Pi-status](PI-SETUP.md).

## Verifiering

```sh
python3 -m unittest discover -s tests -v
node --test tests/matter_read.test.mjs
```

Testerna täcker bland annat gammal cache, oförändrade avläsningar, enheter,
delvisa fel, avbrott och återhämtning, CSV/backup och databasens migration med
återrullning vid fel. Praktiska driftprov och kvarstående hårdvaruprov redovisas
i [Pi-status](PI-SETUP.md). Längre drift och verkligt sensor-/Thread-bortfall
behöver verifieras med hårdvaran.
