"""Import leads.csv into SQLite using schema.sql and run queries.sql SELECTs."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "leads.db"


def extract_select_statements(sql_text: str) -> list[str]:
    """Extract top-level SELECT/WITH statements (ignore comment-only blocks)."""
    # Strip /* */ and -- comments roughly by keeping executable lines
    lines: list[str] = []
    for line in sql_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("--"):
            continue
        lines.append(line)
    cleaned = "\n".join(lines)
    parts = [p.strip() for p in cleaned.split(";") if p.strip()]
    selects = []
    for part in parts:
        head = part.lstrip().upper()
        if head.startswith("SELECT") or head.startswith("WITH"):
            selects.append(part)
    return selects


def main() -> None:
    DB_PATH.parent.mkdir(exist_ok=True)
    if DB_PATH.exists():
        DB_PATH.unlink()

    conn = sqlite3.connect(DB_PATH)
    conn.executescript((ROOT / "schema.sql").read_text(encoding="utf-8"))

    df = pd.read_csv(ROOT / "leads.csv")
    df["crm_record_hash"] = df["crm_record_hash"].astype(str)
    df.to_sql("leads", conn, if_exists="append", index=False)

    n = conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
    print(f"Loaded {n} rows into {DB_PATH}")

    dup = conn.execute(
        """
        SELECT
            SUM(CASE WHEN cnt > 1 THEN 1 ELSE 0 END) AS duplicate_groups,
            SUM(CASE WHEN cnt > 1 THEN cnt ELSE 0 END) AS rows_in_duplicate_groups,
            SUM(CASE WHEN cnt > 1 THEN cnt - 1 ELSE 0 END) AS extra_duplicate_rows,
            COUNT(*) AS distinct_hashes
        FROM (
            SELECT crm_record_hash, COUNT(*) AS cnt
            FROM leads
            GROUP BY crm_record_hash
        )
        """
    ).fetchone()
    print(
        "Duplicate analysis:",
        f"groups={dup[0]}, rows_in_groups={dup[1]}, extra_rows={dup[2]}, "
        f"distinct_hashes={dup[3]}",
    )

    statements = extract_select_statements(
        (ROOT / "queries.sql").read_text(encoding="utf-8")
    )
    assert len(statements) >= 3, f"Expected >=3 SELECTs, got {len(statements)}"

    labels = [
        "Query 1 — conversion by source (>=200)",
        "Query 2 — canonical row per duplicate group",
        "Query 3 — conversion by normalized city",
    ]
    results: dict[str, list] = {}
    for label, stmt in zip(labels, statements[:3]):
        rows = list(conn.execute(stmt))
        cols = [d[0] for d in conn.execute(stmt).description]
        results[label] = rows
        print(f"\n=== {label} ===")
        print(" | ".join(cols))
        for row in rows:
            print(row)
        print(f"({len(rows)} rows)")

    # Sanity checks
    q1 = results[labels[0]]
    assert all(r[1] >= 200 for r in q1)
    rates = [r[3] for r in q1]
    assert rates == sorted(rates, reverse=True)

    q2 = results[labels[1]]
    assert len(q2) == dup[0], f"Expected {dup[0]} canonical dup rows, got {len(q2)}"

    q3 = results[labels[2]]
    cities = {r[0] for r in q3}
    assert "Islamabad" in cities and "Rawalpindi" in cities and "Karachi" in cities
    assert "ISB" not in cities and "Rwp" not in cities and "khi" not in cities
    assert "ISLAMABAD" not in cities

    print("\nAll validation checks passed.")
    conn.close()


if __name__ == "__main__":
    main()
