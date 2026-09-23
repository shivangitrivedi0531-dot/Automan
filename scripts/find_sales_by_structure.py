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

# Specified column groups for Sales structure match calculation
GROUPS = {
    "GROUP A (Transaction Identity)": [
        "invoice_no", "inv_no", "invoice_number", "doc_no"
    ],
    "GROUP B (Dates)": [
        "invoice_date", "inv_date", "doc_date", "sale_date", "dt_sale"
    ],
    "GROUP C (Product)": [
        "product_code", "product_id", "dms_product_code", "sub_prd_code"
    ],
    "GROUP D (Customer)": [
        "customer_code", "cust_code", "customer_ac_code", "customer_accode", "ac_code", "customer_name"
    ],
    "GROUP E (Salesman)": [
        "salesman_code", "salesman_id", "salesman_codev"
    ],
    "GROUP F (Finance)": [
        "financer_code", "financer_id", "finance_ref_no", "loan_no", "loan_amt", "payout_amt", "disb_amt"
    ],
    "GROUP G (Sales Classification)": [
        "sale_type", "sale_type_code", "inv_type"
    ],
    "GROUP H (Quantity/Pricing)": [
        "qty", "quantity", "sale_rate", "rate", "discount", "basic_value", "net_amount", "tot_amount", "amount"
    ],
    "GROUP I (Vehicle Indicators)": [
        "chassis_no", "engine_no", "vehicle_no", "model_code", "variant_code"
    ]
}

SENSITIVE_PATTERNS = {
    "chassis", "engine", "vehicle_no", "name", "customer_name", "cust_name",
    "first_name", "last_name", "address", "city", "phone", "mobile",
    "email", "pan", "gst", "aadhar", "dob", "father"
}


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


