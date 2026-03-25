#!/usr/bin/env python3
"""
Analyze budget utilization per district for BO 2027 Gdańsk.
Reads data/budgets.json and data/projects.json, then shows:
  - Districts sorted by % budget used (lowest first) for regular BO
  - Same for Zielony BO (green budget)

Run scrape_budgets.py and scrape_projects.py first to populate data/.
"""

import json
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"

# Mapping: project district name -> budget district name
# (handles inconsistencies between bo.gdansk.pl and gdansk.pl)
DISTRICT_NAME_MAP = {
    "Orunia Górna-Gdańsk Południe": "Orunia Górna - Gdańsk Południe",
    "Śródmieście": "Środmieście",
}


def normalize_district(name):
    """Map project district name to budget district name."""
    return DISTRICT_NAME_MAP.get(name, name)


def main():
    with open(DATA_DIR / "budgets.json", encoding="utf-8") as f:
        budgets = json.load(f)
    with open(DATA_DIR / "projects.json", encoding="utf-8") as f:
        projects = json.load(f)

    # Verify all projects map to a known budget district
    unmatched = set()
    for p in projects:
        d = normalize_district(p.get("district", "???"))
        if d not in budgets:
            unmatched.add(d)
    if unmatched:
        print(f"WARNING: Unmatched districts: {unmatched}")
        print("Update DISTRICT_NAME_MAP in analyze.py")
        return

    # Aggregate costs per district, split by BO type
    # bo_costs[district] = total cost of regular BO projects
    # zbo_costs[district] = total cost of green BO projects
    bo_costs = {}
    zbo_costs = {}
    bo_counts = {}
    zbo_counts = {}

    for p in projects:
        district = normalize_district(p.get("district", "???"))
        cost = p.get("total_cost", 0) or 0
        is_green = p.get("is_green", False)

        if is_green:
            zbo_costs[district] = zbo_costs.get(district, 0) + cost
            zbo_counts[district] = zbo_counts.get(district, 0) + 1
        else:
            bo_costs[district] = bo_costs.get(district, 0) + cost
            bo_counts[district] = bo_counts.get(district, 0) + 1

    # Print regular BO analysis
    print("=" * 100)
    print("BUDŻET OBYWATELSKI (regular) - utilization by district")
    print("Sorted by % used (lowest = most opportunity)")
    print("=" * 100)
    print(f"{'Dzielnica':<42} {'%':>7} {'Suma projektów':>16} {'Budżet':>16} {'Projektów':>10}")
    print("-" * 100)

    rows_bo = []
    for district, budget_data in budgets.items():
        bo_budget = budget_data.get("budget_bo", 0)
        if bo_budget <= 0:
            continue
        spent = bo_costs.get(district, 0)
        count = bo_counts.get(district, 0)
        pct = (spent / bo_budget) * 100 if bo_budget > 0 else 0
        rows_bo.append((district, pct, spent, bo_budget, count))

    rows_bo.sort(key=lambda x: x[1])
    for district, pct, spent, budget, count in rows_bo:
        remaining = budget - spent
        marker = " <<<" if pct < 100 else ""
        print(f"{district:<42} {pct:>6.1f}% {spent:>14,.2f} zł {budget:>14,.2f} zł {count:>10}{marker}")

    # Print green BO analysis
    print()
    print("=" * 100)
    print("ZIELONY BUDŻET OBYWATELSKI (green) - utilization by district")
    print("Sorted by % used (lowest = most opportunity)")
    print("=" * 100)
    print(f"{'Dzielnica':<42} {'%':>7} {'Suma projektów':>16} {'Budżet':>16} {'Projektów':>10}")
    print("-" * 100)

    rows_zbo = []
    for district, budget_data in budgets.items():
        zbo_budget = budget_data.get("budget_zbo", 0)
        if zbo_budget <= 0:
            continue
        spent = zbo_costs.get(district, 0)
        count = zbo_counts.get(district, 0)
        pct = (spent / zbo_budget) * 100 if zbo_budget > 0 else 0
        rows_zbo.append((district, pct, spent, zbo_budget, count))

    rows_zbo.sort(key=lambda x: x[1])
    for district, pct, spent, budget, count in rows_zbo:
        marker = " <<<" if pct < 100 else ""
        print(f"{district:<42} {pct:>6.1f}% {spent:>14,.2f} zł {budget:>14,.2f} zł {count:>10}{marker}")

    # Summary: districts with 0% utilization
    print()
    print("=" * 100)
    print("DISTRICTS WITH ZERO PROJECTS (fully available budget)")
    print("=" * 100)

    print("\nRegular BO:")
    for district, pct, spent, budget, count in rows_bo:
        if count == 0:
            print(f"  {district}: {budget:,.2f} zł available")

    print("\nZielony BO:")
    for district, pct, spent, budget, count in rows_zbo:
        if count == 0:
            print(f"  {district}: {budget:,.2f} zł available")


if __name__ == "__main__":
    main()
