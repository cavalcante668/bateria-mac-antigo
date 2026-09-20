#!/usr/bin/env python3

import json
import os
import socket
import sys
import threading
import time
import urllib.request
from pathlib import Path

import webview


HOST = "127.0.0.1"
PORT = int(os.environ.get("BATTERY_GUARD_PORT", "8765"))

URL = f"http://{HOST}:{PORT}"
API_URL = f"{URL}/api"

# DYNAMIC_DOCK_STATUS_ICON_V1

# BATTERY_GUARD_MENUBAR_V1

_STATUS_ITEM = None
_STATUS_MENU = None
_MENU_HANDLER = None
_MENU_FIELDS = {}
_MENUBAR_BLINK_RED = False


_ICON_CACHE = {}
_CURRENT_DOCK_STATE = None
_MACOS_UI_READY = False

# BATTERY_GUARD_BACKGROUND_MODE_V1
_MAIN_WINDOW = None
_QUITTING = False

# BATTERY_GUARD_NATIVE_APP_MENU_V1
_APP_MENU_HANDLER = None
_APP_MAIN_MENU = None

# BATTERY_GUARD_DEBUG_WINDOW_V1
_DEBUG_MODULE = None


def _load_debug_module():
    global _DEBUG_MODULE
    if _DEBUG_MODULE is not None:
        return _DEBUG_MODULE

    import importlib.util

    module_path = Path(__file__).resolve().parent / "debug_window.py"
    spec = importlib.util.spec_from_file_location(
        "battery_guard_debug_window",
        module_path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Não foi possível carregar debug_window.py")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _DEBUG_MODULE = module
    return module


def install_debug_menu():
    try:
        _load_debug_module().install_debug_menu()
    except Exception as exc:
        print(
            f"Erro ao instalar menu Debug: {exc}",
            file=sys.stderr,
        )





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


def make_tinted_icon(base_image, color, alpha=0.68):
    from AppKit import (
        NSCompositingOperationSourceAtop,
        NSCompositingOperationSourceOver,
        NSImage,
        NSMakeRect,
        NSRectFillUsingOperation,
        NSZeroRect,
    )

    size = base_image.size()

    result = NSImage.alloc().initWithSize_(size)

    rect = NSMakeRect(
        0,
        0,
        size.width,
        size.height
    )

    result.lockFocus()

    base_image.drawInRect_fromRect_operation_fraction_(
        rect,
        NSZeroRect,
        NSCompositingOperationSourceOver,
        1.0
    )

    color.colorWithAlphaComponent_(alpha).set()

    NSRectFillUsingOperation(
        rect,
        NSCompositingOperationSourceAtop
    )

    result.unlockFocus()

    return result


def build_icon_cache():
    global _ICON_CACHE

    from AppKit import NSImage

    base_path = find_app_icon()

    app_dir = Path(__file__).resolve().parent

    yellow_path = (
        app_dir / "BatteryGuard-yellow.png"
    )

    red_path = (
        app_dir / "BatteryGuard-red.png"
    )

    if not base_path:
        raise RuntimeError(
            "BatteryGuard.icns não encontrado"
        )

    if not yellow_path.exists():
        raise RuntimeError(
            "BatteryGuard-yellow.png não encontrado"
        )

    if not red_path.exists():
        raise RuntimeError(
            "BatteryGuard-red.png não encontrado"
        )

    base = NSImage.alloc().initWithContentsOfFile_(
        str(base_path)
    )

    yellow = NSImage.alloc().initWithContentsOfFile_(
        str(yellow_path)
    )

    red = NSImage.alloc().initWithContentsOfFile_(
        str(red_path)
    )

    if not base or not yellow or not red:
        raise RuntimeError(
            "Não foi possível carregar os ícones de status"
        )

    _ICON_CACHE = {
        "green": base,
        "yellow": yellow,
        "red": red,
    }


def set_dock_icon(color_name):
    global _CURRENT_DOCK_STATE

    if color_name == _CURRENT_DOCK_STATE:
        return

    image = _ICON_CACHE.get(color_name)

    if image is None:
        return

    from AppKit import NSApplication

    app = NSApplication.sharedApplication()

    app.setApplicationIconImage_(
        image
    )

    _CURRENT_DOCK_STATE = color_name


def schedule_icon(color_name):
    try:
        from PyObjCTools import AppHelper

        AppHelper.callAfter(
            set_dock_icon,
            color_name
        )

    except Exception as exc:
        print(
            f"Erro ao atualizar ícone: {exc}",
            file=sys.stderr
        )


def extract_status(payload):
    if not isinstance(payload, dict):
        return None

    status = payload.get("status")

    if isinstance(status, str):
        return status.upper()

    for key in (
        "current",
        "battery",
        "data",
        "sample",
    ):
        value = payload.get(key)

        if isinstance(value, dict):
            status = value.get("status")

            if isinstance(status, str):
                return status.upper()

    return None


def fetch_status():
    try:
        request = urllib.request.Request(
            API_URL,
            headers={
                "Cache-Control": "no-cache",
                "User-Agent": "Battery-Guard",
            }
        )

        with urllib.request.urlopen(
            request,
            timeout=2
        ) as response:

            payload = json.loads(
                response.read().decode("utf-8")
            )

        return extract_status(payload)

    except Exception:
        return None


def dock_status_monitor():
    status = "SEGURO"
    blink_red = False
    last_fetch = 0.0

    while True:
        now = time.time()

        if now - last_fetch >= 2:
            new_status = fetch_status()

            if new_status in {
                "SEGURO",
                "ATENÇÃO",
                "ALERTA",
                "CRÍTICO",
            }:
                status = new_status

            last_fetch = now

        if status == "CRÍTICO":
            schedule_icon("red")
            time.sleep(1)

        elif status == "ALERTA":
            blink_red = not blink_red

            schedule_icon(
                "red" if blink_red else "yellow"
            )

            time.sleep(0.8)

        elif status == "ATENÇÃO":
            schedule_icon("yellow")
            time.sleep(1)

        else:
            schedule_icon("green")
            time.sleep(1)


def initialize_macos_ui():
    global _MACOS_UI_READY

    if _MACOS_UI_READY:
        return

    _MACOS_UI_READY = True

    # BATTERY_GUARD_ACCESSORY_MODE_V1
    # Remove o aplicativo do Dock e do Command+Tab.
    # A barra superior e as janelas continuam funcionando.
    from AppKit import (
        NSApplication,
        NSApplicationActivationPolicyAccessory,
    )

    NSApplication.sharedApplication().setActivationPolicy_(
        NSApplicationActivationPolicyAccessory
    )

    try:
        build_icon_cache()

        set_dock_icon(
            "green"
        )

        create_menubar()

        monitor = threading.Thread(
            target=dock_status_monitor,
            name="BatteryGuardDockStatus",
            daemon=True
        )

        monitor.start()

    except Exception as exc:
        _MACOS_UI_READY = False

        print(
            f"Não foi possível iniciar a interface macOS: {exc}",
            file=sys.stderr
        )


def apply_macos_identity():
    try:
        from PyObjCTools import AppHelper

        AppHelper.callAfter(
            initialize_macos_ui
        )

    except Exception as exc:
        print(
            f"Não foi possível agendar a interface macOS: {exc}",
            file=sys.stderr
        )


def get_current_payload():
    try:
        request = urllib.request.Request(
            API_URL,
            headers={
                "Cache-Control": "no-cache",
                "User-Agent": "Battery-Guard",
            }
        )

        with urllib.request.urlopen(
            request,
            timeout=2
        ) as response:
            payload = json.loads(
                response.read().decode("utf-8")
            )

        current = payload.get("current")

        if isinstance(current, dict):
            return current

    except Exception:
        pass

    return None


def status_color(status, blink_red=False):
    from AppKit import NSColor

    if status == "CRÍTICO":
        return NSColor.systemRedColor()

    if status == "ALERTA":
        if blink_red:
            return NSColor.systemRedColor()
        return NSColor.systemYellowColor()

    if status == "ATENÇÃO":
        return NSColor.systemYellowColor()

    return NSColor.systemGreenColor()


def make_menu_battery_icon(
    percent,
    status,
    blink_red=False
):
    from AppKit import (
        NSBezierPath,
        NSColor,
        NSImage,
        NSMakeRect,
    )

    width = 25.0
    height = 13.0

    image = NSImage.alloc().initWithSize_(
        (width, height)
    )

    image.lockFocus()

    body = NSMakeRect(
        1.0,
        1.0,
        20.0,
        11.0
    )

    outline = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
        body,
        2.5,
        2.5
    )

    NSColor.labelColor().setStroke()
    outline.setLineWidth_(1.4)
    outline.stroke()

    tip = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
        NSMakeRect(
            22.0,
            4.0,
            2.0,
            5.0
        ),
        0.8,
        0.8
    )

    NSColor.labelColor().setFill()
    tip.fill()

    try:
        pct = float(percent)
    except Exception:
        pct = 0.0

    pct = max(
        0.0,
        min(
            100.0,
            pct
        )
    )

    inner_width = 16.0 * pct / 100.0

    if inner_width > 0:
        fill_rect = NSMakeRect(
            3.0,
            3.0,
            inner_width,
            7.0
        )

        fill = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            fill_rect,
            1.3,
            1.3
        )

        status_color(
            status,
            blink_red
        ).setFill()

        fill.fill()

    image.unlockFocus()

    image.setTemplate_(False)

    return image


