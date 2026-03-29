#!/usr/bin/env python3
"""
Parse BO results PDFs (bo-2022.pdf through bo-2026.pdf) into structured JSON.
Extracts per-district and citywide data: budgets, all projects (winning and losing),
vote counts, and carryover amounts.

Uses pdfplumber's table extraction for clean structured project data,
and word-level extraction for metadata (district names, budgets, carryover).

Requires: pdfplumber (pip install pdfplumber)
Usage: python parse_bo_results.py
"""

import json
import re
import sys
from pathlib import Path

try:
    import pdfplumber
except ImportError:
    print("ERROR: pdfplumber not installed. Run: pip install pdfplumber")
    sys.exit(1)


BO_RESULTS_DIR = Path(__file__).parent / "bo-results"
OUTPUT_DIR = Path(__file__).parent / "bo-results"

# Canonical district names and their known PDF text variants
DISTRICT_CANONICAL = {
    "Aniołki": ["Aniołki"],
    "Brętowo": ["Brętowo"],
    "Brzeźno": ["Brzeźno"],
    "Chełm": ["Chełm"],
    "Jasień": ["Jasień"],
    "Kokoszki": ["Kokoszki"],
    "Krakowiec-Górki Zachodnie": [
        "Krakowiec-Górki Zachodnie",
        "Krakowiec- Górki Zachodnie",
        "Krakowiec Górki Zachodnie",
    ],
    "Letnica": ["Letnica"],
    "Matarnia": ["Matarnia"],
    "Młyniska": ["Młyniska"],
    "Nowy Port": ["Nowy Port"],
    "Oliwa": ["Oliwa"],
    "Olszynka": ["Olszynka"],
    "Orunia-Św. Wojciech-Lipce": [
        "Orunia-Św. Wojciech-Lipce",
        "Orunia- Św. Wojciech- Lipce",
        "Orunia Św. Wojciech Lipce",
        "Orunia Św.Wojciech Lipce",
    ],
    "Orunia Górna-Gdańsk Południe": [
        "Orunia Górna-Gdańsk Południe",
        "Orunia Górna - Gdańsk Południe",
        "Orunia Górna Gdańsk Południe",
    ],
    "Osowa": ["Osowa"],
    "Piecki-Migowo": [
        "Piecki-Migowo",
        "Piecki- Migowo",
        "Piecki Migowo",
    ],
    "Przeróbka": ["Przeróbka"],
    "Przymorze Małe": ["Przymorze Małe"],
    "Przymorze Wielkie": ["Przymorze Wielkie"],
    "Rudniki": ["Rudniki"],
    "Siedlce": ["Siedlce"],
    "Stogi": ["Stogi"],
    "Strzyża": ["Strzyża"],
    "Suchanino": ["Suchanino"],
    "Śródmieście": ["Śródmieście"],
    "Ujeścisko-Łostowice": [
        "Ujeścisko-Łostowice",
        "Ujeścisko- Łostowice",
        "Ujeścisko Łostowice",
    ],
    "VII Dwór": ["VII Dwór"],
    "Wrzeszcz Dolny": ["Wrzeszcz Dolny"],
    "Wrzeszcz Górny": ["Wrzeszcz Górny"],
    "Wyspa Sobieszewska": ["Wyspa Sobieszewska"],
    "Wzgórze Mickiewicza": ["Wzgórze Mickiewicza"],
    "Zaspa Młyniec": ["Zaspa Młyniec"],
    "Zaspa Rozstaje": ["Zaspa Rozstaje"],
    "Żabianka-Wejhera-Jelitkowo-Tysiąclecia": [
        "Żabianka-Wejhera-Jelitkowo-Tysiąclecia",
        "Żabianka- Wejhera- Jelitkowo- Tysiąclecia",
        "Żabianka Wejhera Jelitkowo Tysiąclecia",
        "Żabianka Wejhera Jelitkowo- Tysiąclecia",
    ],
}

# Build reverse lookup: variant -> canonical
DISTRICT_LOOKUP = {}
for canonical, variants in DISTRICT_CANONICAL.items():
    for v in variants:
        DISTRICT_LOOKUP[v] = canonical


