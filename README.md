# MGC Developments — AI Developer & Engineer Assessment

Local Python toolkit that helps MGC sales staff (1) answer project questions grounded in the three supplied documents, and (2) prioritise which new leads to call first.

**Deadline reminder (from BRIEF):** Wednesday 14 October, 3:00 PM PKT — submit a public GitHub repo link.

## Architecture

```
docs/*.md  ──►  app/knowledge_base.py + app/pricing.py
                      │
                      ▼
              app/document_assistant.py  ──►  POST /ask
                      │
leads.csv ──► scripts/train_model.py ──► models/lead_scoring_model.joblib
                      │                         │
                      ▼                         ▼
              app/lead_scoring.py  ────────►  POST /score
                      │
                      ▼
                   run.py  (Flask: GET /, /health)
```

| Part | What | Key files |
|---|---|---|
| 1 | Document Q&A + Decimal pricing | `app/document_assistant.py`, `app/pricing.py`, `app/knowledge_base.py` |
| 2 | SQL schema + 3 queries | `schema.sql`, `queries.sql`, `scripts/validate_part2.py` |
| 3 | Intake-time conversion model | `app/lead_scoring.py`, `scripts/train_model.py`, `models/`, `reports/` |
| 4 | Minimal web UI | `run.py`, `templates/index.html` |

No external LLM API. Pricing math is deterministic Python `Decimal`. Paths are resolved from the project root (portable).

## Prerequisites

- Python 3.10+ (tested on 3.14)
- pip
- Optional: `sqlite3` CLI (validation also works via the Python script)

## Setup

```bash
cd mgc-task-pack
pip install -r requirements.txt
```

Do **not** modify `BRIEF.md`, `docs/`, or `leads.csv`.

## Part 2 — Import data & run SQL

```bash
python scripts/validate_part2.py
```

This creates a fresh `data/leads.db` from `schema.sql` + `leads.csv`, then runs the three statements in `queries.sql`.

**Manual alternative (if `sqlite3` CLI is installed):**

```bash
python scripts/validate_part2.py   # preferred reproducible path
# or: create DB yourself, then open queries.sql in any SQLite client
```

**Conversion rate convention:** fraction in `[0, 1]` (`conversions / total_leads`), not a percentage.

### Duplicate analysis (measured)

| Metric | Value |
|---|---|
| CSV rows | 9,160 |
| Distinct `crm_record_hash` | 9,000 |
| Duplicate groups | **160** |
| Rows in those groups | **320** |
| Query 2 canonical winners | **160** (0 of them use the `-B` suffix) |

Winner rule: earliest `created_at`, then lexicographically smallest `lead_id`. Future prevention: commented `UNIQUE(crm_record_hash)` in `schema.sql` (not enforced on the dirty load table).

### Query 1 — source conversion (≥ 200 leads)

| source | total_leads | conversions | conversion_rate |
|---|---:|---:|---:|
| Referral | 730 | 95 | 0.1301 |
| Walk-in | 610 | 63 | 0.1033 |
| Facebook Ads | 2366 | 160 | 0.0676 |
| Google Search | 1460 | 96 | 0.0658 |
| WhatsApp Campaign | 548 | 35 | 0.0639 |
| Property Portal | 1812 | 108 | 0.0596 |
| Instagram | 1007 | 55 | 0.0546 |
| Billboard | 282 | 12 | 0.0426 |
| Expo Stall | 345 | 10 | 0.0290 |

### Query 3 — city conversion (normalized in-SQL)

`ISB`→Islamabad, `Rwp`→Rawalpindi, `khi`→Karachi, plus case folding of known cities. Unknown blanks would be `Unknown` (none in this dump).

| normalized_city | total_leads | conversions | conversion_rate |
|---|---:|---:|---:|
| Gujranwala | 295 | 28 | 0.0949 |
| Peshawar | 645 | 60 | 0.0930 |
| Islamabad | 2702 | 195 | 0.0722 |
| Lahore | 1375 | 92 | 0.0669 |
| Karachi | 987 | 65 | 0.0659 |
| Multan | 389 | 25 | 0.0643 |
| Faisalabad | 513 | 32 | 0.0624 |
| Rawalpindi | 1981 | 122 | 0.0616 |
| Abbottabad | 273 | 15 | 0.0549 |

## Part 3 — Train the model

```bash
python scripts/train_model.py
```

Writes:

- `models/lead_scoring_model.joblib` — sklearn Pipeline (preprocess + LogisticRegression)
- `reports/model_metrics.json` — split boundary, metric, baseline, top-100

