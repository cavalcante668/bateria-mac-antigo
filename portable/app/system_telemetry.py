#!/usr/bin/env python3
import argparse
import json
import os
import re
import shutil
import sqlite3
import subprocess
import threading
import time
from collections import defaultdict, deque
from pathlib import Path

SCHEMA_VERSION = 2


def run_cmd(args, timeout=5):
    try:
        return subprocess.run(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=timeout,
            check=False,
        ).stdout.strip()
    except Exception:
        return ""


def as_float(value, default=0.0):
    try:
        return float(str(value).replace(",", "."))
    except Exception:
        return default


def as_int(value, default=0):
    try:
        return int(float(value))
    except Exception:
        return default


def process_description(name):
    known = {
        "WindowServer": "Composição gráfica das janelas e telas do macOS.",
        "kernel_task": "Kernel, drivers e gerenciamento térmico do macOS.",
        "powerd": "Gerenciamento de energia do macOS.",
        "mds": "Indexação do Spotlight.",
        "mdworker": "Processo auxiliar de indexação do Spotlight.",
        "mdworker_shared": "Processo auxiliar compartilhado do Spotlight.",
        "fseventsd": "Monitoramento de alterações no sistema de arquivos.",
        "mDNSResponder": "DNS e descoberta de serviços de rede do macOS.",
        "coreaudiod": "Gerenciamento de áudio do macOS.",
        "loginwindow": "Gerenciamento da sessão gráfica do usuário.",
        "launchd": "Inicialização e supervisão de serviços do macOS.",
        "Finder": "Gerenciador de arquivos do macOS.",
    }
    return known.get(name)


def app_from_comm(comm):
    text = comm or ""
    match = re.search(r"/([^/]+)\.app/Contents/", text)
    if match:
        return match.group(1)
    if "Google Chrome" in text:
        return "Google Chrome"
    if "Battery Guard" in text:
        return "Battery Guard"
    return Path(text).name or "Desconhecido"


