-- =============================================================================
-- MGC Developments — Part 2 queries (SQLite)
-- Assumes schema from schema.sql and data loaded into table `leads`.
--
-- Conversion rate convention used throughout:
--   conversion_rate = CAST(conversions AS REAL) / total_leads
--   expressed as a FRACTION in [0, 1] (e.g. 0.1301 ≈ 13.01%).
--   Division-by-zero is avoided by filtering out empty groups (HAVING / WHERE
--   total_leads > 0) or using NULLIF(total_leads, 0).
-- =============================================================================


-- -----------------------------------------------------------------------------
-- Query 1 — Conversion rate by lead source
-- Highest conversion first; only sources with at least 200 leads.
-- -----------------------------------------------------------------------------
SELECT
    source,
    COUNT(*) AS total_leads,
    SUM(converted) AS conversions,
    CAST(SUM(converted) AS REAL) / COUNT(*) AS conversion_rate
FROM leads
GROUP BY source
HAVING COUNT(*) >= 200
ORDER BY conversion_rate DESC, source ASC;


-- -----------------------------------------------------------------------------
-- Query 2 — Duplicate leads: keep exactly one canonical row per duplicate group
--
-- Investigation notes (from leads.csv):
--   • crm_record_hash is the defensible duplicate key: 160 hashes appear twice
--     (320 rows). Within each pair, every column matches except lead_id
--     (one id ends with '-B'). created_at is identical within each pair.
--   • There is no agent_id / phone / email in this dump. agent_experience_years
--     does not differ within pairs, so "different agents" is not observable as
--     a column — only the shared hash (+ optional -B suffix) indicates a
--     double entry.
--
-- Winner rule (deterministic):
--   1) earliest created_at
--   2) then lexicographically smallest lead_id as a stable tie-breaker
--      (so 'MGC-104183' wins over 'MGC-104183-B' when timestamps match)
--
-- This SELECT does NOT delete source data; it returns the canonical subset.
-- Materialize with CREATE TABLE leads_canonical AS … if needed.
--
-- Future prevention: after cleaning, add
--   CREATE UNIQUE INDEX uq_leads_crm_record_hash ON leads (crm_record_hash);
-- and upsert-on-hash in the application. Do not invent UNIQUE constraints on
-- names/phones that are absent from this dataset.
-- -----------------------------------------------------------------------------
WITH ranked AS (
    SELECT
        l.*,
        ROW_NUMBER() OVER (
            PARTITION BY l.crm_record_hash
            ORDER BY l.created_at ASC, l.lead_id ASC
        ) AS rn,
        COUNT(*) OVER (
            PARTITION BY l.crm_record_hash
        ) AS hash_group_size
    FROM leads AS l
)
SELECT
    lead_id,
    created_at,
    source,
    city,
    area,
    property_type,
    budget_pkr_lac,
    bedrooms,
    first_response_minutes,
    calls_made,
    total_call_seconds,
    whatsapp_replies,
    site_visits,
    agent_experience_years,
    is_overseas,
    referred_by_existing_client,
    has_financing_approved,
    token_amount_received_pkr,
    crm_record_hash,
    converted,
    hash_group_size
FROM ranked
WHERE rn = 1
  AND hash_group_size > 1   -- one canonical row per duplicate group only
ORDER BY crm_record_hash, lead_id;

-- Full canonical lead set (one row per crm_record_hash, including non-dupes):
-- CREATE TABLE leads_canonical AS
-- SELECT * FROM (
--     SELECT l.*, ROW_NUMBER() OVER (
--         PARTITION BY l.crm_record_hash
--         ORDER BY l.created_at ASC, l.lead_id ASC
--     ) AS rn
--     FROM leads AS l
-- ) WHERE rn = 1;

-- Supporting check (optional): how many duplicate groups / extra rows exist?
-- SELECT
--     COUNT(*) FILTER (WHERE cnt > 1) AS duplicate_groups,  -- SQLite 3.30+; else see below
--     ...
-- Prefer portable form:
-- SELECT
--     SUM(CASE WHEN cnt > 1 THEN 1 ELSE 0 END) AS duplicate_groups,
--     SUM(CASE WHEN cnt > 1 THEN cnt ELSE 0 END) AS rows_in_duplicate_groups,
--     SUM(CASE WHEN cnt > 1 THEN cnt - 1 ELSE 0 END) AS extra_duplicate_rows
-- FROM (
--     SELECT crm_record_hash, COUNT(*) AS cnt
--     FROM leads
--     GROUP BY crm_record_hash
-- );


-- -----------------------------------------------------------------------------
-- Query 3 — Conversion rate by city, with in-query spelling / case normalization
--
-- Mapping (minimum required + case/whitespace cleanup of known cities only):
--   ISB            → Islamabad
--   Rwp            → Rawalpindi
--   khi            → Karachi
--   UPPER/lower of known city names → Title Case canonical form
-- Unknown / blank after trim → 'Unknown' (not guessed into a real city).
--
-- conversion_rate is a FRACTION (see header). NULLIF guards division-by-zero.
-- -----------------------------------------------------------------------------
SELECT
    normalized_city,
    COUNT(*) AS total_leads,
    SUM(converted) AS conversions,
    CAST(SUM(converted) AS REAL) / NULLIF(COUNT(*), 0) AS conversion_rate
FROM (
    SELECT
        converted,
        CASE
            -- Explicit abbreviations first
            WHEN upper(trim(city)) = 'ISB' THEN 'Islamabad'
            WHEN upper(trim(city)) = 'RWP' THEN 'Rawalpindi'
            WHEN lower(trim(city)) = 'khi' THEN 'Karachi'
            -- Known cities: collapse case / whitespace only (no guessing)
            WHEN upper(trim(city)) = 'ISLAMABAD'  THEN 'Islamabad'
            WHEN upper(trim(city)) = 'RAWALPINDI' THEN 'Rawalpindi'
            WHEN upper(trim(city)) = 'KARACHI'    THEN 'Karachi'
            WHEN upper(trim(city)) = 'LAHORE'     THEN 'Lahore'
            WHEN upper(trim(city)) = 'PESHAWAR'   THEN 'Peshawar'
            WHEN upper(trim(city)) = 'FAISALABAD' THEN 'Faisalabad'
            WHEN upper(trim(city)) = 'MULTAN'     THEN 'Multan'
            WHEN upper(trim(city)) = 'GUJRANWALA' THEN 'Gujranwala'
            WHEN upper(trim(city)) = 'ABBOTTABAD' THEN 'Abbottabad'
            WHEN trim(city) = '' OR city IS NULL THEN 'Unknown'
            -- Any other distinct spelling stays as trimmed original (not invented)
            ELSE trim(city)
        END AS normalized_city
    FROM leads
)
GROUP BY normalized_city
ORDER BY conversion_rate DESC, normalized_city ASC;
