#!/usr/bin/env python3

from __future__ import annotations

import fcntl
import json
import os
import subprocess
import tempfile
import threading
import uuid
from datetime import datetime
from pathlib import Path

DATA_DIR = Path(
    os.environ.get(
        "BATTERY_GUARD_DATA_DIR",
        Path.home()
        / "Library"
        / "Application Support"
        / "Battery Guard",
    )
)

NOTIFICATION_DIR = DATA_DIR / "notifications"
NOTIFICATION_FILE = NOTIFICATION_DIR / "notifications.json"
LOCK_FILE = NOTIFICATION_DIR / "notifications.lock"

LOG_DIR = DATA_DIR / "logs"
LOG_FILE = LOG_DIR / "notifications.log"

MAX_NOTIFICATIONS = 1000

_THREAD_LOCK = threading.RLock()


def ensure_dirs():
    NOTIFICATION_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def timestamp():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def log_event(event, message=""):
    ensure_dirs()

    stamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")

    line = f"{stamp} | {event}"

    if message:
        line += f" | {message}"

    try:
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


class FileLock:
    def __enter__(self):
        ensure_dirs()

        self.fp = LOCK_FILE.open("a+")

        fcntl.flock(
            self.fp.fileno(),
            fcntl.LOCK_EX,
        )

        return self.fp

    def __exit__(self, exc_type, exc, tb):
        try:
            fcntl.flock(
                self.fp.fileno(),
                fcntl.LOCK_UN,
            )
        finally:
            self.fp.close()


def load_unlocked():
    ensure_dirs()

    if not NOTIFICATION_FILE.exists():
        return []

    try:
        data = json.loads(
            NOTIFICATION_FILE.read_text(
                encoding="utf-8"
            )
        )

        if isinstance(data, list):
            return data

    except Exception:
        pass

    return []


def atomic_write(data):
    ensure_dirs()

    fd, temp_name = tempfile.mkstemp(
        prefix=".notifications-",
        suffix=".tmp",
        dir=str(NOTIFICATION_DIR),
    )

    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(
                data,
                f,
                ensure_ascii=False,
                indent=2,
            )

            f.flush()
            os.fsync(f.fileno())

        os.replace(
            temp_name,
            NOTIFICATION_FILE,
        )

    finally:
        if os.path.exists(temp_name):
            try:
                os.unlink(temp_name)
            except Exception:
                pass


def get_notifications():
    with _THREAD_LOCK:
        with FileLock():
            items = load_unlocked()

    return sorted(
        items,
        key=lambda item: str(item.get("timestamp", "")),
        reverse=True,
    )


def get_unread_count():
    return sum(
        1
        for item in get_notifications()
        if not bool(item.get("read", False))
    )


def deliver_native(title, message):
    safe_title = (
        str(title)
        .replace("\\", "\\\\")
        .replace('"', '\\"')
    )

    safe_message = (
        str(message)
        .replace("\\", "\\\\")
        .replace('"', '\\"')
    )

    script = (
        f'display notification "{safe_message}" '
        f'with title "{safe_title}" '
        f'sound name "Glass"'
    )

    try:
        subprocess.run(
            ["/usr/bin/osascript", "-e", script],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
            check=False,
        )

        return True

    except Exception:
        return False


def add_notification(
    notification_type,
    title,
    message,
    severity="info",
    source="",
    metadata=None,
    popup=True,
):
    item = {
        "id": str(uuid.uuid4()),
        "timestamp": timestamp(),
        "type": str(notification_type),
        "title": str(title),
        "message": str(message),
        "severity": str(severity),
        "read": False,
        "source": str(source),
        "repeat_count": 1,
        "metadata": metadata or {},
    }

    with _THREAD_LOCK:
        with FileLock():
            items = load_unlocked()
            items.append(item)

            if len(items) > MAX_NOTIFICATIONS:
                read = [
                    x for x in items
                    if bool(x.get("read", False))
                ]

                unread = [
                    x for x in items
                    if not bool(x.get("read", False))
                ]

                items = (read + unread)[-MAX_NOTIFICATIONS:]

            atomic_write(items)

    log_event(
        f"{str(notification_type).upper()} | CREATED",
        f"{source} | {title}".strip(" |"),
    )

    if popup:
        deliver_native(title, message)

    return item


def increment_repeat(notification_id):
    changed = False

    with _THREAD_LOCK:
        with FileLock():
            items = load_unlocked()

            for item in items:
                if item.get("id") == notification_id:
                    item["repeat_count"] = (
                        int(item.get("repeat_count", 1))
                        + 1
                    )

                    changed = True
                    break

            if changed:
                atomic_write(items)

    return changed


def mark_read(notification_id):
    changed = False

    with _THREAD_LOCK:
        with FileLock():
            items = load_unlocked()

            for item in items:
                if item.get("id") == notification_id:
                    if not bool(item.get("read", False)):
                        item["read"] = True
                        changed = True

                    break

            if changed:
                atomic_write(items)

    if changed:
        log_event("READ", notification_id)

    return changed


def mark_all_read():
    count = 0

    with _THREAD_LOCK:
        with FileLock():
            items = load_unlocked()

            for item in items:
                if not bool(item.get("read", False)):
                    item["read"] = True
                    count += 1

            if count:
                atomic_write(items)

    if count:
        log_event("READ_ALL", str(count))

    return count


def clear_notifications():
    with _THREAD_LOCK:
        with FileLock():
            items = load_unlocked()
            count = len(items)

            atomic_write([])

    log_event("CLEAR", str(count))

    return count


ensure_dirs()

if not NOTIFICATION_FILE.exists():
    atomic_write([])
