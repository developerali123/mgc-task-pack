-- =============================================================================
-- MGC Developments — Part 2 schema (SQLite)
-- Source dump: leads.csv (~9,160 historical CRM leads)
-- =============================================================================
-- Design notes:
--   • One table is enough: every CSV column is lead-grain; there is no separate
--     agent identity, phone, or email in this dump to normalize into other tables.
--   • lead_id is unique in the CSV and is the natural primary key.
--   • crm_record_hash identifies duplicate CRM entries (160 pairs share a hash);
--     it is indexed for dedup analysis but NOT declared UNIQUE on this load table
--     because the historical dump already contains duplicates. See prevention note.
-- =============================================================================

DROP TABLE IF EXISTS leads;

CREATE TABLE leads (
    -- Business / CRM identifiers
    lead_id                     TEXT        NOT NULL PRIMARY KEY,
    -- Wall-clock when the lead was created (ISO-like 'YYYY-MM-DD HH:MM:SS')
    created_at                  TEXT        NOT NULL,
    -- Attribution
    source                      TEXT        NOT NULL,
    city                        TEXT        NOT NULL,  -- messy spellings preserved as-is
    area                        TEXT,                  -- NULL: ~5% missing in dump
    property_type               TEXT        NOT NULL,
    -- Preferences / sizing
    budget_pkr_lac              REAL,                  -- NULL: ~3% missing
    bedrooms                    REAL,                  -- NULL: ~39%; always null for Plot
                                                       --       and Commercial Shop (no beds)
    -- Engagement / process metrics (may be filled after intake)
    first_response_minutes      REAL,                  -- NULL: ~2% missing
    calls_made                  INTEGER     NOT NULL DEFAULT 0,
    total_call_seconds          REAL        NOT NULL DEFAULT 0,
    whatsapp_replies            INTEGER     NOT NULL DEFAULT 0,
    site_visits                 INTEGER     NOT NULL DEFAULT 0,
    -- Agent context (years of experience only — no agent_id in source)
    agent_experience_years      REAL,                  -- NULL: ~4% missing
    -- Flags stored as 0/1 integers to match the CSV
    is_overseas                 INTEGER     NOT NULL DEFAULT 0
                                            CHECK (is_overseas IN (0, 1)),
    referred_by_existing_client INTEGER     NOT NULL DEFAULT 0
                                            CHECK (referred_by_existing_client IN (0, 1)),
    has_financing_approved      INTEGER     NOT NULL DEFAULT 0
                                            CHECK (has_financing_approved IN (0, 1)),
    -- Late-funnel / outcome-adjacent money field (often 0 until token paid)
    token_amount_received_pkr   REAL        NOT NULL DEFAULT 0,
    -- Content fingerprint used to detect duplicate CRM rows
    crm_record_hash             TEXT        NOT NULL,
    -- Target / outcome
    converted                   INTEGER     NOT NULL DEFAULT 0
                                            CHECK (converted IN (0, 1))
);

-- -----------------------------------------------------------------------------
-- Nullability rationale (summary)
-- -----------------------------------------------------------------------------
-- NOT NULL: lead_id, created_at, source, city, property_type, engagement counters,
--           boolean flags, token_amount_received_pkr, crm_record_hash, converted
--           — present on every row in leads.csv.
-- NULL allowed:
--   area                     — blank in source for some leads
--   budget_pkr_lac           — not always captured at intake
--   bedrooms                 — structurally absent for Plot / Commercial Shop;
--                              also occasionally missing on other types
--   first_response_minutes   — lead not yet contacted / not logged
--   agent_experience_years   — agent metadata incomplete in CRM export
-- -----------------------------------------------------------------------------

-- Indexes for common filters and Part 2 query patterns
CREATE INDEX idx_leads_created_at      ON leads (created_at);
CREATE INDEX idx_leads_source          ON leads (source);
CREATE INDEX idx_leads_city            ON leads (city);
CREATE INDEX idx_leads_crm_record_hash ON leads (crm_record_hash);
CREATE INDEX idx_leads_converted       ON leads (converted);

-- Composite helpful for "conversion by source over time" style cuts
CREATE INDEX idx_leads_source_converted ON leads (source, converted);

-- =============================================================================
-- Preventing future duplicates (recommendation — NOT enforced on this load table)
-- =============================================================================
-- Observed pattern: 160 duplicate pairs share the same crm_record_hash; rows are
-- identical except lead_id (canonical vs '…-B' suffix). There is NO agent_id,
-- phone, or email column in this dataset, so do not invent uniqueness on those.
--
-- Recommended going forward (pick one application + schema approach):
--
--   1) Schema: after cleaning the dump, enforce uniqueness on the fingerprint:
--        -- CREATE UNIQUE INDEX uq_leads_crm_record_hash ON leads (crm_record_hash);
--
--   2) Application: before INSERT, SELECT by crm_record_hash (or a hash of the
--      stable lead payload). If a row exists, update / merge instead of inserting
--      a second lead_id.
--
--   3) If a true multi-agent race appears later, add an agent_id column when the
--      CRM provides one, keep one canonical lead row, and store competing claims
--      in a lead_assignments table — do not duplicate the lead fact table.
-- =============================================================================
