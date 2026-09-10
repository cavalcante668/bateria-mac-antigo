#!/usr/bin/env python3

import json
import os
import re
import sqlite3
import statistics
import subprocess
import threading
import time

from collections import deque
from http.server import BaseHTTPRequestHandler, HTTPServer


# ============================================================
# CONFIGURAÇÃO
# ============================================================

HOST = "127.0.0.1"
PORT = 8765

# Limite PREVENTIVO, não é o cutoff físico conhecido da bateria.
TARGET_MV = 3250

MAX_POINTS = 300

HOME = os.path.expanduser("~")

DB_PATH = os.path.join(HOME, "battery-history.db")
STATE_PATH = os.path.join(HOME, ".battery-view-state.json")

history = deque(maxlen=MAX_POINTS)
current = {}

lock = threading.Lock()


# ============================================================
# UTILIDADES
# ============================================================

def run(cmd):
    try:
        return subprocess.check_output(
            cmd,
            text=True,
            stderr=subprocess.DEVNULL
        )
    except Exception:
        return ""


def rx(pattern, text, default=None):
    m = re.search(pattern, text, re.M)
    return m.group(1) if m else default


def signed64(value):
    """
    O macOS às vezes mostra corrente negativa como uint64:
    18446744073709550xxx

    Converte corretamente para inteiro negativo.
    """
    try:
        n = int(value)

        if n >= 2**63:
            n -= 2**64

        return n

    except Exception:
        return 0


def format_duration(seconds):
    if seconds is None:
        return "Sem registro"

    seconds = max(0, int(seconds))

    h = seconds // 3600
    m = (seconds % 3600) // 60

    if h:
        return f"{h}h {m} min"

    if m:
        return f"{m} min"

    return f"{seconds}s"


def format_datetime(ts):
    if not ts:
        return "Sem registro"

    return time.strftime(
        "%d/%m %H:%M",
        time.localtime(ts)
    )


# ============================================================
# ESTADO PERSISTENTE DO CARREGADOR
# ============================================================

def load_state():
    try:
        with open(STATE_PATH, "r") as f:
            return json.load(f)

    except Exception:
        return {
            "ac_active": False,
            "ac_start": None,
            "last_ac_end": None,
            "last_ac_duration": None
        }


def save_state(state):
    try:
        with open(STATE_PATH, "w") as f:
            json.dump(state, f)

    except Exception:
        pass


charger_state = load_state()


# ============================================================
# SQLITE
# ============================================================

def db_connect():
    db = sqlite3.connect(DB_PATH, timeout=5, check_same_thread=False)

    db.execute("""
        CREATE TABLE IF NOT EXISTS battery_samples (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp REAL NOT NULL,

            c1 INTEGER,
            c2 INTEGER,
            c3 INTEGER,

            min_mv INTEGER,
            delta_mv INTEGER,

            voltage_v REAL,

            current_ma INTEGER,
            instant_ma INTEGER,

            power_w REAL,
            instant_power_w REAL,

            capacity_mah INTEGER,
            max_capacity_mah INTEGER,
            remaining_wh REAL,

            percent INTEGER,
            temperature_c REAL,

            external_connected INTEGER,
            charging INTEGER,

            system_power_w REAL,

            process_json TEXT
        )
    """)

    db.execute("""
        CREATE TABLE IF NOT EXISTS process_catalog (
            technical_name TEXT PRIMARY KEY,
            friendly_name TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            process_type TEXT,
            description TEXT,
            source TEXT,
            source_url TEXT,
            created_at REAL,
            last_checked REAL
        )
    """)

    db.execute("""
        CREATE TABLE IF NOT EXISTS charger_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            start_timestamp REAL,
            end_timestamp REAL,
            duration_seconds REAL
        )
    """)

    db.commit()

    return db


db = db_connect()


# ============================================================
# CARREGA HISTÓRICO RECENTE
# ============================================================

def load_recent_history():
    try:
        cur = db.execute("""
            SELECT
                timestamp,
                c1,
                c2,
                c3,
                min_mv,
                delta_mv,
                instant_power_w,
                percent
            FROM battery_samples
            ORDER BY timestamp DESC
            LIMIT 180
        """)

        rows = list(reversed(cur.fetchall()))

        for row in rows:
            ts, c1, c2, c3, minimum, delta, power, percent = row

            history.append({
                "ts": ts,
                "time": time.strftime(
                    "%H:%M:%S",
                    time.localtime(ts)
                ),
                "short_time": time.strftime(
                    "%H:%M",
                    time.localtime(ts)
                ),
                "c1": c1,
                "c2": c2,
                "c3": c3,
                "min": minimum,
                "delta": delta,
                "power": abs(power or 0),
                "percent": percent
            })

    except Exception:
        pass


load_recent_history()


# ============================================================
# PROCESSOS / POWER
# ============================================================


process_catalog_cache = {}


def refresh_process_catalog_cache():

    global process_catalog_cache

    try:
        conn = sqlite3.connect(
            DB_PATH,
            timeout=5
        )

        conn.execute("""
            CREATE TABLE IF NOT EXISTS process_catalog (
                technical_name TEXT PRIMARY KEY,
                friendly_name TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                process_type TEXT,
                description TEXT,
                source TEXT,
                source_url TEXT,
                created_at REAL,
                last_checked REAL
            )
        """)

        rows = conn.execute("""
            SELECT
                technical_name,
                friendly_name,
                status
            FROM process_catalog
        """).fetchall()

        conn.close()

        process_catalog_cache = {
            row[0]: {
                "friendly_name": row[1],
                "status": row[2]
            }
            for row in rows
        }

    except Exception:
        pass


def catalog_process_name(technical_name):

    n = technical_name.strip()

    cached = process_catalog_cache.get(n)

    if cached:

        friendly = cached.get("friendly_name")
        status = cached.get("status")

        if friendly and status != "pending":

            # Não duplica o nome técnico caso ele já esteja
            # presente na descrição amigável.
            if n.lower() in friendly.lower():
                return friendly

            return f"{friendly} ({n})"

        return f"{n} (pending)"


    # Processo ainda nunca visto.
    process_catalog_cache[n] = {
        "friendly_name": None,
        "status": "pending"
    }

    try:

        conn = sqlite3.connect(
            DB_PATH,
            timeout=5
        )

        conn.execute("""
            INSERT OR IGNORE INTO process_catalog (
                technical_name,
                status,
                created_at
            )
            VALUES (?, 'pending', ?)
        """, (
            n,
            time.time()
        ))

        conn.commit()
        conn.close()

    except Exception:
        pass

    return f"{n} (pending)"


