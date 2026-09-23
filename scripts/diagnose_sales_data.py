import os
import sys

# Load environment variables from .env file if python-dotenv is available
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Attempt to import psycopg2 driver
try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except ImportError:
    print("Error: Missing required PostgreSQL driver package 'psycopg2' (or 'psycopg2-binary').")
    print("Please install it using: pip install psycopg2-binary")
    sys.exit(1)

TARGET_TRANSACTION_TABLES = [
    "trn_veh_sales",
    "trn_veh_salesfin",
    "trn_veh_salesrto",
    "trn_oth_sales",
    "trn_oth_salesret"
]

TARGET_MASTER_TABLES = [
    "mst_product",
    "mst_customer_profile",
    "mst_financer",
    "mst_salesman"
]

ALL_TARGET_TABLES = TARGET_TRANSACTION_TABLES + TARGET_MASTER_TABLES

TRANSACTION_INSPECT_COLUMNS = [
    "product_code",
    "invoice_no",
    "sub_prd_code",
    "ac_code",
    "sale_type_code",
    "salesman_code",
    "salesman_codev",
    "financer_code",
    "cust_code",
    "customer_accode"
]

MASTER_INSPECT_COLUMNS = {
    "mst_product": ["product_code", "sub_prd_code"],
    "mst_customer_profile": ["customer_code"],
    "mst_financer": ["financer_code"],
    "mst_salesman": ["salesman_code"]
}

# Sensitive columns to mask in sample outputs to prevent PII exposure
SENSITIVE_COLUMNS = {
    "name", "customer_name", "cust_name", "first_name", "last_name",
    "address", "address1", "address2", "address3", "city", "phone", "mobile",
    "email", "pan_no", "gst_no", "aadhar_no", "dob", "father_name"
}


def get_db_connection():
    """
    Establishes a connection to PostgreSQL using environment variables.
    Reuses standard connection configuration (DATABASE_URL or DB_* / POSTGRES_* / PG* parameters).
    """
    database_url = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL")
    if database_url:
        return psycopg2.connect(database_url)

    host = os.getenv("DB_HOST") or os.getenv("POSTGRES_HOST") or os.getenv("PGHOST", "localhost")
    port = os.getenv("DB_PORT") or os.getenv("POSTGRES_PORT") or os.getenv("PGPORT", "5432")
    dbname = os.getenv("DB_NAME") or os.getenv("POSTGRES_DB") or os.getenv("PGDATABASE", "postgres")
    user = os.getenv("DB_USER") or os.getenv("POSTGRES_USER") or os.getenv("PGUSER", "postgres")
    password = os.getenv("DB_PASSWORD") or os.getenv("POSTGRES_PASSWORD") or os.getenv("PGPASSWORD", "")

    return psycopg2.connect(
        host=host,
        port=port,
        dbname=dbname,
        user=user,
        password=password
    )


