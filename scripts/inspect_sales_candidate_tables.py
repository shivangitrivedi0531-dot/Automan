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

# Specified candidate tables for structural and sample inspection
CANDIDATE_TABLES = [
    "transection",
    "transaction",
    "trn_insu_detail",
    "trn_jobcard",
    "trn_labour_issue",
    "trn_enq_followup",
    "trn_log_mod_del_detail"
]

# Additional populated tables found in previous steps
ADDITIONAL_CANDIDATES = [
    "trn_enquiry",
    "trn_followup",
    "trn_job_followup"
]

RELEVANT_COL_KEYWORDS = [
    "invoice_no", "inv_no", "invoice_date", "inv_dt", "product_code",
    "dms_product_code", "sale_type", "sale_type_code", "salesman_code",
    "financer_code", "cust_code", "customer_code", "net_amount",
    "tot_amount", "sale_rate", "qty", "discount", "basic_value", "gst", "tax"
]

MASTER_MAP = {
    "product_code": ("mst_product", "product_code"),
    "dms_product_code": ("mst_product", "product_code"),
    "salesman_code": ("mst_salesman", "salesman_code"),
    "financer_code": ("mst_financer", "financer_code"),
    "cust_code": ("mst_customer_profile", "customer_code"),
    "customer_code": ("mst_customer_profile", "customer_code")
}

SENSITIVE_PATTERNS = {"name", "address", "phone", "mobile", "email", "pan", "gst", "aadhar"}


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