def fmt_cell(value):
    try:
        return f"{float(value) / 1000:.3f} V"
    except Exception:
        return "—"


def fmt_delta(value):
    try:
        return f"{int(value)} mV"
    except Exception:
        return "—"


def fmt_risk(value):
    if value is None:
        return "—"

    try:
        return f"{int(value)}/100"
    except Exception:
        return "—"


def update_menubar(current, blink_red=False):
    global _STATUS_ITEM

    if _STATUS_ITEM is None:
        return

    status = str(
        current.get(
            "status",
            "SEGURO"
        )
    ).upper()

    percent = current.get(
        "percent",
        0
    )

    button = _STATUS_ITEM.button()

    if button is not None:
        button.setImage_(
            make_menu_battery_icon(
                percent,
                status,
                blink_red
            )
        )

        button.setToolTip_(
            f"Battery Guard — {status}"
        )

    values = {
        "status":
            f"Status: {status}",

        "c1":
            f"C1: {fmt_cell(current.get('c1'))}",

        "c2":
            f"C2: {fmt_cell(current.get('c2'))}",

        "c3":
            f"C3: {fmt_cell(current.get('c3'))}",

        "delta":
            f"Delta: {fmt_delta(current.get('delta'))}",

        "risk":
            f"Risco: {fmt_risk(current.get('shutdown_risk'))}",
    }

    for key, title in values.items():
        item = _MENU_FIELDS.get(key)

        if item is not None:
            item.setTitle_(title)


