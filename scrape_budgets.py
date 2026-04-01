#!/usr/bin/env python3
"""
Scrape district budget allocations for BO 2027 from gdansk.pl
Saves to data/budgets.json
"""

import json
import re
import urllib.request
from html.parser import HTMLParser
from pathlib import Path


class BudgetTableParser(HTMLParser):
    """Parse the budget table from the article page."""

    def __init__(self):
        super().__init__()
        self.in_article = False
        self.in_table = False
        self.in_row = False
        self.in_cell = False
        self.current_row = []
        self.current_cell = ""
        self.rows = []
        self.table_count = 0

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag == "div" and "article-content" in (attrs_dict.get("class") or ""):
            self.in_article = True
        if self.in_article and tag == "table":
            self.table_count += 1
            if self.table_count == 1:  # first table in article = budget table
                self.in_table = True
        if self.in_table and tag == "tr":
            self.in_row = True
            self.current_row = []
        if self.in_row and tag == "td":
            self.in_cell = True
            self.current_cell = ""

    def handle_endtag(self, tag):
        if self.in_cell and tag == "td":
            self.in_cell = False
            self.current_row.append(self.current_cell.strip())
        if self.in_row and tag == "tr":
            self.in_row = False
            if self.current_row:
                self.rows.append(self.current_row)
        if self.in_table and tag == "table":
            self.in_table = False

    def handle_data(self, data):
        if self.in_cell:
            self.current_cell += data


def parse_amount(text: str) -> float:
    """Parse Polish formatted amount like '367 527,02 zł' to float."""
    text = text.strip()
    text = text.replace("zł", "").strip()
    text = text.replace("\xa0", "").replace(" ", "")
    text = text.replace(",", ".")
    return float(text)


def main():
    url = "https://www.gdansk.pl/budzet-obywatelski/Kwoty-BO-2027-r,a,305711"
    print(f"Fetching {url} ...")

    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req) as resp:
        html = resp.read().decode("utf-8")

    parser = BudgetTableParser()
    parser.feed(html)

    # First row is header, last row is "Suma"
    districts = {}
    for row in parser.rows[1:]:  # skip header
        if len(row) < 3:
            continue
        name = row[0].strip()
        if name.lower() == "suma":
            continue
        try:
            bo = parse_amount(row[1])
            zbo = parse_amount(row[2])
        except (ValueError, IndexError):
            print(f"  WARNING: Could not parse row: {row}")
            continue
        districts[name] = {
            "budget_bo": bo,
            "budget_zbo": zbo,
            "budget_total": round(bo + zbo, 2),
        }

    # Also scrape the ogolnomiejski budgets from the text above the table.
    # The HTML has: <u>6 070 982,40&nbsp;</u><u>zł </u> na projekty ogólnomiejskie
    # NOTE: this amount is the TOTAL for ogólnomiejskie (BO + ZBO combined).
    # budget_bo = total - zbo (the non-green portion only).
    ogolno_total_match = re.search(
        r"([\d][\d\s]*[\d][,.][\d]+)\s*(?:&nbsp;)?\s*(?:</u>\s*<u>)?\s*zł\s*(?:</u>)?\s*(?:</strong>)?\s*na projekty og",
        html,
    )
    ogolno_zbo_match = re.search(
        r"projekty og[óo]lnomiejskie Zielonego.*?([\d][\d\s]*[\d][,.][\d]+)\s*(?:&nbsp;)?\s*(?:<[^>]*>\s*)*zł",
        html, re.DOTALL,
    )

    ogolno = {}
    ogolno_total = 0
    if ogolno_total_match:
        ogolno_total = parse_amount(ogolno_total_match.group(1))
    if ogolno_zbo_match:
        ogolno["budget_zbo"] = parse_amount(ogolno_zbo_match.group(1))
    if ogolno_total > 0:
        ogolno["budget_bo"] = round(ogolno_total - ogolno.get("budget_zbo", 0), 2)
        ogolno["budget_total"] = ogolno_total
    districts["Ogólnomiejski"] = ogolno

    out_path = Path(__file__).parent / "data" / "budgets.json"
    out_path.parent.mkdir(exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(districts, f, ensure_ascii=False, indent=2)

    print(f"Saved {len(districts)} districts to {out_path}")
    for name, b in districts.items():
        print(f"  {name}: BO={b.get('budget_bo',0):,.2f} ZBO={b.get('budget_zbo',0):,.2f}")

    # ── Sanity checks ────────────────────────────────────────────────────
    # After ANY change to scraping logic, verify these invariants hold.
    # Reference: https://www.gdansk.pl/budzet-obywatelski/Kwoty-BO-2027-r,a,305711
    #
    # 1. For every entry: budget_bo + budget_zbo == budget_total  (to the grosz)
    # 2. Sum of all DISTRICT budget_bo  == 20_382_038.48  (website table "Suma" col 1)
    # 3. Sum of all DISTRICT budget_zbo ==  5_206_485.12  (website table "Suma" col 2)
    # 4. Sum of all DISTRICT budget_total == 25_588_523.60 (website table "Suma" col 3)
    # 5. Ogólnomiejski budget_total       ==  6_070_982.40 (text above table)
    # 6. Ogólnomiejski budget_zbo         ==  1_852_368.42 (text: "w tym ZBO")
    # 7. Ogólnomiejski budget_bo          ==  4_218_613.98 (= total - zbo, NOT 6.07M!)
    # 8. Grand total (all entries)        == 31_659_506.00 (website headline)
    #
    # Common pitfall: the "6 070 982,40 zł na projekty ogólnomiejskie" line is the
    # COMBINED BO+ZBO total, not the BO-only portion. budget_bo must subtract ZBO.
    errors = []
    for name, b in districts.items():
        calc = round(b.get("budget_bo", 0) + b.get("budget_zbo", 0), 2)
        if abs(calc - b.get("budget_total", 0)) > 0.02:
            errors.append(f"{name}: bo+zbo={calc} != total={b.get('budget_total')}")
    dist_only = {k: v for k, v in districts.items() if k != "Ogólnomiejski"}
    sbo = round(sum(v["budget_bo"] for v in dist_only.values()), 2)
    szbo = round(sum(v["budget_zbo"] for v in dist_only.values()), 2)
    stot = round(sum(v["budget_total"] for v in dist_only.values()), 2)
    if abs(sbo - 20_382_038.48) > 0.10:
        errors.append(f"District BO sum {sbo} != 20382038.48")
    if abs(szbo - 5_206_485.12) > 0.10:
        errors.append(f"District ZBO sum {szbo} != 5206485.12")
    if abs(stot - 25_588_523.60) > 0.10:
        errors.append(f"District total sum {stot} != 25588523.60")
    grand = round(sum(v["budget_total"] for v in districts.values()), 2)
    if abs(grand - 31_659_506.00) > 1.00:
        errors.append(f"Grand total {grand} != 31659506.00")
    if errors:
        print("\n  !!! SANITY CHECK FAILURES !!!")
        for e in errors:
            print(f"  {e}")
    else:
        print("  Sanity checks passed (sums match website).")


if __name__ == "__main__":
    main()