class TelemetryCollector:
    def __init__(self, db_path):
        self.db_path = str(db_path)
        self.last_network = None
        self.last_storage = 0.0
        self.windows = defaultdict(lambda: deque(maxlen=40))
        self.cooldowns = {}
        self.ensure_schema()

    def connect(self):
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=10000")
        return conn

    def _ensure_column(self, conn, table, column, ddl):
        cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        if column not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")

    def ensure_schema(self):
        conn = self.connect()
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS schema_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at REAL
        );

        CREATE TABLE IF NOT EXISTS system_inventory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            captured_at REAL NOT NULL,
            hostname TEXT,
            model TEXT,
            os_version TEXT,
            architecture TEXT,
            cpu_model TEXT,
            logical_cpus INTEGER,
            memory_total_bytes INTEGER
        );

        CREATE TABLE IF NOT EXISTS system_samples (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp REAL NOT NULL,
            cpu_user_pct REAL,
            cpu_system_pct REAL,
            cpu_idle_pct REAL,
            cpu_total_pct REAL,
            load_1 REAL,
            load_5 REAL,
            load_15 REAL,
            ram_total_bytes INTEGER,
            ram_used_bytes INTEGER,
            ram_available_bytes INTEGER,
            ram_used_pct REAL,
            swap_used_bytes INTEGER,
            uptime_seconds REAL,
            foreground_app TEXT,
            on_battery INTEGER,
            battery_percent INTEGER,
            battery_power_w REAL,
            network_interface TEXT,
            rx_bytes_per_sec REAL,
            tx_bytes_per_sec REAL
        );
        CREATE INDEX IF NOT EXISTS idx_system_samples_ts
            ON system_samples(timestamp);

        CREATE TABLE IF NOT EXISTS process_instances (
            process_key TEXT PRIMARY KEY,
            technical_name TEXT,
            app_name TEXT,
            executable TEXT,
            first_seen REAL,
            last_seen REAL,
            last_pid INTEGER,
            last_ppid INTEGER,
            description TEXT
        );

        CREATE TABLE IF NOT EXISTS process_samples (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp REAL NOT NULL,
            process_key TEXT NOT NULL,
            pid INTEGER,
            ppid INTEGER,
            technical_name TEXT,
            app_name TEXT,
            cpu_pct REAL,
            memory_pct REAL,
            rss_bytes INTEGER,
            foreground INTEGER,
            on_battery INTEGER,
            battery_power_w REAL
        );
        CREATE INDEX IF NOT EXISTS idx_process_samples_key_ts
            ON process_samples(process_key, timestamp);
        CREATE INDEX IF NOT EXISTS idx_process_samples_ts
            ON process_samples(timestamp);

        CREATE TABLE IF NOT EXISTS app_samples (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp REAL NOT NULL,
            app_name TEXT NOT NULL,
            process_count INTEGER,
            cpu_pct REAL,
            memory_pct REAL,
            rss_bytes INTEGER,
            foreground INTEGER,
            on_battery INTEGER,
            battery_power_w REAL,
            impact_score REAL,
            impact_label TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_app_samples_app_ts
            ON app_samples(app_name, timestamp);

        CREATE TABLE IF NOT EXISTS network_samples (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp REAL NOT NULL,
            interface TEXT,
            rx_bytes INTEGER,
            tx_bytes INTEGER,
            rx_bytes_per_sec REAL,
            tx_bytes_per_sec REAL
        );
        CREATE INDEX IF NOT EXISTS idx_network_samples_ts
            ON network_samples(timestamp);

        CREATE TABLE IF NOT EXISTS storage_samples (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp REAL NOT NULL,
            mount_point TEXT,
            total_bytes INTEGER,
            used_bytes INTEGER,
            free_bytes INTEGER,
            used_pct REAL
        );
        CREATE INDEX IF NOT EXISTS idx_storage_samples_ts
            ON storage_samples(timestamp);

        CREATE TABLE IF NOT EXISTS thermal_samples (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp REAL NOT NULL,
            thermal_state TEXT,
            source TEXT
        );

        CREATE TABLE IF NOT EXISTS analysis_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp REAL NOT NULL,
            event_type TEXT NOT NULL,
            severity TEXT NOT NULL,
            app_name TEXT,
            process_key TEXT,
            title TEXT,
            detail TEXT,
            value REAL,
            threshold REAL,
            on_battery INTEGER,
            battery_power_w REAL
        );
        CREATE INDEX IF NOT EXISTS idx_analysis_events_ts
            ON analysis_events(timestamp);
        """)
        self._ensure_column(
            conn, "system_samples", "memory_pressure_pct", "REAL"
        )
        conn.execute(
            """
            INSERT INTO schema_meta(key, value, updated_at)
            VALUES('system_telemetry_schema', ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value=excluded.value,
                updated_at=excluded.updated_at
            """,
            (str(SCHEMA_VERSION), time.time()),
        )
        if not conn.execute("SELECT 1 FROM system_inventory LIMIT 1").fetchone():
            conn.execute(
                """
                INSERT INTO system_inventory(
                    captured_at, hostname, model, os_version, architecture,
                    cpu_model, logical_cpus, memory_total_bytes
                ) VALUES(?,?,?,?,?,?,?,?)
                """,
                (
                    time.time(),
                    run_cmd(["scutil", "--get", "ComputerName"]) or run_cmd(["hostname"]),
                    run_cmd(["sysctl", "-n", "hw.model"]),
                    run_cmd(["sw_vers", "-productVersion"]),
                    run_cmd(["uname", "-m"]),
                    run_cmd(["sysctl", "-n", "machdep.cpu.brand_string"]),
                    as_int(run_cmd(["sysctl", "-n", "hw.logicalcpu"])),
                    as_int(run_cmd(["sysctl", "-n", "hw.memsize"])),
                ),
            )
        conn.commit()
        conn.close()

    def battery_context(self, conn):
        row = conn.execute(
            """
            SELECT external_connected, percent, instant_power_w
            FROM battery_samples
            ORDER BY timestamp DESC
            LIMIT 1
            """
        ).fetchone()
        if not row:
            return False, None, None
        return not bool(row[0]), row[1], row[2]

    def collect_cpu(self):
        out = run_cmd(["top", "-l", "1", "-n", "0"], timeout=4)
        user = system = idle = 0.0
        for line in out.splitlines():
            if "CPU usage:" not in line:
                continue
            mu = re.search(r"([\d.]+)% user", line)
            ms = re.search(r"([\d.]+)% sys", line)
            mi = re.search(r"([\d.]+)% idle", line)
            if mu:
                user = as_float(mu.group(1))
            if ms:
                system = as_float(ms.group(1))
            if mi:
                idle = as_float(mi.group(1))
            break
        load1, load5, load15 = os.getloadavg()
        return user, system, idle, max(0.0, 100.0 - idle), load1, load5, load15

    def collect_memory(self):
        total = as_int(run_cmd(["sysctl", "-n", "hw.memsize"]))
        out = run_cmd(["vm_stat"])
        size_match = re.search(r"page size of (\d+) bytes", out)
        page_size = as_int(size_match.group(1), 4096) if size_match else 4096
        pages = {}
        for line in out.splitlines():
            match = re.match(r"^([^:]+):\s+(\d+)\.", line)
            if match:
                pages[match.group(1).strip()] = as_int(match.group(2))

        # "Livre" no macOS não deve ser interpretado como o único recurso
        # reutilizável. Páginas inativas/especulativas também podem ser
        # reaproveitadas pelo sistema. Este valor é uma aproximação operacional,
        # não uma reprodução exata do Activity Monitor.
        reusable_pages = (
            pages.get("Pages free", 0)
            + pages.get("Pages inactive", 0)
            + pages.get("Pages speculative", 0)
        )
        available = min(total, max(0, reusable_pages * page_size))
        used = max(0, total - available)
        used_pct = used / total * 100.0 if total else 0.0

        pressure_pct = None
        pressure = run_cmd(["memory_pressure", "-Q"], timeout=4)
        pm = re.search(
            r"System-wide memory free percentage:\s*([\d.]+)%",
            pressure,
        )
        if pm:
            pressure_pct = max(0.0, min(100.0, 100.0 - as_float(pm.group(1))))

        swap = run_cmd(["sysctl", "-n", "vm.swapusage"])
        sm = re.search(r"used = ([\d.]+)([MG])", swap)
        swap_used = 0
        if sm:
            multiplier = 1024 ** 2 if sm.group(2) == "M" else 1024 ** 3
            swap_used = int(as_float(sm.group(1)) * multiplier)

        return total, used, available, used_pct, swap_used, pressure_pct

    def uptime(self):
        out = run_cmd(["sysctl", "-n", "kern.boottime"])
        match = re.search(r"sec = (\d+)", out)
        return max(0.0, time.time() - as_int(match.group(1))) if match else None

    def foreground_app(self):
        script = (
            'tell application "System Events" to get name of first '
            'application process whose frontmost is true'
        )
        return run_cmd(["osascript", "-e", script], timeout=3)

    def network(self, now):
        route = run_cmd(["route", "-n", "get", "default"])
        match = re.search(r"interface:\s+(\S+)", route)
        interface = match.group(1) if match else None
        rx = tx = 0
        if interface:
            out = run_cmd(["netstat", "-ibn", "-I", interface])
            lines = [line for line in out.splitlines() if line.strip()]
            if len(lines) >= 2:
                header = re.split(r"\s+", lines[0].strip())
                try:
                    i_idx = header.index("Ibytes")
                    o_idx = header.index("Obytes")
                    for line in lines[1:]:
                        cols = re.split(r"\s+", line.strip())
                        if len(cols) > max(i_idx, o_idx) and cols[0] == interface:
                            rx = as_int(cols[i_idx])
                            tx = as_int(cols[o_idx])
                            break
                except ValueError:
                    pass
        rx_rate = tx_rate = 0.0
        if self.last_network:
            old_ts, old_if, old_rx, old_tx = self.last_network
            if old_if == interface and now > old_ts:
                elapsed = now - old_ts
                rx_rate = max(0.0, (rx - old_rx) / elapsed)
                tx_rate = max(0.0, (tx - old_tx) / elapsed)
        self.last_network = (now, interface, rx, tx)
        return interface, rx, tx, rx_rate, tx_rate

    def catalog(self, conn):
        return {
            row[0]: {
                "friendly": row[1],
                "status": row[2],
                "description": row[3],
            }
            for row in conn.execute(
                """
                SELECT technical_name, friendly_name, status, description
                FROM process_catalog
                """
            ).fetchall()
        }

    def processes(self, conn, foreground=None):
        out = run_cmd([
            "ps", "-axo", "pid=,ppid=,%cpu=,%mem=,rss=,comm="
        ])
        catalog = self.catalog(conn)
        rows = []
        for line in out.splitlines():
            parts = line.strip().split(None, 5)
            if len(parts) < 6:
                continue
            pid = as_int(parts[0])
            ppid = as_int(parts[1])
            cpu = as_float(parts[2])
            mem = as_float(parts[3])
            rss = as_int(parts[4]) * 1024
            comm = parts[5]
            technical = Path(comm).name
            app = app_from_comm(comm)

            # Ignora processos transitórios criados pela própria instrumentação.
            # Eles não representam carga útil do usuário e poluiriam o ranking.
            if technical in {"ps", "top", "osascript"}:
                continue

            key = f"{app}|{technical}|{comm}"
            info = catalog.get(technical, {})
            description = info.get("description") or process_description(technical)
            if not description:
                description = f"Processo associado a {app}."
            if technical not in catalog:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO process_catalog(
                        technical_name, status, created_at
                    ) VALUES(?, 'pending', ?)
                    """,
                    (technical, time.time()),
                )
            rows.append({
                "pid": pid,
                "ppid": ppid,
                "cpu": cpu,
                "mem": mem,
                "rss": rss,
                "comm": comm,
                "technical": technical,
                "app": app,
                "key": key,
                "description": description,
                "foreground": int(app == foreground),
            })
        return rows

    def impact(self, cpu, rss, total_ram, on_battery):
        memory_pct = rss / total_ram * 100.0 if total_ram else 0.0
        score = cpu * 0.75 + memory_pct * 1.4
        if on_battery:
            score *= 1.10
        score = max(0.0, min(100.0, score))
        if score >= 70:
            label = "ALTO"
        elif score >= 35:
            label = "MÉDIO"
        else:
            label = "BAIXO"
        return score, label

    def add_event(self, conn, now, event_type, app, title, detail,
                  value, threshold, on_battery, battery_power):
        key = (event_type, app)
        if now - self.cooldowns.get(key, 0) < 300:
            return
        self.cooldowns[key] = now
        conn.execute(
            """
            INSERT INTO analysis_events(
                timestamp, event_type, severity, app_name, title, detail,
                value, threshold, on_battery, battery_power_w
            ) VALUES(?,?,'warning',?,?,?,?,?,?,?)
            """,
            (
                now, event_type, app, title, detail, value, threshold,
                int(on_battery), battery_power,
            ),
        )

    def sample(self):
        now = time.time()
        conn = self.connect()
        on_battery, battery_percent, battery_power = self.battery_context(conn)
        user, system, idle, total_cpu, load1, load5, load15 = self.collect_cpu()
        (
            ram_total, ram_used, ram_available, ram_pct,
            swap_used, memory_pressure_pct,
        ) = self.collect_memory()

        # Captura os processos ANTES de consultar o app em primeiro plano.
        # A consulta via System Events pode acordar processos auxiliares e
        # distorcer a própria amostra que estamos tentando medir.
        process_rows = self.processes(conn, None)
        foreground = self.foreground_app()
        for proc in process_rows:
            proc["foreground"] = int(proc["app"] == foreground)

        interface, rx, tx, rx_rate, tx_rate = self.network(now)

        conn.execute(
            """
            INSERT INTO system_samples(
                timestamp, cpu_user_pct, cpu_system_pct, cpu_idle_pct, cpu_total_pct,
                load_1, load_5, load_15, ram_total_bytes, ram_used_bytes,
                ram_available_bytes, ram_used_pct, memory_pressure_pct,
                swap_used_bytes, uptime_seconds, foreground_app, on_battery,
                battery_percent, battery_power_w, network_interface,
                rx_bytes_per_sec, tx_bytes_per_sec
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                now, user, system, idle, total_cpu, load1, load5, load15,
                ram_total, ram_used, ram_available, ram_pct,
                memory_pressure_pct, swap_used, self.uptime(), foreground,
                int(on_battery), battery_percent, battery_power, interface,
                rx_rate, tx_rate,
            ),
        )
        conn.execute(
            """
            INSERT INTO network_samples(
                timestamp, interface, rx_bytes, tx_bytes,
                rx_bytes_per_sec, tx_bytes_per_sec
            ) VALUES(?,?,?,?,?,?)
            """,
            (now, interface, rx, tx, rx_rate, tx_rate),
        )

        usage = shutil.disk_usage("/")
        used = usage.total - usage.free
        storage_pct = used / usage.total * 100.0 if usage.total else 0.0
        if now - self.last_storage >= 60:
            conn.execute(
                """
                INSERT INTO storage_samples(
                    timestamp, mount_point, total_bytes, used_bytes, free_bytes, used_pct
                ) VALUES(?,?,?,?,?,?)
                """,
                (now, "/", usage.total, used, usage.free, storage_pct),
            )
            self.last_storage = now

        grouped = {}
        for proc in process_rows:
            app = grouped.setdefault(proc["app"], {
                "app_name": proc["app"],
                "process_count": 0,
                "cpu_pct": 0.0,
                "memory_pct": 0.0,
                "rss_bytes": 0,
                "foreground": 0,
            })
            app["process_count"] += 1
            app["cpu_pct"] += proc["cpu"]
            app["memory_pct"] += proc["mem"]
            app["rss_bytes"] += proc["rss"]
            app["foreground"] = max(app["foreground"], proc["foreground"])

        # Registra TODOS os processos vistos de forma leve. As métricas
        # detalhadas continuam limitadas aos processos mais relevantes.
        for proc in process_rows:
            conn.execute(
                """
                INSERT INTO process_instances(
                    process_key, technical_name, app_name, executable,
                    first_seen, last_seen, last_pid, last_ppid, description
                ) VALUES(?,?,?,?,?,?,?,?,?)
                ON CONFLICT(process_key) DO UPDATE SET
                    last_seen=excluded.last_seen,
                    last_pid=excluded.last_pid,
                    last_ppid=excluded.last_ppid,
                    description=excluded.description
                """,
                (
                    proc["key"], proc["technical"], proc["app"], proc["comm"],
                    now, now, proc["pid"], proc["ppid"], proc["description"],
                ),
            )

        selected = sorted(
            process_rows,
            key=lambda item: (item["cpu"], item["rss"]),
            reverse=True,
        )
        selected = [
            item for idx, item in enumerate(selected)
            if idx < 25 or item["cpu"] >= 5.0 or item["rss"] >= 200 * 1024 ** 2
        ]

        for proc in selected:
            conn.execute(
                """
                INSERT INTO process_samples(
                    timestamp, process_key, pid, ppid, technical_name, app_name,
                    cpu_pct, memory_pct, rss_bytes, foreground,
                    on_battery, battery_power_w
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    now, proc["key"], proc["pid"], proc["ppid"], proc["technical"],
                    proc["app"], proc["cpu"], proc["mem"], proc["rss"],
                    proc["foreground"], int(on_battery), battery_power,
                ),
            )

        apps = []
        for app in grouped.values():
            score, label = self.impact(
                app["cpu_pct"], app["rss_bytes"], ram_total, on_battery
            )
            app["impact_score"] = round(score, 1)
            app["impact_label"] = label
            apps.append(app)

        apps.sort(
            key=lambda item: (
                item["impact_score"], item["cpu_pct"], item["rss_bytes"]
            ),
            reverse=True,
        )

        # Evita centenas de linhas por amostra. Persistimos as aplicações de
        # maior impacto, o app em primeiro plano e qualquer app que ultrapasse
        # limiares mínimos de CPU/RAM. O inventário de processos continua
        # registrando todos os processos vistos em process_instances.
        persist_apps = []
        seen_apps = set()
        for idx, app in enumerate(apps):
            keep = (
                idx < 30
                or app["foreground"]
                or app["cpu_pct"] >= 5.0
                or app["rss_bytes"] >= 200 * 1024 ** 2
            )
            if not keep or app["app_name"] in seen_apps:
                continue
            seen_apps.add(app["app_name"])
            persist_apps.append(app)

        for app in persist_apps:
            conn.execute(
                """
                INSERT INTO app_samples(
                    timestamp, app_name, process_count, cpu_pct, memory_pct,
                    rss_bytes, foreground, on_battery, battery_power_w,
                    impact_score, impact_label
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    now, app["app_name"], app["process_count"], app["cpu_pct"],
                    app["memory_pct"], app["rss_bytes"], app["foreground"],
                    int(on_battery), battery_power, app["impact_score"],
                    app["impact_label"],
                ),
            )

            window = self.windows[app["app_name"]]
            window.append((now, app["cpu_pct"]))
            recent = [item for item in window if now - item[0] <= 300]
            avg_cpu = sum(item[1] for item in recent) / len(recent)

            if len(recent) >= 4 and avg_cpu >= 40:
                self.add_event(
                    conn, now, "HIGH_CPU_SUSTAINED", app["app_name"],
                    "CPU alta persistente",
                    f"{app['app_name']} manteve CPU média elevada na janela recente.",
                    avg_cpu, 40.0, on_battery, battery_power,
                )

            if (
                len(recent) >= 4
                and avg_cpu >= 30
                and foreground
                and app["app_name"] != foreground
            ):
                self.add_event(
                    conn, now, "BACKGROUND_CPU", app["app_name"],
                    "CPU alta em segundo plano",
                    f"{app['app_name']} está consumindo CPU sem estar em primeiro plano.",
                    avg_cpu, 30.0, on_battery, battery_power,
                )

        conn.commit()
        conn.close()
        apps.sort(
            key=lambda item: (item["impact_score"], item["cpu_pct"], item["rss_bytes"]),
            reverse=True,
        )
        return {
            "timestamp": now,
            "cpu_pct": round(total_cpu, 1),
            "load": [round(load1, 2), round(load5, 2), round(load15, 2)],
            "ram_used_pct": round(ram_pct, 1),
            "memory_pressure_pct": (
                None if memory_pressure_pct is None
                else round(memory_pressure_pct, 1)
            ),
            "ram_used_bytes": ram_used,
            "ram_total_bytes": ram_total,
            "swap_used_bytes": swap_used,
            "uptime_seconds": self.uptime(),
            "foreground_app": foreground,
            "on_battery": on_battery,
            "battery_percent": battery_percent,
            "battery_power_w": battery_power,
            "network_interface": interface,
            "rx_bytes_per_sec": round(rx_rate, 1),
            "tx_bytes_per_sec": round(tx_rate, 1),
            "storage_used_pct": round(storage_pct, 1),
            "storage_free_bytes": usage.free,
            "apps": apps[:15],
        }

    def run_forever(self, interval):
        while True:
            started = time.time()
            try:
                self.sample()
            except KeyboardInterrupt:
                raise
            except Exception as exc:
                print(f"system telemetry error: {exc}", flush=True)
            elapsed = time.time() - started
            time.sleep(max(1.0, interval - elapsed))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(

        "--db",

        default=os.environ.get(

            "BATTERY_GUARD_DB",

            str(

                Path(

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

                / "battery-history.db"

            ),

        ),

    )

    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval", type=float, default=15.0)
    args = parser.parse_args()
    collector = TelemetryCollector(args.db)
    if args.once:
        print(json.dumps(collector.sample(), ensure_ascii=False, indent=2))
        return
    collector.run_forever(args.interval)


if __name__ == "__main__":
    main()
