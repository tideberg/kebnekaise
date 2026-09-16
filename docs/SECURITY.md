# Säkerhetsarkitektur och integrationsunderlag

## Omfattning

Sensorerna mäter temperatur och CO₂ i tio lokala områden. Ingen identifiering
av individer, mikrofon, kamera eller åtkomst till verksamhetssystem behövs.
Mönstren kan ändå indirekt säga något om när lokaler används. Händelser ska
skrivas utan namn. En driftsättande organisation behöver klassificera data och
bestämma retention innan verklig insamling startar.

Repo:t antar inte något specifikt hem-, gäst- eller företagsnät. Matter behöver
lokal IPv6 och mDNS, vilket måste verifieras i målmiljön. Ingen brandvägg,
port-forwarding eller nätpolicy ändras av programvaran; sådana förändringar
kräver ett separat, godkänt driftsbeslut.

## Faktiska skydd i M1

- UI-server och mock-HA är hårdkodade till IPv4-loopback `127.0.0.1`.
- Dashboarden har ingen `--host 0.0.0.0`-möjlighet och inga CORS-undantag.
- Host/Origin-kontroll och cross-site-filter mot DNS-rebinding/webbangrepp.
- Anteckningar kräver en slumpad sessionstoken i en egen HTTP-header.
- CSP, inget externt innehåll, textinmatning renderas med `textContent`.
- Endast tre explicit tillåtna statiska filer serveras. Ingen filbläddring.
- Max åtta samtidiga klienttrådar, socket-timeout och begränsad POST-storlek.
- SQL-parametrar för data. Bunden analysperiod och begränsat antal grafpunkter.
- DB med `0600`; CLI sätter umask `0077`. Export/backup vägrar skriva över filer.
- HA-token används bara av serverprocessen. HA-läsning följer inte redirects
  och ärver inte proxyinställningar som skulle kunna läcka token.
- HTTPS med certifikatkontroll krävs till extern HA-värd. Ett enda uttryckligt
  undantag finns för HA-appens interna `http://supervisor/core` och Supervisor-token.
- Produktionsläge tillåter bara ha/matter/disabled och använder en separat databas.

Loopback skyddar mot andra nätklienter, inte mot en annan process som redan kör
som samma lokala användare. Servern är en lokal verktygsserver, inte en härdad
intern webbprodukt för många användare. Aktivera diskkryptering på värddatorn
enligt organisationens policy; krypteringen sköts inte av programvaran.

## Supply chain

Loggerns Python- och dashboardkod använder endast standardbibliotek och lokal
JavaScript. Det betyder inte noll tillit: Python, SQLite, OS, webbläsaren och
projektets egna källfiler ingår. Matter-spåret har ett separat, låst npm-träd
under `deploy/matter/package-lock.json`. Inga installationsinstruktioner använder
curl-pipe-shell. Just är en valfri genväg; alla kommandon finns även som Python.

Referenskonfigurationen använder `matter-server@1.4.0` och Node.js 24 med låst
npm-beroendeträd och installationsskript avstängda. Vald Thread-borderrouter och
Matter-kontroller är miljöbeslut. Loggeradaptern skickar endast `read_attribute`
till kontrollern på loopback. Styr-API:t behöver ändå betraktas som privilegierat
för andra lokala processer. Controlleridentiteten ska lagras under en separat
tjänsteanvändare och säkerhetskopieras privat, separat från SQLite-historiken.
Att själv implementera Matter-kryptering och livscykel skulle öka underhålls-
och säkerhetsbördan. HACS och community-integrationer behövs inte.

HA-appens enda extra containerbas är Docker Official Image `python` med exakt
tagg och SHA-256. Den hämtas först vid det verkliga byggsteget. En digest låser
innehåll men intygar inte att innehållet är säkert. Dokumentera val/version,
granska uppdateringar, och lås upp/pinna om när säkerhetsunderhåll kräver det.

HA:s token kan ha bredare rättigheter än de två sensorer som adaptern läser.
Använd separat HA-användare med minsta tillgängliga rättigheter för extern
adapter. HA OS-appen begär HA API-åtkomst, inte Supervisor-adminfunktioner.
Supervisor-token lagras inte i konfigurationshistorik eller export.

## Förslag: börja utan koppling till centrala system

Rådata stannar på Pi:n. Administration sker lokalt/med nyckelbaserad SSH eller
HA:s skyddade lokala administration. Analys sker på loopback eller en nedhämtad
SQLite-kopia. Backup flyttas till godkänd lagring. Det uppfyller grundbehovet och
kräver inget centralt API i M1.

Om centralisering behövs rekommenderar vi i första hand **utgående push av
begränsade mätpaket över HTTPS**. Det är vårt tekniska förslag, inte ett beslut
från den mottagande organisationens säkerhetsfunktion.

| Egenskap | Pi pushar | Server drar |
|---|---|---|
| Ingående tjänst på Pi | Behövs inte | Behövs, t.ex. SFTP med separat konto |
| Hemlighet på Pi | Begränsad upload-identitet | Serverns publika SSH-nyckel/annan klienttrust |
| Klientnät → server | En allowlistad destination på TCP 443 | Servern måste nå klienten på dess nät |
| Avbrott | Lokal kö och försök igen | Server återupptar senare |
| Konsekvens av stulen Pi | Upload-identitet måste kunna spärras | Lokal data/hostnyckel kan röjas |

Push ska använda separerad inlämningstjänst, certifikatkontroll/mTLS eller
snävt scoped token, storleksgräns, schema-/värdevalidering, idempotens och
kvittens. Pi:n får ingen generell databasanslutning eller läsrätt i
en central verksamhetsdatabas. En mottagande tjänst importerar godkända värden
till egen SQL-databas; existerande Grafana kan använda den.

**M1 implementerar paketet, inte en uppladdning till en ännu okänd destination.**
`bundle` ger ZIP med UTC-CSV och SHA-256-manifest. Standardfiltret inkluderar
bara `ha`; välj `--source matter` för den direkta Matter-piloten. Inga anrop görs
till en central server eller internet. SHA-256 är
integritetskontroll, inte avsändarautentisering. En mottagare behöver sin egen
autentiserade kanal och kvittens innan lokal kö kan gallras.

Om säkerhetsfunktionen föredrar pull används snapshots med läsbehörighet via
nyckelbaserad SFTP. Undvik SQL/HTTP-direktåtkomst till loggern och håll värden i egen
inlämningszon. Mottagare, certifikat, åtkomstriktning, frekvens, retention och
incidentägare beslutas först när den konkreta målmiljön är känd.

## Återstående driftbeslut

Vem äger eventuella plattformskonton och enheter? Vilka administrerar Pi:n? Var
sparas extern backup? Hur ofta uppdateras firmware? Är valda kontokopplingar
acceptabla i organisationens driftmodell? Detta påverkar M3/M4, men blockerar
inte M1.
Ingen automatisk publicering, telemetri eller extern notifiering har lagts till.