def schedule_menubar_update(
    current,
    blink_red=False
):
    try:
        from PyObjCTools import AppHelper

        AppHelper.callAfter(
            update_menubar,
            current,
            blink_red
        )

    except Exception as exc:
        print(
            f"Erro ao atualizar barra de menus: {exc}",
            file=sys.stderr
        )


def menubar_monitor():
    global _MENUBAR_BLINK_RED

    last_current = {
        "status": "SEGURO",
        "percent": 0,
    }

    while True:
        current = get_current_payload()

        if current is not None:
            last_current = current

        status = str(
            last_current.get(
                "status",
                "SEGURO"
            )
        ).upper()

        if status == "ALERTA":
            _MENUBAR_BLINK_RED = (
                not _MENUBAR_BLINK_RED
            )
        else:
            _MENUBAR_BLINK_RED = False

        schedule_menubar_update(
            last_current.copy(),
            _MENUBAR_BLINK_RED
        )

        if status == "ALERTA":
            time.sleep(0.8)
        else:
            time.sleep(1.5)



# BATTERY_GUARD_NOTIFICATION_BADGE_MONITOR_V1
def notification_badge_monitor():
    import time

    last_count = None

    while True:
        try:
            from battery_notifications import get_unread_count

            count = int(get_unread_count())

            if count != last_count:
                last_count = count

                label = (
                    "99+"
                    if count > 99
                    else str(count)
                    if count > 0
                    else ""
                )

                try:
                    from AppKit import NSApp

                    NSApp.dockTile().setBadgeLabel_(label)

                except Exception:
                    pass

                try:
                    item = _MENU_FIELDS.get("notifications")

                    if item is not None:
                        if count > 0:
                            item.setTitle_(
                                "🔔 Notificações  🔴 "
                                + label
                            )
                        else:
                            item.setTitle_(
                                "🔔 Notificações"
                            )

                except Exception:
                    pass

        except Exception:
            pass

        time.sleep(2)