def normalize_district(name):
    """Normalize a district name to canonical form."""
    name = " ".join(name.split())
    return DISTRICT_LOOKUP.get(name, name)


def parse_amount(text):
    """Parse Polish formatted amount like '367 527,02 zł' or '367527 zł' to float."""
    if text is None:
        return None
    text = str(text).strip()
    text = text.replace("zł", "").strip()
    text = text.replace("\xa0", "").replace(" ", "")
    text = text.replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def parse_int_amount(text):
    """Parse amount like '365 906' (without zł) to int."""
    text = text.strip().replace("\xa0", "").replace(" ", "")
    try:
        return int(text)
    except ValueError:
        return None


# --------------------------------------------------------------------------- #
#  Page-level extraction helpers
# --------------------------------------------------------------------------- #

def get_non_table_text(page):
    """
    Extract text from a page excluding any table regions.
    Returns a single string of space-separated words.
    """
    tables = page.find_tables()
    table_bboxes = [t.bbox for t in tables]
    words = page.extract_words()

    def in_table(word):
        for tb in table_bboxes:
            if (word["x0"] >= tb[0] - 2 and word["x1"] <= tb[2] + 2
                    and word["top"] >= tb[1] - 2 and word["bottom"] <= tb[3] + 2):
                return True
        return False

    non_table_words = [w["text"] for w in words if not in_table(w)]
    return " ".join(non_table_words)


def extract_tables_from_page(page):
    """Extract all tables from a page as lists of [title, cost, votes] dicts."""
    raw_tables = page.extract_tables()
    result = []
    for raw in raw_tables:
        projects = []
        for row in raw:
            if not row or len(row) < 3:
                continue
            title, cost_str, votes_str = row[0], row[1], row[2]
            # Skip header row
            if title and title.strip().lower() == "tytuł":
                continue
            if not title or not cost_str or not votes_str:
                continue
            # Clean up multiline titles
            title = " ".join(title.replace("\n", " ").split())
            cost = parse_amount(cost_str)
            try:
                votes = int(votes_str.strip().replace(" ", ""))
            except (ValueError, AttributeError):
                continue
            if cost is not None and title:
                projects.append({
                    "title": title,
                    "cost": cost,
                    "votes": votes,
                })
        result.append(projects)
    return result


# --------------------------------------------------------------------------- #
#  Metadata parsing from non-table text
# --------------------------------------------------------------------------- #

# Pattern: numbers followed by "zł" in non-table text
AMOUNT_RE = re.compile(r'(\d[\d\s]*\d)\s*zł')