refresh_process_catalog_cache()


def normalize_process(name):

    n = name.strip()

    # Aplicativos conhecidos
    if "Google Chrome" in n:
        return "Google Chrome"

    if "VBoxHeadless" in n:
        return "Máquina virtual VirtualBox (VBoxHeadless)"

    if "WindowServer" in n:
        return "Interface gráfica do macOS (WindowServer)"

    if "Spotify" in n:
        return "Spotify"

    if "Terminal" in n:
        return "Terminal"

    if "Microsoft Excel" in n:
        return "Microsoft Excel"

    if "Microsoft Word" in n:
        return "Microsoft Word"


    # Spotlight / indexação
    if n == "mdworker_shared":
        return "Indexação do Spotlight (mdworker_shared)"

    if n == "mdworker":
        return "Indexação do Spotlight (mdworker)"

    if n == "mds":
        return "Serviço do Spotlight (mds)"

    if n == "mds_stores":
        return "Banco de índice do Spotlight (mds_stores)"

    if n == "Spotlight":
        return "Busca do Spotlight"


    # Segurança / privacidade
    if n == "trustd":
        return "Segurança e certificados (trustd)"

    if n == "tccd":
        return "Privacidade e permissões (tccd)"

    if n == "syspolicyd":
        return "Verificação de segurança de apps (syspolicyd)"

    if n == "securityd":
        return "Segurança do sistema (securityd)"


    # Serviços de fundo
    if n == "dasd":
        return "Tarefas em segundo plano (dasd)"

    if n == "UserEventAgent":
        return "Eventos do sistema (UserEventAgent)"

    if n == "ContextStoreAgent":
        return "Contexto do sistema e Siri (ContextStoreAgent)"

    if n == "sharedfilelistd":
        return "Itens recentes do macOS (sharedfilelistd)"

    if n == "runningboardd":
        return "Gerenciamento de aplicativos (runningboardd)"

    if n == "launchservicesd":
        return "Gerenciamento de aplicativos (launchservicesd)"


    # Hardware / conectividade
    if n == "bluetoothd":
        return "Bluetooth (bluetoothd)"

    if n == "airportd":
        return "Wi-Fi (airportd)"

    if n == "coreaudiod":
        return "Áudio do sistema (coreaudiod)"

    if n == "powerd":
        return "Gerenciamento de energia (powerd)"


    # Data / hora
    if n == "timed":
        return "Data e hora do sistema (timed)"


    # Arquivos / armazenamento
    if n == "fseventsd":
        return "Monitoramento de arquivos (fseventsd)"

    if n == "diskarbitrationd":
        return "Gerenciamento de discos (diskarbitrationd)"


    # iCloud
    if n == "bird":
        return "Sincronização do iCloud Drive (bird)"

    if n == "cloudd":
        return "Sincronização do iCloud (cloudd)"


    # Se não conhecermos, mantém o nome original
    return catalog_process_name(n)
def top_processes():

    refresh_process_catalog_cache()

    # Duas amostras são necessárias para POWER funcionar direito.
    out = run([
        "top",
        "-l", "2",
        "-s", "1",
        "-o", "power",
        "-stats", "pid,command,cpu,power"
    ])

    if not out:
        return []

    # Pega somente a última tabela.
    pos = out.rfind("PID")

    if pos >= 0:
        out = out[pos:]

    grouped = {}

    for line in out.splitlines():

        m = re.match(
            r'^\s*(\d+)\s+(.+?)\s+([\d.]+)\s+([\d.]+)\s*$',
            line
        )

        if not m:
            continue

        pid = int(m.group(1))
        name = normalize_process(m.group(2))
        cpu = float(m.group(3))
        power = float(m.group(4))

        if name in ("top", "head", "sleep"):
            continue

        if name not in grouped:
            grouped[name] = {
                "name": name,
                "cpu": 0.0,
                "power": 0.0,
                "pids": []
            }

        grouped[name]["cpu"] += cpu
        grouped[name]["power"] += power
        grouped[name]["pids"].append(pid)

    rows = list(grouped.values())

    rows.sort(
        key=lambda x: x["power"],
        reverse=True
    )

    return rows[:10]


# ============================================================
# TENDÊNCIA
# ============================================================

def estimate_slope(points):

    if len(points) < 4:
        return None

    now = points[-1]["ts"]

    recent = [
        p
        for p in points
        if now - p["ts"] <= 300
    ]

    if len(recent) < 4:
        return None

    xs = [
        (p["ts"] - recent[0]["ts"]) / 60.0
        for p in recent
    ]

    ys = [
        p["min"]
        for p in recent
    ]

    xmean = statistics.mean(xs)
    ymean = statistics.mean(ys)

    den = sum(
        (x - xmean) ** 2
        for x in xs
    )

    if den == 0:
        return None

    slope = sum(
        (x - xmean) * (y - ymean)
        for x, y in zip(xs, ys)
    ) / den

    return slope


# ============================================================
# COLETOR
# ============================================================

