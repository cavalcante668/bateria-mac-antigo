#!/usr/bin/env python3

import html
import re
import sqlite3
import time
import urllib.parse
import urllib.request
from pathlib import Path


DB_PATH = str(Path.home() / "battery-history.db")
LOG_PATH = str(Path.home() / "process-resolver.log")

MAX_PER_RUN = 15


# ============================================================
# CATÁLOGO LOCAL
# ============================================================

LOCAL_CATALOG = {

    # Interface / macOS
    "ControlCenter":
        ("Central de Controle do macOS", "Sistema"),

    "SystemUIServer":
        ("Barra de menus do macOS", "Sistema"),

    "NotificationCenter":
        ("Central de Notificações do macOS", "Sistema"),

    "NotificationCent":
        ("Central de Notificações do macOS", "Sistema"),

    "Dock":
        ("Dock do macOS", "Sistema"),

    "WindowServer":
        ("Interface gráfica do macOS", "Sistema"),


    # Widgets
    "WorldClockWidget":
        ("Widget Relógio Mundial do macOS", "Sistema"),

    "StocksWidget":
        ("Widget Bolsa do macOS", "Sistema"),

    "WeatherWidget":
        ("Widget Clima do macOS", "Sistema"),

    "CalendarAgent":
        ("Calendário do macOS", "Sistema"),


    # Compartilhamento
    "sharingd":
        ("AirDrop e compartilhamento do macOS", "Sistema"),

    "AirPlayXPCHelper":
        ("AirPlay do macOS", "Sistema"),


    # Áudio
    "coreaudiod":
        ("Áudio do sistema", "Sistema"),

    "mediaremoted":
        ("Controle de mídia do macOS", "Sistema"),

    "systemsoundserverd":
        ("Sons do sistema do macOS", "Sistema"),

    "systemsoundserve":
        ("Sons do sistema do macOS", "Sistema"),


    # Rede
    "airportd":
        ("Wi-Fi do macOS", "Sistema"),

    "wifianalyticsd":
        ("Diagnóstico e análise do Wi-Fi", "Sistema"),

    "captiveagent":
        ("Detecção de redes Wi-Fi com portal", "Sistema"),

    "mDNSResponder":
        ("Rede local e DNS do macOS", "Sistema"),


    # Bluetooth
    "bluetoothd":
        ("Bluetooth do macOS", "Sistema"),

    "BlueTool":
        ("Gerenciamento Bluetooth do macOS", "Sistema"),


    # Energia
    "powerd":
        ("Gerenciamento de energia", "Sistema"),

    "systemstats":
        ("Estatísticas de uso do sistema", "Sistema"),


    # Preferências / contas
    "cfprefsd":
        ("Preferências do macOS", "Sistema"),

    "accountsd":
        ("Contas de Internet do macOS", "Sistema"),

    "AppSSOAgent":
        ("Autenticação de contas do macOS", "Sistema"),

    "TrustedPeersHelper":
        ("Segurança e dispositivos confiáveis do iCloud", "Sistema"),

    "TrustedPeersHelp":
        ("Segurança e dispositivos confiáveis do iCloud", "Sistema"),


    # Segurança
    "trustd":
        ("Segurança e certificados", "Sistema"),

    "securityd":
        ("Segurança do sistema", "Sistema"),

    "securityd_service":
        ("Serviço de segurança do macOS", "Sistema"),

    "securityd_servic":
        ("Serviço de segurança do macOS", "Sistema"),

    "syspolicyd":
        ("Verificação de segurança de aplicativos", "Sistema"),


    # Arquivos
    "fseventsd":
        ("Monitoramento de arquivos do macOS", "Sistema"),

    "filecoordinationd":
        ("Coordenação de arquivos do macOS", "Sistema"),

    "filecoordination":
        ("Coordenação de arquivos do macOS", "Sistema"),

    "automountd":
        ("Montagem automática de discos e volumes", "Sistema"),


    # Spotlight
    "mds":
        ("Serviço do Spotlight", "Sistema"),

    "mds_stores":
        ("Banco de índice do Spotlight", "Sistema"),

    "mdworker":
        ("Indexação do Spotlight", "Sistema"),

    "mdworker_shared":
        ("Indexação do Spotlight", "Sistema"),


    # Notas / lembretes
    "usernoted":
        ("Notas e dados pessoais do macOS", "Sistema"),

    "Stickies":
        ("Notas Adesivas do macOS", "Aplicativo"),


    # Câmera
    "AppleCameraAssistant":
        ("Câmera do Mac", "Sistema"),

    "AppleCameraAssis":
        ("Câmera do Mac", "Sistema"),

    "UVCAssistant":
        ("Suporte a câmeras USB", "Sistema"),


    # Cores / vídeo
    "colorsyncd":
        ("Gerenciamento de cores ColorSync", "Sistema"),

    "colorsync.display":
        ("Gerenciamento de cores da tela", "Sistema"),

    "colorsync.displa":
        ("Gerenciamento de cores da tela", "Sistema"),


    # Entrada
    "hidd":
        ("Teclado, mouse e dispositivos de entrada", "Sistema"),


    # Atualização / instalação
    "softwareupdated":
        ("Atualização do macOS", "Sistema"),

    "bootinstalld":
        ("Instalação e atualização do macOS", "Sistema"),


    # Sistema
    "talagent":
        ("Gerenciamento de tarefas do macOS", "Sistema"),

    "appleeventsd":
        ("Automação e eventos entre aplicativos", "Sistema"),

    "fontd":
        ("Gerenciamento de fontes do macOS", "Sistema"),

    "fontworker":
        ("Processamento de fontes do macOS", "Sistema"),

    "contactsd":
        ("Contatos do macOS", "Sistema"),

    "donotdisturbd":
        ("Não Perturbe / Foco do macOS", "Sistema"),

    "backgroundtaskmanagementagent":
        ("Gerenciamento de tarefas em segundo plano", "Sistema"),

    "backgroundtaskma":
        ("Gerenciamento de tarefas em segundo plano", "Sistema"),

    "gamecontrollerd":
        ("Controle de videogame do macOS", "Sistema"),

    "identityservicesd":
        ("Serviços de identidade da Apple", "Sistema"),

    "homed":
        ("Casa / HomeKit do macOS", "Sistema"),

    "followupd":
        ("Avisos e ações pendentes do macOS", "Sistema"),

    "iconservicesagent":
        ("Ícones e miniaturas do macOS", "Sistema"),

    "iconservicesagen":
        ("Ícones e miniaturas do macOS", "Sistema"),


    # NÃO deve aparecer como consumidor
    "top":
        ("IGNORAR", "Monitor"),
}