def parse_page_metadata(non_table_text):
    """
    Parse non-table text from a district/citywide page.
    Returns dict with: district, is_citywide, is_zbo, budget, carryover,
    zbo_budget, zbo_carryover.
    """
    meta = {
        "district": None,
        "is_citywide": False,
        "has_zbo": False,
        "budget": None,
        "carryover": None,
        "zbo_budget": None,
        "zbo_carryover": None,
    }

    text = non_table_text

    # Detect citywide
    if "PROJEKTY OGÓLNOMIEJSKIE" in text:
        meta["is_citywide"] = True

    # Detect ZBO section
    if "Zielony Budżet Obywatelski" in text:
        meta["has_zbo"] = True

    # Strip known prefixes to find district name
    # Non-table text pattern: "LISTA WYGRANYCH PROJEKTÓW {district} {budget} zł
    #   do następnej edycji przechodzi {carryover} zł
    #   [Zielony Budżet Obywatelski {zbo_budget} zł
    #   do następnej edycji przechodzi {zbo_carryover} zł]"

    # Remove "LISTA WYGRANYCH PROJEKTÓW" prefix
    cleaned = text.replace("LISTA WYGRANYCH PROJEKTÓW", "").strip()

    # For citywide pages, the structure is different
    if meta["is_citywide"]:
        # Citywide non-table text like:
        # "3 324 084 zł PROJEKTY OGÓLNOMIEJSKIE do następnej edycji przechodzi 2184 zł"
        # or "PROJEKTY OGÓLNOMIEJSKIE 1 431 981 zł ZIELONY BUDŻET OBYWATELSKI do..."
        _parse_citywide_meta(text, meta)
        return meta

    # For district pages, extract district name
    # The district name is everything before the first amount or "Zielony Budżet"
    # or "do następnej edycji"
    name_end_markers = ["Zielony Budżet", "do następnej edycji"]

    # First, try to find the district name by checking against known names
    district_found = _find_district_in_text(cleaned)
    if district_found:
        meta["district"] = district_found

    # Extract amounts - pattern: "{budget} zł do następnej edycji przechodzi {carryover} zł"
    # There may be two sets (BO + ZBO)
    amounts = list(AMOUNT_RE.finditer(text))

    if meta["has_zbo"]:
        # Split text at "Zielony Budżet Obywatelski"
        zbo_pos = text.index("Zielony Budżet Obywatelski")
        bo_text = text[:zbo_pos]
        zbo_text = text[zbo_pos:]

        # BO amounts
        bo_amounts = list(AMOUNT_RE.finditer(bo_text))
        if bo_amounts:
            meta["budget"] = parse_amount(bo_amounts[0].group(1) + " zł")
        carryover_match = re.search(r'przechodzi\s+(\d[\d\s]*\d)\s*zł', bo_text)
        if carryover_match:
            meta["carryover"] = parse_amount(carryover_match.group(1) + " zł")

        # ZBO amounts
        zbo_amounts = list(AMOUNT_RE.finditer(zbo_text))
        if zbo_amounts:
            meta["zbo_budget"] = parse_amount(zbo_amounts[0].group(1) + " zł")
        zbo_carryover_match = re.search(r'przechodzi\s+(\d[\d\s]*\d)\s*zł', zbo_text)
        if zbo_carryover_match:
            meta["zbo_carryover"] = parse_amount(zbo_carryover_match.group(1) + " zł")
    else:
        # Only BO section on this page
        if amounts:
            meta["budget"] = parse_amount(amounts[0].group(1) + " zł")
        carryover_match = re.search(r'przechodzi\s+(\d[\d\s]*\d)\s*zł', text)
        if carryover_match:
            meta["carryover"] = parse_amount(carryover_match.group(1) + " zł")

    return meta


def _find_district_in_text(text):
    """Find a known district name within text. Returns canonical name or None."""
    # Try longest variants first for greedy matching
    all_variants = sorted(DISTRICT_LOOKUP.keys(), key=len, reverse=True)
    for variant in all_variants:
        if variant in text:
            return DISTRICT_LOOKUP[variant]
    return None


def _parse_citywide_meta(text, meta):
    """Parse citywide page metadata."""
    # Check if this is a ZBO citywide page
    if "ZIELONY BUDŻET OBYWATELSKI" in text:
        meta["has_zbo"] = True
        # ZBO budget: "PROJEKTY OGÓLNOMIEJSKIE {amount} zł ZIELONY BUDŻET OBYWATELSKI"
        zbo_budget_match = re.search(
            r'PROJEKTY OGÓLNOMIEJSKIE\s+(\d[\d\s]*\d)\s*zł\s+ZIELONY BUDŻET OBYWATELSKI',
            text
        )
        if zbo_budget_match:
            meta["zbo_budget"] = parse_amount(zbo_budget_match.group(1) + " zł")
        carryover_match = re.search(r'przechodzi\s+(\d[\d\s]*\d)\s*zł', text)
        if carryover_match:
            meta["zbo_carryover"] = parse_amount(carryover_match.group(1) + " zł")
    else:
        # Regular BO citywide page
        # Budget is first amount in text
        amounts = list(AMOUNT_RE.finditer(text))
        if amounts:
            meta["budget"] = parse_amount(amounts[0].group(1) + " zł")
        carryover_match = re.search(r'przechodzi\s+(\d[\d\s]*\d)\s*zł', text)
        if carryover_match:
            meta["carryover"] = parse_amount(carryover_match.group(1) + " zł")


# --------------------------------------------------------------------------- #
#  General stats parsing (pages 1-4)
# --------------------------------------------------------------------------- #

