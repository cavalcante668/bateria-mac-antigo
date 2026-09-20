#!/usr/bin/env python3

import argparse
import os
import json
import sqlite3
import statistics
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

DATA_DIR = Path(
    os.environ.get(
        "BATTERY_GUARD_DATA_DIR",
        str(
            Path.home()
            / "Library"
            / "Application Support"
            / "Battery Guard"
        )
    )
)

DATA_DIR.mkdir(
    parents=True,
    exist_ok=True
)

DB = DATA_DIR / "battery-history.db"

DESIGN_CAPACITY = 6400
MIN_PREVENTIVE_MV = 3250
DELTA_ALERT_MV = 400

SESSION_GAP = 20 * 60
MAX_INTEGRATION_GAP = 5 * 60
MIN_SESSION = 5 * 60


def n(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def fmt_dt(ts):
    return datetime.fromtimestamp(ts).strftime("%d/%m/%Y %H:%M:%S")


def fmt_duration(seconds):
    if seconds is None:
        return "—"

    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)

    if h:
        return f"{h}h {m:02d}min"
    if m:
        return f"{m}min {s:02d}s"
    return f"{s}s"


def med(values):
    values = [x for x in values if x is not None]
    return statistics.median(values) if values else None


def parse_date(text, is_end=False):
    if not text:
        return None

    for fmt in (
        "%Y-%m-%dT%H:%M",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
    ):
        try:
            dt = datetime.strptime(text, fmt)

            if fmt == "%Y-%m-%d" and is_end:
                dt += timedelta(days=1)

            return dt.timestamp()

        except ValueError:
            pass

    raise SystemExit(f"Data inválida: {text}")


def connect():
    if not DB.exists():
        raise SystemExit(f"Banco não encontrado: {DB}")

    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    return conn


def load_rows(conn, start=None, end=None):
    sql = "SELECT * FROM battery_samples WHERE 1=1"
    params = []

    if start is not None:
        sql += " AND timestamp >= ?"
        params.append(start)

    if end is not None:
        sql += " AND timestamp < ?"
        params.append(end)

    sql += " ORDER BY timestamp"

    return conn.execute(sql, params).fetchall()


def process_list(raw):
    if not raw:
        return []

    try:
        obj = json.loads(raw)
    except Exception:
        return []

    if isinstance(obj, dict):
        for key in ("processes", "top_processes", "items", "data"):
            if isinstance(obj.get(key), list):
                obj = obj[key]
                break
        else:
            obj = [obj]

    if not isinstance(obj, list):
        return []

    out = []

    for item in obj:
        if not isinstance(item, dict):
            continue

        name = (
            item.get("name")
            or item.get("process")
            or item.get("command")
            or item.get("process_name")
            or item.get("display_name")
        )

        if not name:
            continue

        name = str(name).strip()

        if name.lower() in ("top", "ignorar (top)"):
            continue

        power = (
            item.get("power")
            or item.get("power_drain")
            or item.get("POWER")
            or 0
        )

        try:
            power = float(power)
        except Exception:
            power = 0.0

        out.append((name, power))

    return out


def reconstruct_sessions(rows):
    sessions = []
    current = []

    for row in rows:
        on_battery = not bool(row["external_connected"])

        if on_battery:

            if current:
                gap = row["timestamp"] - current[-1]["timestamp"]

                if gap > SESSION_GAP:
                    if len(current) >= 2:
                        sessions.append(current)
                    current = []

            current.append(row)

        else:

            if current:
                if len(current) >= 2:
                    sessions.append(current)
                current = []

    if current and len(current) >= 2:
        sessions.append(current)

    return [
        s for s in sessions
        if s[-1]["timestamp"] - s[0]["timestamp"] >= MIN_SESSION
    ]


