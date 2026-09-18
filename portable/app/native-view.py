#!/usr/bin/env python3

import os
import socket
import sys
import time

import webview


HOST = "127.0.0.1"
PORT = int(
    os.environ.get(
        "BATTERY_GUARD_PORT",
        "8765"
    )
)

URL = f"http://{HOST}:{PORT}"

# BATTERY_GUARD_MACOS_IDENTITY_V1

def find_app_icon():
    candidates = [
        Path.home()
        / "Projects/macbook-battery-guard"
        / "portable/assets/BatteryGuard.icns",

        Path(__file__).resolve().parent.parent
        / "assets/BatteryGuard.icns",

        Path(sys.executable).resolve().parent.parent
        / "Resources/BatteryGuard.icns",
    ]

    for candidate in candidates:
        if candidate.exists():
            return candidate

    return None


def apply_macos_identity():
    try:
        from AppKit import (
            NSApplication,
            NSImage,
        )

        app = NSApplication.sharedApplication()

        icon_path = find_app_icon()

        if icon_path:
            image = NSImage.alloc().initWithContentsOfFile_(
                str(icon_path)
            )

            if image:
                app.setApplicationIconImage_(image)

    except Exception as exc:
        print(
            f"Não foi possível aplicar o ícone: {exc}",
            file=sys.stderr
        )



def server_is_ready():
    try:
        with socket.create_connection(
            (HOST, PORT),
            timeout=0.5
        ):
            return True
    except OSError:
        return False


def wait_for_server(timeout=30):
    deadline = time.time() + timeout

    while time.time() < deadline:
        if server_is_ready():
            return True

        time.sleep(0.25)

    return False


if not wait_for_server():
    print(
        f"Battery Guard não respondeu em {URL}",
        file=sys.stderr
    )
    raise SystemExit(1)


webview.create_window(
    "Battery Guard",
    URL,
    width=1280,
    height=820,
    min_size=(900, 620),
    resizable=True,
)

webview.start(
    apply_macos_identity,
    debug=False,
    private_mode=False
)