def parse_general_stats(pdf):
    """Parse first few pages for general voting statistics."""
    stats = {}

    # Page 2 (index 1): voting period, number of voters
    if len(pdf.pages) > 1:
        p2_text = get_non_table_text(pdf.pages[1])

        period_match = re.search(r'od\s+(.+?\d{4})', p2_text)
        if period_match:
            stats["voting_period"] = " ".join(period_match.group(0).split())

        voters_match = re.search(r'(\d[\d\s]*\d)\s*osób', p2_text)
        if voters_match:
            stats["total_voters"] = parse_int_amount(voters_match.group(1))

        women_match = re.search(r'(\d[\d\s]*\d)\s*kobiet', p2_text)
        men_match = re.search(r'(\d[\d\s]*\d)\s*mężczyzn', p2_text)
        if women_match:
            stats["women_voters"] = parse_int_amount(women_match.group(1))
        if men_match:
            stats["men_voters"] = parse_int_amount(men_match.group(1))

    # Page 3 (index 2): turnout, projects count, top districts
    if len(pdf.pages) > 2:
        p3_text = get_non_table_text(pdf.pages[2])

        turnout_match = re.search(r'(\d+[,.]\d+)\s*%', p3_text)
        if turnout_match:
            stats["turnout_percent"] = float(turnout_match.group(1).replace(",", "."))

        projects_match = re.search(r'(\d+)\s*projektów', p3_text)
        if projects_match:
            stats["total_projects_voted_on"] = int(projects_match.group(1))

        # Top districts by turnout
        top_districts = []
        for m in re.finditer(r'([A-ZĄĆĘŁŃÓŚŹŻ][a-ząćęłńóśźż\s\-–]+?)\s*[–-]\s*(\d+[,.]\d+)\s*%', p3_text):
            name = m.group(1).strip()
            pct = float(m.group(2).replace(",", "."))
            top_districts.append({"district": name, "turnout_percent": pct})
        if top_districts:
            stats["top_turnout_districts"] = top_districts

    # Page 4 (index 3): budget summary (not present in 2026)
    if len(pdf.pages) > 3:
        p4_text = pdf.pages[3].extract_text() or ""
        if "kwota przeznaczona" in p4_text.lower() or (
            "projekty dzielnicowe" in p4_text.lower() and "LISTA WYGRANYCH" not in p4_text
        ):
            total_match = re.search(r'^(\d[\d\s]*\d)\s*zł\s*$', p4_text, re.MULTILINE)
            if total_match:
                stats["total_budget"] = parse_amount(total_match.group(1) + " zł")

    return stats


# --------------------------------------------------------------------------- #
#  Main parsing: iterate pages, extract tables + metadata
# --------------------------------------------------------------------------- #

def determine_winners(projects, budget):
    """
    Given a list of projects sorted by votes (descending) and a budget,
    mark which projects won (fit within budget).
    Projects must be pre-sorted by votes descending (as they appear in PDF).
    Per BO regulations, a project needs at least 100 votes to be eligible.
    """
    MIN_VOTES = 100

    if budget is None or budget <= 0:
        # Can't determine winners without budget
        for p in projects:
            p["won"] = False
        return projects

    remaining = budget
    for p in projects:
        cost = p.get("cost", 0)
        votes = p.get("votes", 0)
        if votes >= MIN_VOTES and cost <= remaining:
            p["won"] = True
            remaining -= cost
        else:
            p["won"] = False

    return projects


def _fill_carryover(data):
    """
    Fill in missing carryover values by computing budget - sum(won costs).
    The PDF omits the carryover line when it would be 0 zł.
    """
    for suffix in ("bo", "zbo"):
        budget_key = f"budget_{suffix}"
        carry_key = f"carryover_{suffix}"
        projects_key = f"projects_{suffix}"
        budget = data.get(budget_key)
        if budget is not None and data.get(carry_key) is None:
            won_cost = sum(p["cost"] for p in data.get(projects_key, []) if p.get("won"))
            data[carry_key] = round(budget - won_cost, 2)


