"use strict";

const $ = (id) => document.getElementById(id);
const labels = {simulation: "Simulerad", ha: "Verklig · HA", matter: "Verklig · Matter", mock: "HA-simulator", replay: "Replay", disabled: "Ej ansluten"};
const colors = ["#527f9c", "#7791a2", "#36667c", "#9cabb5", "#aec0c8", "#ac8656", "#c3a77c", "#a36643", "#d0a179", "#8b739a"];
const kinds = {warm: ["↗", "För varmt"], cold: ["↘", "För kallt"], stuffy: ["◌", "Instängd luft"], window: ["⊞", "Fönster"], presentation: ["◫", "Presentation"], note: ["◷", "Observation"]};
let config, status, data, days = 28, metric = "co2", custom = null, requestNumber = 0;
let chartGeometry = null;
const nf = new Intl.NumberFormat("sv-SE", {maximumFractionDigits: 1});
const fmt = (x, decimals = 1) => x == null || !Number.isFinite(x) ? "—" : new Intl.NumberFormat("sv-SE", {maximumFractionDigits: decimals, minimumFractionDigits: decimals}).format(x);
const date = (ts, extra = {}) => new Intl.DateTimeFormat("sv-SE", {timeZone: config.timezone, month: "short", day: "numeric", ...extra}).format(new Date(ts * 1000));
const name = (sid) => config.sensors.find(s => s.id === sid)?.name || sid;
const color = (sid) => colors[config.sensors.findIndex(s => s.id === sid) % colors.length] || "#587350";

function node(tag, text, className) {
  const e = document.createElement(tag);
  if (text != null) e.textContent = text;
  if (className) e.className = className;
  return e;
}
function svg(tag, attrs, text) {
  const e = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, String(v));
  if (text != null) e.textContent = text;
  return e;
}
async function api(path, options) {
  const response = await fetch(path, {...options, cache: "no-store"});
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || "Kunde inte läsa lokal data");
  return body;
}
function showError(message) {
  $("error").textContent = message;
  $("error").classList.toggle("hidden", !message);
}
function kpi(id, value, unit = "") {
  $(id).replaceChildren(document.createTextNode(value + " "), node("small", unit));
}
function selectedSensors() {
  return config.sensors.filter(s => $("sensor").value === "all" || s.id === $("sensor").value);
}
function renderKpis() {
  const available = data.summary.filter(r => r.observed_seconds > 0);
  const count = new Set(available.map(r => r.sensor)).size;
  kpi("kpi-sensors", String(count), "/ " + selectedSensors().length);
  $("kpi-sensors-note").textContent = "Med data i vald period och källa";
  const co2 = available.filter(r => r.metric === "co2").sort((a, b) => b.p95 - a.p95);
  kpi("kpi-co2", fmt(co2[0]?.p95, 0), "ppm");
  $("kpi-co2-note").textContent = co2.length ? `${name(co2[0].sensor)} · ${labels[co2[0].source]}` : "Inga CO₂-värden för urvalet";
  const temps = available.filter(r => r.metric === "temperature");
  kpi("kpi-temp", temps.length ? `${fmt(Math.min(...temps.map(r => r.min)))}–${fmt(Math.max(...temps.map(r => r.max)))}` : "—", "°C");
  const rows = data.summary.filter(r => r.metric === metric);
  const source = $("source").value;
  const expected = selectedSensors().filter(s => s.provider !== "disabled" && (source === "all" || s.provider === source));
  const missing = expected.some(s => !rows.some(r => r.sensor === s.id && r.source === s.provider && r.observed_seconds > 0));
  const coverage = !data.expected_seconds ? null : missing ? 0 : rows.length ? Math.min(...rows.map(r => r.coverage || 0)) : null;
  kpi("kpi-coverage", fmt(coverage == null ? null : coverage * 100), "%");
  $("kpi-coverage-note").textContent = `Färskt rapporterat värde · ${metric === "co2" ? "CO₂" : "temperatur"}`;
  $("insight").textContent = co2.length ? `${name(co2[0].sensor)} har urvalets högsta CO₂-P95: ${fmt(co2[0].p95, 0)} ppm. Jämför tidsmönstret med rummets användning och datatäckning.` : "Här visas återkommande mönster när det finns data för ditt urval.";
}

