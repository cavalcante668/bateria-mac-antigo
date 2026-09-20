#!/usr/bin/env python3

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent

if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from battery_notifications import (
    add_notification,
    increment_repeat,
    log_event,
)

DATA_DIR = Path(
    os.environ.get(
        "BATTERY_GUARD_DATA_DIR",
        Path.home()
        / "Library"
        / "Application Support"
        / "Battery Guard",
    )
)

LOG_DIR = DATA_DIR / "logs"
RUN_DIR = DATA_DIR / "run"
STATE_DIR = DATA_DIR / "notifications"

STATE_FILE = STATE_DIR / "monitor-state.json"
LOCK_FILE = RUN_DIR / "notification-monitor.lock"
OWN_LOG = LOG_DIR / "notification-monitor.log"

DISK_WARNING_GIB = 15.0
DISK_CRITICAL_GIB = 8.0

ERROR_COOLDOWN = 600
WARNING_REMINDER = 21600
CRITICAL_REMINDER = 3600

LOG_POLL_SECONDS = 2
DISK_POLL_SECONDS = 60

ERROR_RE = re.compile(
    r"(?i)(\bERROR\b|\bERRO\b|\bFATAL\b|"
    r"\bTRACEBACK\b|\bEXCEPTION\b|\bFAILED\b|\bFAILURE\b)"
)

EXCLUDED_LOGS = {
    "notifications.log",
    "notification-monitor.log",
}


def own_log(message):
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)

        stamp = datetime.now().astimezone().strftime(
            "%Y-%m-%d %H:%M:%S"
        )

        with OWN_LOG.open("a", encoding="utf-8") as f:
            f.write(f"{stamp} | {message}\n")

    except Exception:
        pass


def acquire_singleton():
    RUN_DIR.mkdir(parents=True, exist_ok=True)

    fp = LOCK_FILE.open("w")

    try:
        fcntl.flock(
            fp.fileno(),
            fcntl.LOCK_EX | fcntl.LOCK_NB,
        )

    except BlockingIOError:
        own_log("Monitor já está em execução.")
        return None

    fp.write(str(os.getpid()))
    fp.flush()

    return fp


def load_state():
    try:
        obj = json.loads(
            STATE_FILE.read_text(encoding="utf-8")
        )

        if isinstance(obj, dict):
            return obj

    except Exception:
        pass

    return {
        "disk_level": "normal",
        "disk_last_notification": 0,
        "error_fingerprints": {},
    }


