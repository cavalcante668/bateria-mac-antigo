#!/usr/bin/env python3
import argparse
import csv
import os
import sqlite3
import statistics
import time
from datetime import datetime
from pathlib import Path

DEFAULT_DB_CANDIDATES = [
    Path.home() / "battery-history.db",
    Path.home() / "Library" / "Application Support" / "Battery Guard" / "battery-history.db",
]

DEFAULT_CSV = (
    Path.home()
    / "Library"
    / "Application Support"
    / "Battery Guard"
    / "db-growth.csv"
)

FIELDS = [
    "timestamp",
    "iso_time",
    "db_path",
    "db_bytes",
    "wal_bytes",
    "shm_bytes",
    "total_bytes",
    "page_size",
    "page_count",
    "freelist_count",
    "logical_bytes",
]

def choose_db(explicit=None):
    if explicit:
        p = Path(explicit).expanduser()
        if not p.exists():
            raise SystemExit(f"Banco não encontrado: {p}")
        return p

    existing = [p for p in DEFAULT_DB_CANDIDATES if p.exists()]
    if not existing:
        raise SystemExit("Nenhum battery-history.db encontrado.")

    # Em caso de dois bancos, prioriza o mais recentemente modificado.
    return max(existing, key=lambda p: p.stat().st_mtime)

def fsize(path):
    try:
        return path.stat().st_size
    except FileNotFoundError:
        return 0

def sqlite_metrics(db_path):
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
    try:
        page_size = int(conn.execute("PRAGMA page_size").fetchone()[0])
        page_count = int(conn.execute("PRAGMA page_count").fetchone()[0])
        freelist_count = int(conn.execute("PRAGMA freelist_count").fetchone()[0])
    finally:
        conn.close()

    return {
        "page_size": page_size,
        "page_count": page_count,
        "freelist_count": freelist_count,
        "logical_bytes": page_size * page_count,
    }

def snapshot(db_path):
    now = time.time()
    db = Path(db_path)
    wal = Path(str(db) + "-wal")
    shm = Path(str(db) + "-shm")

    metrics = sqlite_metrics(db)

    row = {
        "timestamp": f"{now:.6f}",
        "iso_time": datetime.fromtimestamp(now).astimezone().isoformat(timespec="seconds"),
        "db_path": str(db),
        "db_bytes": fsize(db),
        "wal_bytes": fsize(wal),
        "shm_bytes": fsize(shm),
    }
    row["total_bytes"] = row["db_bytes"] + row["wal_bytes"] + row["shm_bytes"]
    row.update(metrics)
    return row

def append_csv(csv_path, row):
    csv_path = Path(csv_path).expanduser()
    csv_path.parent.mkdir(parents=True, exist_ok=True)

    exists = csv_path.exists()
    with csv_path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        if not exists:
            writer.writeheader()
        writer.writerow(row)

def human_bytes(value):
    value = float(value)
    units = ["B", "KB", "MB", "GB", "TB"]
    idx = 0
    while abs(value) >= 1024 and idx < len(units) - 1:
        value /= 1024
        idx += 1
    return f"{value:.2f} {units[idx]}"

def load_rows(csv_path, db_path=None):
    p = Path(csv_path).expanduser()
    if not p.exists():
        return []

    rows = []
    with p.open("r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                row["timestamp"] = float(row["timestamp"])
                row["total_bytes"] = int(row["total_bytes"])
            except Exception:
                continue

            if db_path and row.get("db_path") != str(db_path):
                continue
            rows.append(row)
    return rows

def summary(csv_path, db_path=None):
    rows = load_rows(csv_path, db_path)
    if len(rows) < 2:
        print("Ainda não há amostras suficientes para estimar crescimento.")
        return

    rows.sort(key=lambda r: r["timestamp"])
    first = rows[0]
    last = rows[-1]

    seconds = last["timestamp"] - first["timestamp"]
    if seconds <= 0:
        print("Intervalo inválido entre amostras.")
        return

    delta = last["total_bytes"] - first["total_bytes"]
    days = seconds / 86400
    bytes_per_day = delta / days

    print(f"Amostras: {len(rows)}")
    print(f"Janela: {days:.2f} dias")
    print(f"Início: {human_bytes(first['total_bytes'])}")
    print(f"Atual: {human_bytes(last['total_bytes'])}")
    print(f"Crescimento observado: {human_bytes(delta)}")
    print(f"Ritmo médio: {human_bytes(bytes_per_day)}/dia")
    print(f"Projeção 7 dias: {human_bytes(bytes_per_day * 7)}")
    print(f"Projeção 30 dias: {human_bytes(bytes_per_day * 30)}")
    print(f"Projeção 365 dias: {human_bytes(bytes_per_day * 365)}")

def print_snapshot(row):
    print(f"Data: {row['iso_time']}")
    print(f"Banco: {row['db_path']}")
    print(f"DB: {human_bytes(row['db_bytes'])}")
    print(f"WAL: {human_bytes(row['wal_bytes'])}")
    print(f"SHM: {human_bytes(row['shm_bytes'])}")
    print(f"Total: {human_bytes(row['total_bytes'])}")
    print(f"SQLite lógico: {human_bytes(row['logical_bytes'])}")
    print(f"Páginas: {row['page_count']}")
    print(f"Páginas livres: {row['freelist_count']}")

def main():
    parser = argparse.ArgumentParser(
        description="Mede o crescimento físico do SQLite do Battery Guard com overhead mínimo."
    )
    parser.add_argument("--db", help="Caminho explícito do battery-history.db")
    parser.add_argument("--csv", default=str(DEFAULT_CSV), help="Arquivo CSV de histórico")
    parser.add_argument("--summary", action="store_true", help="Mostra projeção de crescimento")
    parser.add_argument("--no-write", action="store_true", help="Não grava nova amostra")
    args = parser.parse_args()

    db_path = choose_db(args.db)

    if not args.no_write:
        row = snapshot(db_path)
        append_csv(args.csv, row)
        print_snapshot(row)
        print(f"Histórico: {Path(args.csv).expanduser()}")

    if args.summary:
        print()
        summary(args.csv, db_path)

if __name__ == "__main__":
    main()
