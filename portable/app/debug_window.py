#!/usr/bin/env python3
import csv
import os
import sqlite3
import subprocess
from pathlib import Path

_DEBUG_WINDOW = None
_DEBUG_MENU_HANDLER = None
_DEBUG_WINDOW_HANDLER = None
_SUMMARY_VIEW = None
_LOG_VIEW = None
_LOG_POPUP = None
_LOG_FILES = {}


def _human_bytes(value):
    try:
        value = float(value)
    except Exception:
        return "—"
    units = ("B", "KB", "MB", "GB", "TB")
    idx = 0
    while abs(value) >= 1024 and idx < len(units) - 1:
        value /= 1024.0
        idx += 1
    return f"{value:.2f} {units[idx]}"


def _run(command, timeout=2):
    try:
        return subprocess.check_output(
            command,
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
        ).strip()
    except Exception:
        return ""


def _listener_pid(port=8765):
    output = _run([
        "/usr/sbin/lsof",
        "-nP",
        f"-iTCP:{port}",
        "-sTCP:LISTEN",
        "-F",
        "p",
    ])
    for line in output.splitlines():
        if line.startswith("p") and line[1:].isdigit():
            return int(line[1:])
    return None


def _process_elapsed(pid):
    if not pid:
        return "—"
    value = _run([
        "/bin/ps",
        "-p",
        str(pid),
        "-o",
        "etime=",
    ])
    return value.strip() or "—"


def _active_db_for_pid(pid):
    if pid:
        output = _run([
            "/usr/sbin/lsof",
            "-p",
            str(pid),
            "-Fn",
        ])
        for line in output.splitlines():
            if line.startswith("n") and line[1:].endswith("battery-history.db"):
                path = Path(line[1:])
                if path.exists():
                    return path

    candidates = [
        Path.home() / "battery-history.db",
        Path.home()
        / "Library"
        / "Application Support"
        / "Battery Guard"
        / "battery-history.db",
    ]
    existing = [p for p in candidates if p.exists()]
    if not existing:
        return None
    return max(existing, key=lambda p: p.stat().st_mtime)


def _file_size(path):
    try:
        return Path(path).stat().st_size
    except Exception:
        return 0


def _db_metrics(db_path):
    if not db_path or not Path(db_path).exists():
        return {}

    db_path = Path(db_path)
    result = {
        "db_bytes": _file_size(db_path),
        "wal_bytes": _file_size(Path(str(db_path) + "-wal")),
        "shm_bytes": _file_size(Path(str(db_path) + "-shm")),
    }
    result["total_bytes"] = (
        result["db_bytes"]
        + result["wal_bytes"]
        + result["shm_bytes"]
    )

    try:
        conn = sqlite3.connect(
            f"file:{db_path}?mode=ro",
            uri=True,
            timeout=1,
        )
        try:
            result["page_size"] = int(
                conn.execute("PRAGMA page_size").fetchone()[0]
            )
            result["page_count"] = int(
                conn.execute("PRAGMA page_count").fetchone()[0]
            )
            result["freelist_count"] = int(
                conn.execute("PRAGMA freelist_count").fetchone()[0]
            )
            result["journal_mode"] = str(
                conn.execute("PRAGMA journal_mode").fetchone()[0]
            )
            result["table_count"] = int(
                conn.execute(
                    """
                    SELECT COUNT(*)
                    FROM sqlite_master
                    WHERE type='table'
                      AND name NOT LIKE 'sqlite_%'
                    """
                ).fetchone()[0]
            )
        finally:
            conn.close()
    except Exception as exc:
        result["sqlite_error"] = str(exc)

    return result


