# Källor, 14–15 september 2026

Primärkällor används för produkt-, protokoll- och driftval. Webbsidor kan ändras;
verifiera versioner och priser igen vid inköp/installation. Markeringarna
"antagande" och "ej verifierat" i övriga dokument är avsiktliga.

| Källa | Vad den stöder |
|---|---|
| [IKEA ALPSTUGA Sverige](https://www.ikea.com/se/sv/p/alpstuga-luftkvalitetsmaetare-smart-50604187/) | Pris 299 kr, mätstorheter, Matter over Thread, USB-kabel/laddare separat |
| [Home Assistant Matter](https://www.home-assistant.io/integrations/matter/) | Kontroller/border router, IPv6/mDNS, parning/delning, HA OS som stödd Matter-installation, Apple-OTA-begränsning |
| [Home Assistant Thread](https://www.home-assistant.io/integrations/thread/) | Thread-nät, OTBR och credential-hantering |
| [Home Assistant Connect ZBT-2](https://www.home-assistant.io/connect/zbt-2/) | Radio, Thread-/Zigbee-val, officiella återförsäljarlänkar, rekommenderat pris 45 EUR vid kontroll |
| [Apple: Thread-enheter](https://support.apple.com/en-ie/102078) | Apple TV 4K generation 2, generation 3 Wi-Fi + Ethernet, HomePod mini/generation 2 |
| [Apple: bakgrundskörning](https://developer.apple.com/documentation/uikit/about-the-background-execution-sequence) | En vanlig tvOS/UIKit-app kan suspenderas |
| [Apple BGTaskRequest.earliestBeginDate](https://developer.apple.com/documentation/backgroundtasks/bgtaskrequest/earliestbegindate) | Begärd bakgrundstidpunkt garanteras inte |
| [HA REST API](https://developers.home-assistant.io/docs/api/rest/) | Bearer-token, states och historikformat |
| [HA app configuration](https://developers.home-assistant.io/docs/apps/configuration/) | `/data`, `/data/options.json`, arkitektur, API-/share-behörigheter och byggkonfiguration |
| [HA app communication](https://developers.home-assistant.io/docs/apps/communication/) | Supervisor-token och HA:s interna API |
| [HA på Raspberry Pi](https://www.home-assistant.io/installation/raspberrypi/) | HA OS-installation på stödd Pi |
| [Raspberry Pi OS](https://www.raspberrypi.com/software/operating-systems/) | Officiella OS-varianter och Imager |
| [Arbetsmiljöverket: termiskt klimat](https://www.av.se/inomhusmiljo/temperatur-och-termiskt-klimat-pa-arbetsplatsen/bedom-det-termiska-klimatet/) | Temperaturreferenser, säsong och begränsning hos enbart lufttemperatur |
| [Folkhälsomyndigheten: ventilation](https://www.folkhalsomyndigheten.se/regler-och-tillsyn/tillsynsvagledning-och-stod/halsoskydd-vagledning-och-tillsyn/vagledning-om-ventilation/) | CO₂ som möjlig indikation för fortsatt ventilationskontroll |
| [HSE: CO₂ monitors](https://www.hse.gov.uk/ventilation/using-co2-monitors.htm) | Praktisk mätning, placering och tolkning |
| [NIST: CO₂ generation rates](https://www.nist.gov/publications/carbon-dioxide-generation-rates-building-occupants) | Modellens typ och varför generering per person inte är en universell konstant |

## Apple TV-frågan

Den lokalt installerade tvOS-SDK:n kontrollerades också. `HMHomeManager` och
`HMCharacteristic` är tillgängliga från tvOS 10. HomeKit-avläsning i en egen app
är alltså möjlig i princip. `BGTaskRequest.h` anger samtidigt att systemet inte
garanterar den begärda starttiden. En app för visning är en annan sak än en
övervakad process som skriver historik varje minut även när appen inte visas.

**Slutsats/inferens:** återanvänd en befintlig Thread-kapabel Apple TV för radio-
transport, men låt Pi/HA stå för beständig insamling. Ingen egen tvOS-app behöver
byggas för den kedjan. HA beskriver dessutom en begränsning för firmware-
uppdatering av Thread-enheter via HA när Apple-border routrar ingår; prova och
dokumentera hur ALPSTUGA uppdateras innan kontorsdrift.

## Sökning efter verkliga ALPSTUGA-tidsserier

Sökningar omfattade `ALPSTUGA csv`, `ALPSTUGA dataset` och `ALPSTUGA CO2 csv github`.
Resultaten innehöll användarerfarenheter, grafer och exportinstruktioner, bland
annat en [gist-lista med exportexempel](https://gist.github.com/mrchrisadams?direction=desc&sort=updated).
Vi hittade ingen nedladdad, kontrollerad råtidsserie med klar återanvändningsrätt
och tillräcklig sensor-/miljömetadata. Därför har inga sådana data införts eller
använts som kalibrering. Det betyder inte att ett dataset inte kan finnas.

När vi får en verklig CSV kan den importeras som replay. För modellkalibrering
behövs dessutom instrument/firmware, placering, tidszon, rapportintervall och
beläggnings-/ventilationskontext. Första egna sensorn ger ett bättre känt underlag.
