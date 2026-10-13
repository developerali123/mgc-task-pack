import sqlite3
from pathlib import Path

conn = sqlite3.connect(Path(__file__).resolve().parent.parent / "data" / "leads.db")
q = """
WITH ranked AS (
    SELECT
        lead_id,
        ROW_NUMBER() OVER (
            PARTITION BY crm_record_hash
            ORDER BY created_at ASC, lead_id ASC
        ) AS rn,
        COUNT(*) OVER (PARTITION BY crm_record_hash) AS gs
    FROM leads
)
SELECT
    SUM(CASE WHEN lead_id LIKE '%-B' THEN 1 ELSE 0 END) AS winners_with_b_suffix,
    COUNT(*) AS canonical_dup_rows
FROM ranked
WHERE rn = 1 AND gs > 1
"""
print("canonical winners (-B count, total):", conn.execute(q).fetchone())
conn.close()