def parse_single_pdf(pdf_path, year):
    """Parse a single BO results PDF into structured data."""
    print(f"  Parsing {pdf_path.name}...")

    with pdfplumber.open(pdf_path) as pdf:
        # 1. General statistics from first pages
        stats = parse_general_stats(pdf)
        stats["year"] = year

        # 2. Process each page with tables
        districts = {}
        citywide = {
            "budget_bo": None, "budget_zbo": None,
            "carryover_bo": None, "carryover_zbo": None,
            "projects_bo": [], "projects_zbo": [],
        }

        for page_idx, page in enumerate(pdf.pages):
            tables = page.find_tables()
            if not tables:
                continue  # Skip pages without tables (stats pages, empty last page)

            # Get metadata from non-table text
            non_table_text = get_non_table_text(page)
            meta = parse_page_metadata(non_table_text)

            # Get project data from tables
            table_data = extract_tables_from_page(page)

            if meta["is_citywide"]:
                # Citywide page
                _process_citywide_page(citywide, meta, table_data)
            else:
                # District page
                _process_district_page(districts, meta, table_data)

        # 3. Determine winners
        for name, data in districts.items():
            data["projects_bo"] = determine_winners(data["projects_bo"], data["budget_bo"])
            data["projects_zbo"] = determine_winners(data["projects_zbo"], data["budget_zbo"])

        citywide["projects_bo"] = determine_winners(citywide["projects_bo"], citywide["budget_bo"])
        citywide["projects_zbo"] = determine_winners(citywide["projects_zbo"], citywide["budget_zbo"])

        # 4. Fill in missing carryover values (PDF omits "przechodzi 0 zł")
        for name, data in districts.items():
            _fill_carryover(data)
        _fill_carryover(citywide)

    return {
        "year": year,
        "stats": stats,
        "districts": districts,
        "citywide": citywide,
    }


def _ensure_district(districts, name):
    """Ensure a district entry exists."""
    if name not in districts:
        districts[name] = {
            "budget_bo": None, "budget_zbo": None,
            "carryover_bo": None, "carryover_zbo": None,
            "projects_bo": [], "projects_zbo": [],
        }
    return districts[name]


def _process_district_page(districts, meta, table_data):
    """Process a single district page's data."""
    district_name = meta.get("district")
    if not district_name:
        print(f"    WARNING: Could not identify district on page")
        return

    d = _ensure_district(districts, district_name)

    if meta["has_zbo"]:
        if len(table_data) >= 2:
            # Page has both BO and ZBO sections
            # Table 0 = BO projects, Table 1 = ZBO projects
            d["projects_bo"].extend(table_data[0])
            d["projects_zbo"].extend(table_data[1])
        elif len(table_data) == 1:
            # has_zbo=True but only 1 table -> ZBO-only page
            # (the BO section for this district was on a previous page)
            d["projects_zbo"].extend(table_data[0])

        # BO metadata
        if meta["budget"] is not None:
            d["budget_bo"] = meta["budget"]
        if meta["carryover"] is not None:
            d["carryover_bo"] = meta["carryover"]
        # ZBO metadata
        if meta["zbo_budget"] is not None:
            d["budget_zbo"] = meta["zbo_budget"]
        if meta["zbo_carryover"] is not None:
            d["carryover_zbo"] = meta["zbo_carryover"]
    else:
        # Page has only one section - could be BO-only or ZBO-only
        # Need to determine which: check if the non-table text has ZBO marker
        # or if the page is a ZBO continuation

        # Check if this is a ZBO-only page (no "Zielony Budżet" text but
        # the previous page for this district had BO already done)
        # Simpler heuristic: if there's no budget in meta and the district
        # already has a budget_bo set, this might be a BO continuation page.

        # Actually, the structure is clear from the non-table text:
        # - If "Zielony Budżet Obywatelski" appears, it's a ZBO page
        # - Otherwise it's a BO page
        # BUT: has_zbo=True means the page HAS the ZBO marker AND the page
        # has 2 tables. A page with has_zbo=False and 1 table is BO-only.
        # However, a page that is ZBO-only (no BO section) would have
        # "Zielony Budżet Obywatelski" in non-table text AND 1 table.
        # We handled has_zbo=True above, but what about ZBO-only pages?

        # Re-check: has_zbo checks for "Zielony Budżet Obywatelski" in
        # non-table text. If it's present with 1 table, that table is ZBO.
        # If it's absent with 1 table, that table is BO.

        # Wait - we already checked has_zbo above, so this branch means
        # has_zbo=False -> this is a BO-only page, all tables are BO.
        if len(table_data) >= 1:
            d["projects_bo"].extend(table_data[0])
        if meta["budget"] is not None:
            d["budget_bo"] = meta["budget"]
        if meta["carryover"] is not None:
            d["carryover_bo"] = meta["carryover"]