def _growth_metrics(db_path):
    csv_path = (
        Path.home()
        / "Library"
        / "Application Support"
        / "Battery Guard"
        / "db-growth.csv"
    )

    result = {
        "csv_path": csv_path,
        "samples": 0,
    }

    if not csv_path.exists() or not db_path:
        return result

    wanted = str(Path(db_path).expanduser().resolve())
    rows = []

    try:
        with csv_path.open("r", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                try:
                    row_path = str(
                        Path(row["db_path"]).expanduser().resolve()
                    )
                    if row_path != wanted:
                        continue
                    rows.append((
                        float(row["timestamp"]),
                        int(row["total_bytes"]),
                    ))
                except Exception:
                    continue
    except Exception:
        return result

    rows.sort()
    result["samples"] = len(rows)

    if len(rows) < 2:
        return result

    first_ts, first_size = rows[0]
    last_ts, last_size = rows[-1]
    seconds = last_ts - first_ts

    if seconds <= 0:
        return result

    delta = last_size - first_size
    per_day = delta / (seconds / 86400.0)

    result.update({
        "window_seconds": seconds,
        "delta_bytes": delta,
        "bytes_per_day": per_day,
        "projected_30d": per_day * 30,
        "projected_365d": per_day * 365,
    })
    return result


def _known_logs():
    home = Path.home()

    app_logs = (
        home
        / "Library"
        / "Application Support"
        / "Battery Guard"
        / "logs"
    )

    result = {}

    if app_logs.exists():
        for path in app_logs.glob("*.log"):
            if path.is_file():
                result[path.name] = path

    extra_logs = [
        home / "battery-view-error.log",
        home / "battery-view-launch.log",
        home / "battery-guard.log",
    ]

    for path in extra_logs:
        if path.exists():
            result.setdefault(path.name, path)

    def modified(item):
        try:
            return item[1].stat().st_mtime
        except Exception:
            return 0

    return dict(
        sorted(
            result.items(),
            key=modified,
            reverse=True,
        )
    )

def _tail_text(path, max_lines=250, max_bytes=262144):
    if not path or not Path(path).exists():
        return "Log não encontrado."

    path = Path(path)

    try:
        size = path.stat().st_size

        with path.open("rb") as handle:
            if size > max_bytes:
                handle.seek(-max_bytes, os.SEEK_END)
            data = handle.read()

        text = data.decode("utf-8", errors="replace")
        lines = text.splitlines()

        prefix = ""
        if len(lines) > max_lines or size > max_bytes:
            prefix = "[… últimas linhas do arquivo …]\n"

        return prefix + "\n".join(lines[-max_lines:])
    except Exception as exc:
        return f"Erro ao ler log: {exc}"


def _summary():
    pid = _listener_pid(8765)
    db_path = _active_db_for_pid(pid)
    db = _db_metrics(db_path)
    growth = _growth_metrics(db_path)

    lines = [
        "BATTERY GUARD — DEBUG INTERNO",
        "",
        "SERVIÇO",
        f"Servidor: {'ATIVO' if pid else 'NÃO LOCALIZADO'}",
        f"PID: {pid if pid else '—'}",
        "Porta: 8765",
        f"Uptime do processo: {_process_elapsed(pid)}",
        "",
        "BANCO ATIVO",
        str(db_path) if db_path else "Não localizado",
    ]

    if db:
        lines.extend([
            "",
            f"DB:    {_human_bytes(db.get('db_bytes', 0))}",
            f"WAL:   {_human_bytes(db.get('wal_bytes', 0))}",
            f"SHM:   {_human_bytes(db.get('shm_bytes', 0))}",
            f"Total: {_human_bytes(db.get('total_bytes', 0))}",
            "",
            "SQLITE",
            f"Journal mode: {db.get('journal_mode', '—')}",
            f"Page size: {db.get('page_size', '—')} bytes",
            f"Page count: {db.get('page_count', '—')}",
            f"Freelist: {db.get('freelist_count', '—')}",
            f"Tabelas: {db.get('table_count', '—')}",
        ])

        if db.get("sqlite_error"):
            lines.append(f"Erro SQLite: {db['sqlite_error']}")

    lines.extend([
        "",
        "CRESCIMENTO",
        f"Amostras: {growth.get('samples', 0)}",
    ])

    if growth.get("window_seconds"):
        lines.extend([
            f"Janela observada: {growth['window_seconds'] / 3600:.1f} h",
            f"Crescimento observado: {_human_bytes(growth['delta_bytes'])}",
            f"Ritmo médio: {_human_bytes(growth['bytes_per_day'])}/dia",
            f"Projeção 30 dias: {_human_bytes(growth['projected_30d'])}",
            f"Projeção 365 dias: {_human_bytes(growth['projected_365d'])}",
        ])
    else:
        lines.append(
            "Ainda não há medições suficientes para projetar crescimento."
        )

    return "\n".join(lines)


def _make_label(frame, text, size=13, bold=False):
    from AppKit import NSFont, NSTextField

    field = NSTextField.alloc().initWithFrame_(frame)
    field.setStringValue_(text)
    field.setEditable_(False)
    field.setSelectable_(False)
    field.setBezeled_(False)
    field.setDrawsBackground_(False)
    field.setFont_(
        NSFont.boldSystemFontOfSize_(size)
        if bold
        else NSFont.systemFontOfSize_(size)
    )
    return field


def _make_text_area(frame):
    from AppKit import (
        NSBezelBorder,
        NSFont,
        NSScrollView,
        NSTextView,
    )

    scroll = NSScrollView.alloc().initWithFrame_(frame)
    scroll.setHasVerticalScroller_(True)
    scroll.setHasHorizontalScroller_(True)
    scroll.setBorderType_(NSBezelBorder)

    text = NSTextView.alloc().initWithFrame_(frame)
    text.setEditable_(False)
    text.setSelectable_(True)
    text.setRichText_(False)
    text.setFont_(NSFont.userFixedPitchFontOfSize_(12))

    scroll.setDocumentView_(text)
    return scroll, text


def _selected_log_path():
    if _LOG_POPUP is None:
        return None

    title = _LOG_POPUP.titleOfSelectedItem()

    if title is None:
        return None

    return _LOG_FILES.get(str(title))


def refresh_debug_window():
    global _LOG_FILES

    if _SUMMARY_VIEW is not None:
        _SUMMARY_VIEW.setString_(_summary())

    previous = None

    if _LOG_POPUP is not None:
        selected = _LOG_POPUP.titleOfSelectedItem()
        if selected is not None:
            previous = str(selected)

    _LOG_FILES = _known_logs()

    if _LOG_POPUP is not None:
        _LOG_POPUP.removeAllItems()
        titles = list(_LOG_FILES.keys())

        if titles:
            _LOG_POPUP.addItemsWithTitles_(titles)

            if previous in _LOG_FILES:
                _LOG_POPUP.selectItemWithTitle_(previous)

    if _LOG_VIEW is not None:
        path = _selected_log_path()

        if path:
            header = f"{path}\n{'=' * 72}\n"
            _LOG_VIEW.setString_(header + _tail_text(path))
        else:
            _LOG_VIEW.setString_(
                "Nenhum log conhecido foi localizado."
            )


def _open_logs_folder():
    from AppKit import NSWorkspace

    path = (
        Path.home()
        / "Library"
        / "Application Support"
        / "Battery Guard"
        / "logs"
    )

    path.mkdir(parents=True, exist_ok=True)

    NSWorkspace.sharedWorkspace().openFile_(str(path))


def show_debug_window():
    global _DEBUG_WINDOW
    global _DEBUG_WINDOW_HANDLER
    global _SUMMARY_VIEW
    global _LOG_VIEW
    global _LOG_POPUP

    from AppKit import (
        NSBackingStoreBuffered,
        NSButton,
        NSMakeRect,
        NSPopUpButton,
        NSWindow,
        NSWindowStyleMaskClosable,
        NSWindowStyleMaskMiniaturizable,
        NSWindowStyleMaskResizable,
        NSWindowStyleMaskTitled,
    )
    from Foundation import NSObject

    if _DEBUG_WINDOW is not None:
        refresh_debug_window()
        _DEBUG_WINDOW.makeKeyAndOrderFront_(None)
        return

    class DebugWindowHandler(NSObject):
        def refresh_(self, sender):
            refresh_debug_window()

        def logChanged_(self, sender):
            refresh_debug_window()

        def openLogs_(self, sender):
            _open_logs_folder()

    _DEBUG_WINDOW_HANDLER = (
        DebugWindowHandler.alloc().init()
    )

    window = (
        NSWindow.alloc()
        .initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(180, 140, 820, 680),
            (
                NSWindowStyleMaskTitled
                | NSWindowStyleMaskClosable
                | NSWindowStyleMaskMiniaturizable
                | NSWindowStyleMaskResizable
            ),
            NSBackingStoreBuffered,
            False,
        )
    )

    window.setTitle_("Battery Guard — Debug")
    window.setReleasedWhenClosed_(False)
    content = window.contentView()

    title = _make_label(
        NSMakeRect(20, 642, 500, 24),
        "Debug interno — somente leitura",
        size=15,
        bold=True,
    )
    content.addSubview_(title)

    refresh_button = NSButton.alloc().initWithFrame_(
        NSMakeRect(690, 636, 110, 30)
    )
    refresh_button.setTitle_("↻ Atualizar")
    refresh_button.setTarget_(_DEBUG_WINDOW_HANDLER)
    refresh_button.setAction_("refresh:")
    content.addSubview_(refresh_button)

    summary_scroll, _SUMMARY_VIEW = _make_text_area(
        NSMakeRect(20, 360, 780, 265)
    )
    content.addSubview_(summary_scroll)

    content.addSubview_(
        _make_label(
            NSMakeRect(20, 324, 50, 24),
            "Log:",
            size=13,
            bold=True,
        )
    )

    _LOG_POPUP = (
        NSPopUpButton.alloc()
        .initWithFrame_pullsDown_(
            NSMakeRect(66, 320, 330, 30),
            False,
        )
    )
    _LOG_POPUP.setTarget_(_DEBUG_WINDOW_HANDLER)
    _LOG_POPUP.setAction_("logChanged:")
    content.addSubview_(_LOG_POPUP)

    open_button = NSButton.alloc().initWithFrame_(
        NSMakeRect(405, 320, 155, 30)
    )
    open_button.setTitle_("Abrir pasta de logs")
    open_button.setTarget_(_DEBUG_WINDOW_HANDLER)
    open_button.setAction_("openLogs:")
    content.addSubview_(open_button)

    log_scroll, _LOG_VIEW = _make_text_area(
        NSMakeRect(20, 20, 780, 290)
    )
    content.addSubview_(log_scroll)

    _DEBUG_WINDOW = window

    refresh_debug_window()
    window.center()
    window.makeKeyAndOrderFront_(None)