### Cleaning / feature decisions

**Prediction time:** intake (before calls / WhatsApp / site visits / token).

- Parse `created_at`; normalize city/source/area/property_type.
- Deduplicate on `crm_record_hash` before the time split (160 pairs removed).
- Validate `converted` ∈ {0,1}.
- Impute inside a Pipeline fit **only on train**.

**Used:** `source`, `city`, `area`, `property_type`, `budget_pkr_lac`, `bedrooms`, `is_overseas`, `referred_by_existing_client`, `has_financing_approved`.

**Excluded:** `token_amount_received_pkr` (outcome leakage), post-intake activity columns, `first_response_minutes`, `agent_experience_years` (assignment leakage), IDs, target.

### Chronological split (why)

Older leads train, newer leads test. A random split would leak future patterns into training and overstate performance for “who should we call next?”. Split is 80/20 on deduped data:

- Train end: **2025-05-27 20:37:22** (7,200 rows)
- Test start: **2025-05-28 01:39:02** (1,800 rows, 143 conversions)

### Measured test results (from `scripts/train_model.py`)

| Item | Value |
|---|---|
| Primary metric | Average precision (PR-AUC) = **0.1917** |
| No-skill baseline | Test prevalence = **0.0794** |
| Top 100 scored test leads | **29** conversions (rate **0.29** vs test rate **0.0794**) |

Honest read: real but modest ranking lift; useful as a weak call-order baseline, not a guarantee.

```python
from app.lead_scoring import score_lead
print(score_lead({
    "source": "Referral",
    "city": "Islamabad",
    "area": "GT Road Corridor",
    "property_type": "Apartment",
    "budget_pkr_lac": 120,
    "bedrooms": 2,
    "is_overseas": 0,
    "referred_by_existing_client": 1,
    "has_financing_approved": 0,
}))
```

## Part 1 — Document assistant

```bash
python scripts/audit_part1.py
python -m pytest tests/test_document_assistant.py -v
```

```python
from app.document_assistant import answer_question
print(answer_question("What's the transfer fee?").full_text())
```

Hard cases: stacked Decimal premiums, discount-only-on-base, transfer-fee **conflict disclosed (2% vs 2.5%)**, rental yield refused → marketing manager, anchor tenant **unconfirmed**.

## Part 4 — Start the web app

```bash
python scripts/train_model.py   # if model file missing
python run.py
```

Open **http://127.0.0.1:5000/** · health **http://127.0.0.1:5000/health**

| Route | Behaviour |
|---|---|
| `GET /` | Section A ask + Section B score |
| `POST /ask` | Calls `answer_question` (live Part 1) |
| `POST /score` | Calls `score_lead` (live Part 3); rejects outcome/post-intake fields |
| `GET /health` | `{status, model_present, model_path}` |

Jinja2 auto-escapes output (no `|safe`). Missing model → clear error, no fake probability.

## Tests

```bash
python -m pytest tests/ -v
```

## Pricing assumption (booking token vs 50% upfront)

Documented interpretation used by `app/pricing.py` and the Part 1 overseas example:

| Concept | Meaning in this project |
|---|---|
| **50% upfront** | Discount **eligibility** only: unlocks **6% off base** (stackable with overseas **+2% off base** → effective **× 0.92** on base when both apply). It is **not** the amount due at booking. |
| **Booking / token** | Standard payment-plan share of **10%**, applied to the **price after discounts** (and after any premiums). For Block B 3-Bed Executive with 6%+2% and no premiums: `39,480,000 × 0.92 = 36,321,600`; token `× 0.10 = 3,632,160`. |
| Stacked premiums example | Block B 2-Bed Corner floor 15 Margalla: `26,855,000 × 1.13 = 30,346,150` (4%+3%+6% of base, summed). |

The price list does not redefine the token share when the buyer chooses 50% upfront; if MGC later specifies otherwise, update `BOOKING_SHARE` / payment-plan logic explicitly.

## Known limitations

- Doc assistant uses intent routing + keyword retrieval — not an LLM; unusual phrasing may fall back to best-section retrieval.
- ML baseline is weak; do not oversell scores to customers.
- Flask debug server only — no auth, no deployment config.
- Repo is not yet on GitHub (local folder only until you push).

## Submit checklist

1. `pip install -r requirements.txt`
2. `python scripts/train_model.py`
3. `python scripts/validate_part2.py`
4. `python -m pytest tests/ -v`
5. `python run.py` and smoke-test ask + score
6. `git init` → commit → push **public** GitHub repo → submit link before the form closes
