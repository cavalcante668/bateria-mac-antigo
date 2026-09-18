#!/usr/bin/env python3

import os
import runpy
import socket
import subprocess
import sys
import time
import traceback
from pathlib import Path


APP_NAME = "Battery Guard"
HOST = "127.0.0.1"

PORT = int(
    os.environ.get(
        "BATTERY_GUARD_PORT",
        "8765"
    )
)


# ============================================================
# DIRETÓRIO DE DADOS
# ============================================================

DATA_DIR = Path(
    os.environ.get(
        "BATTERY_GUARD_DATA_DIR",
        str(
            Path.home()
            / "Library"
            / "Application Support"
            / APP_NAME
        )
    )
)

LOG_DIR = DATA_DIR / "logs"

DATA_DIR.mkdir(
    parents=True,
    exist_ok=True
)

LOG_DIR.mkdir(
    parents=True,
    exist_ok=True
)

LAUNCHER_LOG = LOG_DIR / "launcher.log"


def log(message):

    timestamp = time.strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    try:
        with LAUNCHER_LOG.open(
            "a",
            encoding="utf-8"
        ) as f:

            f.write(
                f"{timestamp} | {message}\n"
            )

    except Exception:
        pass


def is_frozen():

    return bool(
        getattr(
            sys,
            "frozen",
            False
        )
    )


# ============================================================
# LOCALIZAÇÃO DOS SCRIPTS DENTRO DO .APP
# ============================================================

def find_app_dir():

    candidates = []


    # PyInstaller _MEIPASS
    meipass = getattr(
        sys,
        "_MEIPASS",
        None
    )

    if meipass:

        base = Path(meipass)

        candidates.extend([
            base / "app",
            base.parent / "Resources" / "app",
            base.parent / "Frameworks" / "app",
        ])


    # Battery Guard.app/Contents/MacOS/Battery Guard
    if is_frozen():

        exe = Path(
            sys.executable
        ).resolve()

        contents = (
            exe.parent.parent
        )

        candidates.extend([
            contents / "Resources" / "app",
            contents / "Frameworks" / "app",
            contents / "MacOS" / "app",
            contents / "_internal" / "app",
        ])


    # Execução em desenvolvimento
    candidates.append(
        Path(__file__)
        .resolve()
        .parents[1]
        / "app"
    )


    for candidate in candidates:

        try:

            if (
                candidate.exists()
                and
                (
                    candidate
                    / "battery-view.py"
                ).exists()
            ):

                log(
                    "Diretório app localizado: "
                    + str(candidate)
                )

                return candidate

        except Exception:
            pass


    # Busca de último recurso dentro do bundle.
    if is_frozen():

        exe = Path(
            sys.executable
        ).resolve()

        contents = (
            exe.parent.parent
        )

        try:

            for candidate in (
                contents.rglob(
                    "battery-view.py"
                )
            ):

                directory = (
                    candidate.parent
                )

                if (
                    directory
                    / "battery-analysis.py"
                ).exists():

                    log(
                        "Diretório app localizado por busca: "
                        + str(directory)
                    )

                    return directory

        except Exception as e:

            log(
                "Erro procurando recursos: "
                + repr(e)
            )


    log("ERRO: diretório app não localizado")

    log(
        "Candidatos testados: "
        + " | ".join(
            str(x)
            for x in candidates
        )
    )

    raise RuntimeError(
        "Não foi possível localizar "
        "os componentes internos do Battery Guard."
    )


APP_DIR = find_app_dir()


# ============================================================
# AMBIENTE DOS WORKERS
# ============================================================

def child_environment():

    env = os.environ.copy()

    env[
        "BATTERY_GUARD_DATA_DIR"
    ] = str(DATA_DIR)

    env[
        "BATTERY_GUARD_APP_DIR"
    ] = str(APP_DIR)

    env[
        "BATTERY_GUARD_PORT"
    ] = str(PORT)

    return env


def self_command():

    if is_frozen():

        return [
            sys.executable
        ]

    return [
        sys.executable,
        str(
            Path(__file__).resolve()
        )
    ]


# ============================================================
# SERVIDOR
# ============================================================

def port_is_open():

    try:

        with socket.create_connection(
            (HOST, PORT),
            timeout=0.5
        ):

            return True

    except OSError:

        return False


def wait_for_server(
    timeout=30
):

    deadline = (
        time.time()
        +
        timeout
    )

    while (
        time.time()
        <
        deadline
    ):

        if port_is_open():

            return True

        time.sleep(0.25)

    return False


# ============================================================
# WORKERS
# ============================================================