def find_sales_by_structure(schema_name: str = "public"):
    print("=" * 80)
    print(" SALES DATA DISCOVERY BY COLUMN STRUCTURE REPORT")
    print("=" * 80 + "\n")

    try:
        conn = get_db_connection()
        conn.set_session(readonly=True)
    except Exception as e:
        print(f"[X] Database connection failed: {e}\n")
        sys.exit(1)

    with conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            # 1. Fetch all base tables in schema public
            cursor.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = %s AND table_type = 'BASE TABLE'
                ORDER BY table_name;
                """,
                (schema_name,)
            )
            tables = [r["table_name"] for r in cursor.fetchall()]

            print(f"Inspecting {len(tables)} base tables in schema '{schema_name}'...\n")

            # 2. Fetch all columns in target schema
            cursor.execute(
                """
                SELECT table_name, column_name, data_type
                FROM information_schema.columns
                WHERE table_schema = %s
                ORDER BY table_name, ordinal_position;
                """,
                (schema_name,)
            )
            columns_raw = cursor.fetchall()

            table_columns = {}
            for row in columns_raw:
                t = row["table_name"]
                c = row["column_name"]
                dt = row["data_type"]
                if t not in table_columns:
                    table_columns[t] = []
                table_columns[t].append({"col": c, "type": dt})

            # 3. Process each table: check row count & column group matches
            results = []

            for t in tables:
                cols_meta = table_columns.get(t, [])
                col_lower_map = {item["col"].lower(): item["col"] for item in cols_meta}

                # Check row count safely
                try:
                    cursor.execute(f'SELECT COUNT(*) AS row_cnt FROM "{schema_name}"."{t}";')
                    row_cnt = cursor.fetchone()["row_cnt"]
                except Exception:
                    continue

                if row_cnt == 0:
                    continue  # Ignore tables with 0 rows

                matched_groups = {}
                matched_cols_all = set()

                for grp_name, grp_terms in GROUPS.items():
                    grp_matched = []
                    for term in grp_terms:
                        for clow, creal in col_lower_map.items():
                            if clow == term or (term in clow and len(term) >= 4):
                                if creal not in grp_matched:
                                    grp_matched.append(creal)
                                matched_cols_all.add(creal)
                    if grp_matched:
                        matched_groups[grp_name] = grp_matched

                num_groups = len(matched_groups)

                if num_groups > 0:
                    results.append({
                        "table": t,
                        "rows": row_cnt,
                        "num_groups": num_groups,
                        "matched_groups": matched_groups,
                        "matched_cols": sorted(list(matched_cols_all))
                    })

            # Rank strictly by structural match count (number of matching groups) descending, then row count descending
            results.sort(key=lambda x: (x["num_groups"], x["rows"]), reverse=True)

            print("=" * 80)
            print(f"TOP {min(20, len(results))} CANDIDATE TABLES BY STRUCTURAL MATCH COUNT")
            print("=" * 80 + "\n")

            top_candidates = results[:20]

            for rank, item in enumerate(top_candidates, start=1):
                t = item["table"]
                rows = item["rows"]
                ngroups = item["num_groups"]
                mgroups = item["matched_groups"]
                mcols = item["matched_cols"]

                print(f"Candidate #{rank:02d}: {schema_name}.{t}")
                print(f"  Row Count            : {rows}")
                print(f"  Matching Group Count : {ngroups} / {len(GROUPS)}")
                print("  Matched Groups & Columns:")
                for gname, gcols in mgroups.items():
                    print(f"    - {gname:<32}: {', '.join(gcols)}")
                print()

                # Calculate non-null, distinct, and safe examples for matching columns
                print("  Column Statistics & Safe Examples:")
                for c in mcols:
                    cursor.execute(
                        f"""
                        SELECT 
                            COUNT("{c}") AS non_null_cnt,
                            COUNT(DISTINCT "{c}") AS distinct_cnt
                        FROM "{schema_name}"."{t}";
                        """
                    )
                    st = cursor.fetchone()
                    nn_cnt = st["non_null_cnt"]
                    dist_cnt = st["distinct_cnt"]

                    # Safe examples (redact sensitive values)
                    cursor.execute(
                        f"""
                        SELECT DISTINCT "{c}"
                        FROM "{schema_name}"."{t}"
                        WHERE "{c}" IS NOT NULL AND CAST("{c}" AS TEXT) != ''
                        LIMIT 5;
                        """
                    )
                    samples_raw = cursor.fetchall()
                    sample_vals = []
                    for s in samples_raw:
                        v = s[c]
                        v_str = str(v)
                        if any(sp in c.lower() for sp in SENSITIVE_PATTERNS):
                            sample_vals.append("<REDACTED_PII>")
                        else:
                            if len(v_str) > 40:
                                v_str = v_str[:37] + "..."
                            sample_vals.append(v_str)

                    samples_str = "[" + ", ".join(sample_vals) + "]" if sample_vals else "[]"
                    print(f"    * {c:<25} | Non-Null: {nn_cnt:<8} | Distinct: {dist_cnt:<8} | Examples: {samples_str}")

                print("-" * 80 + "\n")

            # Check Combination Cases across top candidates
            print("=" * 80)
            print("STRUCTURAL COMBINATION CASES EVALUATION")
            print("=" * 80 + "\n")

            case_matches = {f"CASE {i}": [] for i in range(1, 7)}

            for item in top_candidates:
                t = item["table"]
                mgroups = item["matched_groups"]

                has_inv = "GROUP A (Transaction Identity)" in mgroups or "GROUP B (Dates)" in mgroups
                has_prd = "GROUP C (Product)" in mgroups
                has_amt = "GROUP H (Quantity/Pricing)" in mgroups
                has_salesman = "GROUP E (Salesman)" in mgroups
                has_customer = "GROUP D (Customer)" in mgroups
                has_saletype = "GROUP G (Sales Classification)" in mgroups
                has_financer = "GROUP F (Finance)" in mgroups

                if has_inv and has_prd and has_amt:
                    case_matches["CASE 1"].append(t)
                if has_inv and has_prd and has_salesman and has_amt:
                    case_matches["CASE 2"].append(t)
                if has_inv and has_prd and has_customer and has_amt:
                    case_matches["CASE 3"].append(t)
                if has_inv and has_prd and has_saletype and has_amt:
                    case_matches["CASE 4"].append(t)
                if has_inv and has_prd and has_financer and has_amt:
                    case_matches["CASE 5"].append(t)
                if has_inv and has_prd and has_salesman and has_customer and has_amt:
                    case_matches["CASE 6"].append(t)

            print("Combination Cases Found:")
            print("  CASE 1 (Invoice/Date + Product + Qty/Amount)                 :", ", ".join(case_matches["CASE 1"]) or "None")
            print("  CASE 2 (Invoice/Date + Product + Salesman + Amount)          :", ", ".join(case_matches["CASE 2"]) or "None")
            print("  CASE 3 (Invoice/Date + Product + Customer + Amount)          :", ", ".join(case_matches["CASE 3"]) or "None")
            print("  CASE 4 (Invoice/Date + Product + Sale Type + Amount)         :", ", ".join(case_matches["CASE 4"]) or "None")
            print("  CASE 5 (Invoice/Date + Product + Financer + Amount)          :", ", ".join(case_matches["CASE 5"]) or "None")
            print("  CASE 6 (Invoice/Date + Product + Salesman + Customer + Amount):", ", ".join(case_matches["CASE 6"]) or "None")
            print()

            # Final Output Header required
            print("=" * 80)
            print("SALES STRUCTURE SEARCH COMPLETE")
            print("=" * 80 + "\n")

            # Categorized summaries based strictly on observable structural evidence
            completed_sales = [t for t in case_matches["CASE 1"] if t in ["transection", "trn_insu_detail", "trn_veh_inventory"]]
            enquiry_presales = [item["table"] for item in top_candidates if "enq" in item["table"] or "followup" in item["table"]]
            service_job_ins = [item["table"] for item in top_candidates if "job" in item["table"] or "labour" in item["table"] or "insu" in item["table"] or "spares" in item["table"]]
            manual_inspection = [item["table"] for item in top_candidates if item["table"] not in enquiry_presales and item["table"] not in service_job_ins]

            print("1. TOP CANDIDATE TABLES BY NUMBER OF SALES-RELATED COLUMN GROUPS:")
            for item in top_candidates[:5]:
                print(f"   - {item['table']} ({item['num_groups']} matching groups, {item['rows']} rows)")
            print()

            print("2. TABLES THAT LOOK LIKE COMPLETED SALES TRANSACTIONS:")
            if not case_matches["CASE 1"]:
                print("   - None definitively matched full completed sales transaction combination.")
            else:
                for t in case_matches["CASE 1"]:
                    print(f"   - {t}")
            print()

            print("3. TABLES THAT LOOK LIKE ENQUIRY / PRE-SALES:")
            if not enquiry_presales:
                print("   - None found in top candidates.")
            else:
                for t in enquiry_presales:
                    print(f"   - {t}")
            print()

            print("4. TABLES THAT LOOK LIKE SERVICE / JOB / INSURANCE:")
            if not service_job_ins:
                print("   - None found in top candidates.")
            else:
                for t in service_job_ins:
                    print(f"   - {t}")
            print()

            print("5. TABLES REQUIRING MANUAL INSPECTION:")
            if not manual_inspection:
                print("   - None.")
            else:
                for t in manual_inspection:
                    print(f"   - {t}")
            print("\n" + "=" * 80 + "\n")

    conn.close()


if __name__ == "__main__":
    find_sales_by_structure()