def analyze(rows):
    if len(rows) < 2:
        return None

    start = rows[0]["timestamp"]
    end = rows[-1]["timestamp"]

    energy_wh = 0.0
    charge_mah = 0.0
    weighted_power = 0.0
    valid_seconds = 0.0

    good_intervals = 0
    total_intervals = 0

    process_score = defaultdict(float)
    process_time = defaultdict(float)

    for a, b in zip(rows, rows[1:]):

        dt = b["timestamp"] - a["timestamp"]

        if dt <= 0:
            continue

        total_intervals += 1

        if dt > MAX_INTEGRATION_GAP:
            continue

        good_intervals += 1
        valid_seconds += dt

        pa = n(a["instant_power_w"])
        pb = n(b["instant_power_w"])

        if pa is not None and pb is not None:
            p = (abs(pa) + abs(pb)) / 2
            energy_wh += p * dt / 3600
            weighted_power += p * dt

        ia = n(a["instant_ma"])
        ib = n(b["instant_ma"])

        if ia is not None and ib is not None:
            amps = (abs(ia) + abs(ib)) / 2
            charge_mah += amps * dt / 3600

        for name, power in process_list(a["process_json"]):
            process_score[name] += power * dt
            process_time[name] += dt

    powers = [
        abs(n(r["instant_power_w"]))
        for r in rows
        if n(r["instant_power_w"]) is not None
    ]

    temps = [
        n(r["temperature_c"])
        for r in rows
        if n(r["temperature_c"]) is not None
    ]

    deltas = [
        n(r["delta_mv"])
        for r in rows
        if n(r["delta_mv"]) is not None
    ]

    cells = []

    for r in rows:
        for label, key in (
            ("C1", "c1"),
            ("C2", "c2"),
            ("C3", "c3"),
        ):
            value = n(r[key])

            if value is not None:
                cells.append((value, label))

    min_cell_mv = None
    min_cell_name = None

    if cells:
        min_cell_mv, min_cell_name = min(cells)

    total_score = sum(process_score.values())

    offenders = []

    for name, score in sorted(
        process_score.items(),
        key=lambda x: x[1],
        reverse=True
    )[:10]:

        offenders.append({
            "name": name,
            "impact_score": round(score / 60, 2),
            "share": round(
                score / total_score * 100,
                1
            ) if total_score else 0,
            "minutes": round(
                process_time[name] / 60,
                1
            ),
        })

    start_cap = n(rows[0]["capacity_mah"])
    end_cap = n(rows[-1]["capacity_mah"])

    start_max = n(rows[0]["max_capacity_mah"])
    end_max = n(rows[-1]["max_capacity_mah"])

    coverage = (
        good_intervals / total_intervals * 100
        if total_intervals else 0
    )

    return {
        "start": fmt_dt(start),
        "end": fmt_dt(end),
        "duration_seconds": end - start,
        "duration": fmt_duration(end - start),
        "samples": len(rows),
        "coverage": round(coverage, 1),

        "energy_wh": round(energy_wh, 2),
        "charge_mah": round(charge_mah, 0),

        "avg_power_w": (
            round(weighted_power / valid_seconds, 2)
            if valid_seconds else None
        ),

        "peak_power_w": (
            round(max(powers), 2)
            if powers else None
        ),

        "avg_temp_c": (
            round(statistics.mean(temps), 2)
            if temps else None
        ),

        "max_temp_c": (
            round(max(temps), 2)
            if temps else None
        ),

        "min_cell": min_cell_name,

        "min_cell_mv": (
            round(min_cell_mv)
            if min_cell_mv is not None else None
        ),

        "max_delta_mv": (
            round(max(deltas))
            if deltas else None
        ),

        "median_delta_mv": (
            round(med(deltas))
            if deltas else None
        ),

        "start_capacity_mah": start_cap,
        "end_capacity_mah": end_cap,

        "capacity_drop_mah": (
            round(start_cap - end_cap)
            if start_cap is not None and end_cap is not None
            else None
        ),

        "start_max_capacity_mah": start_max,
        "end_max_capacity_mah": end_max,

        "offenders": offenders,
    }



