# Gdańsk BO 2027 — district & win-probability tracker

**Turns five years of participatory-budget PDFs into "submit here, ask for about this much."**

Gdańsk runs an annual participatory budget (Budżet Obywatelski): residents submit project proposals, other residents vote, and each district gets a fixed pool of money to fund whichever proposals get enough votes to fit the budget, ranked by vote count. Budget remaining per district is public but not obvious at a glance, and nobody publishes win odds. This started as a way to answer both questions for real — I'm currently tracking around a dozen disc-golf-course proposals I've submitted across multiple districts this cycle, and needed to know where the money still is and how big to make each ask.

## How it works

1. **Scrapes the live listing.** [`scrape_projects.py`](scrape_projects.py) pulls every submitted project from bo.gdansk.pl — a quirky government CMS with POST-paginated listings and per-project detail pages — using nothing but `urllib` and a hand-rolled `HTMLParser` subclass (no BeautifulSoup). Pulls full structured data per project: cost breakdown table, category, description, and GPS coordinates parsed out of an embedded GeoJSON blob. Re-run hourly by cron.
2. **Parses five years of official results PDFs.** [`parse_bo_results.py`](parse_bo_results.py) uses `pdfplumber` to pull per-district project tables (title/cost/votes) out of `bo-2022.pdf` through `bo-2026.pdf`, then reconstructs the actual winner-determination rule from the regulations (projects need ≥100 votes, funded by vote rank until the district budget runs out) to mark winners project-by-project. Handles ~10 different spelling variants of the same district names across years of inconsistent PDF formatting, and fills in "carryover" amounts the PDF only prints when non-zero.
3. **Fits a per-district statistical model.** [`recalibrate_mc_params.py`](recalibrate_mc_params.py) regresses `ln(votes) ~ baseMu + 0.7·ln(cost/budget)` separately for every district from the 1,623 historical project results this produces, because voting behavior varies a lot district to district — some districts have far more predictable (low-variance) turnout than others.
4. **Two independent win estimates, not one.** For any hypothetical project cost, `tracker.html` computes:
   - **A guaranteed threshold** — a 0/1-knapsack DP (`maxSubsetSum`) finds the worst-case combination of competing projects' costs that still fits inside the district budget. Below that threshold, your project mathematically cannot lose, regardless of how votes fall.
   - **A win-probability curve** — a from-scratch Box–Muller Monte Carlo simulation (run across a small Web Worker pool, 10k iterations) samples competitor vote counts from the fitted per-district distribution, with an 8% "chaos" injection rate to account for real-world unpredictability the regression can't capture.
5. **Tracks the competition, not just the odds.** [`diff_projects.py`](diff_projects.py) and [`extract_tracked.py`](extract_tracked.py) watch specifically the districts I've submitted projects in, flagging new or withdrawn competing proposals since the last check.

## Dashboards

- `index.html` — current-cycle district budgets sorted by what's left, with a submission recommendation.
- `tracker.html` — per-project guaranteed-win threshold + Monte Carlo win-probability chart.
- `history.html` — multi-year (2022–2026) trends across all districts.

## Stack

Python (stdlib `urllib`/`html.parser` for scraping, `pdfplumber` for PDF tables) for the data pipeline. Static HTML/JS dashboards — vanilla Canvas rendering, Web Workers for simulation — no framework, no backend, no build step.

## Live

https://nicofisi.github.io/gdansk-bo-2027-stats