def _process_citywide_page(citywide, meta, table_data):
    """Process a single citywide page's data."""
    if meta.get("has_zbo") or "ZIELONY BUDŻET OBYWATELSKI" in str(meta):
        # ZBO citywide page
        if len(table_data) >= 1:
            citywide["projects_zbo"].extend(table_data[0])
        if meta["zbo_budget"] is not None:
            citywide["budget_zbo"] = meta["zbo_budget"]
        if meta["zbo_carryover"] is not None:
            citywide["carryover_zbo"] = meta["zbo_carryover"]
    else:
        # BO citywide page
        if len(table_data) >= 1:
            citywide["projects_bo"].extend(table_data[0])
        if meta["budget"] is not None:
            citywide["budget_bo"] = meta["budget"]
        if meta["carryover"] is not None:
            citywide["carryover_bo"] = meta["carryover"]


# --------------------------------------------------------------------------- #
#  Validation & output
# --------------------------------------------------------------------------- #

def validate_result(result):
    """Print validation summary for a parsed result."""
    year = result["year"]
    stats = result["stats"]
    districts = result["districts"]
    citywide = result["citywide"]

    total_projects = sum(
        len(d["projects_bo"]) + len(d["projects_zbo"])
        for d in districts.values()
    ) + len(citywide["projects_bo"]) + len(citywide["projects_zbo"])

    print(f"\n  BO {year}:")
    print(f"    Voters: {stats.get('total_voters', '?')}, Turnout: {stats.get('turnout_percent', '?')}%")
    print(f"    Total projects parsed: {total_projects}"
          f" (expected: {stats.get('total_projects_voted_on', '?')})")
    print(f"    Districts found: {len(districts)}")
    for name in sorted(districts.keys()):
        d = districts[name]
        bo_count = len(d["projects_bo"])
        zbo_count = len(d["projects_zbo"])
        bo_won = sum(1 for p in d["projects_bo"] if p.get("won"))
        zbo_won = sum(1 for p in d["projects_zbo"] if p.get("won"))
        budget_bo = d.get("budget_bo") or 0
        budget_zbo = d.get("budget_zbo") or 0
        carryover_bo = d.get("carryover_bo")
        carryover_zbo = d.get("carryover_zbo")
        print(f"    {name:42s} BO: {bo_won:>2}/{bo_count:<3} budget={budget_bo:>12,.0f} carry={str(carryover_bo):>10}"
              f"  ZBO: {zbo_won:>2}/{zbo_count:<3} budget={budget_zbo:>10,.0f} carry={str(carryover_zbo):>10}")

    # Citywide
    cw_bo = len(citywide["projects_bo"])
    cw_zbo = len(citywide["projects_zbo"])
    cw_bo_won = sum(1 for p in citywide["projects_bo"] if p.get("won"))
    cw_zbo_won = sum(1 for p in citywide["projects_zbo"] if p.get("won"))
    print(f"    {'Ogólnomiejski':42s} BO: {cw_bo_won:>2}/{cw_bo:<3} budget={citywide.get('budget_bo') or 0:>12,.0f}"
          f"  ZBO: {cw_zbo_won:>2}/{cw_zbo:<3} budget={citywide.get('budget_zbo') or 0:>10,.0f}")


def main():
    OUTPUT_DIR.mkdir(exist_ok=True)

    all_results = {}
    for year in [2022, 2023, 2024, 2025, 2026]:
        pdf_path = BO_RESULTS_DIR / f"bo-{year}.pdf"
        if not pdf_path.exists():
            print(f"  WARNING: {pdf_path} not found, skipping")
            continue

        result = parse_single_pdf(pdf_path, year)
        all_results[str(year)] = result
        validate_result(result)

    # Save combined JSON
    out_path = OUTPUT_DIR / "bo-results.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)
    print(f"\nSaved combined results to {out_path}")

    # Also save per-year JSONs
    for year_str, result in all_results.items():
        year_path = OUTPUT_DIR / f"bo-{year_str}-parsed.json"
        with open(year_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"Saved {year_path}")


if __name__ == "__main__":
    main()
