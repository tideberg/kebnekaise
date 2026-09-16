# Pi: installation och SSH

Detta är en generell drift- och verifieringsguide för en Pi-installation.
**Värdnamn, IP-adress, användarnamn, Wi-Fi-inställningar, SSH-nycklar och
mätresultat är lokala uppgifter och ska dokumenteras utanför repot.**

| Del | Inställning |
|---|---|
| Referenshårdvara | Raspberry Pi eller annan verifierad Linux-värd; kontrollera RAM och lagring lokalt |
| Lagring | Dimensioneras för OS, SQLite-data och externa backuper; verifiera rätt mål före flashning |
| OS | Raspberry Pi OS Lite 64-bit eller annan stödd Linux-distribution |
| Kärna | Dokumentera exakt version lokalt efter installation |
| Värdnamn | `<pi-host>.local` eller annan lokal namnupplösning |
| Administratör | `<pi-user>`, med lösenordsfri sudo endast om det behövs |
| SSH | Nyckelbaserad inloggning; lösenordsinloggning avstängd |
| Ethernet | DHCP eller reserverad adress; skriv aldrig in den faktiska adressen här |
| Wi-Fi | Konfigureras lokalt; SSID och nyckel får inte läggas i repo eller rapport |
| Tid och tangentbord | Europe/Stockholm, sv_SE.UTF-8, svensk layout |

## Anslut från Macen

```sh
ssh <pi-user>@<pi-host>.local
```

Behåll nätverkskabeln ansluten vid första installationen. IP-adressen tilldelas
av nätet och kan ändras; använd lokal namnupplösning i första hand. SSH och mDNS
ska starta automatiskt efter att de verifierats på målmaskinen.

## Verifiera på Pi:n

- Nyckelinloggning fungerar även efter omstart och SSH tillåter inte lösenord.
- OS-uppdateringar är installerade och inga paketinstallationer väntar.
- Klockan är NTP-synkroniserad i tidszonen Europe/Stockholm.
- Det finns tillräckligt ledigt utrymme för SQLite-databasen och externa kopior.
- `vcgencmd get_throttled` är `0x0` på Raspberry Pi när kommandot finns.
- Kör projektets skrivskyddade `scripts/pi_check.py` och spara detaljerna i en
  lokal driftanteckning, inte i detta repo.

## Program som kör på Pi:n

Referenslayout:

| Del | Drift |
|---|---|
| Logger | `kebnekaise.service`, egen användare `kebnekaise`; ingen webbserver |
| Dashboard | `kebnekaise-dashboard.service`, manuell start, loopback och högst två timmar |
| Konfiguration och data | `/etc/kebnekaise/pilot.json`, `/var/lib/kebnekaise/pilot.sqlite3` |
| Daglig SQLite-backup | `kebnekaise-backup.timer`, lokal tid med en separat backupkatalog |
| Backupretention | Markerade dagskopior behålls enligt lokal driftpolicy |
| Demo | Separat konfiguration, databas och backupkatalog om demo körs parallellt |
| Matter-kontroller | `kebnekaise-matter.service`, egen användare `kebnekaise-matter` |
| Matter-versioner | Lås versioner i `deploy/matter/package-lock.json` och dokumentera runtime lokalt |
| Matter-tillstånd | `/var/lib/kebnekaise-matter`, rättighet `0700`; aldrig i Git |

Kör hela testsviten på målmaskinen före aktivering. Verifiera därefter att
logger, Matter-kontroller och backuptimer startar efter omstart, att dashboarden
inte startar, att databasen
har rätt läge och att en återställd kopia klarar integritetskontrollen. Spara
testresultat, loggar och kopior i lokal eller godkänd extern lagring.

### Öppna från Macen

Starta dashboarden på Pi:n först när den behövs:

```sh
sudo systemctl start kebnekaise-dashboard.service
```

Öppna därefter en lokal tunnel. Matter-porten tas bara med när kontrollerns
lokala administrationsgränssnitt verkligen behövs:

```sh
ssh -N -o ExitOnForwardFailure=yes \
  -L 127.0.0.1:8840:127.0.0.1:8840 \
  -L 127.0.0.1:5580:127.0.0.1:5580 <pi-user>@<pi-host>.local
```