def log(message):

    line = (
        time.strftime("%Y-%m-%d %H:%M:%S")
        + " | "
        + message
    )

    try:
        with open(LOG_PATH, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


def clean_text(value):

    value = re.sub(
        r"<[^>]+>",
        " ",
        value
    )

    value = html.unescape(value)

    value = re.sub(
        r"\s+",
        " ",
        value
    )

    return value.strip()


# ============================================================
# DDG LITE
# ============================================================

def online_lookup(process_name):

    query = (
        f'"{process_name}" macOS process daemon application'
    )

    url = (
        "https://lite.duckduckgo.com/lite/?"
        + urllib.parse.urlencode({"q": query})
    )

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent":
                "Mozilla/5.0"
        }
    )

    try:

        with urllib.request.urlopen(
            request,
            timeout=10
        ) as response:

            body = response.read(
                750000
            ).decode(
                "utf-8",
                errors="ignore"
            )

    except Exception as e:

        log(
            f"WEB ERRO | {process_name} | "
            f"{type(e).__name__}: {e}"
        )

        return None


    # Texto pesquisável
    text = clean_text(body)

    if len(text) < 200:

        log(
            f"WEB VAZIO | {process_name}"
        )

        return None


    # --------------------------------------------------------
    # Extrai links/títulos do DuckDuckGo Lite
    # --------------------------------------------------------

    titles = re.findall(
        r'<a[^>]+href="[^"]+"[^>]*>(.*?)</a>',
        body,
        flags=re.I | re.S
    )

    titles = [
        clean_text(x)
        for x in titles
    ]

    useful_titles = []

    for title in titles:

        if len(title) < 4:
            continue

        lower = title.lower()

        if (
            "duckduckgo" in lower
            or "next page" in lower
        ):
            continue

        useful_titles.append(title)


    # Precisamos que o resultado realmente tenha relação
    # com o nome pesquisado.
    related = [
        x for x in useful_titles
        if process_name.lower() in x.lower()
    ]


    if not related:

        # Mesmo sem título exato, registra que a pesquisa
        # funcionou. Mantemos pending em vez de inventar.
        log(
            f"WEB SEM IDENTIFICAÇÃO | {process_name}"
        )

        return None


    title = related[0]


    # Remove construções comuns de páginas de suporte
    friendly = title

    friendly = re.sub(
        r'\s*[-|–—]\s*Apple.*$',
        '',
        friendly,
        flags=re.I
    )

    friendly = friendly.strip()


    # Não aceitamos como tradução algo que seja basicamente
    # o mesmo nome técnico.
    compact_friendly = re.sub(
        r'[^a-z0-9]',
        '',
        friendly.lower()
    )

    compact_process = re.sub(
        r'[^a-z0-9]',
        '',
        process_name.lower()
    )

    if compact_friendly == compact_process:

        log(
            f"WEB RESULTADO INÚTIL | "
            f"{process_name} | {title}"
        )

        return None


    log(
        f"WEB IDENTIFICADO | "
        f"{process_name} -> {friendly}"
    )


    return {
        "friendly_name": friendly[:140],
        "description": title[:300],
        "source": "duckduckgo"
    }


