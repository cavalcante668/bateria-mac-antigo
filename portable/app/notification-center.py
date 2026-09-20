#!/usr/bin/env python3

from __future__ import annotations

import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent

if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from battery_notifications import (
    clear_notifications,
    get_notifications,
    get_unread_count,
    mark_all_read,
    mark_read,
)


class Api:
    def state(self):
        return {
            "notifications": get_notifications(),
            "unread": get_unread_count(),
        }

    def read(self, notification_id):
        mark_read(str(notification_id))
        return self.state()

    def read_all(self):
        mark_all_read()
        return self.state()

    def clear(self):
        clear_notifications()
        return self.state()


HTML = """
<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">

<style>
:root {
    color-scheme: light dark;
    font-family: -apple-system, BlinkMacSystemFont, sans-serif;
}

body {
    margin: 0;
    background: #f5f5f7;
    color: #1d1d1f;
}

header {
    position: sticky;
    top: 0;
    background: rgba(245,245,247,.96);
    border-bottom: 1px solid #d2d2d7;
    padding: 18px 20px 14px;
}

.head {
    display: flex;
    align-items: center;
    justify-content: space-between;
}

h1 {
    font-size: 22px;
    margin: 0;
}

#badge {
    background: #d70015;
    color: white;
    border-radius: 999px;
    min-width: 24px;
    height: 24px;
    padding: 0 7px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    font-size: 12px;
    font-weight: 700;
}

.actions {
    margin-top: 14px;
    display: flex;
    gap: 8px;
}

button {
    border: 1px solid #c7c7cc;
    border-radius: 8px;
    padding: 7px 12px;
    background: white;
}

main {
    padding: 16px 20px 28px;
}

.item {
    background: white;
    border: 1px solid #dedee3;
    border-radius: 12px;
    margin-bottom: 10px;
    padding: 14px 16px;
    cursor: pointer;
}

.item.unread {
    border-left: 4px solid #0a84ff;
    padding-left: 13px;
}

.item.warning {
    border-left-color: #ff9f0a;
}

.item.critical {
    border-left-color: #d70015;
}

.title {
    font-weight: 650;
    margin-bottom: 5px;
}

.message {
    font-size: 13px;
    line-height: 1.4;
    white-space: pre-wrap;
}

.meta {
    margin-top: 8px;
    color: #6e6e73;
    font-size: 11px;
}

.empty {
    text-align: center;
    color: #6e6e73;
    padding: 70px 20px;
}

@media (prefers-color-scheme: dark) {
    body {
        background: #1c1c1e;
        color: #f5f5f7;
    }

    header {
        background: rgba(28,28,30,.96);
        border-color: #3a3a3c;
    }

    button,
    .item {
        background: #2c2c2e;
        color: #f5f5f7;
        border-color: #48484a;
    }

    .meta,
    .empty {
        color: #aeaeb2;
    }
}
</style>
</head>

<body>

<header>
<div class="head">
<h1>Notificações</h1>
<span id="badge" hidden>0</span>
</div>

<div class="actions">
<button id="all">Marcar todas como lidas</button>
<button id="clear">Limpar notificações</button>
</div>
</header>

<main id="list">
<div class="empty">Carregando…</div>
</main>

<script>
let ready = false;

function esc(value) {
    const e = document.createElement("div");
    e.textContent = value == null ? "" : String(value);
    return e.innerHTML;
}

function date(value) {
    try {
        return new Date(value).toLocaleString("pt-BR");
    } catch (_) {
        return value || "";
    }
}

function render(state) {
    const list = document.getElementById("list");
    const badge = document.getElementById("badge");

    const unread = Number(state.unread || 0);

    if (unread) {
        badge.hidden = false;
        badge.textContent = unread > 99 ? "99+" : unread;
    } else {
        badge.hidden = true;
    }

    const items = Array.isArray(state.notifications)
        ? state.notifications
        : [];

    if (!items.length) {
        list.innerHTML =
            '<div class="empty">Nenhuma notificação.</div>';
        return;
    }

    list.innerHTML = items.map(item => {
        const unreadClass =
            item.read ? "" : "unread";

        const severity =
            item.severity === "critical"
                ? "critical"
                : item.severity === "warning"
                    ? "warning"
                    : "";

        const repeat =
            Number(item.repeat_count || 1);

        return `
        <article class="item ${unreadClass} ${severity}"
                 data-id="${esc(item.id)}">

            <div class="title">
                ${esc(item.title)}
                ${repeat > 1 ? ` ×${repeat}` : ""}
            </div>

            <div class="message">
                ${esc(item.message)}
            </div>

            <div class="meta">
                ${esc(date(item.timestamp))}
                ${item.source ? " · " + esc(item.source) : ""}
            </div>
        </article>
        `;
    }).join("");

    document.querySelectorAll(".item")
        .forEach(node => {
            node.addEventListener("click", async () => {
                try {
                    const state =
                        await window.pywebview.api.read(
                            node.dataset.id
                        );

                    render(state);
                } catch (_) {}
            });
        });
}

async function refresh() {
    if (!ready) return;

    try {
        render(
            await window.pywebview.api.state()
        );
    } catch (_) {}
}

document.getElementById("all")
.addEventListener("click", async () => {
    try {
        render(
            await window.pywebview.api.read_all()
        );
    } catch (_) {}
});

document.getElementById("clear")
.addEventListener("click", async () => {
    if (!confirm(
        "Deseja apagar o histórico de notificações do Battery Guard?"
    )) {
        return;
    }

    try {
        render(
            await window.pywebview.api.clear()
        );
    } catch (_) {}
});

window.addEventListener(
    "pywebviewready",
    () => {
        ready = true;
        refresh();
        setInterval(refresh, 2000);
    }
);
</script>

</body>
</html>
"""


def main():
    import webview

    webview.create_window(
        "Battery Guard — Notificações",
        html=HTML,
        js_api=Api(),
        width=760,
        height=620,
        min_size=(540, 420),
    )

    webview.start()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
