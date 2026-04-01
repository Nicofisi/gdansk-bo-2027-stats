#!/usr/bin/env python3
"""
Scrape all BO 2027 projects from bo.gdansk.pl
Fetches the listing page (all projects in one request), then each project detail page.
Saves to data/projects.json

Re-run anytime to refresh with newly submitted projects.
"""

import json
import re
import sys
import time
import urllib.request
import urllib.parse
from html.parser import HTMLParser
from pathlib import Path
from typing import Optional


DATA_DIR = Path(__file__).parent / "data"

LIST_URL = "https://bo.gdansk.pl/index.php?RewriteUrlDir=&RewriteFriendlyLinks=lista-zgloszonych-projektow&RewriteController=html"
BASE_URL = "https://bo.gdansk.pl"

# POST data to get all projects on one page
LIST_POST_DATA = urllib.parse.urlencode({
    "WE[search-panel][active-id]": "1110",
    "WE[search-panel][1110][per-page]": "1000",
    "WE[search-panel][1110][sort-field]": "[950][1401998439][VALUE]",
    "WE[search-panel][1110][sort-order]": "ASC",
    "WE[search-panel][1110][page-current]": "0",
}).encode("utf-8")

HEADERS = {"User-Agent": "Mozilla/5.0"}


def fetch(url: str, post_data: Optional[bytes] = None) -> str:
    """Fetch a URL, return decoded HTML."""
    req = urllib.request.Request(url, data=post_data, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8")


def get_project_urls() -> list[str]:
    """Get all project detail URLs from the listing page."""
    html = fetch(LIST_URL, LIST_POST_DATA)
    urls = list(set(re.findall(r'href="(/szczegoly-projektu[^"]+)"', html)))
    urls.sort()
    return urls


def parse_amount_from_table(text: str) -> float:
    """Parse '327 790.00 zł' to float."""
    text = text.replace("zł", "").replace("\xa0", "").strip()
    text = text.replace(" ", "")
    text = text.replace(",", ".")
    return float(text)


class ProjectDetailParser(HTMLParser):
    """Extract structured data from a project detail page."""

    # Fields we look for (label text -> key name)
    FIELD_MAP = {
        "TYTUŁ PROJEKTU:": "title",
        "RODZAJ / KATEGORIA:": "category",
        "KATEGORIE PROJEKTU:": "project_categories",
        "KRÓTKI OPIS PROJEKTU:": "short_description",
        "OPIS PROJEKTU:": "description",
        "PROJEKTOWANIE UNIWERSALNE:": "universal_design",
        "KOSZT UTRZYMANIA PROJEKTU W KOLEJNYCH LATACH:": "maintenance_cost",
    }

    def __init__(self):
        super().__init__()
        self.data = {}
        self.current_field = None
        self.capture_text = False
        self.captured = ""
        self.in_cost_table = False
        self.cost_rows = []
        self.current_row = []
        self.in_td = False
        self.td_text = ""
        self.scope_items = []
        self.in_scope = False
        self.in_li = False
        self.li_text = ""
        # Map coordinates
        self.lat = None
        self.lon = None
        # Track title-box-red-mini for field detection
        self.last_label = None
        self.in_label = False
        self.label_text = ""
        # Cost table detection
        self.tables_seen = 0
        self.in_main_col = False
        self.div_depth = 0

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        cls = attrs_dict.get("class") or ""

        # Detect the main left column (col-12 col-lg-7)
        if tag == "div" and "col-12" in cls and "col-lg-7" in cls:
            self.in_main_col = True

        # Detect field labels
        if "title-box-red-mini" in cls:
            self.in_label = True
            self.label_text = ""

        # After a label, capture the next <p> content
        if tag == "p" and self.last_label and self.last_label in self.FIELD_MAP:
            self.current_field = self.FIELD_MAP[self.last_label]
            self.capture_text = True
            self.captured = ""
            self.last_label = None

        # Detect scope list (ZAKRES RZECZOWY)
        if tag == "ol" and self.last_label and "ZAKRES RZECZOWY" in (self.last_label or ""):
            self.in_scope = True
            self.scope_items = []
            self.last_label = None
        if self.in_scope and tag == "li":
            self.in_li = True
            self.li_text = ""

        # Detect cost table (SZACOWANY KOSZT)
        if tag == "table" and self.in_main_col:
            self.tables_seen += 1
            if self.tables_seen == 1:
                self.in_cost_table = True
                self.cost_rows = []
        if self.in_cost_table and tag == "tr":
            self.current_row = []
        if self.in_cost_table and tag == "td":
            self.in_td = True
            self.td_text = ""

        # Map coordinates from GeoJSON
        if tag == "div" and "we-mapcreator" in cls:
            geojson_str = attrs_dict.get("data-mapediting-geojson-object", "")
            if geojson_str:
                try:
                    geo = json.loads(geojson_str)
                    coords = geo["features"][0]["geometry"]["coordinates"]
                    self.lon = coords[0]
                    self.lat = coords[1]
                except (json.JSONDecodeError, KeyError, IndexError):
                    pass

    def handle_endtag(self, tag):
        if self.in_label and tag == "p":
            self.in_label = False
            self.last_label = self.label_text.strip()

        if self.capture_text and tag == "p":
            self.capture_text = False
            if self.current_field:
                self.data[self.current_field] = self.captured.strip()
                self.current_field = None

        if self.in_li and tag == "li":
            self.in_li = False
            text = self.li_text.strip()
            if text:
                self.scope_items.append(text)

        if self.in_scope and tag == "ol":
            self.in_scope = False
            self.data["scope"] = self.scope_items

        if self.in_td and tag == "td":
            self.in_td = False
            self.current_row.append(self.td_text.strip())
        if self.in_cost_table and tag == "tr" and self.current_row:
            self.cost_rows.append(self.current_row)
        if self.in_cost_table and tag == "table":
            self.in_cost_table = False

    def handle_data(self, data):
        if self.in_label:
            self.label_text += data
        if self.capture_text:
            self.captured += data
        if self.in_li:
            self.li_text += data
        if self.in_td:
            self.td_text += data

    def get_result(self) -> dict:
        result = dict(self.data)

        # Parse cost from table
        if self.cost_rows:
            total_cost = None
            cost_items = []
            for row in self.cost_rows[1:]:  # skip header
                if len(row) >= 2:
                    label = row[0].strip()
                    try:
                        amount = parse_amount_from_table(row[1])
                    except (ValueError, IndexError):
                        continue
                    if "ŁĄCZNIE" in label.upper() or "łącznie" in label.lower():
                        total_cost = amount
                    else:
                        cost_items.append({"name": label, "amount": amount})
            result["cost_items"] = cost_items
            result["total_cost"] = total_cost

        if self.lat is not None:
            result["lat"] = self.lat
            result["lon"] = self.lon

        return result


def parse_category(category_str: str) -> dict:
    """Parse 'Budżet Obywatelski / Dzielnicowy - Wzgórze Mickiewicza' into components."""
    info = {}
    if "/" in category_str:
        parts = category_str.split("/", 1)
        budget_type = parts[0].strip()
        scope = parts[1].strip()
    else:
        budget_type = category_str.strip()
        scope = ""

    info["budget_type"] = budget_type  # "Budżet Obywatelski" or "Zielony Budżet Obywatelski"
    info["is_green"] = "Zielony" in budget_type

    if "Ogólnomiejski" in scope:
        info["scope"] = "Ogólnomiejski"
        info["district"] = "Ogólnomiejski"
    elif "Dzielnicowy" in scope:
        info["scope"] = "Dzielnicowy"
        district = scope.replace("Dzielnicowy", "").strip().lstrip("-").strip()
        info["district"] = district
    else:
        info["scope"] = scope
        info["district"] = scope

    return info


def scrape_project(url: str) -> dict:
    """Scrape a single project detail page."""
    html = fetch(BASE_URL + url)
    parser = ProjectDetailParser()
    parser.feed(html)
    result = parser.get_result()
    result["url"] = BASE_URL + url

    # Parse category into structured fields
    if "category" in result:
        cat_info = parse_category(result["category"])
        result.update(cat_info)

    return result


def main():
    DATA_DIR.mkdir(exist_ok=True)

    print("Fetching project listing...")
    urls = get_project_urls()
    print(f"Found {len(urls)} projects")

    # Load existing data if any (for incremental updates)
    out_path = DATA_DIR / "projects.json"
    existing = {}
    if out_path.exists():
        with open(out_path, encoding="utf-8") as f:
            for p in json.load(f):
                existing[p["url"]] = p

    projects = []
    new_count = 0
    for i, url in enumerate(urls, 1):
        full_url = BASE_URL + url
        if full_url in existing:
            projects.append(existing[full_url])
            print(f"  [{i}/{len(urls)}] cached: {existing[full_url].get('title', url)[:60]}")
            continue

        print(f"  [{i}/{len(urls)}] scraping: {url[:70]}...")
        try:
            project = scrape_project(url)
            projects.append(project)
            new_count += 1
        except Exception as e:
            print(f"    ERROR: {e}")
            projects.append({"url": full_url, "error": str(e)})

        # Be polite
        if i < len(urls):
            time.sleep(0.3)

    # Assign sequential number based on URL ID order (lower ID = earlier submission)
    def url_sort_key(p):
        m = re.search(r'szczegoly-projektu-\d+-(\d+)', p.get("url", ""))
        return int(m.group(1)) if m else 0

    projects.sort(key=url_sort_key)
    for i, p in enumerate(projects, 1):
        p["seq"] = i

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(projects, f, ensure_ascii=False, indent=2)

    # Save metadata with timestamp
    import datetime
    meta_path = DATA_DIR / "meta.json"
    meta = {}
    if meta_path.exists():
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
    meta["last_updated"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    meta["project_count"] = len(projects)
    meta["refresh_interval_hours"] = 5 / 60  # every 5 minutes
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    print(f"\nSaved {len(projects)} projects to {out_path} ({new_count} newly scraped)")

    # Quick summary
    districts = {}
    for p in projects:
        d = p.get("district", "???")
        districts[d] = districts.get(d, 0) + 1
    print(f"\nProjects per district:")
    for d in sorted(districts.keys()):
        print(f"  {d}: {districts[d]}")


if __name__ == "__main__":
    main()