def aggregate_period_rows(rows):
    """
    Analisa um intervalo arbitrário de datas.

    Se houver várias sessões na bateria dentro do período,
    soma apenas os intervalos em bateria, sem contabilizar
    períodos na tomada ou grandes buracos de coleta.
    """

    sessions = reconstruct_sessions(rows)

    analyses = [
        analyze(session)
        for session in sessions
    ]

    analyses = [
        x for x in analyses
        if x is not None
    ]

    if not analyses:
        return None

    if len(analyses) == 1:
        result = analyses[0]
        result["session_count"] = 1
        return result


    total_duration = sum(
        x["duration_seconds"]
        for x in analyses
    )

    total_energy = sum(
        x["energy_wh"]
        for x in analyses
        if x["energy_wh"] is not None
    )

    total_charge = sum(
        x["charge_mah"]
        for x in analyses
        if x["charge_mah"] is not None
    )


    if total_duration:

        avg_power = sum(
            (
                (x["avg_power_w"] or 0)
                *
                x["duration_seconds"]
            )
            for x in analyses
        ) / total_duration

        avg_temp = sum(
            (
                (x["avg_temp_c"] or 0)
                *
                x["duration_seconds"]
            )
            for x in analyses
        ) / total_duration

        coverage = sum(
            (
                (x["coverage"] or 0)
                *
                x["duration_seconds"]
            )
            for x in analyses
        ) / total_duration

    else:

        avg_power = None
        avg_temp = None
        coverage = None


    cell_candidates = [
        (
            x["min_cell_mv"],
            x["min_cell"]
        )
        for x in analyses
        if x["min_cell_mv"] is not None
    ]

    if cell_candidates:
        min_cell_mv, min_cell = min(
            cell_candidates,
            key=lambda x: x[0]
        )
    else:
        min_cell_mv = None
        min_cell = None


    # --------------------------------------------------------
    # AGREGA IMPACT SCORE DOS PROCESSOS
    # --------------------------------------------------------

    process_scores = defaultdict(float)
    process_minutes = defaultdict(float)

    for session in analyses:

        for item in session["offenders"]:

            process_scores[
                item["name"]
            ] += item["impact_score"]

            process_minutes[
                item["name"]
            ] += item["minutes"]


    total_score = sum(
        process_scores.values()
    )

    offenders = []

    for name, score in sorted(
        process_scores.items(),
        key=lambda x: x[1],
        reverse=True
    )[:10]:

        offenders.append({
            "name": name,

            "impact_score":
                round(score, 2),

            "share":
                round(
                    score
                    /
                    total_score
                    * 100,
                    1
                )
                if total_score
                else 0,

            "minutes":
                round(
                    process_minutes[name],
                    1
                ),
        })


    first = analyses[0]
    last = analyses[-1]


    return {

        "start":
            first["start"],

        "end":
            last["end"],

        "duration_seconds":
            total_duration,

        "duration":
            fmt_duration(
                total_duration
            ),

        "session_count":
            len(analyses),

        "samples":
            sum(
                x["samples"]
                for x in analyses
            ),

        "coverage":
            round(
                coverage,
                1
            )
            if coverage is not None
            else None,

        "energy_wh":
            round(
                total_energy,
                2
            ),

        "charge_mah":
            round(
                total_charge,
                0
            ),

        "avg_power_w":
            round(
                avg_power,
                2
            )
            if avg_power is not None
            else None,

        "peak_power_w":
            max(
                x["peak_power_w"]
                for x in analyses
                if x["peak_power_w"]
                is not None
            )
            if any(
                x["peak_power_w"]
                is not None
                for x in analyses
            )
            else None,

        "avg_temp_c":
            round(
                avg_temp,
                2
            )
            if avg_temp is not None
            else None,

        "max_temp_c":
            max(
                x["max_temp_c"]
                for x in analyses
                if x["max_temp_c"]
                is not None
            )
            if any(
                x["max_temp_c"]
                is not None
                for x in analyses
            )
            else None,

        "min_cell":
            min_cell,

        "min_cell_mv":
            min_cell_mv,

        "max_delta_mv":
            max(
                x["max_delta_mv"]
                for x in analyses
                if x["max_delta_mv"]
                is not None
            )
            if any(
                x["max_delta_mv"]
                is not None
                for x in analyses
            )
            else None,

        "median_delta_mv":
            med([
                x["median_delta_mv"]
                for x in analyses
            ]),

        "start_capacity_mah":
            first[
                "start_capacity_mah"
            ],

        "end_capacity_mah":
            last[
                "end_capacity_mah"
            ],

        "capacity_drop_mah":
            round(
                total_charge,
                0
            ),

        "start_max_capacity_mah":
            first[
                "start_max_capacity_mah"
            ],

        "end_max_capacity_mah":
            last[
                "end_max_capacity_mah"
            ],

        "offenders":
            offenders,
    }


