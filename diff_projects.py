#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
diff_projects.py — Porównuje projects.json z projects-last-day.json
===================================================================

Pokazuje nowe projekty (dodane po ostatnim dniu składania) i usunięte
(obecne w last-day ale nie w bieżącym). Filtruje tylko interesujące
budżety/dzielnice. Wynik sortowany po: typ budżetu → dzielnica → kwota.

Identyfikacja projektu po URL (unikalne).

JAK URUCHOMIĆ:
    powershell.exe -Command "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; python -X utf8 diff_projects.py"

PLIKI WEJŚCIOWE:
    data/projects.json          — bieżący stan (ze scrapera)
    data/projects-last-day.json — snapshot z ostatniego dnia składania

FILTR DZIELNIC (edytuj FILTER poniżej żeby zmienić):
    Domyślnie: BO Krakowiec-Górki Zachodnie, BO Orunia Górna-Gdańsk
    Południe, BO Wyspa Sobieszewska, BO Brzeźno, BO Nowy Port,
    BO ogólnomiejski, ZBO Zaspa-Rozstaje, ZBO Przymorze Wielkie.
    Ustaw FILTER = None żeby pokazać wszystkie.
"""

import json
import sys
import io
from pathlib import Path

# Force UTF-8 output even on Windows without -X utf8
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# ── Konfiguracja ─────────────────────────────────────────────────────────────

DATA_DIR = Path(__file__).parent / "data"
CURRENT = DATA_DIR / "projects.json"
LAST_DAY = DATA_DIR / "projects-last-day.json"

# (budget_type_short, district) — budget_type_short = "BO" lub "ZBO"
# None = pokaż wszystkie (bez filtra)
FILTER = {
    ("BO", "Krakowiec-Górki Zachodnie"),
    ("BO", "Orunia Górna-Gdańsk Południe"),
    ("BO", "Wyspa Sobieszewska"),
    ("BO", "Brzeźno"),
    ("BO", "Nowy Port"),
    ("BO", None),  # ogólnomiejski — district is None / empty
    ("ZBO", "Zaspa-Rozstaje"),
    ("ZBO", "Przymorze Wielkie"),
}

# ── Helpers ──────────────────────────────────────────────────────────────────

def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def budget_short(p):
    bt = p.get("budget_type", "")
    if "Zielony" in bt:
        return "ZBO"
    return "BO"


def matches_filter(p):
    if FILTER is None:
        return True
    bs = budget_short(p)
    dist = p.get("district") or None
    # ogólnomiejski: scope == "Ogólnomiejski" or district is empty/None
    scope = p.get("scope", "")
    if scope == "Ogólnomiejski" or not dist:
        return (bs, None) in FILTER
    return (bs, dist) in FILTER


def fmt_cost(n):
    """Format cost Polish-style: 327 790 zł"""
    s = f"{n:,.0f}".replace(",", "\u00a0")
    return f"{s} z\u0142"


def sort_key(p):
    bs = budget_short(p)
    dist = p.get("district") or ""
    cost = p.get("total_cost", 0)
    return (bs, dist, cost)


def print_project(p, prefix=""):
    bs = budget_short(p)
    dist = p.get("district") or "Ogólnomiejski"
    cost = p.get("total_cost", 0)
    title = p.get("title", "???")
    green = " 🌿" if p.get("is_green") else ""
    url = p.get("url", "")
    print(f"{prefix}[{bs}] {dist} | {fmt_cost(cost)} | {title}{green}")
    if url:
        print(f"{prefix}  {url}")


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    if not CURRENT.exists():
        print(f"BŁĄD: {CURRENT} nie istnieje. Uruchom scraper.", file=sys.stderr)
        sys.exit(1)
    if not LAST_DAY.exists():
        print(f"BŁĄD: {LAST_DAY} nie istnieje.", file=sys.stderr)
        sys.exit(1)

    current = load(CURRENT)
    last_day = load(LAST_DAY)

    cur_urls = {p["url"]: p for p in current}
    old_urls = {p["url"]: p for p in last_day}

    new_urls = set(cur_urls.keys()) - set(old_urls.keys())
    removed_urls = set(old_urls.keys()) - set(cur_urls.keys())

    new_projects = [cur_urls[u] for u in new_urls if matches_filter(cur_urls[u])]
    removed_projects = [old_urls[u] for u in removed_urls if matches_filter(old_urls[u])]

    new_projects.sort(key=sort_key)
    removed_projects.sort(key=sort_key)

    # Stats
    all_new = [cur_urls[u] for u in new_urls]
    all_removed = [old_urls[u] for u in removed_urls]
    print(f"Porównanie: {LAST_DAY.name} ({len(last_day)} proj.) → {CURRENT.name} ({len(current)} proj.)")
    print(f"Ogółem: +{len(all_new)} nowych, -{len(all_removed)} usuniętych")
    if FILTER is not None:
        print(f"Filtr: {len(new_projects)} nowych, {len(removed_projects)} usuniętych (po filtrze)")
    print()

    if new_projects:
        print(f"{'═' * 70}")
        print(f"  NOWE PROJEKTY ({len(new_projects)})")
        print(f"{'═' * 70}")
        prev_group = None
        for p in new_projects:
            group = (budget_short(p), p.get("district") or "Ogólnomiejski")
            if group != prev_group:
                if prev_group is not None:
                    print()
                print(f"── {group[0]} / {group[1]} ──")
                prev_group = group
            print_project(p, prefix="  ")
        print()
    else:
        print("Brak nowych projektów (po filtrze).\n")

    if removed_projects:
        print(f"{'═' * 70}")
        print(f"  USUNIĘTE PROJEKTY ({len(removed_projects)})")
        print(f"{'═' * 70}")
        prev_group = None
        for p in removed_projects:
            group = (budget_short(p), p.get("district") or "Ogólnomiejski")
            if group != prev_group:
                if prev_group is not None:
                    print()
                print(f"── {group[0]} / {group[1]} ──")
                prev_group = group
            print_project(p, prefix="  ")
        print()
    else:
        print("Brak usuniętych projektów (po filtrze).\n")


if __name__ == "__main__":
    main()