function renderChart() {
  const chart = $("chart");
  chart.replaceChildren();
  const unit = metric === "co2" ? "ppm" : "°C";
  $("chart-unit").textContent = `${metric === "co2" ? "CO₂" : "Temperatur"} · ${unit}`;
  const thresholds = metric === "co2" ? [config.thresholds.co2] : [config.thresholds.temperature_low, config.thresholds.temperature_high];
  $("reference-label").textContent = `Analysreferens ${thresholds.map(x => fmt(x, 0)).join("–")} ${unit}`;
  const allPoints = data.series.flatMap(s => s.points.filter(p => p.mean != null));
  $("chart-empty").classList.toggle("hidden", allPoints.length > 0);
  const min = Math.min(...allPoints.map(p => p.min), ...thresholds, metric === "co2" ? 400 : 18);
  const max = Math.max(...allPoints.map(p => p.max), ...thresholds, metric === "co2" ? 1100 : 25);
  const padding = Math.max((max - min) * .1, metric === "co2" ? 40 : .5);
  const low = Math.floor((min - padding) / (metric === "co2" ? 100 : 1)) * (metric === "co2" ? 100 : 1);
  const high = Math.ceil((max + padding) / (metric === "co2" ? 100 : 1)) * (metric === "co2" ? 100 : 1);
  const width = Math.max(320, $("chart-wrap").clientWidth || 1100);
  chart.setAttribute("viewBox", `0 0 ${width} 280`);
  const left = 44, right = width-12, top = 12, bottom = 245;
  const x = ts => left + (ts - data.start) / (data.end - data.start) * (right-left);
  const y = value => bottom - (value-low)/(high-low)*(bottom-top);
  chartGeometry = {left, right, top, bottom, x, y, width};
  for (let i = 0; i <= 4; i++) {
    const v = low + (high-low) * i/4;
    chart.append(svg("line", {x1: left, x2: right, y1: y(v), y2: y(v), class: "grid-line"}));
    chart.append(svg("text", {x: left-10, y: y(v)+3, "text-anchor": "end"}, fmt(v, metric === "co2" ? 0 : 1)));
  }
  for (const threshold of thresholds) chart.append(svg("line", {x1: left, x2: right, y1: y(threshold), y2: y(threshold), class: "reference"}));
  const ticks = width < 650 ? 3 : 6;
  for (let i = 0; i <= ticks; i++) {
    const ts = data.start + (data.end-data.start) * i/ticks;
    chart.append(svg("text", {x: x(ts), y: 272, "text-anchor": i === 0 ? "start" : i === ticks ? "end" : "middle"},
      data.end-data.start <= 86400 ? date(ts, {hour: "2-digit", minute: "2-digit"}) : date(ts)));
  }
  if (data.end-data.start <= 3*86400 || $("sensor").value !== "all") {
    for (const event of data.events) {
      const line = svg("line", {x1: x(event.ts), x2: x(event.ts), y1: top, y2: bottom, class: "event-line"});
      line.append(svg("title", {}, `${date(event.ts, {hour: "2-digit", minute: "2-digit"})} · ${event.note}`));
      chart.append(line);
    }
  }
  for (const series of data.series) {
    let path = "", connected = false;
    for (const point of series.points) {
      if (point.mean == null) { connected = false; continue; }
      const px = x(Math.min(data.end, point.ts + data.bucket_seconds/2));
      path += `${connected ? "L" : "M"}${px.toFixed(2)},${y(point.mean).toFixed(2)} `;
      if (!connected) chart.append(svg("circle", {cx: px, cy: y(point.mean), r: 1.5, fill: color(series.sensor)}));
      connected = true;
    }
    const line = svg("path", {d: path, stroke: color(series.sensor), class: "series-line"});
    if (series.source === "mock" || series.source === "replay") line.setAttribute("stroke-dasharray", "5 4");
    chart.append(line);
    // The envelope preserves extrema that bucket means alone would hide.
    if (data.series.length === 1) {
      for (const p of series.points.filter(p => p.mean != null)) chart.append(svg("line", {
        x1: x(p.ts + data.bucket_seconds/2), x2: x(p.ts + data.bucket_seconds/2), y1: y(p.min), y2: y(p.max),
        stroke: color(series.sensor), opacity: .2, "stroke-width": 2}));
    }
  }
  $("legend").replaceChildren();
  for (const series of data.series) {
    const button = node("button", null, "legend-item");
    const swatch = node("i"); swatch.style.backgroundColor = color(series.sensor);
    button.append(swatch, document.createTextNode(`${name(series.sensor)} · ${labels[series.source]}`));
    button.addEventListener("click", () => selectSensor(series.sensor));
    $("legend").append(button);
  }
  $("aggregation-note").textContent = `Medel per ${nf.format(data.bucket_seconds/60)} min. Välj en punkt för min–max. Tomma intervall är luckor.`;
}