def inspect_sales_candidate_tables(schema_name: str = "public"):
    print("=" * 80)
    print(" SALES CANDIDATE TABLES INSPECTION REPORT")
    print("=" * 80 + "\n")

    try:
        conn = get_db_connection()
        conn.set_session(readonly=True)
    except Exception as e:
        print(f"[X] Database connection failed: {e}\n")
        sys.exit(1)

    tables_for_deeper_inspection = []

    with conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            # 1. Discover existing candidate tables in the database
            all_target_names = CANDIDATE_TABLES + ADDITIONAL_CANDIDATES
            cursor.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = %s AND table_name = ANY(%s);
                """,
                (schema_name, all_target_names)
            )
            existing_tables = {r["table_name"] for r in cursor.fetchall()}

            # Keep order of CANDIDATE_TABLES
            ordered_tables = [t for t in CANDIDATE_TABLES if t in existing_tables]
            for t in ADDITIONAL_CANDIDATES:
                if t in existing_tables and t not in ordered_tables:
                    ordered_tables.append(t)

            print(f"Found {len(ordered_tables)} populated candidate tables to inspect in schema '{schema_name}'.\n")

            for table in ordered_tables:
                print("=" * 80)
                print(f"TABLE: {schema_name}.{table}")
                print("=" * 80)

                # 2. Total row count
                cursor.execute(f'SELECT COUNT(*) AS total_rows FROM "{schema_name}"."{table}";')
                total_rows = cursor.fetchone()["total_rows"]
                print(f"Total Rows: {total_rows}\n")

                # 3 & 4. Complete column names & data types
                cursor.execute(
                    """
                    SELECT column_name, data_type
                    FROM information_schema.columns
                    WHERE table_schema = %s AND table_name = %s
                    ORDER BY ordinal_position;
                    """,
                    (schema_name, table)
                )
                columns_meta = cursor.fetchall()

                print(f"Complete Columns ({len(columns_meta)} total):")
                col_type_dict = {}
                for c in columns_meta:
                    col_name = c["column_name"]
                    col_type = c["data_type"]
                    col_type_dict[col_name] = col_type
                    print(f"  - {col_name:<30} | {col_type}")
                print()

                # 5. Matching / resembling columns
                matching_columns = []
                for col_name in col_type_dict.keys():
                    col_lower = col_name.lower()
                    for kw in RELEVANT_COL_KEYWORDS:
                        if kw in col_lower:
                            matching_columns.append(col_name)
                            break

                print("Matching / Resembling Key Sales Columns:")
                if not matching_columns:
                    print("  None matched target keywords.")
                else:
                    for mc in matching_columns:
                        print(f"  - {mc}")
                print()

                # 6. Column statistics & SAFE example values
                print("Important Candidate Column Statistics & Safe Examples:")
                print("-" * 80)
                if not matching_columns:
                    print("  No candidate columns to report.")
                else:
                    for col_name in matching_columns:
                        ctype = col_type_dict[col_name]

                        # Non-null & distinct count
                        cursor.execute(
                            f"""
                            SELECT 
                                COUNT("{col_name}") AS non_null_cnt,
                                COUNT(DISTINCT "{col_name}") AS distinct_cnt
                            FROM "{schema_name}"."{table}";
                            """
                        )
                        stats = cursor.fetchone()
                        non_null_cnt = stats["non_null_cnt"]
                        distinct_cnt = stats["distinct_cnt"]

                        # Fetch up to 5 safe sample values
                        cursor.execute(
                            f"""
                            SELECT DISTINCT "{col_name}"
                            FROM "{schema_name}"."{table}"
                            WHERE "{col_name}" IS NOT NULL AND CAST("{col_name}" AS TEXT) != ''
                            LIMIT 5;
                            """
                        )
                        samples_raw = cursor.fetchall()
                        sample_vals = []
                        for s in samples_raw:
                            val = s[col_name]
                            val_str = str(val)
                            if any(sp in col_name.lower() for sp in SENSITIVE_PATTERNS):
                                sample_vals.append("<REDACTED_PII>")
                            else:
                                if len(val_str) > 40:
                                    val_str = val_str[:37] + "..."
                                sample_vals.append(val_str)

                        samples_str = "[" + ", ".join(sample_vals) + "]" if sample_vals else "[]"

                        print(f"Column: {col_name}")
                        print(f"Type: {ctype}")
                        print(f"Non-null: {non_null_cnt}")
                        print(f"Distinct: {distinct_cnt}")
                        print(f"Examples: {samples_str}")
                        print()

                # 7. Candidate Value Overlaps with Master Tables
                print("Master Table Candidate Value Overlaps:")
                print("-" * 80)

                overlaps_found = 0
                for col_name in matching_columns:
                    col_lower = col_name.lower()
                    matched_tgt = None
                    for key_term, (tgt_tbl, tgt_col) in MASTER_MAP.items():
                        if key_term in col_lower:
                            matched_tgt = (tgt_tbl, tgt_col)
                            break

                    if matched_tgt:
                        tgt_tbl, tgt_col = matched_tgt
                        cursor.execute(
                            f"""
                            SELECT COUNT(DISTINCT "{col_name}") AS src_cnt
                            FROM "{schema_name}"."{table}"
                            WHERE "{col_name}" IS NOT NULL AND CAST("{col_name}" AS TEXT) != '';
                            """
                        )
                        src_cnt = cursor.fetchone()["src_cnt"]

                        if src_cnt == 0:
                            print(f"Source column: {table}.{col_name}")
                            print(f"Target column: {tgt_tbl}.{tgt_col}")
                            print(f"Source distinct count: 0")
                            print(f"Matched distinct count: 0")
                            print(f"Match percentage: 0.00%\n")
                        else:
                            cursor.execute(
                                f"""
                                SELECT COUNT(DISTINCT s."{col_name}") AS matched_cnt
                                FROM (
                                    SELECT DISTINCT "{col_name}"
                                    FROM "{schema_name}"."{table}"
                                    WHERE "{col_name}" IS NOT NULL AND CAST("{col_name}" AS TEXT) != ''
                                ) s
                                JOIN (
                                    SELECT DISTINCT "{tgt_col}"
                                    FROM "{schema_name}"."{tgt_tbl}"
                                    WHERE "{tgt_col}" IS NOT NULL AND CAST("{tgt_col}" AS TEXT) != ''
                                ) t ON CAST(s."{col_name}" AS TEXT) = CAST(t."{tgt_col}" AS TEXT);
                                """
                            )
                            matched_cnt = cursor.fetchone()["matched_cnt"]
                            match_pct = (matched_cnt / src_cnt) * 100.0 if src_cnt > 0 else 0.0

                            print(f"Source column: {table}.{col_name}")
                            print(f"Target column: {tgt_tbl}.{tgt_col}")
                            print(f"Source distinct count: {src_cnt}")
                            print(f"Matched distinct count: {matched_cnt}")
                            print(f"Match percentage: {match_pct:.2f}%\n")
                            overlaps_found += 1

                if overlaps_found == 0:
                    print("No candidate value overlaps with master key columns.\n")

                # 8. Preliminary Classification
                print("Preliminary Classification:")
                print("-" * 80)

                has_invoice = any("inv" in c.lower() or "invoice" in c.lower() for c in matching_columns)
                has_product = any("product" in c.lower() or "prd" in c.lower() for c in matching_columns)
                has_amounts = any("amount" in c.lower() or "rate" in c.lower() or "tot" in c.lower() or "price" in c.lower() for c in matching_columns)

                if total_rows > 0 and (table in ["transection", "transaction"] or (has_invoice and (has_product or has_amounts))):
                    classification = "LIKELY SALES TRANSACTION"
                    tables_for_deeper_inspection.append((table, classification, f"Contains {total_rows} rows with core invoice/transaction/financial columns"))
                elif total_rows > 0 and (has_invoice or has_product or has_amounts):
                    classification = "POSSIBLE SALES-RELATED"
                    tables_for_deeper_inspection.append((table, classification, f"Contains {total_rows} rows with sales-resembling attributes"))
                elif total_rows > 0:
                    classification = "LIKELY NON-SALES"
                else:
                    classification = "INSUFFICIENT EVIDENCE"

                print(f"Classification: {classification}")
                print("\n")

            # Final summary & termination string
            print("=" * 80)
            print("SALES CANDIDATE INVESTIGATION COMPLETE")
            print("=" * 80 + "\n")

            print("SUMMARY OF TABLES REQUIRING DEEPER INSPECTION:")
            print("-" * 80)
            if not tables_for_deeper_inspection:
                print("No candidate tables identified for deeper sales inspection.")
            else:
                for tbl, cls, reason in tables_for_deeper_inspection:
                    print(f"  - {schema_name}.{tbl:<25} | [{cls}] -> {reason}")
            print("\n" + "=" * 80 + "\n")

    conn.close()


if __name__ == "__main__":
    inspect_sales_candidate_tables()