def diagnose_sales_data(schema_name: str = "public"):
    print("=" * 80)
    print(" SALES DATA DIAGNOSTIC REPORT")
    print("=" * 80 + "\n")

    # 1. Connection Information
    try:
        conn = get_db_connection()
        conn.set_session(readonly=True)
    except Exception as e:
        print(f"[X] Database connection failed: {e}\n")
        print("=" * 80)
        print("7. FINAL DIAGNOSIS:")
        print("=" * 80)
        print("CASE D:")
        print("Schema/database connection mismatch detected. Could not connect to database.\n")
        sys.exit(1)

    with conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            # Query connection metadata
            cursor.execute("SELECT current_database(), current_schema(), inet_server_addr(), inet_server_port();")
            conn_info = cursor.fetchone()
            curr_db = conn_info["current_database"]
            curr_schema = conn_info["current_schema"]
            server_addr = conn_info["inet_server_addr"] or os.getenv("DB_HOST") or os.getenv("POSTGRES_HOST") or "localhost"
            server_port = conn_info["inet_server_port"] or os.getenv("DB_PORT") or os.getenv("POSTGRES_PORT") or "5432"

            print("1. CURRENT DATABASE CONNECTION INFORMATION:")
            print(f"   Database Name : {curr_db}")
            print(f"   Current Schema: {curr_schema}")
            print(f"   Target Schema : {schema_name}")
            print(f"   Host          : {server_addr}")
            print(f"   Port          : {server_port}")
            print()

            # 5. Schema verification for 'public'
            cursor.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = %s AND table_name = ANY(%s);
                """,
                (schema_name, ALL_TARGET_TABLES)
            )
            found_tables = {row["table_name"] for row in cursor.fetchall()}

            print("5. SCHEMA 'public' VERIFICATION:")
            missing_tables = set(ALL_TARGET_TABLES) - found_tables
            if not missing_tables:
                print(f"   All {len(ALL_TARGET_TABLES)} target tables exist in schema '{schema_name}'.")
            else:
                print(f"   [!] WARNING: Missing tables in schema '{schema_name}': {sorted(list(missing_tables))}")
            print()

            # 6. Verify connection configuration consistency
            print("6. DATABASE CONNECTION CONSISTENCY VERIFICATION:")
            print("   Script uses standard environment connection parameters (DATABASE_URL / DB_* / POSTGRES_* / PG*).")
            print(f"   Active connection target: DB='{curr_db}', Host={server_addr}, Port={server_port}.")
            print("   Matches the connection logic used in inspect_sales_tables.py and inspect_database.py.")
            print()

            # 2 & 3. Table row counts and column stats
            print("2 & 3. TABLE ROW COUNTS AND COLUMN STATISTICS:")
            print("-" * 80)

            table_stats = {}
            total_trn_rows = 0
            total_trn_relevant_non_null = 0
            total_trn_relevant_distinct = 0

            for table in ALL_TARGET_TABLES:
                if table not in found_tables:
                    print(f"Table: {table} [NOT FOUND IN SCHEMA '{schema_name}']")
                    print("-" * 80)
                    continue

                cursor.execute(f'SELECT COUNT(*) AS total_rows FROM "{schema_name}"."{table}";')
                total_rows = cursor.fetchone()["total_rows"]

                if table in TARGET_TRANSACTION_TABLES:
                    total_trn_rows += total_rows

                print(f"Table: {table}")
                print(f"  Total Rows: {total_rows}")

                # Determine target columns for this table
                if table in MASTER_INSPECT_COLUMNS:
                    target_cols = MASTER_INSPECT_COLUMNS[table]
                else:
                    # Check which transaction columns exist in this table
                    cursor.execute(
                        """
                        SELECT column_name
                        FROM information_schema.columns
                        WHERE table_schema = %s AND table_name = %s;
                        """,
                        (schema_name, table)
                    )
                    existing_cols = {row["column_name"] for row in cursor.fetchall()}
                    target_cols = [c for c in TRANSACTION_INSPECT_COLUMNS if c in existing_cols]

                col_stats = []
                for col in target_cols:
                    query = f"""
                        SELECT 
                            COUNT("{col}") AS non_null_count,
                            COUNT(DISTINCT "{col}") AS distinct_count
                        FROM "{schema_name}"."{table}";
                    """
                    cursor.execute(query)
                    res = cursor.fetchone()
                    non_null = res["non_null_count"]
                    distinct_cnt = res["distinct_count"]

                    if table in TARGET_TRANSACTION_TABLES:
                        total_trn_relevant_non_null += non_null
                        total_trn_relevant_distinct += distinct_cnt

                    col_stats.append({
                        "column": col,
                        "non_null": non_null,
                        "distinct": distinct_cnt
                    })

                    print(f"    - {col:<20} | Non-Null Count: {non_null:<8} | Distinct Non-Null: {distinct_cnt:<8}")

                table_stats[table] = {
                    "total_rows": total_rows,
                    "col_stats": col_stats
                }
                print("-" * 80)

            print()

            # 4. Transaction table sample structural inspection (LIMIT 3)
            print("4. TRANSACTION TABLE SAMPLE INSPECTION (SELECT * FROM table LIMIT 3):")
            print("-" * 80)

            for table in TARGET_TRANSACTION_TABLES:
                if table not in found_tables:
                    print(f"Table: {table} [NOT FOUND IN SCHEMA '{schema_name}']")
                    print("-" * 80)
                    continue

                cursor.execute(f'SELECT * FROM "{schema_name}"."{table}" LIMIT 3;')
                rows = cursor.fetchall()

                print(f"Table: {table}")
                print(f"  Rows Returned: {len(rows)}")

                if not rows:
                    print("  Sample Rows: [0 rows returned]")
                else:
                    col_names = list(rows[0].keys())
                    print(f"  Total Columns: {len(col_names)}")
                    print(f"  Column Names: {', '.join(col_names)}")

                    for idx, row in enumerate(rows, start=1):
                        safe_row = {}
                        for k, v in row.items():
                            if k.lower() in SENSITIVE_COLUMNS:
                                safe_row[k] = "<REDACTED PII>"
                            else:
                                safe_row[k] = v
                        print(f"  Sample Row #{idx}: {safe_row}")

                print("-" * 80)

            print()

            # 7. Clear Final Diagnosis
            print("=" * 80)
            print("7. FINAL DIAGNOSIS:")
            print("=" * 80)

            schema_mismatch = bool(missing_tables)

            if schema_mismatch:
                print("CASE D:")
                print("Schema/database connection mismatch detected.")
                print(f"Reason: Target tables missing in schema '{schema_name}': {sorted(list(missing_tables))}")

            elif total_trn_rows == 0:
                print("CASE A:")
                print("Transaction tables genuinely contain 0 rows.")
                print("Observed:")
                for t in TARGET_TRANSACTION_TABLES:
                    rows = table_stats.get(t, {}).get("total_rows", 0)
                    print(f"  - {t}: {rows} rows")

            elif total_trn_relevant_non_null == 0 or total_trn_relevant_distinct == 0:
                print("CASE B:")
                print("Transaction tables contain rows, but relevant columns contain 0 non-null values.")
                print("Observed:")
                for t in TARGET_TRANSACTION_TABLES:
                    rows = table_stats.get(t, {}).get("total_rows", 0)
                    print(f"  - {t} has {rows} rows, but relevant columns contain 0 non-null/distinct values.")

            else:
                print("CASE C:")
                print("Transaction tables contain data and relevant columns contain values.")
                print("Therefore the relationship discovery script has a query/filter/logic problem.")
                print("Observed:")
                for t in TARGET_TRANSACTION_TABLES:
                    t_info = table_stats.get(t, {})
                    rows = t_info.get("total_rows", 0)
                    print(f"  - {t}: {rows} total rows")
                    for c_info in t_info.get("col_stats", []):
                        print(f"      - {c_info['column']}: non_null={c_info['non_null']}, distinct={c_info['distinct']}")

            print("=" * 80 + "\n")

    conn.close()


if __name__ == "__main__":
    diagnose_sales_data()