def find_worst_comparable(selected, analyses):

    if (
        selected is None
        or
        selected.get(
            "start_capacity_mah"
        ) is None
    ):
        return None


    start_capacity = (
        selected[
            "start_capacity_mah"
        ]
    )

    tolerance = (
        DESIGN_CAPACITY * 0.10
    )

    candidates = []

    for item in analyses:

        other_start = item.get(
            "start_capacity_mah"
        )

        if other_start is None:
            continue

        if abs(
            other_start
            -
            start_capacity
        ) > tolerance:
            continue

        if (
            item["start"]
            ==
            selected["start"]
        ):
            continue

        candidates.append(item)


    if not candidates:
        return None


    return min(
        candidates,
        key=lambda x:
            x["duration_seconds"]
    )

def capacity_history(rows):
    values = [
        n(r["max_capacity_mah"])
        for r in rows
        if n(r["max_capacity_mah"]) is not None
    ]

    if not values:
        return None

    return {
        "first": values[0],
        "current": values[-1],
        "minimum": min(values),
        "maximum": max(values),
        "change": round(values[-1] - values[0], 1),
        "design_percent": round(
            values[-1] / DESIGN_CAPACITY * 100,
            1
        ),
    }


# BATTERY_GUARD_C1_REQUESTED_NOTIFICATION_V2
def notify_analysis_completed():
    try:
        from battery_notifications import add_notification

        add_notification(
            notification_type="analysis",
            title="Battery Guard — Análise da C1 concluída",
            message=(
                "A análise do comportamento dos aplicativos "
                "durante o uso elevado da C1 está pronta "
                "para consulta."
            ),
            severity="info",
            source="battery-analysis.py",
            metadata={
                "analysis_kind": "applications_x_c1",
            },
            popup=True,
        )

    except Exception:
        # Falha na notificação nunca pode derrubar a análise.
        pass


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument("--from", dest="date_from")
    parser.add_argument("--to", dest="date_to")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--notify", action="store_true")

    args = parser.parse_args()

    start = parse_date(args.date_from)
    end = parse_date(args.date_to, True)

    conn = connect()

    all_rows = load_rows(conn)
    sessions = reconstruct_sessions(all_rows)

    analyses = [
        analyze(session)
        for session in sessions
    ]

    analyses = [
        x for x in analyses
        if x is not None
    ]

    if start is not None or end is not None:

        period_rows = load_rows(
            conn,
            start,
            end
        )

        selected = aggregate_period_rows(
            period_rows
        )

        previous = None

    else:

        selected = (
            analyses[-1]
            if analyses else None
        )

        previous = (
            analyses[-2]
            if len(analyses) >= 2 else None
        )

    baseline = {
        "session_count": len(analyses),

        "median_duration_seconds": med([
            x["duration_seconds"]
            for x in analyses
        ]),

        "median_power_w": med([
            x["avg_power_w"]
            for x in analyses
        ]),

        "median_max_temp_c": med([
            x["max_temp_c"]
            for x in analyses
        ]),

        "median_max_delta_mv": med([
            x["max_delta_mv"]
            for x in analyses
        ]),

        "median_energy_wh": med([
            x["energy_wh"]
            for x in analyses
        ]),
    }

    report = {
        "selected": selected,
        "previous": previous,

        "worst_comparable":
            find_worst_comparable(
                selected,
                analyses
            ),

        "baseline": baseline,
        "capacity": capacity_history(all_rows),

        "references": {
            "design_capacity_mah":
                DESIGN_CAPACITY,

            "min_preventive_mv":
                MIN_PREVENTIVE_MV,

            "delta_alert_mv":
                DELTA_ALERT_MV,
        },
    }

    conn.close()

    if args.json:
        print(json.dumps(
            report,
            ensure_ascii=False,
            indent=2
        ))
        if args.notify:
            notify_analysis_completed()

        return

    print()
    print("=" * 70)
    print("BATTERY GUARD — ANÁLISE HISTÓRICA")
    print("=" * 70)

    if selected is None:
        print("Nenhum período suficiente encontrado.")
        return

    print()
    print("ANÁLISE DO PERÍODO")
    print("-" * 70)

    print("Início:               ", selected["start"])
    print("Fim:                  ", selected["end"])
    print("Tempo na bateria:     ", selected["duration"])
    print("Energia consumida:    ", selected["energy_wh"], "Wh")
    print("Carga consumida:      ", selected["charge_mah"], "mAh")
    print("Potência média:       ", selected["avg_power_w"], "W")
    print("Pico:                 ", selected["peak_power_w"], "W")
    print("Temperatura média:    ", selected["avg_temp_c"], "°C")
    print("Temperatura máxima:   ", selected["max_temp_c"], "°C")

    if selected["min_cell_mv"] is not None:
        print(
            "Menor célula:         ",
            selected["min_cell"],
            f'{selected["min_cell_mv"]/1000:.3f}',
            "V"
        )

    print("DELTA máximo:         ", selected["max_delta_mv"], "mV")
    print("Cobertura dos dados:  ", selected["coverage"], "%")

    print()
    print("MAIORES OFENSORES")
    print("-" * 70)

    if not selected["offenders"]:
        print("Nenhum dado de processos encontrado.")
    else:
        for i, item in enumerate(
            selected["offenders"][:5],
            start=1
        ):
            print(
                f'{i}. {item["name"]} | '
                f'Impact Score {item["impact_score"]} | '
                f'{item["share"]}% | '
                f'{item["minutes"]} min observados'
            )

    print()
    print("REFERÊNCIAS")
    print("-" * 70)

    if baseline["median_duration_seconds"] is not None:
        print(
            "Mediana autonomia:   ",
            fmt_duration(
                baseline["median_duration_seconds"]
            )
        )

    print(
        "Potência média hist.: ",
        round(baseline["median_power_w"], 2)
        if baseline["median_power_w"] is not None
        else "—",
        "W"
    )

    print(
        "Temp. máxima hist.:   ",
        round(baseline["median_max_temp_c"], 2)
        if baseline["median_max_temp_c"] is not None
        else "—",
        "°C"
    )

    print(
        "DELTA máximo hist.:   ",
        round(baseline["median_max_delta_mv"])
        if baseline["median_max_delta_mv"] is not None
        else "—",
        "mV"
    )

    print(
        "Limite preventivo:   ",
        MIN_PREVENTIVE_MV,
        "mV"
    )

    print(
        "DELTA de alerta:      ",
        DELTA_ALERT_MV,
        "mV"
    )

    if previous is not None:

        print()
        print("CICLO ANTERIOR")
        print("-" * 70)

        print("Tempo:                ", previous["duration"])
        print("Energia:              ", previous["energy_wh"], "Wh")
        print("Potência média:       ", previous["avg_power_w"], "W")
        print("DELTA máximo:         ", previous["max_delta_mv"], "mV")

    capacity = report["capacity"]

    if capacity is not None:

        print()
        print("CAPACIDADE BMS")
        print("-" * 70)

        print("Primeiro registro:    ", capacity["first"], "mAh")
        print("Atual:                ", capacity["current"], "mAh")
        print("Mínima observada:     ", capacity["minimum"], "mAh")
        print("Máxima observada:     ", capacity["maximum"], "mAh")
        print("Variação:             ", capacity["change"], "mAh")
        print("Atual / design:       ", capacity["design_percent"], "%")

    if args.notify:
        notify_analysis_completed()


if __name__ == "__main__":
    main()
