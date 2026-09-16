python := env_var_or_default("PYTHON", "python3")

# Visa alla kommandon.
default:
    @just --list

# Kör kontroll av konfiguration och skapa demodatabasen.
init:
    {{python}} -m kebnekaise init

# Komplett demo: 28 dagars historik, levande simulering och lokal dashboard.
demo: seed
    {{python}} -m kebnekaise run

# Lägg till reproducerbar historik; befintliga tidsstämplar skrivs inte över.
seed days="28":
    {{python}} -m kebnekaise seed --days {{quote(days)}}

# Starta insamling + UI utan att generera historik.
run config="config/demo.json" db="data/demo.sqlite3" port="8840":
    {{python}} -m kebnekaise --config {{quote(config)}} --db {{quote(db)}} run --port {{quote(port)}}

# Visa befintlig databas, utan insamlare.
view config="config/demo.json" db="data/demo.sqlite3" port="8840":
    {{python}} -m kebnekaise --config {{quote(config)}} --db {{quote(db)}} serve --port {{quote(port)}}

# Testa riktiga HA-adaptern mot lokal mock; nio mätpunkter fortsätter simuleras.
hil-demo:
    {{python}} scripts/hil_demo.py

# Separat mock-HA för manuella felfall. Kräver KEBNEKAISE_HA_TOKEN.
mock-ha fault="none":
    {{python}} -m kebnekaise --config config/hil.json --db data/hil.sqlite3 mock-ha --fault {{quote(fault)}}

# Samla ett varv (t.ex. när en riktig sensor ska provas).
collect-once config="config/demo.json" db="data/demo.sqlite3":
    {{python}} -m kebnekaise --config {{quote(config)}} --db {{quote(db)}} collect --once

# Meningsfulla tester för statistik, säkerhet, backup, källor och HIL-bortfall.
test:
    {{python}} -m unittest discover -s tests -v
    {{python}} -m compileall -q kebnekaise scripts tests

# Matter-transportens cache-, avbrotts- och svarstester. Kräver Node.js 24.
test-matter:
    {{env_var_or_default("NODE", "node")}} --test tests/matter_read.test.mjs

# Kontrollera databasens integritet och källor.
check config="config/demo.json" db="data/demo.sqlite3":
    {{python}} -m kebnekaise --config {{quote(config)}} --db {{quote(db)}} check

# Tidsviktad rapport under arbetstid. Befintlig målfil skrivs aldrig över.
report output="exports/rapport.md" config="config/demo.json" db="data/demo.sqlite3" days="28":
    {{python}} -m kebnekaise --config {{quote(config)}} --db {{quote(db)}} report --work --days {{quote(days)}} --output {{quote(output)}}

# CSV med UTC-tid, en rad per storhet, källa och konfigurationshash.
export output="exports/readings.csv" config="config/demo.json" db="data/demo.sqlite3" source="all":
    {{python}} -m kebnekaise --config {{quote(config)}} --db {{quote(db)}} export --source {{quote(source)}} --output {{quote(output)}}

# Skapa lokal överföringsfil. Standardfiltreringen tar bara verkliga HA-värden.
bundle output="exports/office.zip" config="config/office.example.json" db="data/office.sqlite3" source="ha":
    {{python}} -m kebnekaise --config {{quote(config)}} --db {{quote(db)}} bundle --source {{quote(source)}} --output {{quote(output)}}

# Import för uppspelning; märks alltid replay och ligger i separat databas.
replay file:
    {{python}} -m kebnekaise --config config/replay.json --db data/replay.sqlite3 import-csv --file {{quote(file)}}

# Konsistent SQLite-backup, även när insamlingen pågår.
backup output="exports/backup.sqlite3" config="config/demo.json" db="data/demo.sqlite3":
    {{python}} -m kebnekaise --config {{quote(config)}} --db {{quote(db)}} backup --output {{quote(output)}}

# Terminalmarkering. Välj gärna en specifik mätpunkt och undvik namn i texten.
note kind sensor="all" text="":
    {{python}} -m kebnekaise note --kind {{quote(kind)}} --sensor {{quote(sensor)}} --text {{quote(text)}}

# Läs Pi:ns systeminformation utan att ändra något (kör lokalt på Pi:n).
pi-check:
    {{python}} scripts/pi_check.py
