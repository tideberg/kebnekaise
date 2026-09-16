"""Time-weighted statistics; gaps have no value and are never filled indefinitely."""

from __future__ import annotations

import bisect
import math
from collections import defaultdict
from datetime import datetime, time as day_time, timedelta
from zoneinfo import ZoneInfo


def windows(start, end, timezone, hours, work_only):
    if not work_only:
        return [(start, end)]
    zone = ZoneInfo(timezone)
    day = datetime.fromtimestamp(start, zone).date()
    last = datetime.fromtimestamp(end, zone).date()
    result = []
    while day <= last:
        if day.weekday() < 5:
            midnight = datetime.combine(day, day_time(), zone)
            a = int((midnight + timedelta(hours=hours[0])).timestamp())
            b = int((midnight + timedelta(hours=hours[1])).timestamp())
            if max(start, a) < min(end, b):
                result.append((max(start, a), min(end, b)))
        day += timedelta(days=1)
    return result


def intersections(start, end, spans, ends):
    index = bisect.bisect_right(ends, start)
    while index < len(spans) and spans[index][0] < end:
        a, b = spans[index]
        if max(start, a) < min(end, b):
            yield max(start, a), min(end, b)
        index += 1


def summarize(con, config, start, end, work_only=False, source="all", metric="co2", sensor="all"):
    if not 0 < end - start <= 366 * 86400:
        raise ValueError("Välj en period mellan 1 sekund och 366 dagar")
    spans = windows(start, end, config["timezone"], config["work_hours"], work_only)
    ends = [b for _, b in spans]
    expected = sum(b-a for a, b in spans)
    hold = config["max_hold_seconds"]
    bucket = max(config["interval_seconds"], math.ceil((end-start) / 480 / 60) * 60)
    clauses, args = ["ts>=?", "ts<?"], [start-hold, end]
    if source != "all":
        clauses.append("source=?")
        args.append(source)
    if sensor != "all":
        clauses.append("sensor=?")
        args.append(sensor)
    # Ordered index scan streams rows; never load a year's raw data into RAM.
    sql = "SELECT sensor,metric,source,ts,value FROM readings WHERE " + " AND ".join(clauses)
    sql += " ORDER BY sensor,metric,source,ts"
    stats, chart = {}, defaultdict(dict)
    previous = None

    def add(row, next_ts):
        sid, measure, src, ts, value = row
        key = (sid, measure, src)
        item = stats.setdefault(key, {"sensor": sid, "metric": measure, "source": src,
                                      "observed_seconds": 0, "weighted_sum": 0.,
                                      "above_seconds": 0, "below_seconds": 0,
                                      "min": None, "max": None, "distribution": defaultdict(int)})
        limit_hi = config["thresholds"]["co2" if measure == "co2" else "temperature_high"]
        limit_lo = config["thresholds"]["temperature_low"] if measure == "temperature" else -math.inf
        for a, b in intersections(max(start, ts), min(next_ts, ts + hold, end), spans, ends):
            seconds = b-a
            item["observed_seconds"] += seconds
            item["weighted_sum"] += seconds*value
            item["above_seconds"] += seconds if value > limit_hi else 0
            item["below_seconds"] += seconds if value < limit_lo else 0
            item["min"] = value if item["min"] is None else min(item["min"], value)
            item["max"] = value if item["max"] is None else max(item["max"], value)
            item["distribution"][round(value, 2 if measure == "temperature" else 0)] += seconds
            if measure != metric:
                continue
            while a < b:
                index = (a - start) // bucket
                stop = min(b, start + (index+1)*bucket)
                cell = chart[key].setdefault(index, [0., 0, value, value])
                cell[0] += value * (stop-a)
                cell[1] += stop-a
                cell[2], cell[3] = min(cell[2], value), max(cell[3], value)
                a = stop

    for row in con.execute(sql, args):
        row = tuple(row)
        if previous:
            next_ts = row[3] if row[:3] == previous[:3] else end
            add(previous, next_ts)
        previous = row
    if previous:
        add(previous, end)
    summaries = []
    for item in stats.values():
        observed = item["observed_seconds"]
        item["mean"] = item.pop("weighted_sum") / observed if observed else None
        item["coverage"] = observed / expected if expected else None
        item["expected_seconds"] = expected
        target, cumulative, p95 = observed*.95, 0, None
        for value, weight in sorted(item.pop("distribution").items()):
            cumulative += weight
            if cumulative >= target:
                p95 = value
                break
        item["p95"] = p95
        summaries.append(item)
    series = []
    for (sid, measure, src), cells in chart.items():
        points = []
        for index in range(math.ceil((end-start) / bucket)):
            cell = cells.get(index)
            t = start + index*bucket
            points.append({"ts": t, "mean": cell[0]/cell[1] if cell else None,
                           "min": cell[2] if cell else None, "max": cell[3] if cell else None,
                           "seconds": cell[1] if cell else 0})
        series.append({"sensor": sid, "source": src, "metric": measure, "points": points})
    event_args = [start, end]
    event_sql = "SELECT * FROM events WHERE ts>=? AND ts<?"
    if sensor != "all":
        event_sql += " AND (sensor=? OR sensor='all')"
        event_args.append(sensor)
    if source != "all":
        event_sql += " AND source=?"
        event_args.append(source)
    events = [dict(r) for r in con.execute(event_sql + " ORDER BY ts LIMIT 500", event_args)]
    return {"start": start, "end": end, "bucket_seconds": bucket,
            "work_only": work_only, "expected_seconds": expected,
            "summary": summaries, "series": series, "events": events}
