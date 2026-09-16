# Simulering och stegvis inkoppling

## Vad modellen gör

`kebnekaise/simulation.py` beskriver nio rum och tio mätplatser. CO₂ följer en
enkel massbalans för ett välblandat rum:

```text
dC/dt = G/V + ACH × (C_ute − C)
C(t+dt) = C_jämvikt + (C(t) − C_jämvikt) × exp(−ACH × dt)
```

Enheter konverteras i koden: liter CO₂/s/person till m³/h och därefter ppm/h.
Scenariots antaganden är 430 ppm utomhus och 0,0045 liter/s/person. NIST visar
varför CO₂-generering beror på bland annat aktivitet och människors egenskaper;
vårt fasta värde är en förenkling.
[NIST](https://www.nist.gov/publications/carbon-dioxide-generation-rates-building-occupants)

Temperatur är ett första ordningens förlopp mot ett börvärde med bidrag från
sol och beläggning. NE får morgonsol, SW eftermiddagssol. Stora SW-rummets två
punkter delar samma rumstillstånd men har en antagen lokal temperaturskillnad.
Lunch/fika samt onsdagspresentationer ger beläggningspulser. NE-3 har vissa
vardagar lägre antagen luftväxling. NE-5 har en 25-minuters paus klockan 13:00.
Hashbaserat, litet brus gör körningen reproducerbar för samma seed och tidsföljd.

Detta är **syntetiska rumsscenarier**, inte ALPSTUGA:s sensorfysik eller en
modell validerad för era lokaler. Ingen öppen råtidsserie med verifierad
proveniens hittades vid M1-sökningen. Grafer och användarberättelser från nätet
används inte som kalibreringsdata. Ingen mätdata har hittats på, eller fått en
falsk källa. Se [sökunderlag](SOURCES.md).

## Hela kedjan utan hårdvara

```sh
just hil-demo
```

På [127.0.0.1:8842](http://127.0.0.1:8842) kommer NE-1 genom samma REST-adapter
som senare ska läsa riktig HA. Mock-servern har en slumpad token som enbart
lever i de startade processernas miljö. Övriga nio punkter fortsätter simuleras.
`Ctrl-C` stoppar båda processerna. Demons fulla historik är separat från HIL:s
live-databas.

För manuellt felfall, skapa samma testtoken i **båda terminalernas miljö**.
Detta är en uttryckligen ofarlig lokal testtoken; använd inte en riktig HA-token.

Terminal 1:

```sh
export KEBNEKAISE_HA_TOKEN=local-test-only
just mock-ha stale
```

Terminal 2:

```sh
export KEBNEKAISE_HA_TOKEN=local-test-only
just run config/hil.json data/hil.sqlite3 8842
```

Byt `stale` mot `offline`, `bad-unit` eller `none` och starta om mock-servern.
NE-1 ska sluta få nya värden, märkas med lucka och därefter återhämta sig när
friska data återkommer. Nio andra punkter fortsätter. Inga värden för NE-1 ska
plötsligt byta källa till simulation. Automatiska tester täcker samma beteende.

Detta är ett programvarutest av gränssnittet, inte en komplett Matter-simulator.
Thread-radio, parning, mesh-räckvidd, firmware och strömavbrott på sensorn kan
bara verifieras med hårdvaran.

## Första riktiga sensorn

1. Välj en befintlig kompatibel Apple TV/HomePod som border router, eller ZBT-2
   + OpenThread Border Router. Installera HA:s Matter-kontroller.
2. Anslut ALPSTUGA till USB-ström och para via HA:s Companion-app. Har sensorn
   först lagts i Apple Hem kan den delas till HA genom Matter multi-admin;
   följ HA:s dokumenterade delningsflöde. Border routern routar paketen och HA
   blir en egen Matter-kontroller – Apple TV erbjuder inte vår egen REST-logger.
3. I HA, kontrollera temperatur/CO₂-entiteter och enheter. Hitta verkliga id:n;
   anta inte att namnen i nedanstående exempel stämmer.
4. Kopiera `config/office.example.json` till `config/local-office.json` och ändra
   NE-1 ungefär så här. Övriga punkter är fortsatt disabled:

   ```json
   {
     "id": "ne-1",
     "name": "Nordost 1",
     "room": "ne-1",
     "zone": "Nordost",
     "provider": "ha",
     "device_id": "ANGE_SERIENUMMER_ELLER_ASSET_ID",
     "entities": {
       "temperature": "sensor.DET_VERKLIGA_TEMPERATUR_IDT",
       "co2": "sensor.DET_VERKLIGA_CO2_IDT"
     }
   }
   ```

   Platshållarna är inte giltiga entity-id:n och avvisas tills de ersätts.
   I lokal Pi/Linux-körning anger du rätt `home_assistant.url` och tokenmiljö.
   I HA OS-appen använder runnern i stället HA:s interna Supervisor-API.
5. Kör `just collect-once config/local-office.json data/office.sqlite3`, sedan
   `just run config/local-office.json data/office.sqlite3`. Kontrollera att källa
   **Verklig** visas och att exporter innehåller `source=ha`.
6. I pilot kan `mode=pilot` i en **egen** konfiguration/databas användas för en
   verklig punkt + nio simulerade. Använd aldrig skarp office-databas för blandad
   demonstration. Nästa sensor kopplas in genom en konfigurationsändring och
   omstart, inte en kodändring.

## Acceptanstest med hårdvara

| Test | Förväntat resultat / vad vi dokumenterar |
|---|---|
| Normal drift 48–72 h | Båda storheter finns; faktiskt rapportintervall och fördröjning kända |
| Oförändrad temperatur | HA-last_reported/last_updated granskas; samma gamla värde får ingen ny polltidsstämpel |
| Dra ur sensorström | Bortfall blir synligt; ingen simulerad ersättning; återanslutning utan dataradering |
| Starta om HA/border router/Pi | Loggern återkommer; korrekta källor och UTC-tider; inga dubbla nycklar |
| Jämför display/HA/export | Rätt entity, storhet och enhet; fördröjning dokumenterad |
| Lånat referensinstrument | Temperatur/CO₂-avvikelse och testförhållanden dokumenteras |
| Gäst-Wi-Fi | Lokal kommunikation redan visad av quiz; mDNS, lokal IPv6 och parning verifieras nu |
| Fysisk utplacering | Stabil kommunikation på alla punkter; sensorer skyddade mot direkt sol/utandning |

Om rapporteringen är långsammare än väntat justeras intervallet/åldersgränsen
efter observation, utan att äldre data etiketteras om. Vid behov kompletteras
adaptern med HA-historikhämtning eller händelseström innan M4.

## Replay av insamlad tidsserie

CSV med `timestamp,sensor,metric,value` och explicit tidszon kan importeras.
Ordinarie export har dessutom källa, konfigurationshash och mottagningstid.

```sh
just export exports/demo.csv
just replay exports/demo.csv
just view config/replay.json data/replay.sqlite3 8843
```

Alla importerade värden märks **replay**, även om originalfilen säger ha.
Originalfilens SHA-256 sparas i metadata. Importen sparar inte ursprungskällan
som en separat kolumn: behåll originalfil/manifest för full proveniens. Importen
är atomisk och strömmas i små block; återimport är idempotent. Filer över 500 MB
måste delas före import.
Replay behåller tidsstämplarna; den låtsas inte vara en levande sensor.