# ============================================================
# PRINCIPAL
# ============================================================

def main():

    conn = sqlite3.connect(
        DB_PATH,
        timeout=10
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

    conn.commit()


    # --------------------------------------------------------
    # 1. RESOLVE LOCALMENTE O QUE JÁ CONHECEMOS
    # --------------------------------------------------------

    rows = conn.execute("""
        SELECT technical_name
        FROM process_catalog
        WHERE status = 'pending'
    """).fetchall()


    local_count = 0

    for row in rows:

        technical = row[0]

        if technical not in LOCAL_CATALOG:
            continue

        friendly, process_type = LOCAL_CATALOG[technical]

        if friendly == "IGNORAR":

            conn.execute("""
                UPDATE process_catalog
                SET
                    friendly_name = ?,
                    status = 'ignored',
                    process_type = ?,
                    source = 'local',
                    last_checked = ?
                WHERE technical_name = ?
            """, (
                friendly,
                process_type,
                time.time(),
                technical
            ))

        else:

            conn.execute("""
                UPDATE process_catalog
                SET
                    friendly_name = ?,
                    status = 'identified_local',
                    process_type = ?,
                    source = 'local',
                    last_checked = ?
                WHERE technical_name = ?
            """, (
                friendly,
                process_type,
                time.time(),
                technical
            ))

        local_count += 1


    conn.commit()

    log(
        f"LOCAL | {local_count} identificados"
    )


    # --------------------------------------------------------
    # 2. RESTANTE VAI PARA INTERNET
    # --------------------------------------------------------

    pending = conn.execute("""
        SELECT technical_name
        FROM process_catalog
        WHERE status = 'pending'
        ORDER BY
            COALESCE(last_checked, 0) ASC,
            COALESCE(created_at, 0) ASC
        LIMIT ?
    """, (
        MAX_PER_RUN,
    )).fetchall()


    log(
        f"INÍCIO WEB | {len(pending)} pendentes"
    )


    for row in pending:

        technical = row[0]

        result = online_lookup(
            technical
        )

        now = time.time()

        if result:

            conn.execute("""
                UPDATE process_catalog
                SET
                    friendly_name = ?,
                    status = 'identified_online',
                    description = ?,
                    source = ?,
                    last_checked = ?
                WHERE technical_name = ?
            """, (
                result["friendly_name"],
                result["description"],
                result["source"],
                now,
                technical
            ))

        else:

            conn.execute("""
                UPDATE process_catalog
                SET
                    last_checked = ?
                WHERE technical_name = ?
            """, (
                now,
                technical
            ))


        conn.commit()

        time.sleep(1)


    conn.close()

    log("FIM")


if __name__ == "__main__":
    main()