def worker(
    name,
    arguments
):

    os.environ.update(
        child_environment()
    )


    scripts = {

        "view":
            APP_DIR
            / "battery-view.py",

        "resolver":
            APP_DIR
            / "process-resolver.py",

        "analysis":
            APP_DIR
            / "battery-analysis.py",

        "native":
            APP_DIR
            / "native-view.py",
    }


    script = scripts.get(
        name
    )


    if script is None:

        raise RuntimeError(
            f"Worker desconhecido: {name}"
        )


    if not script.exists():

        raise RuntimeError(
            f"Arquivo não encontrado: {script}"
        )


    log(
        f"Iniciando worker {name}: {script}"
    )


    sys.argv = [
        str(script),
        *arguments
    ]


    runpy.run_path(
        str(script),
        run_name="__main__"
    )


def launch_worker(
    name,
    *arguments
):

    log_file = (
        LOG_DIR
        / f"{name}.log"
    )


    out = open(
        log_file,
        "a",
        buffering=1
    )


    command = (
        self_command()
        +
        [
            "--worker",
            name,
            *arguments
        ]
    )


    log(
        "Subprocesso: "
        + repr(command)
    )


    return subprocess.Popen(
        command,
        env=child_environment(),
        stdout=out,
        stderr=out
    )


# ============================================================
# NAVEGADOR
# ============================================================

def open_dashboard():

    url = (
        f"http://{HOST}:{PORT}"
    )

    log(
        "Abrindo interface nativa: "
        + url
    )

    native = launch_worker(
        "native"
    )

    time.sleep(1)

    if native.poll() is not None:

        raise RuntimeError(
            "Interface nativa encerrou "
            "prematuramente. Código: "
            + str(native.returncode)
        )

    log(
        "Interface nativa iniciada."
    )

    return native


# ============================================================
# MAIN
# ============================================================

def main():

    log("=" * 60)

    log(
        "Battery Guard iniciado"
    )

    log(
        "Frozen: "
        + str(is_frozen())
    )

    log(
        "Executável: "
        + str(sys.executable)
    )

    log(
        "APP_DIR: "
        + str(APP_DIR)
    )

    log(
        "DATA_DIR: "
        + str(DATA_DIR)
    )

    log(
        "Porta: "
        + str(PORT)
    )


    # --------------------------------------------------------
    # EXECUÇÃO COMO WORKER
    # --------------------------------------------------------

    if (
        len(sys.argv) >= 3
        and
        sys.argv[1]
        ==
        "--worker"
    ):

        worker(
            sys.argv[2],
            sys.argv[3:]
        )

        return


    # --------------------------------------------------------
    # SERVIDOR JÁ EXISTE
    # --------------------------------------------------------

    if port_is_open():

        log(
            "Servidor já ativo."
        )

        open_dashboard()

        return


    # --------------------------------------------------------
    # DASHBOARD
    # --------------------------------------------------------

    log(
        "Iniciando dashboard..."
    )

    view = launch_worker(
        "view"
    )


    # --------------------------------------------------------
    # ALERTAS
    # --------------------------------------------------------

    guard_log_path = (
        LOG_DIR
        / "guard-process.log"
    )

    guard_log = open(
        guard_log_path,
        "a",
        buffering=1
    )


    guard_script = (
        APP_DIR
        / "battery-guard.sh"
    )


    guard = None

    if guard_script.exists():

        log(
            "Iniciando Battery Guard shell"
        )

        guard = subprocess.Popen(
            [
                "/bin/bash",
                str(
                    guard_script
                )
            ],
            env=child_environment(),
            stdout=guard_log,
            stderr=guard_log
        )

    else:

        log(
            "AVISO: battery-guard.sh "
            "não encontrado."
        )


    # --------------------------------------------------------
    # RESOLVER
    # --------------------------------------------------------

    log(
        "Executando process resolver"
    )

    launch_worker(
        "resolver"
    )


    # --------------------------------------------------------
    # AGUARDA HTTP
    # --------------------------------------------------------

    if not wait_for_server():

        log(
            "ERRO: servidor HTTP "
            "não iniciou em 30 segundos."
        )

        if view.poll() is not None:

            log(
                "Worker view encerrou com código "
                + str(
                    view.returncode
                )
            )

        return


    log(
        "Servidor HTTP ativo"
    )

    open_dashboard()


    # --------------------------------------------------------
    # RESOLVER PERIÓDICO
    # --------------------------------------------------------

    next_resolver = (
        time.time()
        +
        1800
    )


    while True:

        if view.poll() is not None:

            log(
                "Dashboard encerrou. "
                "Código: "
                + str(
                    view.returncode
                )
            )

            break


        now = time.time()


        if now >= next_resolver:

            log(
                "Executando resolver periódico"
            )

            launch_worker(
                "resolver"
            )

            next_resolver = (
                now
                +
                1800
            )


        time.sleep(2)


    if (
        guard is not None
        and
        guard.poll() is None
    ):

        guard.terminate()


    guard_log.close()


if __name__ == "__main__":

    try:

        main()

    except Exception:

        log(
            "ERRO FATAL:\n"
            + traceback.format_exc()
        )

        raise