def install_debug_menu():
    global _DEBUG_MENU_HANDLER

    from AppKit import (
        NSApplication,
        NSEventModifierFlagCommand,
        NSEventModifierFlagOption,
        NSMenuItem,
    )
    from Foundation import NSObject

    app = NSApplication.sharedApplication()
    main_menu = app.mainMenu()

    if main_menu is None:
        return False

    app_item = main_menu.itemWithTitle_("Battery Guard")

    if app_item is None or app_item.submenu() is None:
        return False

    menu = app_item.submenu()

    if menu.itemWithTitle_("Debug…") is not None:
        return True

    class DebugMenuHandler(NSObject):
        def openDebug_(self, sender):
            show_debug_window()

    _DEBUG_MENU_HANDLER = (
        DebugMenuHandler.alloc().init()
    )

    item = (
        NSMenuItem.alloc()
        .initWithTitle_action_keyEquivalent_(
            "Debug…",
            "openDebug:",
            "d",
        )
    )

    item.setTarget_(_DEBUG_MENU_HANDLER)
    item.setKeyEquivalentModifierMask_(
        NSEventModifierFlagCommand
        | NSEventModifierFlagOption
    )

    about_index = menu.indexOfItemWithTitle_(
        "Sobre o Battery Guard"
    )

    if about_index >= 0:
        menu.insertItem_atIndex_(
            item,
            about_index + 1,
        )
    else:
        menu.insertItem_atIndex_(item, 0)

    return True