def collector():

    global current
    global charger_state

    last_update_time = None
    last_process_read = 0
    processes = []

    while True:

        text = run([
            "ioreg",
            "-rn",
            "AppleSmartBattery"
        ])

        cells = re.search(
            r'CellVoltage"=\((\d+),(\d+),(\d+)\)',
            text
        )

        if not cells:
            time.sleep(1)
            continue

        # ----------------------------------------------------
        # CÉLULAS
        # ----------------------------------------------------

        c1, c2, c3 = map(
            int,
            cells.groups()
        )

        minimum = min(c1, c2, c3)
        maximum = max(c1, c2, c3)

        delta = maximum - minimum


        # ----------------------------------------------------
        # TENSÃO DO PACK
        # ----------------------------------------------------

        voltage_mv = int(
            rx(
                r'^\s+"Voltage" = (\d+)',
                text,
                "0"
            )
        )

        voltage_v = voltage_mv / 1000.0


        # ----------------------------------------------------
        # CORRENTE
        # ----------------------------------------------------

        avg_raw = rx(
            r'^\s+"Amperage" = (\d+)',
            text,
            "0"
        )

        instant_raw = rx(
            r'^\s+"InstantAmperage" = (\d+)',
            text,
            "0"
        )

        current_ma = signed64(avg_raw)
        instant_ma = signed64(instant_raw)


        # ----------------------------------------------------
        # POTÊNCIA REAL NO LADO DA BATERIA
        # ----------------------------------------------------

        avg_power_w = (
            voltage_v *
            current_ma /
            1000.0
        )

        instant_power_w = (
            voltage_v *
            instant_ma /
            1000.0
        )


        # ----------------------------------------------------
        # CAPACIDADE
        # ----------------------------------------------------

        capacity_mah = int(
            rx(
                r'^\s+"CurrentCapacity" = (\d+)',
                text,
                "0"
            )
        )

        max_capacity_mah = int(
            rx(
                r'^\s+"MaxCapacity" = (\d+)',
                text,
                "0"
            )
        )


        # ----------------------------------------------------
        # ENERGIA RESTANTE APROXIMADA
        # ----------------------------------------------------

        remaining_wh = (
            voltage_v *
            capacity_mah /
            1000.0
        )


        # ----------------------------------------------------
        # SYSTEM POWER
        # ----------------------------------------------------

        system_power_raw = int(
            rx(
                r'"SystemPower"=(\d+)',
                text,
                "0"
            )
        )

        system_power_w = (
            system_power_raw /
            1000.0
        )


        # ----------------------------------------------------
        # TEMPERATURA
        # ----------------------------------------------------

        temp_raw = rx(
            r'^\s+"Temperature" = (\d+)',
            text,
            None
        )

        try:
            temperature_c = (
                int(temp_raw) / 100.0
            )
        except Exception:
            temperature_c = None


        # ----------------------------------------------------
        # %
        # ----------------------------------------------------

        percent_raw = rx(
            r'"StateOfCharge"=(\d+)',
            text,
            None
        )

        try:
            percent = int(percent_raw)
        except Exception:
            percent = None


        # ----------------------------------------------------
        # CARREGADOR
        # ----------------------------------------------------

        external = rx(
            r'^\s+"ExternalConnected" = (Yes|No)',
            text,
            "No"
        )

        charging = rx(
            r'^\s+"IsCharging" = (Yes|No)',
            text,
            "No"
        )

        external_bool = external == "Yes"
        charging_bool = charging == "Yes"

        now = time.time()


        # ----------------------------------------------------
        # CONTROLE DE TEMPO NA CA
        # ----------------------------------------------------

        was_ac = charger_state.get(
            "ac_active",
            False
        )

        if external_bool:

            if not was_ac:

                # Terminou uma sessão na bateria.
                battery_start = charger_state.get("battery_start")

                if battery_start:

                    charger_state["last_battery_start"] = battery_start
                    charger_state["last_battery_end"] = now
                    charger_state["last_battery_duration"] = (
                        now - battery_start
                    )

                charger_state["ac_start"] = now
                charger_state["ac_active"] = True
                charger_state["battery_start"] = None

                save_state(charger_state)

        else:

            if was_ac:

                start = charger_state.get(
                    "ac_start"
                )

                if start:

                    duration = now - start

                    charger_state[
                        "last_ac_end"
                    ] = now

                    charger_state[
                        "last_ac_duration"
                    ] = duration

                    try:
                        db.execute("""
                            INSERT INTO charger_sessions (
                                start_timestamp,
                                end_timestamp,
                                duration_seconds
                            )
                            VALUES (?, ?, ?)
                        """, (
                            start,
                            now,
                            duration
                        ))

                        db.commit()

                    except Exception:
                        pass

                charger_state["ac_active"] = False
                charger_state["ac_start"] = None
                charger_state["battery_start"] = now

                save_state(charger_state)


        # ----------------------------------------------------
        # TEMPO DE CONEXÃO
        # ----------------------------------------------------

        if external_bool:

            ac_start = charger_state.get(
                "ac_start"
            )

            if ac_start:

                ac_duration_text = (
                    "Conectado há " +
                    format_duration(
                        now - ac_start
                    )
                )

            else:
                ac_duration_text = (
                    "Carregador conectado"
                )

            last_ac_text = "Agora"

        else:

            last_end = charger_state.get(
                "last_ac_end"
            )

            last_duration = (
                charger_state.get(
                    "last_ac_duration"
                )
            )

            last_ac_text = (
                format_datetime(last_end)
            )

            ac_duration_text = (
                "Ficou conectado por " +
                format_duration(
                    last_duration
                )
            )


        # ----------------------------------------------------
        # TEMPO NA BATERIA
        # ----------------------------------------------------

        if external_bool:

            # Enquanto está na tomada, mostramos a ÚLTIMA
            # sessão concluída na bateria.
            last_battery_duration = charger_state.get(
                "last_battery_duration"
            )

            last_battery_start = charger_state.get(
                "last_battery_start"
            )

            last_battery_end = charger_state.get(
                "last_battery_end"
            )

            # Compatibilidade com sessões anteriores à atualização:
            # se acabamos de conectar e ainda não havia
            # last_battery_duration, tenta reconstruir usando
            # fim da CA anterior -> início da CA atual.
            if (
                not last_battery_duration
                and charger_state.get("last_ac_end")
                and charger_state.get("ac_start")
            ):

                inferred_start = charger_state.get(
                    "last_ac_end"
                )

                inferred_end = charger_state.get(
                    "ac_start"
                )

                if inferred_end > inferred_start:

                    last_battery_start = inferred_start
                    last_battery_end = inferred_end
                    last_battery_duration = (
                        inferred_end - inferred_start
                    )

                    charger_state["last_battery_start"] = (
                        last_battery_start
                    )

                    charger_state["last_battery_end"] = (
                        last_battery_end
                    )

                    charger_state["last_battery_duration"] = (
                        last_battery_duration
                    )

                    save_state(charger_state)


            if last_battery_duration:

                battery_duration_text = format_duration(
                    last_battery_duration
                )

                if last_battery_start and last_battery_end:

                    battery_since_text = (
                        "última sessão: "
                        + format_datetime(last_battery_start)
                        + " → "
                        + format_datetime(last_battery_end)
                    )

                else:

                    battery_since_text = "última sessão na bateria"

            else:

                battery_duration_text = "Sem registro"
                battery_since_text = "nenhuma sessão anterior registrada"


        else:

            # Sessão atual na bateria.
            battery_start = charger_state.get(
                "battery_start"
            )

            if not battery_start:

                battery_start = (
                    charger_state.get("last_ac_end")
                    or now
                )

                charger_state["battery_start"] = battery_start
                save_state(charger_state)


            battery_duration_text = format_duration(
                now - battery_start
            )

            battery_since_text = (
                "desde "
                + format_datetime(battery_start)
            )


        # ----------------------------------------------------
        # PROCESSOS
        # Só roda 1 vez/min para não pesar.
        # ----------------------------------------------------

        if now - last_process_read >= 60:

            processes = top_processes()

            last_process_read = now


        # ----------------------------------------------------
        # UPDATE TIME REAL DO BMS
        # ----------------------------------------------------

        update_time = rx(
            r'"UpdateTime"=(\d+)',
            text,
            None
        )


        # ----------------------------------------------------
        # PONTO DO GRÁFICO
        # ----------------------------------------------------

        point = {
            "ts": now,

            "time": time.strftime(
                "%H:%M:%S"
            ),

            "short_time": time.strftime(
                "%H:%M"
            ),

            "c1": c1,
            "c2": c2,
            "c3": c3,

            "min": minimum,
            "delta": delta,

            "power": round(
                abs(instant_power_w),
                2
            ),

            "percent": percent
        }

        with lock:

            history.append(point)

            slope = estimate_slope(
                list(history)
            )

            eta = None

            if (
                slope is not None and
                slope < -1 and
                minimum > TARGET_MV
            ):

                eta_calc = (
                    minimum - TARGET_MV
                ) / (-slope)

                if eta_calc >= 0:
                    eta = round(eta_calc)


            # ------------------------------------------------
            # STATUS
            # ------------------------------------------------

            if (
                minimum <= 3200 or
                delta >= 500
            ):

                status = "CRÍTICO"

            elif (
                minimum <= 3350 and
                delta >= 400
            ):

                status = "ALERTA"

            elif (
                minimum <= 3500 or
                delta >= 350
            ):

                status = "ATENÇÃO"

            else:

                status = "SEGURO"


            # ------------------------------------------------
            # DIREÇÃO DA ENERGIA
            # ------------------------------------------------

            if instant_ma > 0:

                power_direction = (
                    "↑ entrando na bateria"
                )

                current_direction = (
                    "↑ corrente de carga"
                )

            elif instant_ma < 0:

                power_direction = (
                    "↓ saindo da bateria"
                )

                current_direction = (
                    "↓ corrente de descarga"
                )

            else:

                power_direction = (
                    "sem fluxo detectado"
                )

                current_direction = (
                    "sem fluxo detectado"
                )


            current = {

                **point,

                "status": status,

                "voltage_v": round(
                    voltage_v,
                    3
                ),

                "current_ma": current_ma,

                "instant_ma": instant_ma,

                "avg_power_w": round(
                    avg_power_w,
                    2
                ),

                "instant_power_w": round(
                    instant_power_w,
                    2
                ),

                "system_power_w": round(
                    system_power_w,
                    2
                ),

                "power_direction":
                    power_direction,

                "current_direction":
                    current_direction,

                "capacity_mah":
                    capacity_mah,

                "max_capacity_mah":
                    max_capacity_mah,

                "remaining_wh":
                    round(
                        remaining_wh,
                        2
                    ),

                "max_wh_estimate": round(
                    voltage_v *
                    max_capacity_mah /
                    1000.0,
                    2
                ),

                "temperature":
                    temperature_c,

                "external":
                    external,

                "charging":
                    charging,

                "slope":
                    None
                    if slope is None
                    else round(slope, 1),

                "eta":
                    eta,

                "last_ac_text":
                    last_ac_text,

                "ac_duration_text":
                    ac_duration_text,

                "battery_duration_text":
                    battery_duration_text,

                "battery_since_text":
                    battery_since_text,

                "processes":
                    processes
            }


        # ----------------------------------------------------
        # SQLITE — somente quando BMS realmente atualiza
        # ----------------------------------------------------

        if (
            update_time and
            update_time != last_update_time
        ):

            last_update_time = update_time

            try:

                db.execute("""
                    INSERT INTO battery_samples (
                        timestamp,
                        c1,
                        c2,
                        c3,
                        min_mv,
                        delta_mv,
                        voltage_v,
                        current_ma,
                        instant_ma,
                        power_w,
                        instant_power_w,
                        capacity_mah,
                        max_capacity_mah,
                        remaining_wh,
                        percent,
                        temperature_c,
                        external_connected,
                        charging,
                        system_power_w,
                        process_json
                    )
                    VALUES (
                        ?,?,?,?,?,?,?,?,?,?,
                        ?,?,?,?,?,?,?,?,?,?
                    )
                """, (
                    now,

                    c1,
                    c2,
                    c3,

                    minimum,
                    delta,

                    voltage_v,

                    current_ma,
                    instant_ma,

                    avg_power_w,
                    instant_power_w,

                    capacity_mah,
                    max_capacity_mah,

                    remaining_wh,

                    percent,
                    temperature_c,

                    1 if external_bool else 0,
                    1 if charging_bool else 0,

                    system_power_w,

                    json.dumps(
                        processes
                    )
                ))

                db.commit()

            except Exception:
                pass


        time.sleep(1)


