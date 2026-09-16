# Installation och drift

M1 kör på macOS utan installation av tredjepartspaket. Instruktionerna nedan
är för M2/M3 och beskriver både Pi OS- och Home Assistant-spåren. En Pi-pilot
kan köra loggern med automatisk start, daglig SQLite-backup och en fristående
Matter-kontroller. Värdnamn, användare, nätverksuppgifter, statusrapporter och
mätdata är lokala installationsdata och ska dokumenteras separat.
Se [Pi: installation och SSH](PI-SETUP.md).

## Val av OS för hårdvaran

**Pi 4/5 eller lämplig mini-PC:** Home Assistant OS är vårt förstahandsval för
en enkel, officiellt stödd Matter-installation. HA hanterar Matter Server och,
om ZBT-2 används, OpenThread Border Router. Den egna loggern körs som en lokal
HA-app utan publicerade portar. Dashboarden kan läsa en nedhämtad SQLite-kopia
på din dator. Se HA-appsteget längre ned.
[HA:s Pi-installation](https://www.home-assistant.io/installation/raspberrypi/)

**Äldre Pi eller önskemål om vanlig Linux:** Raspberry Pi OS Lite med Python
3.11+ räcker för vår logger och en levande dashboard via SSH-tunnel. Använd
64-bitars OS om modellen stöder det. En äldre modell kan användas som logger
även om HA/Matter behöver en annan, stödd värd. Vi installerar inte en gammal,
osupportad HA-version för att passa gammal hårdvara.
[Raspberry Pi OS](https://www.raspberrypi.com/software/operating-systems/)

Home Assistant Container + separat Matter Server på Linux är möjligt men
anges som ett **osupportat Matter-driftsätt** i HA:s dokumentation. Vi väljer
inte det som standard enbart för att slippa ett OS-byte. Om M2 börjar med Pi OS
och vi senare väljer HA OS flyttar vi först data med verifierad backup.
[Matter-installation](https://www.home-assistant.io/integrations/matter/)

## Pi OS Lite: första start

1. Hämta Raspberry Pi Imager från leverantören och välj rätt modell/OS. Kontrollera
   att rätt kort är målet innan skrivning; flashningen raderar kortet.
2. Ställ in värdnamn, ett eget användarkonto, Wi-Fi/land och nyckelbaserad SSH.
   Lägg inga Wi-Fi-lösenord eller privata SSH-nycklar i detta repo.
3. Starta Pi:n, anslut lokalt och kontrollera `date -Is`, `timedatectl status`,
   `python3 --version`, `df -h` och modell. Systemklockan måste vara synkroniserad.
4. Installera tillgängliga säkerhetsuppdateringar från OS:ets officiella förråd.
   Loggern behöver bara systemets Python, SQLite-stöd och `tzdata`.
5. Kopiera en granskad version av repot via SSH/USB. Kör i dess katalog:

   ```sh
   python3 scripts/pi_check.py
   python3 -m unittest discover -s tests -v
   python3 -m kebnekaise seed --days 2
   python3 -m kebnekaise run
   ```

6. På din dator, ersätt `ANVANDARE` och `PI_ADRESS` med faktiska värden:

   ```sh
   ssh -N -L 127.0.0.1:8840:127.0.0.1:8840 ANVANDARE@PI_ADRESS
   ```

   Öppna [127.0.0.1:8840](http://127.0.0.1:8840). Stoppa en eventuell lokal
   demo på samma port först. Ingen dashboardport behöver öppnas på Pi:ns Wi-Fi.

## Pi OS: systemd

Filerna i `deploy/systemd` är förberedda för en egen användare med namnet
`kebnekaise`. Utför på Pi:n, efter test och granskning av konfigurationen:

```sh
sudo useradd --system --home /var/lib/kebnekaise --shell /usr/sbin/nologin kebnekaise
sudo install -d -o root -g root -m 755 /opt/kebnekaise
sudo install -d -o root -g kebnekaise -m 750 /etc/kebnekaise
git archive HEAD | sudo tar -x -C /opt/kebnekaise
sudo install -o root -g kebnekaise -m 640 config/local-office.json /etc/kebnekaise/office.json
sudo install -m 644 deploy/systemd/kebnekaise.service /etc/systemd/system/
sudo install -m 644 deploy/systemd/kebnekaise-backup.service /etc/systemd/system/
sudo install -m 644 deploy/systemd/kebnekaise-backup.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now kebnekaise.service kebnekaise-backup.timer
```

Om användaren redan finns ska `useradd` hoppas över. För M2 kopieras
demokonfigurationen till `/etc/kebnekaise/demo.json` och båda drop-in-filerna
under `deploy/systemd/demo/` installeras i motsvarande `.service.d/`-kataloger
under `/etc/systemd/system/`. De väljer `demo.sqlite3` och `backups-demo`.
En Matter-pilot kan i stället använda `deploy/systemd/pilot/`, en separat
konfiguration, `pilot.sqlite3` och en separat backupkatalog; se
[Matter-insamling](MATTER-COLLECTION.md).
**Byt aldrig bara läge på en
fylld demodatabas.** En riktig pilot behöver egen konfiguration och databas;
granska även backuptjänstens sökväg när drop-in-filerna ändras eller tas bort.

Med HA på en annan värd: ange en verifierad HTTPS-adress i konfigurationen och
lägg token i `/etc/kebnekaise/credentials.env`, enbart läsbar av root (`0600`).
Formatet är `KEBNEKAISE_HA_TOKEN=...` utan att token skrivs i kommandoraden.
systemd läser filen och sätter miljövariabeln. Token ska inte hamna i Git,
rapporter, webbläsare eller delade loggar.

```sh
systemctl status kebnekaise.service
journalctl -u kebnekaise.service --since today
sudo systemctl restart kebnekaise.service
```

Tjänsten kör som egen användare, återstartar vid fel, har skrivskyddad kod och
skyddad datakatalog. Inga brandväggsregler, port-forwarding eller nätbryggor
ändras av repot. `systemd-analyze verify` och omstartstest görs på den riktiga
Pi:n; macOS kan inte verifiera systemd-driften.

## HA OS: portlös logger-app

Detta är en förberedd bygg- och installationsväg, **inte en container som har
provkörts i M1**. Den kräver en officiell Python-image och HA:s appsystem.
Ingen community-app, HACS-plugin eller Python-paket behöver laddas in.

1. Installera HA OS via dess officiella instruktioner. Behåll HA-administrationen
   lokal och lösenordsskyddad; ingen HA Cloud, extern DNS eller routerpublicering.
2. Installera officiell Matter-integration/Matter Server. Med ZBT-2: konfigurera
   den som **Thread**, med officiell OpenThread Border Router-app. Med en redan
   fungerande Apple TV-border router behövs ingen ZBT-2/OTBR på Pi:n.
3. Para första sensorn via HA Companion på telefonen. Inventera entity-id:n.
4. Förbered `office.json`, läge production. Lägg den i
   `/share/kebnekaise/office.json` via HA:s lokala fil-/terminalåtkomst.
5. Välj en underhållen, exakt Python-version >=3.11 från **Docker Official Image
   python** (`docker.io/library/python`). Läs och spara multi-arkitekturmanifestets
   SHA-256 från registret. Vi hämtar inte en rörlig `latest` under installation.
   Verifiera att vald slim-image innehåller systemets tzdata/Europe/Stockholm.
6. På utvecklingsdatorn, med faktisk tagg och digest:

   ```sh
   python3 scripts/package_ha_app.py \
     --python-image 'docker.io/library/python:3.X.Y-slim-bookworm@sha256:DIGEST'
   ```

   Platshållaren ovan **ska inte köras oförändrad**; generatorn vägrar ogiltiga
   värden. Digest hämtas och dokumenteras när vi faktiskt bygger i M2/M3, så att
   installationen använder en då granskad version. Generatorn hämtar ingenting.
7. Kopiera den genererade katalogen `deploy/ha-app/build/kebnekaise` till
   `/addons/kebnekaise` på HA OS. Uppdatera listan över lokala appar, bygg och
   installera **Kebnekaise logger**. Den officiella images hämtning sker då.
8. Appen läser HA:s interna `/core/api/states` med Supervisor-token och lagrar
   `/data/office.sqlite3`. Den behöver `homeassistant_api` och skrivbar `share`,
   men saknar host networking, publicerade portar, ingress och enhetsåtkomst.
   Home Assistant API-token har bredare behörighet än vår enbart läsande kod;
   det är en uttrycklig kvarvarande tillitsgräns.
9. Dagliga, verifierade kopior hamnar i `/share/kebnekaise/snapshots`. Kopiera en
   snapshot och motsvarande office-konfiguration till datorn och öppna:

   ```sh
   just view config/local-office.json data/office-snapshot.sqlite3
   ```

Den vyn är en **snapshot**, inte ett liveflöde. Mätpunkterna blir korrekt märkta
som gamla när sista rapporten är äldre än åldersgränsen. Historiken förblir
läsbar. Anteckningar i en kopia stannar i kopian och synkas inte tillbaka till
HA-appen. Vill vi ha löpande användarnoteringar i den gemensamma databasen på
HA OS behövs ett senare godkänt ingress- eller importflöde. Pi OS-spåret har
redan levande noteringar via SSH-tunnel.

## Backup och återställning

```sh
just backup exports/office-2026-09-15.sqlite3 config/local-office.json data/office.sqlite3
just check config/local-office.json exports/office-2026-09-15.sqlite3
just view config/local-office.json exports/office-2026-09-15.sqlite3
```

Använd SQLite backup-API, inte en ensam filkopiering av en aktiv `.sqlite3` utan
dess WAL. En backup på samma SD-kort hjälper mot logiska misstag men inte mot
trasigt/stulet kort. För en kopia till annan godkänd lagring minst veckovis.
Automatiska dagsbackuper roterar sju markerade kopior; manuella kopior behålls.

Vid återställning: stoppa insamlaren; kontrollera backup med `check`; återställ
till en **ny databasväg** och peka tjänsten dit. Spara den gamla databasen för
felsökning. Lägesmarkering och konfiguration ska matcha. Gör återställningsprov
före kontorsdrift och efter förändrad backupmetod.

## Löpande kontroll

- Veckovis: dataluckor, sensorer med gamla värden, diskrum och extern backup.
- Vid firmware-/OS-byte: backup före, dokumenterad version efter, återanslutningstest.
- Vid flytt/kalibrering: anteckna åtgärd, device-id och ny placeringsidentitet vid behov.
- Kvartalsvis eller vid misstänkt drift: samplacering/referensjämförelse och granskad uppdatering.
- Vid avbrott: loggern återhämtar sig vid nästa poll. Saknad radiohistorik fylls inte i efterhand.
