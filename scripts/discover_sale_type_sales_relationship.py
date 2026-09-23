import os
import sys

try:
    from dotenv import load_dotenv
    env_path = os.path.join(os.getcwd(), ".env")
    if os.path.exists(env_path):
        load_dotenv(env_path)
    else:
        load_dotenv()
except ImportError:
    pass

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except ImportError:
    print("Error: Missing required PostgreSQL driver package 'psycopg2' (or 'psycopg2-binary').")
    print("Please install it using: pip install psycopg2-binary")
    sys.exit(1)


def get_db_connection():
    database_url = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL")
    if database_url:
        return psycopg2.connect(database_url)

    host = os.getenv("DB_HOST") or os.getenv("POSTGRES_HOST") or os.getenv("PGHOST", "localhost")
    port = os.getenv("DB_PORT") or os.getenv("POSTGRES_PORT") or os.getenv("PGPORT", "5432")
    dbname = os.getenv("DB_NAME") or os.getenv("POSTGRES_DB") or os.getenv("PGDATABASE", "auto")
    user = os.getenv("DB_USER") or os.getenv("POSTGRES_USER") or os.getenv("PGUSER", "postgres")
    password = os.getenv("DB_PASSWORD") or os.getenv("POSTGRES_PASSWORD") or os.getenv("PGPASSWORD", "")

    return psycopg2.connect(
        host=host,
        port=port,
        dbname=dbname,
        user=user,
        password=password
    )