function renderTable() {
  const tbody = $("comparison");
  tbody.replaceChildren();
  $("table-metric").textContent = metric === "co2" ? "CO₂ · ppm" : "Temperatur · °C";
  const rows = data.summary.filter(r => r.metric === metric);
  const ordered = selectedSensors();
  for (const sensor of ordered) {
    const values = rows.filter(r => r.sensor === sensor.id);
    if (!values.length && $("source").value !== "all" && sensor.provider !== $("source").value) continue;
    if (!values.length) values.push({sensor: sensor.id, source: sensor.provider, coverage: null});
    for (const r of values) {
      const tr = node("tr");
      const link = node("button", name(r.sensor), "legend-item");
      link.addEventListener("click", () => selectSensor(r.sensor));
      const first = node("td"); first.append(link); tr.append(first);
      const source = node("td"); source.append(node("span", labels[r.source], "source-pill " + r.source)); tr.append(source);
      tr.append(node("td", fmt(r.mean, metric === "co2" ? 0 : 1)), node("td", fmt(r.p95, metric === "co2" ? 0 : 1)));
      tr.append(node("td", r.min == null ? "—" : `${fmt(r.min, metric === "co2" ? 0 : 1)}–${fmt(r.max, metric === "co2" ? 0 : 1)}`));
      tr.append(node("td", r.mean == null ? "—" : `${fmt(r.above_seconds/3600)} h`));
      tr.append(node("td", r.mean == null || metric === "co2" ? "—" : `${fmt(r.below_seconds/3600)} h`));
      const coverage = node("td");
      if (r.coverage != null) {
        const track = node("span", null, "coverage"), bar = node("i");
        bar.style.width = `${Math.min(100, r.coverage*100)}%`; track.append(bar);
        coverage.append(track, document.createTextNode(`${fmt(r.coverage*100)} %`));
      } else coverage.textContent = "Inga data";
      tr.append(coverage); tbody.append(tr);
    }
  }
  if (!tbody.children.length) {
    const tr = node("tr"), td = node("td", "Inga mätvärden för den valda källan och perioden.");
    td.colSpan = 8; tr.append(td); tbody.append(tr);
  }
}

