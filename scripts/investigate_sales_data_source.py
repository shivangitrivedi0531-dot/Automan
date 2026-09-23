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

TARGET_TRANSACTION_TABLES = {
    "trn_veh_sales",
    "trn_veh_salesfin",
    "trn_veh_salesrto",
    "trn_oth_sales",
    "trn_oth_salesret"
}

TABLE_KEYWORDS = [
    "sales", "sale", "invoice", "billing", "veh", "vehicle",
    "customer", "finance", "financer", "rto", "transaction",
    "tran", "product", "order"
]

IMPORTANT_COLUMNS = [
    "invoice_no", "invoice_date", "product_code", "sale_type_code",
    "salesman_code", "financer_code", "cust_code", "customer_code",
    "net_amount", "tot_amount", "sale_type", "inv_no", "inv_date"
]


def get_db_connection():
    """
    Establishes a connection to PostgreSQL using standard environment variables.
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


def investigate_sales_data_source():
    print("=" * 80)
    print(" INVESTIGATE SALES DATA SOURCE REPORT")
    print("=" * 80 + "\n")

    # 1. Connect to DB with read-only session
    try:
        conn = get_db_connection()
        conn.set_session(readonly=True)
    except Exception as e:
        print(f"[X] Database connection failed: {e}\n")
        print("=" * 80)
        print("11. FINAL DIAGNOSIS:")
        print("=" * 80)
        print('CASE A:\n"No alternative Sales transaction tables found in the connected database."\n')
        sys.exit(1)

    with conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            # 1. Connection information
            cursor.execute("SELECT current_database(), current_schema(), inet_server_addr(), inet_server_port();")
            conn_info = cursor.fetchone()
            curr_db = conn_info["current_database"]
            curr_schema = conn_info["current_schema"]
            server_addr = conn_info["inet_server_addr"] or os.getenv("DB_HOST") or os.getenv("POSTGRES_HOST") or "localhost"
            server_port = conn_info["inet_server_port"] or os.getenv("DB_PORT") or os.getenv("POSTGRES_PORT") or "5432"

            print("1. CURRENT DATABASE CONNECTION INFORMATION:")
            print(f"   Database Name : {curr_db}")
            print(f"   Current Schema: {curr_schema}")
            print(f"   Host          : {server_addr}")
            print(f"   Port          : {server_port}")
            print()

            # 2. Available schemas
            cursor.execute(
                """
                SELECT schema_name
                FROM information_schema.schemata
                WHERE schema_name NOT IN ('pg_catalog', 'information_schema')
                  AND schema_name NOT LIKE 'pg_temp_%%'
                  AND schema_name NOT LIKE 'pg_toast_%%'
                ORDER BY schema_name;
                """
            )
            schemas = [r["schema_name"] for r in cursor.fetchall()]
            print(f"2. AVAILABLE NON-SYSTEM SCHEMAS ({len(schemas)} found):")
            for s in schemas:
                print(f"   - {s}")
            print()

            # 3. List all tables and views in non-system schemas
            cursor.execute(
                """
                SELECT table_schema, table_name, table_type
                FROM information_schema.tables
                WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
                  AND table_schema NOT LIKE 'pg_temp_%%'
                  AND table_schema NOT LIKE 'pg_toast_%%'
                ORDER BY table_schema, table_name;
                """
            )
            all_tables = cursor.fetchall()
            print(f"3. ALL TABLES AND VIEWS IN NON-SYSTEM SCHEMAS ({len(all_tables)} found):")
            for t in all_tables:
                print(f"   - {t['table_schema']}.{t['table_name']} ({t['table_type']})")
            print()

            # Fetch columns for all non-system tables
            cursor.execute(
                """
                SELECT table_schema, table_name, column_name
                FROM information_schema.columns
                WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
                  AND table_schema NOT LIKE 'pg_temp_%%'
                  AND table_schema NOT LIKE 'pg_toast_%%'
                ORDER BY table_schema, table_name, ordinal_position;
                """
            )
            all_columns = cursor.fetchall()

            # Group columns by (schema, table)
            table_col_map = {}
            for col in all_columns:
                key = (col["table_schema"], col["table_name"])
                if key not in table_col_map:
                    table_col_map[key] = []
                table_col_map[key].append(col["column_name"])

            table_type_map = {(t["table_schema"], t["table_name"]): t["table_type"] for t in all_tables}

            # 4, 5, 6, 7, 8: Search tables and columns matching keywords
            target_existing_tables = []
            other_potential_sales_tables = []
            other_relevant_schemas = set()

            for (sch, tbl), cols in table_col_map.items():
                obj_type = table_type_map.get((sch, tbl), "BASE TABLE")

                # Count rows safely
                row_count = 0
                try:
                    cursor.execute(f'SELECT COUNT(*) AS cnt FROM "{sch}"."{tbl}";')
                    row_count = cursor.fetchone()["cnt"]
                except Exception:
                    row_count = -1

                tbl_lower = tbl.lower()
                name_match = any(kw in tbl_lower for kw in TABLE_KEYWORDS)

                # Matching key columns
                matched_cols = [c for c in cols if any(imp_col in c.lower() for imp_col in IMPORTANT_COLUMNS)]

                if sch == "public" and tbl in TARGET_TRANSACTION_TABLES:
                    target_existing_tables.append({
                        "schema": sch,
                        "table": tbl,
                        "type": obj_type,
                        "rows": row_count,
                        "cols": cols,
                        "matched_cols": matched_cols
                    })
                elif name_match or matched_cols:
                    if sch != "public":
                        other_relevant_schemas.add(sch)
                    other_potential_sales_tables.append({
                        "schema": sch,
                        "table": tbl,
                        "type": obj_type,
                        "rows": row_count,
                        "cols": cols,
                        "matched_cols": matched_cols,
                        "name_match": name_match
                    })

            # 4, 7, 8: Print search results
            print("4, 7 & 8. RELEVANT TABLES AND COLUMNS SEARCH RESULTS:")
            print("-" * 80)
            if not other_potential_sales_tables:
                print("No additional potential Sales/Transaction tables matched the search criteria.")
                print("-" * 80)
            else:
                for t in other_potential_sales_tables:
                    print(f"Table       : {t['schema']}.{t['table']} ({t['type']})")
                    print(f"Row Count   : {t['rows']}")
                    print(f"Name Match  : {t['name_match']}")
                    print(f"Matching Key Columns: {', '.join(t['matched_cols']) if t['matched_cols'] else 'None'}")
                    print("-" * 80)
            print()

            # 10. Clear separation
            print("=" * 80)
            print("10. SEPARATED CATEGORIZATION OF TABLES")
            print("=" * 80 + "\n")

            print("A. EXISTING TARGET SALES TABLES (in schema 'public'):")
            print("-" * 80)
            for t in target_existing_tables:
                print(f"   Table                : {t['schema']}.{t['table']} ({t['type']})")
                print(f"   Row Count            : {t['rows']}")
                print(f"   Matching Key Columns : {', '.join(t['matched_cols']) if t['matched_cols'] else 'None'}")
                print()

            print("B. OTHER POTENTIALLY RELEVANT SALES / TRANSACTION TABLES:")
            print("-" * 80)
            if not other_potential_sales_tables:
                print("   None found.")
                print()
            else:
                for t in other_potential_sales_tables:
                    print(f"   Table                : {t['schema']}.{t['table']} ({t['type']})")
                    print(f"   Row Count            : {t['rows']}")
                    print(f"   Name Match           : {t['name_match']}")
                    print(f"   Matching Key Columns : {', '.join(t['matched_cols']) if t['matched_cols'] else 'None'}")
                    print()

            print("C. OTHER SCHEMAS CONTAINING POTENTIALLY RELEVANT DATA:")
            print("-" * 80)
            if not other_relevant_schemas:
                print("   No non-public schemas contain relevant tables.")
                print()
            else:
                for s in sorted(list(other_relevant_schemas)):
                    print(f"   - Schema: {s}")
                print()

            # 11. Final Diagnosis Selection
            print("=" * 80)
            print("11. FINAL DIAGNOSIS:")
            print("=" * 80)

            # Focus transaction-related alternative tables (excluding master tables for data presence decision)
            alternative_trn_tables_with_data = [
                t for t in other_potential_sales_tables
                if not t["table"].startswith("mst_") and t["rows"] > 0
            ]
            non_public_trn_with_data = [
                t for t in alternative_trn_tables_with_data
                if t["schema"] != "public"
            ]

            if non_public_trn_with_data:
                print("CASE C:")
                print('"Sales transaction data appears to exist in another schema."')
                print("\nObserved:")
                for t in non_public_trn_with_data:
                    print(f"  - {t['schema']}.{t['table']}: {t['rows']} rows (Columns: {', '.join(t['matched_cols'])})")

            elif alternative_trn_tables_with_data:
                print("CASE B:")
                print('"Potential alternative Sales transaction tables found in the same database."')
                print("\nObserved:")
                for t in alternative_trn_tables_with_data:
                    print(f"  - {t['schema']}.{t['table']}: {t['rows']} rows (Columns: {', '.join(t['matched_cols'])})")

            elif other_potential_sales_tables:
                print("CASE D:")
                print('"Potential Sales data exists in other tables but requires further inspection."')
                print("\nObserved:")
                for t in other_potential_sales_tables:
                    print(f"  - {t['schema']}.{t['table']}: {t['rows']} rows (Columns: {', '.join(t['matched_cols'])})")

            else:
                print("CASE A:")
                print('"No alternative Sales transaction tables found in the connected database."')

            print("=" * 80 + "\n")

    conn.close()


if __name__ == "__main__":
    investigate_sales_data_source()