def create_menubar():
    global _STATUS_ITEM
    global _STATUS_MENU
    global _MENU_HANDLER

    from AppKit import (
        NSApplication,
        NSMenu,
        NSMenuItem,
        NSObject,
        NSStatusBar,
        NSVariableStatusItemLength,
    )

    class BatteryGuardMenuHandler(NSObject):

        # BATTERY_GUARD_NOTIFICATION_MENU_HANDLER_V1
        def openNotifications_(self, sender):
            try:
                import subprocess
                import sys
                from pathlib import Path

                if getattr(sys, "frozen", False):
                    cmd = [
                        sys.executable,
                        "--worker",
                        "notifications",
                    ]

                else:
                    script = (
                        Path(__file__).resolve().parent
                        / "notification-center.py"
                    )

                    cmd = [
                        sys.executable,
                        str(script),
                    ]

                subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )

            except Exception:
                pass


        def openBatteryGuard_(self, sender):
            show_main_window()

        def quitBatteryGuard_(self, sender):
            global _QUITTING

            _QUITTING = True

            try:
                if _MAIN_WINDOW is not None:
                    try:
                        _MAIN_WINDOW.destroy()
                    except Exception:
                        pass

            finally:
                NSApplication.sharedApplication().terminate_(
                    None
                )


    _MENU_HANDLER = (
        BatteryGuardMenuHandler.alloc().init()
    )

    status_bar = NSStatusBar.systemStatusBar()

    _STATUS_ITEM = status_bar.statusItemWithLength_(
        NSVariableStatusItemLength
    )

    menu = NSMenu.alloc().init()

    title = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
        "Battery Guard",
        None,
        ""
    )

    title.setEnabled_(False)

    menu.addItem_(title)
    menu.addItem_(NSMenuItem.separatorItem())

    field_definitions = [
        ("status", "Status: —"),
        ("c1", "C1: —"),
        ("c2", "C2: —"),
        ("c3", "C3: —"),
        ("delta", "Delta: —"),
        ("risk", "Risco: —"),
    ]

    for key, text in field_definitions:
        item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            text,
            None,
            ""
        )

        item.setEnabled_(False)

        menu.addItem_(item)

        _MENU_FIELDS[key] = item

    menu.addItem_(NSMenuItem.separatorItem())

    open_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
        "Abrir Battery Guard",
        "openBatteryGuard:",
        ""
    )

    open_item.setTarget_(
        _MENU_HANDLER
    )

    menu.addItem_(open_item)

    # BATTERY_GUARD_NOTIFICATION_MENU_ITEM_V1
    notifications_item = (
        NSMenuItem.alloc()
        .initWithTitle_action_keyEquivalent_(
            "🔔 Notificações",
            "openNotifications:",
            "",
        )
    )
    notifications_item.setTarget_(_MENU_HANDLER)
    menu.addItem_(notifications_item)
    _MENU_FIELDS["notifications"] = notifications_item
    menu.addItem_(NSMenuItem.separatorItem())

    quit_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
        "Sair",
        "quitBatteryGuard:",
        ""
    )

    quit_item.setTarget_(
        _MENU_HANDLER
    )

    menu.addItem_(quit_item)

    _STATUS_MENU = menu

    _STATUS_ITEM.setMenu_(
        menu
    )

    current = get_current_payload()

    if current is None:
        current = {
            "status": "SEGURO",
            "percent": 0,
        }

    update_menubar(
        current
    )

    thread = threading.Thread(
        target=menubar_monitor,
        name="BatteryGuardMenuBar",
        daemon=True
    )

    thread.start()