function renderMap() {
  const grids = new Map();
  $("zone-map").replaceChildren();
  for (const zone of new Set(config.sensors.map(s => s.zone))) {
    const sensors = config.sensors.filter(s => s.zone === zone);
    const title = node("div", null, "zone-title");
    title.append(node("i", null, "dot " + (zone === "Sydväst" ? "sw" : "ne")),
      document.createTextNode(zone.toUpperCase()), node("span", `${sensors.length} ${sensors.length === 1 ? "mätpunkt" : "mätpunkter"}`));
    const grid = node("div", null, "sensor-grid " + (zone === "Nordost" ? "ne-grid" : zone === "Sydväst" ? "sw-grid" : "live-grid"));
    $("zone-map").append(title, grid);
    grids.set(zone, grid);
  }
  for (const s of config.sensors) {
    const latest = key => status.latest.find(r => r.sensor === s.id && r.source === s.provider && r.metric === key);
    const temp = latest("temperature"), co2 = latest("co2");
    const health = status.health.find(r => r.sensor === s.id);
    const inactive = s.provider === "disabled";
    const tFresh = temp && !temp.stale, cFresh = co2 && !co2.stale;
    const stale = !tFresh || !cFresh || (health && !health.ok);
    const card = node("button", null, "sensor-card" + ($("sensor").value === s.id ? " selected" : ""));
    card.title = `${s.name} · ${labels[s.provider]}${temp ? " · Temperatur avläst " + date(temp.ts, {hour: "2-digit", minute: "2-digit"}) : ""}${co2 ? " · CO₂ avläst " + date(co2.ts, {hour: "2-digit", minute: "2-digit"}) : ""}${health ? " · " + health.detail : ""}`;
    const short = s.provider === "matter" ? s.name : s.id === "lunch" ? "LUNCHAREA · GEMENSAMT" : s.id.toUpperCase();
    card.append(node("small", short), node("strong", tFresh ? `${fmt(temp.value)}°` : "—", stale ? "stale" : ""),
      node("span", cFresh ? `${fmt(co2.value, 0)} ppm` : "Inga färska data", stale ? "stale" : ""),
      node("span", `${labels[s.provider]}${stale && !inactive ? " · insamlingsfel eller gamla värden" : ""}`, "source-mark"));
    if (temp || co2) card.append(node("span", "Avläst " + date(Math.min(temp?.ts ?? Infinity, co2?.ts ?? Infinity), {hour: "2-digit", minute: "2-digit", second: "2-digit"}), "read-time"));
    card.addEventListener("click", () => selectSensor(s.id));
    grids.get(s.zone).append(card);
  }
}

function renderEvents() {
  $("event-list").replaceChildren();
  for (const event of [...data.events].reverse()) {
    const [icon, label] = kinds[event.kind] || kinds.note;
    const row = node("button", null, "event-row"), text = node("div");
    row.title = "Visa mätningar två timmar före och efter händelsen";
    row.addEventListener("click", () => {
      custom = {start: event.ts-7200, end: Math.min(Math.floor(Date.now()/1000), event.ts+7200)};
      $("sensor").value = event.sensor;
      $("work").checked = false;
      document.querySelectorAll(".period-buttons button").forEach(b => b.classList.toggle("selected", b.id === "custom-toggle"));
      refresh();
      $("history").scrollIntoView({block: "start"});
    });
    text.append(node("strong", `${label} · ${event.sensor === "all" ? config.site_name : name(event.sensor)}`),
      node("p", `${event.note || "Ingen notering"} · ${labels[event.source]}`));
    row.append(node("span", icon, "event-icon"), text, node("time", date(event.ts, {hour: "2-digit", minute: "2-digit"})));
    $("event-list").append(row);
  }
  if (!data.events.length) $("event-list").append(node("p", "Inga händelser i urvalet. Lägg till en observation när något känns annorlunda.", "table-note"));
}