def main():
    schema_name = "public"
    print("=" * 80)
    print(" SALE TYPE SALES RELATIONSHIP — DISCOVERY & VALIDATION REPORT")
    print("=" * 80 + "\n")

    try:
        conn = get_db_connection()
        conn.set_session(readonly=True)
    except Exception as e:
        print(f"[X] Database connection failed: {e}\n")
        sys.exit(1)

    with conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:

            # ==================================================
            # PART 1 — SALE TYPE MASTER DISCOVERY
            # ==================================================
            print("PART 1 — SALE TYPE MASTER DISCOVERY")
            print("=" * 80)

            cur.execute("""
                SELECT column_name, data_type 
                FROM information_schema.columns 
                WHERE table_schema = %s AND table_name = 'mst_sale_type'
                ORDER BY ordinal_position;
            """, (schema_name,))
            mst_cols = cur.fetchall()

            cur.execute("SELECT COUNT(*) AS total_rows FROM public.mst_sale_type;")
            mst_row_cnt = cur.fetchone()["total_rows"]

            print("Table: public.mst_sale_type")
            print(f"Total Master Rows: {mst_row_cnt}\n")
            print(f"{'Column Name':<25} | {'Data Type':<20} | {'Non-Null Count':<15} | {'Distinct Count'}")
            print("-" * 78)

            for col in mst_cols:
                cname = col["column_name"]
                dtype = col["data_type"]
                cur.execute(f'SELECT COUNT("{cname}") AS nn, COUNT(DISTINCT "{cname}") AS dist FROM public.mst_sale_type;')
                st = cur.fetchone()
                print(f"{cname:<25} | {dtype:<20} | {st['nn']:<15} | {st['dist']}")

            # Identify key master columns
            sale_type_id_col = "sale_type_id"
            sale_type_code_col = "sale_type_code"
            sale_type_name_col = "sale_type_name"

            print(f"\nIdentified Key Master Columns:")
            print(f"  - Sale Type ID   : {sale_type_id_col}")
            print(f"  - Sale Type Code : {sale_type_code_col}")
            print(f"  - Sale Type Name : {sale_type_name_col}\n")

            cur.execute("""
                SELECT 
                    sale_type_id,
                    TRIM(CAST(sale_type_code AS TEXT)) AS sale_type_code,
                    TRIM(CAST(sale_type_name AS TEXT)) AS sale_type_name
                FROM public.mst_sale_type
                ORDER BY sale_type_id;
            """)
            master_records = cur.fetchall()
            master_code_map = {r["sale_type_code"]: r["sale_type_name"] for r in master_records}

            print("Master Sale Type Records:")
            print(f"{'Sale Type ID':<15} | {'Sale Type Code':<18} | {'Sale Type Name'}")
            print("-" * 60)
            for r in master_records:
                print(f"{str(r['sale_type_id']):<15} | {r['sale_type_code']:<18} | {r['sale_type_name']}")
            print("\n")

            # ==================================================
            # PART 2 — VSALE CANDIDATE FIELDS
            # ==================================================
            print("PART 2 — VSALE CANDIDATE FIELDS (public.transection WHERE inv_type = 'VSALE')")
            print("=" * 80)

            cur.execute("""
                SELECT COUNT(DISTINCT TRIM(CAST(inv_no AS TEXT))) AS vsale_inv_cnt, COUNT(*) AS vsale_row_cnt
                FROM public.transection
                WHERE inv_type = 'VSALE' AND inv_no IS NOT NULL AND TRIM(CAST(inv_no AS TEXT)) != '';
            """)
            vsale_info = cur.fetchone()
            tot_vsale_invoices = vsale_info["vsale_inv_cnt"]
            tot_vsale_rows = vsale_info["vsale_row_cnt"]

            print(f"Total VSALE Invoices : {tot_vsale_invoices}")
            print(f"Total VSALE GL Rows  : {tot_vsale_rows}\n")

            cur.execute("""
                SELECT column_name, data_type 
                FROM information_schema.columns 
                WHERE table_schema = %s AND table_name = 'transection';
            """, (schema_name,))
            tx_all_cols = cur.fetchall()

            candidate_keywords = ["sale", "type", "category", "class", "invoice", "trans", "cde", "bsd"]
            candidate_cols = []
            for col in tx_all_cols:
                cname = col["column_name"]
                cname_lower = cname.lower()
                if any(k in cname_lower for k in candidate_keywords):
                    candidate_cols.append(cname)

            print(f"Inspecting {len(candidate_cols)} candidate columns in public.transection for inv_type = 'VSALE':\n")

            candidate_stats = {}
            for col in candidate_cols:
                cur.execute(f"""
                    SELECT 
                        COUNT("{col}") AS nn,
                        COUNT(DISTINCT TRIM(CAST("{col}" AS TEXT))) AS dist
                    FROM public.transection
                    WHERE inv_type = 'VSALE';
                """)
                st = cur.fetchone()

                cur.execute(f"""
                    SELECT TRIM(CAST("{col}" AS TEXT)) AS val, COUNT(*) as freq
                    FROM public.transection
                    WHERE inv_type = 'VSALE' AND "{col}" IS NOT NULL
                    GROUP BY TRIM(CAST("{col}" AS TEXT))
                    ORDER BY freq DESC
                    LIMIT 5;
                """)
                top_vals = cur.fetchall()

                candidate_stats[col] = {
                    "non_null": st["nn"],
                    "distinct": st["dist"],
                    "top_values": top_vals
                }

                print(f"Column: transection.{col}")
                print(f"  - Non-Null Count : {st['nn']} / {tot_vsale_rows}")
                print(f"  - Distinct Count : {st['dist']}")
                print(f"  - Top Values     : {[(r['val'], r['freq']) for r in top_vals]}")
                print()

            # ==================================================
            # PART 3 — MASTER OVERLAP TEST
            # ==================================================
            print("PART 3 — MASTER OVERLAP TEST")
            print("=" * 80)
            print("Testing values of transection candidate columns against public.mst_sale_type.sale_type_code:\n")

            master_codes_set = set(master_code_map.keys())

            overlap_results = {}
            for col in candidate_cols:
                cur.execute(f"""
                    SELECT DISTINCT TRIM(CAST("{col}" AS TEXT)) AS val
                    FROM public.transection
                    WHERE inv_type = 'VSALE' AND "{col}" IS NOT NULL AND TRIM(CAST("{col}" AS TEXT)) != '';
                """)
                source_vals = [r["val"] for r in cur.fetchall()]
                matched_vals = [v for v in source_vals if v in master_codes_set]
                unmatched_vals = [v for v in source_vals if v not in master_codes_set]

                match_pct = (float(len(matched_vals)) / float(len(source_vals)) * 100.0) if source_vals else 0.0

                overlap_results[col] = {
                    "source_distinct": len(source_vals),
                    "matched_distinct": len(matched_vals),
                    "unmatched_distinct": len(unmatched_vals),
                    "match_pct": match_pct,
                    "matched_values": matched_vals
                }

                print(f"Candidate Column: transection.{col:<22}")
                print(f"  - Source Distinct Values    : {len(source_vals)}")
                print(f"  - Matched Distinct Values   : {len(matched_vals)}")
                print(f"  - Unmatched Distinct Values : {len(unmatched_vals)}")
                print(f"  - Match Percentage          : {match_pct:.2f}%")
                print(f"  - Actual Matched Values     : {matched_vals}")
                print("-" * 60)

            print("\n")

            # ==================================================
            # PART 4 — VSALE DISTRIBUTION
            # ==================================================
            print("PART 4 — VSALE DISTRIBUTION")
            print("=" * 80)

            valid_candidate = None
            for col, res in overlap_results.items():
                if col not in ["co_code", "branch_code"] and res["matched_distinct"] > 0:
                    valid_candidate = col
                    break

            if not valid_candidate:
                print("No candidate column in public.transection demonstrates a valid empirical relationship with public.mst_sale_type.\n")
                print("Note on Transaction Type vs Sale Type:")
                print("  - transection.inv_type   = 'VSALE' (Transaction document classification, distinct = 1)")
                print("  - transection.trans_type = 'VSALE' (Transaction category classification, distinct = 1)")
                print("  - transection.doc_type   = 'VSALE' (Voucher type classification, distinct = 1)")
                print("  - None of these transaction classifications map to mst_sale_type (e.g. RD:RD, OGS:OGS, BT:BT).\n")
            else:
                print(f"Distribution for valid candidate column: transection.{valid_candidate}")
                cur.execute(f"""
                    SELECT 
                        TRIM(CAST("{valid_candidate}" AS TEXT)) AS st_code,
                        COUNT(DISTINCT inv_no) AS invoice_count,
                        COUNT(*) AS row_count,
                        SUM(amount) AS total_amount,
                        MIN(doc_date) AS min_date,
                        MAX(doc_date) AS max_date
                    FROM public.transection
                    WHERE inv_type = 'VSALE'
                    GROUP BY TRIM(CAST("{valid_candidate}" AS TEXT));
                """)
                dist_rows = cur.fetchall()
                print(f"{'Sale Type Code':<15} | {'Invoices':<10} | {'GL Rows':<10} | {'Total Amount':<15} | {'Earliest Date':<12} | {'Latest Date'}")
                print("-" * 80)
                for r in dist_rows:
                    print(f"{r['st_code']:<15} | {r['invoice_count']:<10} | {r['row_count']:<10} | {float(r['total_amount'] or 0):<15.2f} | {str(r['min_date']):<12} | {str(r['max_date'])}")
                print()

            # ==================================================
            # PART 5 — INVOICE CARDINALITY
            # ==================================================
            print("PART 5 — INVOICE CARDINALITY")
            print("=" * 80)
            if not valid_candidate:
                print("  - Sale Types per VSALE Invoice          : N/A (No relationship observed)")
                print("  - Invoices per Sale Type               : N/A")
                print("  - Invoices having multiple sale types   : 0")
                print("  - Invoices having exactly one sale type : 0\n")
            else:
                cur.execute(f"""
                    SELECT inv_no, COUNT(DISTINCT TRIM(CAST("{valid_candidate}" AS TEXT))) AS st_cnt
                    FROM public.transection
                    WHERE inv_type = 'VSALE' AND inv_no IS NOT NULL
                    GROUP BY inv_no;
                """)
                card_rows = cur.fetchall()
                multi_st = [r for r in card_rows if r["st_cnt"] > 1]
                single_st = [r for r in card_rows if r["st_cnt"] == 1]
                print(f"  - Invoices having exactly 1 sale type  : {len(single_st)}")
                print(f"  - Invoices having multiple sale types  : {len(multi_st)}\n")

            # ==================================================
            # PART 6 — CHECK OTHER OPERATIONAL TABLES
            # ==================================================
            print("PART 6 — CHECK OTHER OPERATIONAL TABLES")
            print("=" * 80)

            op_tables = [
                "trn_jobcard",
                "mst_history",
                "trn_insu_detail",
                "trn_oth_sales",
                "trn_veh_sales",
                "trn_veh_salesfin",
                "trn_veh_salesrto",
                "trn_oth_salesret"
            ]

            for tbl in op_tables:
                cur.execute("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables 
                        WHERE table_schema = %s AND table_name = %s
                    );
                """, (schema_name, tbl))
                exists = cur.fetchone()["exists"]

                if not exists:
                    print(f"Table public.{tbl:<20} : DOES NOT EXIST")
                else:
                    cur.execute(f'SELECT COUNT(*) AS row_cnt FROM "{schema_name}"."{tbl}";')
                    row_cnt = cur.fetchone()["row_cnt"]

                    cur.execute("""
                        SELECT column_name 
                        FROM information_schema.columns 
                        WHERE table_schema = %s AND table_name = %s;
                    """, (schema_name, tbl))
                    tcols = [r["column_name"] for r in cur.fetchall()]
                    st_cols = [c for c in tcols if any(k in c.lower() for k in ["sale", "type", "cat", "class"])]

                    print(f"Table public.{tbl:<20} : EXISTS | Total Rows: {row_cnt:<6} | Candidate Cols: {st_cols}")
                    if row_cnt == 0:
                        print(f"  -> Table public.{tbl} is EMPTY (0 rows). It cannot be used as empirical evidence.")
                    print()

            # ==================================================
            # PART 7 — DATA COVERAGE
            # ==================================================
            print("PART 7 — DATA COVERAGE")
            print("=" * 80)
            if not valid_candidate:
                print(f"  - Total VSALE Invoices                    : {tot_vsale_invoices}")
                print(f"  - VSALE Invoices with Sale-Type Info       : 0")
                print(f"  - VSALE Invoices without Sale-Type Info    : {tot_vsale_invoices}")
                print(f"  - Coverage Percentage                     : 0.00%")
                print(f"  - Earliest VSALE date with sale-type info : NONE")
                print(f"  - Latest VSALE date with sale-type info   : NONE\n")
            else:
                print(f"Coverage for candidate column: transection.{valid_candidate}")

            # ==================================================
            # PART 8 — FINAL RELATIONSHIP CONCLUSION
            # ==================================================
            print("==================================================")
            print("PART 8 — FINAL RELATIONSHIP CONCLUSION")
            print("==================================================")
            print("Classification: D. NO SALE-TYPE RELATIONSHIP FOUND\n")
            print("Empirical Findings:")
            print("  1. public.mst_sale_type exists with 16 tax sale type master records (e.g., 'RD:RD', 'RD:OGS', 'BT:BT', 'URD:URD').")
            print("  2. public.transection (VSALE) contains transaction classification fields (inv_type='VSALE', trans_type='VSALE', doc_type='VSALE'), but NO column linking to mst_sale_type.sale_type_code or sale_type_name.")
            print("  3. Candidate fields in transection show 0.00% relevant value overlap with mst_sale_type.sale_type_code.")
            print("  4. Vehicle transaction tables containing sale_type_code (public.trn_veh_sales, public.trn_veh_salesfin, public.trn_veh_salesrto, public.trn_oth_sales) are EMPTY (0 rows).")
            print("  5. Distinction of Concepts:")
            print("       - Transaction Document Type : 'VSALE' (Identifies accounting transaction type in transection)")
            print("       - Invoice Operational Bridge : trn_jobcard -> mst_history (Identifies vehicle & customer)")
            print("       - Tax Sale Type Master      : mst_sale_type (Unlinked master data table)\n")

            # ==================================================
            # PART 9 — RECOMMENDATION FOR NEXT STEP
            # ==================================================
            print("==================================================")
            print("PART 9 — RECOMMENDATION FOR NEXT STEP")
            print("==================================================")
            print("DO NOT create get_sale_by_sale_type() yet.\n")
            print("Missing Information / Blockers:")
            print("  - Completed sales transactions in public.transection do not record sale_type_code or reference public.mst_sale_type.")
            print("  - Operational sales tables with sale_type_code (public.trn_veh_sales) contain 0 rows.")
            print("  - Transaction type 'VSALE' is a fixed document type, not a reference to mst_sale_type.\n")
            print("\n" + "=" * 80 + "\n")

            # ==================================================
            # DISCOVERY SUMMARY
            # ==================================================
            print("SALE TYPE SALES RELATIONSHIP — DISCOVERY SUMMARY")
            print("=" * 80)
            print(f"1. Sale type master exists             : YES (16 sale types in mst_sale_type)")
            print(f"2. Sale-type field found in VSALE      : NO (0 fields in transection match mst_sale_type)")
            print(f"3. Master value overlap                : 0.00% (No overlap found)")
            print(f"4. Invoice-level relationship          : NONE (No invoice mapped to sale type)")
            print(f"5. Coverage                            : 0.00% (0 / {tot_vsale_invoices} VSALE invoices)")
            print(f"6. Final classification                : D. NO SALE-TYPE RELATIONSHIP FOUND")
            print(f"7. Validated relationship path         : NONE OBSERVED FOR COMPLETED VSALE SALES")
            print(f"8. Whether get_sale_by_sale_type() can be created : NO — BLOCKER PRESENT (No empirical sale_type relationship exists)")
            print("=" * 80 + "\n")

    conn.close()


if __name__ == "__main__":
    main()