- [Kebnekaise dashboard](http://127.0.0.1:8840)
- [Matter-kontroller och parning](http://127.0.0.1:5580)

Båda portarna lyssnar enbart på loopback. Dashboarden stängs automatiskt efter
två timmar och bör stoppas direkt efter användning; insamlingen fortsätter
oberoende. Tunneln kan behöva öppnas igen när klienten vaknar. Stäng en tunnel
med dess lokala kontrollsocket och stoppa dashboarden:

```sh
ssh -S /path/to/dashboard-ssh.sock \
  -O exit <pi-user>@<pi-host>.local
sudo systemctl stop kebnekaise-dashboard.service
```

### Första riktiga sensorn

Para en test-sensor via den valda Matter-borderroutern och kontrollern. Node-id,
parningskoder, controller state, firmwareversioner och sensorvärden är lokala
uppgifter. Lägg dem i en lokal konfiguration och privat driftanteckning; använd
bara neutrala exempelvärden i Git.

| Verifierad egenskap | Värde |
|---|---|
| Nod på kontrollern | `<node-id>` |
| Tillverkare och modell | Dokumenteras lokalt efter parning |
| Temperatur | Matter-attribut enligt sensorns modell; verifiera enhet lokalt |
| CO₂ | Matter-attribut enligt sensorns modell; verifiera enhet lokalt |

Verifiera att explicita `read_attribute`-svar, även oförändrade värden, blir
prover och att cachehändelser inte blir prover. Tiderna ska avse mottagning av
lässvaret om sensorns interna mättid inte kan fastställas. Konkreta värden,
tidsstämplar och exportfiler hör hemma i lokal verifieringsdata.

Skapa en konsistent backup av Matter-kontrollerns identitet, nycklar och
tillstånd med tjänsten stoppad. Förvara den i privat, Git-ignorerad lagring med
`0600` och återställ aldrig samma identitet till två aktiva controllers.
SQLite-backupen omfattar inte Matter-identiteten; ta en ny controller-backup
efter ändrad parning.

Matter-kontrollern är förberedd som prototyp enligt [förstudien](MATTER-LITE.md).
OTA och Thread-diagnostik är avstängda. Paketversioner och integritetsvärden
finns i `deploy/matter/package-lock.json`; paketens installationsskript
blockeras av den versionshanterade `.npmrc`-filen. Node 24.21.0 används som
exakt runtime-version och avbildningens SHA-256 ska kontrolleras mot Node.js
officiella `SHASUMS256.txt` före installation.

### Löpande insamling, version 0.2.0

En Matter-pilot ska använda en egen konfiguration och databas. Tjänsten gör en
explicit fjärrläsning av de mappade storheterna vid varje intervall; äldre
provavläsningar ska inte importeras som historik. Källan ska vara `matter` och
tidstypen `matter_read_received` när kontrollern inte tillhandahåller sensorns
interna mättid.

Verifiera före godkänd drift att tester, databasens integritet, källfilter,
dashboard, mottagningstider och loopback-bindning fungerar. Stoppa sedan
Matter-kontrollern kontrollerat och kontrollera att mätpunkten får felstatus,
att en lucka bevaras och att insamlingen återhämtar sig vid nästa läsning efter
återstart. Spara exakta tidsstämplar, värden och loggar i lokal verifieringsdata.

Provkör daglig SQLite-backup, checksumma, separat återställning och eventuell
ZIP-export. Mätningarnas databas och Matter-identitetens backup är separata
artefakter och ska båda förvaras utanför Git.

## Wi-Fi och nätverk

Konfigurera Wi-Fi lokalt med filrättighet `0600` och förvara SSID, lösenord,
DHCP-adresser och felsökningsloggar utanför repot. Ethernet är ett bra
förstahandsval för en Matter-kontroller på en äldre Pi. Verifiera mDNS/IPv6,
Thread-borderroutern och loopback-tunneln i målmiljön; repo:t ändrar inga
brandväggsregler, port-forwarding eller nätbryggor.

## Verifiering av startkortet

Verifiera Imager och OS-avbildning enligt leverantörens instruktioner. Kontrolläs
det skrivna systemet och dess anpassningar efter flashning. Jämför lokala
`user-data`/`network-config`-filer och kontrollera SSH/mDNS innan kortet tas i
drift.

Installationsfiler, kontrollsummor och eventuella nätverkskonfigurationer ska
förvaras i lokal, privat lagring. Lägg aldrig Wi-Fi-lösenord eller privata
SSH-nycklar i Git-ignorerade artefakter som senare kan delas av misstag.

## Om kortet behöver skrivas om från denna Mac

Om Imagers kommandoläge fastnar vid avmontering kan macOS behöva en grafisk
administratörsbekräftelse. Identifiera alltid kortet på nytt före en eventuell
omskrivning och håll lokala avbildningar, kontrollsummor och nätverksfiler
utanför repot.