function selectSensor(sid) {
  $("sensor").value = sid;
  refresh();
}
async function refresh() {
  const request = ++requestNumber;
  $("refresh-state").textContent = "Beräknar…";
  const end = custom?.end || Math.floor(Date.now()/1000);
  const start = custom?.start || end-days*86400;
  const params = new URLSearchParams({start, end, work: $("work").checked ? "1" : "0", metric, source: $("source").value, sensor: $("sensor").value});
  try {
    const [newData, newStatus] = await Promise.all([api("/api/data?" + params), api("/api/status")]);
    if (request !== requestNumber) return;
    data = newData; status = newStatus;
    renderKpis(); renderChart(); renderTable(); renderMap(); renderEvents();
    $("period-caption").textContent = `${date(start, {year: "numeric"})} – ${date(end, {year: "numeric"})} · ${$("work").checked ? "vardagar, arbetstid" : "hela dygnet"}`;
    $("refresh-state").textContent = `Uppdaterad ${date(status.now, {hour: "2-digit", minute: "2-digit"})}`;
    showError("");
  } catch (err) {
    if (request !== requestNumber) return;
    showError("Kunde inte uppdatera. " + err.message + " Tidigare visade värden kan vara gamla.");
    $("refresh-state").textContent = "Uppdatering misslyckades";
  }
}

function localInputTime(d) {
  return new Date(d.getTime() - d.getTimezoneOffset()*60000).toISOString().slice(0, 16);
}
function openEvent() {
  $("event-time").value = localInputTime(new Date());
  $("event-sensor").value = $("sensor").value;
  $("event-error").textContent = "";
  $("event-dialog").showModal();
}