def save_state(state):
    STATE_DIR.mkdir(parents=True, exist_ok=True)

    temp = STATE_FILE.with_suffix(".tmp")

    temp.write_text(
        json.dumps(
            state,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    os.replace(temp, STATE_FILE)


def free_disk_gib():
    if os.environ.get("BATTERY_GUARD_TEST_MODE") == "1":
        value = os.environ.get("BATTERY_GUARD_TEST_FREE_GIB")

        if value is not None:
            try:
                return float(value)
            except ValueError:
                pass

    usage = shutil.disk_usage("/")

    return usage.free / (1024 ** 3)


def disk_level(free_gib):
    if free_gib <= DISK_CRITICAL_GIB:
        return "critical"

    if free_gib <= DISK_WARNING_GIB:
        return "warning"

    return "normal"


def check_disk(state):
    now = time.time()

    free = free_disk_gib()
    current = disk_level(free)

    previous = state.get(
        "disk_level",
        "normal",
    )

    last = float(
        state.get(
            "disk_last_notification",
            0,
        )
    )

    notify = False

    if current != previous:
        notify = True

    elif current == "warning":
        notify = (
            now - last >= WARNING_REMINDER
        )

    elif current == "critical":
        notify = (
            now - last >= CRITICAL_REMINDER
        )

    if current == "warning" and notify:
        add_notification(
            notification_type="disk_warning",
            title="Battery Guard — Pouco espaço em disco",
            message=f"Restam {free:.1f} GiB disponíveis no disco.",
            severity="warning",
            source="notification-monitor",
            metadata={"free_gib": round(free, 2)},
            popup=True,
        )

        state["disk_last_notification"] = now

    elif current == "critical" and notify:
        add_notification(
            notification_type="disk_critical",
            title="Battery Guard — Espaço crítico",
            message=f"Restam apenas {free:.1f} GiB disponíveis no disco.",
            severity="critical",
            source="notification-monitor",
            metadata={"free_gib": round(free, 2)},
            popup=True,
        )

        state["disk_last_notification"] = now

    elif (
        current == "normal"
        and previous in {"warning", "critical"}
    ):
        add_notification(
            notification_type="info",
            title="Battery Guard — Espaço normalizado",
            message=f"O Mac possui agora {free:.1f} GiB disponíveis.",
            severity="info",
            source="notification-monitor",
            metadata={"free_gib": round(free, 2)},
            popup=False,
        )

        state["disk_last_notification"] = 0

    state["disk_level"] = current


def normalize_error(line):
    value = line.strip()

    value = re.sub(
        r"\b\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}\b",
        "<timestamp>",
        value,
    )

    value = re.sub(
        r"\bPID[=: ]+\d+\b",
        "PID=<pid>",
        value,
        flags=re.I,
    )

    return value[:1000]


def process_error(path, line, state):
    if not ERROR_RE.search(line):
        return

    normalized = normalize_error(line)

    if not normalized:
        return

    digest = hashlib.sha256(
        (
            path.name
            + "\n"
            + normalized
        ).encode(
            "utf-8",
            errors="replace",
        )
    ).hexdigest()

    now = time.time()

    fingerprints = state.setdefault(
        "error_fingerprints",
        {},
    )

    previous = fingerprints.get(digest)

    if isinstance(previous, dict):
        previous_time = float(
            previous.get(
                "timestamp",
                0,
            )
        )

        if now - previous_time < ERROR_COOLDOWN:
            notification_id = previous.get(
                "notification_id"
            )

            if notification_id:
                increment_repeat(notification_id)

            log_event(
                "ERROR | SUPPRESSED_DUPLICATE",
                path.name,
            )

            return

    preview = normalized

    if len(preview) > 220:
        preview = preview[:217] + "..."

    created = add_notification(
        notification_type="error",
        title="Battery Guard — Erro detectado",
        message=f"{path.name}: {preview}",
        severity="critical",
        source=path.name,
        metadata={
            "line": normalized,
            "log_path": str(path),
        },
        popup=True,
    )

    fingerprints[digest] = {
        "timestamp": now,
        "notification_id": created["id"],
    }

    cutoff = now - (7 * 86400)

    state["error_fingerprints"] = {
        key: value
        for key, value in fingerprints.items()
        if float(
            value.get("timestamp", 0)
        ) >= cutoff
    }


class Tailer:
    def __init__(self):
        self.positions = {}

    def discover(self):
        LOG_DIR.mkdir(parents=True, exist_ok=True)

        for path in LOG_DIR.glob("*.log"):
            if path.name in EXCLUDED_LOGS:
                continue

            key = str(path)

            if key in self.positions:
                continue

            try:
                self.positions[key] = path.stat().st_size

                own_log(
                    "Observando a partir do EOF: "
                    + path.name
                )

            except Exception:
                pass

    def poll(self, state):
        self.discover()

        for key in list(self.positions):
            path = Path(key)

            if not path.exists():
                self.positions.pop(key, None)
                continue

            try:
                size = path.stat().st_size
                position = self.positions[key]

                if size < position:
                    position = 0

                if size == position:
                    continue

                with path.open(
                    "r",
                    encoding="utf-8",
                    errors="replace",
                ) as f:

                    f.seek(position)

                    for line in f:
                        process_error(
                            path,
                            line,
                            state,
                        )

                    self.positions[key] = f.tell()

            except Exception as exc:
                own_log(
                    f"Falha ao ler {path.name}: {exc}"
                )


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--once",
        action="store_true",
    )

    args = parser.parse_args()

    lock = acquire_singleton()

    if lock is None:
        return 0

    state = load_state()

    tailer = Tailer()
    tailer.discover()

    try:
        check_disk(state)
        save_state(state)

        if args.once:
            own_log("Teste --once concluído.")
            return 0

        next_disk = (
            time.monotonic()
            + DISK_POLL_SECONDS
        )

        own_log("Monitor iniciado.")

        while True:
            tailer.poll(state)

            if time.monotonic() >= next_disk:
                check_disk(state)

                next_disk = (
                    time.monotonic()
                    + DISK_POLL_SECONDS
                )

            save_state(state)

            time.sleep(LOG_POLL_SECONDS)

    except KeyboardInterrupt:
        return 0

    except Exception as exc:
        own_log(
            "ERRO INTERNO: "
            + repr(exc)
        )

        return 1

    finally:
        try:
            lock.close()
        except Exception:
            pass

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