# ============================================================
# HTML
# ============================================================

HTML = r'''<!doctype html>

<html lang="pt-BR">

<head>

<meta charset="utf-8">

<meta name="viewport"
      content="width=device-width,initial-scale=1">

<title>Battery Guard</title>

<style>

body {
    font-family:
        -apple-system,
        BlinkMacSystemFont,
        sans-serif;

    margin:0;

    background:#111;

    color:#eee;
}

main {
    max-width:1180px;

    margin:auto;

    padding:24px;
}

header {
    display:flex;

    justify-content:space-between;

    align-items:center;

    margin-bottom:18px;
}

h1 {
    margin:0;

    font-size:26px;
}

.status {
    font-weight:700;

    font-size:18px;

    padding:10px 18px;

    border-radius:22px;
}

.SEGURO {
    background:#163c25;
}

.ATENÇÃO {
    background:#574815;
}

.ALERTA {
    background:#663b13;
}

.CRÍTICO {
    background:#671f1f;
}

.cards {
    display:grid;

    grid-template-columns:
        repeat(
            auto-fit,
            minmax(160px,1fr)
        );

    gap:12px;

    margin-bottom:18px;
}

.card {
    background:#1d1d1f;

    border-radius:12px;

    padding:16px;
}

.label {
    color:#999;

    font-size:12px;

    margin-bottom:6px;
}

.value {
    font-size:22px;

    font-weight:600;
}

.small {
    font-size:12px;

    color:#888;

    margin-top:5px;

    line-height:1.35;
}

.panel {
    background:#1d1d1f;

    border-radius:12px;

    padding:16px;

    margin-bottom:14px;
}

.panel h2 {
    margin:0 0 10px 0;

    font-size:16px;
}

svg {
    width:100%;

    height:280px;

    background:#171717;

    border-radius:8px;
}

.grid {
    stroke:#303030;

    stroke-width:1;
}

.axislabel {
    fill:#999;

    font-size:11px;
}

.series-c1 {
    stroke:#ff6b6b;
}

.series-c2 {
    stroke:#4dabf7;
}

.series-c3 {
    stroke:#69db7c;
}

.series-power {
    stroke:#ffd43b;
}

.legend {
    display:flex;

    gap:14px;

    margin-bottom:8px;

    color:#aaa;

    font-size:12px;
}

.dot {
    width:9px;

    height:9px;

    display:inline-block;

    border-radius:50%;

    margin-right:5px;
}

.process {
    display:grid;

    grid-template-columns:
        1fr 90px 110px 120px;

    padding:8px 0;

    border-bottom:
        1px solid #292929;
}

.process-header {
    color:#888;

    font-size:12px;
}


.drain-badge {
    display:inline-block;
    padding:4px 9px;
    border-radius:12px;
    font-size:11px;
    font-weight:700;
    text-align:center;
}

.drain-low {
    background:#183d28;
    color:#9ee6b8;
}

.drain-medium {
    background:#4b4319;
    color:#f1db7a;
}

.drain-high {
    background:#653c17;
    color:#ffbd78;
}

.drain-veryhigh {
    background:#641f24;
    color:#ff9b9b;
}


.mini-gauge {
    width:100%;
    height:110px;
    display:block;
    margin-top:8px;
}

.gauge-track {
    stroke:#2a2a2a;
    stroke-width:10;
    fill:none;
    stroke-linecap:round;
}

.gauge-danger {
    stroke:#8f2d2d;
    stroke-width:10;
    fill:none;
    stroke-linecap:round;
}

.gauge-warn {
    stroke:#8a6e19;
    stroke-width:10;
    fill:none;
    stroke-linecap:round;
}

.gauge-good {
    stroke:#1f6b3b;
    stroke-width:10;
    fill:none;
    stroke-linecap:round;
}

.gauge-needle {
    stroke:#f0f0f0;
    stroke-width:2.6;
    fill:none;
    stroke-linecap:round;
}

.gauge-center {
    fill:#f0f0f0;
}

.gauge-label {
    fill:#9a9a9a;
    font-size:11px;
}

footer {
    color:#777;

    font-size:12px;

    margin-top:16px;
}

</style>

</head>

<body>

<main>

<header>

<h1>Battery Guard</h1>

<div
    id="status"
    class="status">
    ---
</div>

</header>


<div class="cards">


<div class="card">

<div class="label">
C1
</div>

<div id="c1"
     class="value">
---
</div>

</div>


<div class="card">

<div class="label">
C2
</div>

<div id="c2"
     class="value">
---
</div>

</div>


<div class="card">

<div class="label">
C3
</div>

<div id="c3"
     class="value">
---
</div>

</div>


<div class="card">

<div class="label">
DELTA
</div>

<div id="delta"
     class="value">
---
</div>

</div>


<div class="card">

<div class="label">
Potência agora
</div>

<div id="power"
     class="value">
---
</div>

<div
    id="powerdir"
    class="small">
</div>

</div>


<div class="card">

<div class="label">
Corrente agora
</div>

<div id="current"
     class="value">
---
</div>

<div
    id="currentdir"
    class="small">
</div>

</div>


<div class="card">

<div class="label">
Média BMS
</div>

<div id="avgpower"
     class="value">
---
</div>

<div
    id="avgcurrent"
    class="small">
</div>

</div>


<div class="card">

<div class="label">
Energia restante
</div>

<div id="remainingwh"
     class="value">
---
</div>

<div class="small">
estimativa do BMS
</div>



</div>


<div class="card">

<div class="label">
Carga restante
</div>

<div id="remainingmah"
     class="value">
---
</div>

<div id="maxmah"
     class="small">
estimativa do BMS
</div>



</div>


<div class="card">

<div class="label">
Queda da pior célula
</div>

<div id="slope"
     class="value">
---
</div>

</div>


<div class="card">

<div class="label">
Margem estimada
</div>

<div id="eta"
     class="value">
---
</div>

<div class="small">
até 3,25 V — limite preventivo
</div>

</div>


<div class="card">

<div class="label">
% informado pelo macOS
</div>

<div id="percent"
     class="value">
---
</div>

<div class="small">
não confiável nesta bateria
</div>

</div>


<div class="card">

<div class="label">
Tempo na bateria
</div>

<div id="batterytime"
     class="value">
---
</div>

<div id="batterysince"
     class="small">
</div>

</div>


<div class="card">

<div class="label">
Última vez na CA
</div>

<div id="lastac"
     class="value">
---
</div>

<div id="acduration"
     class="small">
</div>

</div>


</div>


<div class="panel">

<h2>
Tensão das células
</h2>

<div class="legend">

<span>
<span class="dot"
      style="background:#ff6b6b"></span>
C1
</span>

<span>
<span class="dot"
      style="background:#4dabf7"></span>
C2
</span>

<span>
<span class="dot"
      style="background:#69db7c"></span>
C3
</span>

</div>

<svg id="cells"></svg>

</div>


<div class="panel">

<h2>
Potência no lado da bateria
</h2>

<div class="small"
     style="margin-bottom:8px">

Valor absoluto da potência instantânea
que entra ou sai da bateria.

</div>

<svg id="powerchart"></svg>

</div>


<div class="panel">

<h2>
Maior impacto agora
</h2>

<div class="process process-header">

<div>Processo</div>

<div>CPU</div>

<div>Power Drain</div>

<div>Nível</div>

</div>

<div id="processes"></div>

</div>


<footer>

Histórico persistente:
~/battery-history.db

<br>

Power Drain indica o impacto energético relativo de cada processo.
Não representa watts individuais.

</footer>

</main>


<script>


function svgEl(
    name,
    attrs={}
) {

    const el =
        document.createElementNS(
            "http://www.w3.org/2000/svg",
            name
        );

    for (
        const [k,v]
        of Object.entries(attrs)
    ) {

        el.setAttribute(k,v);

    }

    return el;
}


function drawChart(
    id,
    data,
    series,
    yMin,
    yMax,
    formatter
) {

    const svg =
        document.getElementById(id);

    svg.innerHTML = "";

    if (
        !data ||
        data.length < 2
    ) {
        return;
    }

    const w =
        svg.clientWidth || 900;

    const h =
        svg.clientHeight || 280;

    const pad = {
        left:60,
        right:18,
        top:12,
        bottom:48
    };

    const iw =
        w -
        pad.left -
        pad.right;

    const ih =
        h -
        pad.top -
        pad.bottom;


    function xPos(i) {

        return (
            pad.left +
            (
                i /
                (data.length - 1)
            ) * iw
        );

    }


    function yPos(v) {

        return (
            pad.top +
            ih -
            (
                (v - yMin) /
                (yMax - yMin)
            ) * ih
        );

    }


    for (
        let i=0;
        i<=4;
        i++
    ) {

        const value =
            yMin +
            (
                yMax - yMin
            ) * i / 4;

        const y =
            yPos(value);


        svg.appendChild(
            svgEl(
                "line",
                {
                    x1:pad.left,
                    y1:y,
                    x2:w-pad.right,
                    y2:y,
                    class:"grid"
                }
            )
        );


        const label =
            svgEl(
                "text",
                {
                    x:pad.left-8,
                    y:y+4,
                    "text-anchor":"end",
                    class:"axislabel"
                }
            );

        label.textContent =
            formatter(value);

        svg.appendChild(label);

    }


    const marks = [
        0,
        Math.floor(
            (data.length-1)/3
        ),
        Math.floor(
            (data.length-1)*2/3
        ),
        data.length-1
    ];


    [...new Set(marks)]
    .forEach(idx => {

        const p = data[idx];

        const x =
            xPos(idx);


        svg.appendChild(
            svgEl(
                "line",
                {
                    x1:x,
                    y1:pad.top,
                    x2:x,
                    y2:h-pad.bottom,
                    class:"grid"
                }
            )
        );


        const timeLabel =
            svgEl(
                "text",
                {
                    x:x,
                    y:h-21,
                    "text-anchor":"middle",
                    class:"axislabel"
                }
            );

        timeLabel.textContent =
            p.time || p.short_time || "";

        svg.appendChild(
            timeLabel
        );


        const pctLabel =
            svgEl(
                "text",
                {
                    x:x,
                    y:h-7,
                    "text-anchor":"middle",
                    class:"axislabel"
                }
            );

        pctLabel.textContent =
            (
                p.percent === null ||
                p.percent === undefined
            )
            ? "—"
            : p.percent + "%";

        svg.appendChild(
            pctLabel
        );

    });


    series.forEach(s => {

        const points =
            data.map(
                (p,i) => {

                    return (
                        xPos(i)
                        .toFixed(1)
                        +
                        ","
                        +
                        yPos(
                            p[s.key]
                        )
                        .toFixed(1)
                    );

                }
            ).join(" ");


        svg.appendChild(
            svgEl(
                "polyline",
                {
                    points:points,
                    fill:"none",
                    "stroke-width":"2.2",
                    class:s.cls
                }
            )
        );

    });

}



function powerDrainLevel(value) {

    if (value >= 5) {
        return {
            label: "Muito Alto",
            cls: "drain-veryhigh"
        };
    }

    if (value >= 3) {
        return {
            label: "Alto",
            cls: "drain-high"
        };
    }

    if (value >= 1) {
        return {
            label: "Médio",
            cls: "drain-medium"
        };
    }

    return {
        label: "Baixo",
        cls: "drain-low"
    };
}



function polarPoint(cx, cy, r, angleDeg) {

    const a =
        (angleDeg - 90) * Math.PI / 180;

    return {
        x: cx + r * Math.cos(a),
        y: cy + r * Math.sin(a)
    };
}


function arcPath(cx, cy, r, startAngle, endAngle) {

    const p1 =
        polarPoint(cx, cy, r, startAngle);

    const p2 =
        polarPoint(cx, cy, r, endAngle);

    const largeArc =
        Math.abs(endAngle - startAngle) > 180
        ? 1
        : 0;

    return (
        "M " + p1.x.toFixed(1) + " " + p1.y.toFixed(1)
        + " A " + r + " " + r + " 0 " + largeArc + " 1 "
        + p2.x.toFixed(1) + " " + p2.y.toFixed(1)
    );
}


function drawGauge(svgId, value, minValue, maxValue, leftLabel, rightLabel) {

    const svg =
        document.getElementById(svgId);

    if (!svg) return;

    svg.innerHTML = "";

    const w = 220;
    const h = 110;
    const cx = 110;
    const cy = 92;
    const r = 66;

    svg.setAttribute("viewBox", "0 0 220 110");

    const safeMax =
        Math.max(maxValue, minValue + 1);

    const ratio =
        Math.max(
            0,
            Math.min(
                1,
                (value - minValue) / (safeMax - minValue)
            )
        );

    const bg = svgEl("path", {
        d: arcPath(cx, cy, r, 180, 0),
        class: "gauge-track"
    });

    svg.appendChild(bg);

    const red = svgEl("path", {
        d: arcPath(cx, cy, r, 180, 120),
        class: "gauge-danger"
    });

    const yellow = svgEl("path", {
        d: arcPath(cx, cy, r, 120, 60),
        class: "gauge-warn"
    });

    const green = svgEl("path", {
        d: arcPath(cx, cy, r, 60, 0),
        class: "gauge-good"
    });

    svg.appendChild(red);
    svg.appendChild(yellow);
    svg.appendChild(green);

    const angle =
        180 - (ratio * 180);

    const needleEnd =
        polarPoint(cx, cy, r - 10, angle);

    const needle = svgEl("line", {
        x1: cx,
        y1: cy,
        x2: needleEnd.x,
        y2: needleEnd.y,
        class: "gauge-needle"
    });

    const center = svgEl("circle", {
        cx: cx,
        cy: cy,
        r: 4,
        class: "gauge-center"
    });

    svg.appendChild(needle);
    svg.appendChild(center);

    const left = svgEl("text", {
        x: 16,
        y: 101,
        class: "gauge-label"
    });

    left.textContent = leftLabel;

    const right = svgEl("text", {
        x: 204,
        y: 101,
        "text-anchor": "end",
        class: "gauge-label"
    });

    right.textContent = rightLabel;

    svg.appendChild(left);
    svg.appendChild(right);
}


async function refresh() {

    try {

        const response =
            await fetch("/api");

        const data =
            await response.json();

        const c =
            data.current;

        const allHistory =
            data.history || [];

        const nowTs = Date.now() / 1000;

        const h = allHistory.filter(
            p => (nowTs - p.ts) <= 300
        );


        if (!c.c1)
            return;


        document
        .getElementById("c1")
        .textContent =
            (c.c1/1000)
            .toFixed(3)
            + " V";


        document
        .getElementById("c2")
        .textContent =
            (c.c2/1000)
            .toFixed(3)
            + " V";


        document
        .getElementById("c3")
        .textContent =
            (c.c3/1000)
            .toFixed(3)
            + " V";


        document
        .getElementById("delta")
        .textContent =
            c.delta
            + " mV";


        document
        .getElementById("power")
        .textContent =
            Math.abs(
                c.instant_power_w
            ).toFixed(1)
            + " W";


        document
        .getElementById("powerdir")
        .textContent =
            c.power_direction;


        document
        .getElementById("current")
        .textContent =
            Math.abs(
                c.instant_ma
            )
            + " mA";


        document
        .getElementById("currentdir")
        .textContent =
            c.current_direction;


        document
        .getElementById("avgpower")
        .textContent =
            Math.abs(
                c.avg_power_w
            ).toFixed(1)
            + " W";


        document
        .getElementById("avgcurrent")
        .textContent =
            Math.abs(
                c.current_ma
            )
            + " mA médios";


        document
        .getElementById("remainingwh")
        .textContent =
            c.remaining_wh
            .toFixed(1)
            + " Wh";


        document
        .getElementById("remainingmah")
        .textContent =
            c.capacity_mah
            + " mAh";


        document
        .getElementById("maxmah")
        .textContent =
            "máx. informado: "
            +
            c.max_capacity_mah
            +
            " mAh";

        drawGauge(
            "gauge-wh",
            c.remaining_wh || 0,
            0,
            Math.max(c.max_wh_estimate || 0, 1),
            "0",
            (Math.max(c.max_wh_estimate || 0, 1)).toFixed(1) + " Wh"
        );

        drawGauge(
            "gauge-mah",
            c.capacity_mah || 0,
            0,
            Math.max(c.max_capacity_mah || 0, 1),
            "0",
            Math.max(c.max_capacity_mah || 0, 1) + " mAh"
        );


        document
        .getElementById("slope")
        .textContent =
            (
                c.slope === null
            )
            ? "calculando…"
            :
            c.slope
            + " mV/min";


        document
        .getElementById("eta")
        .textContent =
            (
                c.eta === null
            )
            ? "—"
            :
            "~"
            + c.eta
            + " min";


        document
        .getElementById("percent")
        .textContent =
            (
                c.percent === null
            )
            ? "—"
            :
            c.percent
            + "%";


        document
        .getElementById("batterytime")
        .textContent =
            c.battery_duration_text || "—";


        document
        .getElementById("batterysince")
        .textContent =
            c.battery_since_text || "";


        document
        .getElementById("lastac")
        .textContent =
            c.last_ac_text;


        document
        .getElementById("acduration")
        .textContent =
            c.ac_duration_text;


        const status =
            document
            .getElementById("status");


        status.textContent =
            c.status;


        status.className =
            "status "
            + c.status;


        drawChart(
            "cells",
            h,
            [
                {
                    key:"c1",
                    cls:"series-c1"
                },

                {
                    key:"c2",
                    cls:"series-c2"
                },

                {
                    key:"c3",
                    cls:"series-c3"
                }
            ],
            3000,
            4300,
            v =>
                (
                    v/1000
                ).toFixed(2)
                + " V"
        );


        const maxPower =
            Math.max(
                8,
                ...h.map(
                    x =>
                        x.power || 0
                )
            );


        drawChart(
            "powerchart",
            h,
            [
                {
                    key:"power",
                    cls:"series-power"
                }
            ],
            0,
            maxPower * 1.15,
            v =>
                v.toFixed(1)
                + " W"
        );


        const procHTML =
            (
                c.processes || []
            )
            .map(p => {

                const level = powerDrainLevel(p.power);

                return (
                    '<div class="process">'
                    +
                    '<div>'
                    + p.name
                    + '</div>'
                    +
                    '<div>'
                    + p.cpu.toFixed(1)
                    + '%'
                    + '</div>'
                    +
                    '<div>'
                    + p.power.toFixed(1)
                    + '</div>'
                    +
                    '<div><span class="drain-badge '
                    + level.cls
                    + '">'
                    + level.label
                    + '</span></div>'
                    +
                    '</div>'
                );

            })
            .join("");


        document
        .getElementById(
            "processes"
        )
        .innerHTML =
            procHTML ||
            '<div class="small">Aguardando coleta...</div>';

    }

    catch(e) {

        console.log(e);

    }

}


refresh();

setInterval(
    refresh,
    1000
);


</script>


<!-- SAFE_ANALOG_GAUGE_V1 -->
<style>

.battery-analog-gauge {
    margin-top: 12px;
    width: 100%;
    max-width: 190px;
    height: 105px;
    display: block;
}

.battery-gauge-track {
    fill: none;
    stroke: #29292c;
    stroke-width: 11;
    stroke-linecap: round;
}

.battery-gauge-red {
    fill: none;
    stroke: #d84a4a;
    stroke-width: 11;
}

.battery-gauge-yellow {
    fill: none;
    stroke: #d6a328;
    stroke-width: 11;
}

.battery-gauge-green {
    fill: none;
    stroke: #2dbf61;
    stroke-width: 11;
}

.battery-gauge-needle {
    stroke: #eeeeee;
    stroke-width: 2.5;
    stroke-linecap: round;
}

.battery-gauge-center {
    fill: #eeeeee;
}

.battery-gauge-percent {
    font-size: 16px;
    font-weight: 700;
    fill: #eeeeee;
}

.battery-gauge-caption {
    font-size: 9px;
    fill: #888888;
}

</style>

<script>

(function () {

    function makeSVG(tag, attrs) {
        const e = document.createElementNS(
            "http://www.w3.org/2000/svg",
            tag
        );

        for (const k in attrs) {
            e.setAttribute(k, attrs[k]);
        }

        return e;
    }


    function point(cx, cy, r, angle) {

        const rad =
            (angle - 90) * Math.PI / 180;

        return {
            x: cx + r * Math.cos(rad),
            y: cy + r * Math.sin(rad)
        };
    }


    function arc(cx, cy, r, start, end) {

        const p1 = point(cx, cy, r, start);
        const p2 = point(cx, cy, r, end);

        const large =
            Math.abs(end - start) > 180
            ? 1
            : 0;

        return (
            "M " +
            p1.x + " " + p1.y +
            " A " +
            r + " " + r +
            " 0 " + large + " 1 " +
            p2.x + " " + p2.y
        );
    }


    function ensureGauge(valueElementId, gaugeId) {

        const valueEl =
            document.getElementById(valueElementId);

        if (!valueEl)
            return null;

        let svg =
            document.getElementById(gaugeId);

        if (!svg) {

            svg = document.createElementNS(
                "http://www.w3.org/2000/svg",
                "svg"
            );

            svg.id = gaugeId;
            svg.classList.add(
                "battery-analog-gauge"
            );

            svg.setAttribute(
                "viewBox",
                "0 0 200 110"
            );

            valueEl.parentElement.appendChild(svg);
        }

        return svg;
    }


    function drawGauge(svg, ratio) {

        if (!svg)
            return;

        ratio = Math.max(
            0,
            Math.min(1, ratio)
        );

        svg.innerHTML = "";

        const cx = 100;
        const cy = 91;
        const radius = 65;

        // Escala de -120° até +120°
        const start = -120;
        const end = 120;

        function pos(p) {
            return start + ((end - start) * p);
        }

        // Fundo
        svg.appendChild(
            makeSVG("path", {
                d: arc(
                    cx,
                    cy,
                    radius,
                    start,
                    end
                ),
                class: "battery-gauge-track"
            })
        );

        // 0 - 20% vermelho
        svg.appendChild(
            makeSVG("path", {
                d: arc(
                    cx,
                    cy,
                    radius,
                    pos(0),
                    pos(0.20)
                ),
                class: "battery-gauge-red"
            })
        );

        // 20 - 40% amarelo
        svg.appendChild(
            makeSVG("path", {
                d: arc(
                    cx,
                    cy,
                    radius,
                    pos(0.20),
                    pos(0.40)
                ),
                class: "battery-gauge-yellow"
            })
        );

        // 40 - 100% verde
        svg.appendChild(
            makeSVG("path", {
                d: arc(
                    cx,
                    cy,
                    radius,
                    pos(0.40),
                    pos(1)
                ),
                class: "battery-gauge-green"
            })
        );

        // Ponteiro
        const angle = pos(ratio);

        const needle =
            point(
                cx,
                cy,
                radius - 9,
                angle
            );

        svg.appendChild(
            makeSVG("line", {
                x1: cx,
                y1: cy,
                x2: needle.x,
                y2: needle.y,
                class: "battery-gauge-needle"
            })
        );

        svg.appendChild(
            makeSVG("circle", {
                cx: cx,
                cy: cy,
                r: 4,
                class: "battery-gauge-center"
            })
        );

        // Percentual
        const percent =
            makeSVG("text", {
                x: cx,
                y: 70,
                "text-anchor": "middle",
                class: "battery-gauge-percent"
            });

        percent.textContent =
            (ratio * 100).toFixed(1) + "%";

        svg.appendChild(percent);


        // MIN / MAX
        const minText =
            makeSVG("text", {
                x: 21,
                y: 104,
                class: "battery-gauge-caption"
            });

        minText.textContent = "MIN";

        svg.appendChild(minText);


        const maxText =
            makeSVG("text", {
                x: 179,
                y: 104,
                "text-anchor": "end",
                class: "battery-gauge-caption"
            });

        maxText.textContent = "MAX";

        svg.appendChild(maxText);
    }


    function getChargeRatio() {

        const currentEl =
            document.getElementById(
                "remainingmah"
            );

        const maxEl =
            document.getElementById(
                "maxmah"
            );

        if (!currentEl || !maxEl)
            return null;


        const currentMatch =
            currentEl.textContent.match(
                /([\d.,]+)/
            );

        const maxMatch =
            maxEl.textContent.match(
                /([\d.,]+)\s*mAh/i
            );


        if (!currentMatch || !maxMatch)
            return null;


        const current =
            parseFloat(
                currentMatch[1]
                .replace(",", ".")
            );

        const maximum =
            parseFloat(
                maxMatch[1]
                .replace(",", ".")
            );


        if (
            !isFinite(current) ||
            !isFinite(maximum) ||
            maximum <= 0
        ) {
            return null;
        }


        return current / maximum;
    }


    function updateAnalogGauges() {

        const ratio =
            getChargeRatio();

        if (ratio === null)
            return;


        const whGauge =
            ensureGauge(
                "remainingwh",
                "analog-gauge-wh"
            );


        const mahGauge =
            ensureGauge(
                "remainingmah",
                "analog-gauge-mah"
            );


        drawGauge(
            whGauge,
            ratio
        );

        drawGauge(
            mahGauge,
            ratio
        );
    }


    // Independente do refresh principal.
    setInterval(
        updateAnalogGauges,
        1000
    );

    setTimeout(
        updateAnalogGauges,
        1500
    );

})();

</script>

</body>

</html>
'''


# ============================================================
# HTTP
# ============================================================

class Handler(
    BaseHTTPRequestHandler
):

    def log_message(
        self,
        *args
    ):
        pass


    def do_GET(self):

        if self.path == "/api":

            with lock:

                payload = json.dumps({
                        "current":
                            current,

                        "history":
                            list(history)
                    }).encode()


            self.send_response(200)

            self.send_header(
                "Content-Type",
                "application/json"
            )

            self.end_headers()

            self.wfile.write(
                payload
            )

            return


        body = HTML.encode()


        self.send_response(200)

        self.send_header(
            "Content-Type",
            "text/html; charset=utf-8"
        )

        self.end_headers()

        self.wfile.write(
            body
        )


# ============================================================
# START
# ============================================================

threading.Thread(
    target=collector,
    daemon=True
).start()


HTTPServer(
    (HOST, PORT),
    Handler
).serve_forever()