async function init() {
  try {
    config = await api("/api/config");
    $("version").textContent = config.version;
    $("site-name").textContent = config.site_name;
    $("page-eyebrow").textContent = config.site_name + " · inomhusklimat";
    $("zone-summary").replaceChildren();
    for (const zone of new Set(config.sensors.map(s => s.zone))) {
      const count = config.sensors.filter(s => s.zone === zone).length;
      const row = node("div", null, "zone-summary");
      row.append(node("i", null, "dot " + (zone === "Sydväst" ? "sw" : "ne")), document.createTextNode(zone), node("span", `${count} ${count === 1 ? "punkt" : "punkter"}`));
      $("zone-summary").append(row);
    }
    if (config.mode === "pilot") {
      days = 1;
      $("work").checked = false;
      document.querySelectorAll("[data-days]").forEach(b => b.classList.toggle("selected", Number(b.dataset.days) === days));
    }
    $("mode-title").textContent = config.mode === "demo" ? "Du utforskar ett simulerat kontor" : config.mode === "pilot" ? "Pilotmiljö · kontrollera datakällan" : "Kontorets mätmiljö";
    $("mode-description").textContent = config.mode === "demo" ? "Modellerade dygn, sol, beläggning och dataluckor. Detta är inte mätningar från ert kontor." : config.mode === "pilot" ? "Verkliga sensorer, HA-simulator och replay märks var för sig. Ingen automatisk ersättning vid bortfall." : "Verkliga mätpunkter aktiveras stegvis. Saknade mätvärden visas som luckor.";
    $("mode-tag").textContent = config.mode === "demo" ? "SYNTETISKA DATA" : config.mode.toUpperCase();
    if (config.mode === "pilot" && config.sensors.every(s => s.provider === "matter")) {
      $("mode-title").textContent = config.site_name + " · verkliga mätvärden";
      $("mode-description").textContent = `Sensorn läses var ${config.interval_seconds}:e sekund. Historiken börjar när insamlingen startar; tom tid före starten sänker täckningen.`;
      $("map-footnote").textContent = "Tiden avser mottaget svar från sensorn. Nuläget visas oberoende av historikfiltret.";
      $("source").value = "matter";
    }
    $("work-label").textContent = config.work_hours.map(x => String(x).padStart(2, "0")).join("–");
    $("reference-note").textContent = `Valda temperaturreferenser: ${config.thresholds.temperature_low}–${config.thresholds.temperature_high} °C. Sommarens bedömning kan behöva andra referenser. Ändras i konfigurationen.`;
    for (const s of config.sensors) {
      for (const id of ["sensor", "event-sensor"]) {
        const option = node("option", s.name); option.value = s.id; $(id).append(option);
      }
    }
    for (const button of document.querySelectorAll("[data-days]")) button.addEventListener("click", () => {
      days = Number(button.dataset.days); custom = null;
      document.querySelectorAll(".period-buttons button").forEach(b => b.classList.toggle("selected", b === button));
      $("custom-range").classList.add("hidden"); refresh();
    });
    $("custom-toggle").addEventListener("click", () => {
      $("custom-range").classList.toggle("hidden");
      $("from").value = localInputTime(new Date(Date.now()-7*86400000));
      $("to").value = localInputTime(new Date());
    });
    $("custom-range").addEventListener("submit", e => {
      e.preventDefault();
      custom = {start: Math.floor(new Date($("from").value).getTime()/1000), end: Math.floor(new Date($("to").value).getTime()/1000)};
      document.querySelectorAll(".period-buttons button").forEach(b => b.classList.toggle("selected", b.id === "custom-toggle"));
      refresh();
    });
    for (const id of ["work", "source", "sensor"]) $(id).addEventListener("change", refresh);
    for (const value of ["co2", "temperature"]) $("metric-" + value).addEventListener("click", () => {
      metric = value;
      for (const m of ["co2", "temperature"]) $("metric-" + m).classList.toggle("selected", m === metric);
      refresh();
    });
    $("open-event").addEventListener("click", openEvent); $("open-event-bottom").addEventListener("click", openEvent);
    $("event-cancel").addEventListener("click", () => $("event-dialog").close());
    $("event-form").addEventListener("submit", async e => {
      e.preventDefault();
      const button = e.submitter; if (button) button.disabled = true;
      try {
        await api("/api/events", {method: "POST", headers: {"Content-Type": "application/json", "X-Kebnekaise-Token": config.csrf},
          body: JSON.stringify({sensor: $("event-sensor").value, kind: $("event-kind").value,
            time: new Date($("event-time").value).toISOString(), note: $("event-note").value})});
        $("event-dialog").close(); $("event-note").value = ""; await refresh();
      } catch (err) { $("event-error").textContent = err.message; }
      finally { if (button) button.disabled = false; }
    });
    $("chart").addEventListener("mousemove", event => {
      if (!data || !chartGeometry) return;
      const box = $("chart").getBoundingClientRect();
      const px = (event.clientX-box.left) / box.width * chartGeometry.width;
      const ratio = Math.max(0, Math.min(.999999, (px-chartGeometry.left)/(chartGeometry.right-chartGeometry.left)));
      const ts = data.start + ratio*(data.end-data.start);
      const index = Math.floor((ts-data.start)/data.bucket_seconds);
      const entries = data.series.map(s => ({series: s, point: s.points[index]})).filter(x => x.point?.mean != null);
      const tooltip = $("tooltip"); tooltip.replaceChildren(node("strong", date(ts, {hour: "2-digit", minute: "2-digit"})));
      for (const {series, point} of entries) tooltip.append(node("div", `${name(series.sensor)}: ${fmt(point.mean, metric === "co2" ? 0 : 1)}`));
      if (entries.length === 1) {
        const p = entries[0].point;
        tooltip.append(node("small", `Min–max ${fmt(p.min)}–${fmt(p.max)} · underlag ${fmt(p.seconds/60)} min`));
      }
      if (!entries.length) tooltip.append(node("div", "Inga värden i intervallet"));
      tooltip.style.left = `${Math.max(0, Math.min(box.width-230, event.clientX-box.left+12))}px`;
      tooltip.style.top = "12px"; tooltip.classList.remove("hidden");
    });
    $("chart").addEventListener("mouseleave", () => $("tooltip").classList.add("hidden"));
    window.addEventListener("resize", () => { if (data) renderChart(); });
    await refresh();
    setInterval(() => { if (!document.hidden && !$("event-dialog").open) refresh(); }, 60000);
  } catch (err) { showError("Kunde inte starta dashboarden. " + err.message); }
}
init();