def set_accessory_mode():
    try:
        from AppKit import (
            NSApplication,
            NSApplicationActivationPolicyAccessory,
        )

        NSApplication.sharedApplication().setActivationPolicy_(
            NSApplicationActivationPolicyAccessory
        )

    except Exception as exc:
        print(
            f"Erro ao ativar modo background: {exc}",
            file=sys.stderr
        )


def set_regular_mode():
    try:
        from AppKit import (
            NSApplication,
            NSApplicationActivationPolicyRegular,
        )

        app = NSApplication.sharedApplication()

        app.setActivationPolicy_(
            NSApplicationActivationPolicyRegular
        )

        create_application_menu()

        app.activateIgnoringOtherApps_(True)

    except Exception as exc:
        print(
            f"Erro ao ativar modo de janela: {exc}",
            file=sys.stderr
        )


def create_application_menu():
    global _APP_MENU_HANDLER
    global _APP_MAIN_MENU

    if _APP_MAIN_MENU is not None:
        return

    from AppKit import (
        NSAlert,
        NSApplication,
        NSBundle,
        NSEventModifierFlagCommand,
        NSEventModifierFlagOption,
        NSMenu,
        NSMenuItem,
        NSObject,
    )

    class BatteryGuardAppMenuHandler(NSObject):

        def showAbout_(self, sender):
            bundle = NSBundle.mainBundle()

            version = (
                bundle.objectForInfoDictionaryKey_(
                    "CFBundleShortVersionString"
                )
                or "—"
            )

            build = (
                bundle.objectForInfoDictionaryKey_(
                    "CFBundleVersion"
                )
                or version
            )

            alert = NSAlert.alloc().init()

            alert.setMessageText_(
                "Battery Guard"
            )

            if str(build) != str(version):
                version_text = (
                    f"Versão {version} "
                    f"(build {build})"
                )
            else:
                version_text = (
                    f"Versão {version}"
                )

            alert.setInformativeText_(
                version_text
                + "\n\n"
                + "Monitoramento avançado da bateria "
                  "e das células no macOS."
                + "\n\n"
                + "Troca essa bateria logo, macho"
            )

            alert.addButtonWithTitle_(
                "OK"
            )

            alert.runModal()

        def showDebug_(self, sender):
            try:
                _load_debug_module().show_debug_window()
            except Exception as exc:
                print(
                    f"Erro ao abrir Debug: {exc}",
                    file=sys.stderr
                )

        def hideBatteryGuard_(self, sender):
            try:
                if _MAIN_WINDOW is not None:
                    _MAIN_WINDOW.hide()
            finally:
                set_accessory_mode()

        def quitBatteryGuard_(self, sender):
            global _QUITTING

            _QUITTING = True

            NSApplication.sharedApplication().terminate_(
                None
            )

    _APP_MENU_HANDLER = (
        BatteryGuardAppMenuHandler.alloc().init()
    )

    main_menu = NSMenu.alloc().init()

    app_menu_item = NSMenuItem.alloc().init()

    main_menu.addItem_(
        app_menu_item
    )

    app_menu = NSMenu.alloc().initWithTitle_(
        "Battery Guard"
    )

    app_menu_item.setSubmenu_(
        app_menu
    )

    about_item = (
        NSMenuItem.alloc()
        .initWithTitle_action_keyEquivalent_(
            "Sobre o Battery Guard",
            "showAbout:",
            ""
        )
    )

    about_item.setTarget_(
        _APP_MENU_HANDLER
    )

    app_menu.addItem_(
        about_item
    )

    debug_item = (
        NSMenuItem.alloc()
        .initWithTitle_action_keyEquivalent_(
            "Debug…",
            "showDebug:",
            "d"
        )
    )

    debug_item.setTarget_(
        _APP_MENU_HANDLER
    )

    debug_item.setKeyEquivalentModifierMask_(
        NSEventModifierFlagCommand
        | NSEventModifierFlagOption
    )

    app_menu.addItem_(
        debug_item
    )

    app_menu.addItem_(
        NSMenuItem.separatorItem()
    )

    hide_item = (
        NSMenuItem.alloc()
        .initWithTitle_action_keyEquivalent_(
            "Ocultar Battery Guard",
            "hideBatteryGuard:",
            "h"
        )
    )

    hide_item.setTarget_(
        _APP_MENU_HANDLER
    )

    app_menu.addItem_(
        hide_item
    )

    app_menu.addItem_(
        NSMenuItem.separatorItem()
    )

    quit_item = (
        NSMenuItem.alloc()
        .initWithTitle_action_keyEquivalent_(
            "Sair do Battery Guard",
            "quitBatteryGuard:",
            "q"
        )
    )

    quit_item.setTarget_(
        _APP_MENU_HANDLER
    )

    app_menu.addItem_(
        quit_item
    )

    window_menu_item = NSMenuItem.alloc().init()

    main_menu.addItem_(
        window_menu_item
    )

    window_menu = NSMenu.alloc().initWithTitle_(
        "Janela"
    )

    window_menu_item.setSubmenu_(
        window_menu
    )

    minimize_item = (
        NSMenuItem.alloc()
        .initWithTitle_action_keyEquivalent_(
            "Minimizar",
            "performMiniaturize:",
            "m"
        )
    )

    window_menu.addItem_(
        minimize_item
    )

    _APP_MAIN_MENU = main_menu

    app = NSApplication.sharedApplication()

    app.setMainMenu_(
        main_menu
    )

    app.setWindowsMenu_(
        window_menu
    )


