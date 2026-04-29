from __future__ import annotations

import os
import sys
from pathlib import Path
from pprint import pprint

import psycopg2 as psql

REPO_ROOT = Path(__file__).resolve().parent.parent

SQL_DIR = REPO_ROOT / "sql"
DATA_DIR = REPO_ROOT / "data"
SECRETS_DIR = REPO_ROOT / "secrets"
PASS_FILE = SECRETS_DIR / ".psql.pass"


HOST = os.environ.get("PSQL_HOST", "hadoop-04.uni.innopolis.ru")
PORT = os.environ.get("PSQL_PORT", "5432")
DB = os.environ.get("PSQL_DB", "team1_projectdb")
USER = os.environ.get("TEAM", "team1")


PASSWORD = PASS_FILE.read_text().strip()

CONN_STRING = (
    f"host={HOST} port={PORT} user={USER} dbname={DB} password={PASSWORD}"
)


def run_sql_script(cur, path: Path) -> None:
    print(f"  [build_projectdb] running {path.relative_to(REPO_ROOT)} ...")
    cur.execute(path.read_text())


def copy_load(cur, copy_sql: str, csv_path: Path, label: str) -> None:
    print(f"  [build_projectdb] COPY-loading {label} from {csv_path.name} ...")
    if not csv_path.is_file():
        sys.exit(f"ERROR: expected CSV not found: {csv_path}")
    with csv_path.open("r", encoding="utf-8") as fh:
        cur.copy_expert(copy_sql, fh)


def main() -> int:
    print(f"[build_projectdb] connecting to {USER}@{HOST}:{PORT}/{DB}")

    with psql.connect(CONN_STRING) as conn:

        with conn.cursor() as cur:
            run_sql_script(cur, SQL_DIR / "create_tables.sql")
        conn.commit()

        copy_statements = (SQL_DIR / "import_data.sql").read_text().splitlines()

        copy_statements = [
            ln for ln in copy_statements
            if ln.strip() and not ln.lstrip().startswith("--")
        ]
        if len(copy_statements) < 2:
            sys.exit(
                "ERROR: import_data.sql is missing the expected 2 COPY lines "
                "(transactions, laundering_patterns)."
            )

        with conn.cursor() as cur:
            copy_load(cur, copy_statements[0], DATA_DIR / "transactions.csv",
                      "transactions")
            copy_load(cur, copy_statements[1], DATA_DIR / "patterns.csv",
                      "laundering_patterns")
        conn.commit()

        print("[build_projectdb] verification queries:")
        with conn.cursor() as cur:
            for cmd in (SQL_DIR / "test_database.sql").read_text().splitlines():
                cmd = cmd.strip()
                if not cmd or cmd.startswith("--"):
                    continue
                cur.execute(cmd)
                try:
                    rows = cur.fetchall()
                except psql.ProgrammingError:
                    continue
                print(f"  > {cmd[:80]}{'...' if len(cmd) > 80 else ''}")
                pprint(rows, indent=4, width=120)

    print("[build_projectdb] done.")
    return 0


if __name__ == "__main__":
    main()