def on_window_closing(window=None):
    global _QUITTING

    if _QUITTING:
        return True

    try:
        target = window or _MAIN_WINDOW

        if target is not None:
            target.hide()

    except Exception as exc:
        print(
            f"Erro ao ocultar janela: {exc}",
            file=sys.stderr
        )

    # False cancela o fechamento real.
    # A janela é apenas escondida.
    return False



# BATTERY_GUARD_NATIVE_FOCUS_V1
def focus_battery_guard_window():
    try:
        from AppKit import (
            NSApplication,
            NSApplicationActivationPolicyRegular,
        )

        app = NSApplication.sharedApplication()

        app.setActivationPolicy_(
            NSApplicationActivationPolicyRegular
        )

        create_application_menu()

        app.unhide_(None)

        for native_window in app.windows():
            try:
                title = str(native_window.title() or "")

                if "Battery Guard" in title:
                    native_window.makeKeyAndOrderFront_(None)
                    native_window.orderFrontRegardless()
                    break

            except Exception:
                continue

        app.activateIgnoringOtherApps_(True)

    except Exception as exc:
        print(
            f"Erro ao ativar janela nativa: {exc}",
            file=sys.stderr
        )


def show_main_window():
    try:
        # Enquanto a janela estiver aberta, o Battery Guard
        # se comporta como aplicativo normal do macOS.
        set_regular_mode()

        target = _MAIN_WINDOW

        if target is None:
            return

        try:
            target.restore()
        except Exception:
            pass

        target.show()

        # O pywebview pode terminar de materializar a NSWindow
        # alguns instantes depois de show().
        from PyObjCTools import AppHelper

        AppHelper.callAfter(
            focus_battery_guard_window
        )

        AppHelper.callLater(
            0.25,
            focus_battery_guard_window
        )

    except Exception as exc:
        print(
            f"Erro ao mostrar Battery Guard: {exc}",
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



# BATTERY_GUARD_NOTIFICATION_BADGE_START_V1
try:
    import threading

    threading.Thread(
        target=notification_badge_monitor,
        name="BatteryGuardNotificationBadge",
        daemon=True,
    ).start()

except Exception:
    pass


_MAIN_WINDOW = webview.create_window(
    "Battery Guard",
    URL,
    width=1280,
    height=820,
    min_size=(900, 620),
    resizable=True,
    hidden=True,
    focus=False,
)

_MAIN_WINDOW.events.closing += on_window_closing



webview.start(
    apply_macos_identity,
    debug=False,
    private_mode=False
)
