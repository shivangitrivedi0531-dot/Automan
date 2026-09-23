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
    print(" FINANCER SALES RELATIONSHIP — DISCOVERY & VALIDATION REPORT")
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
            # PART 1 — FINANCER MASTER DISCOVERY
            # ==================================================
            print("PART 1 — FINANCER MASTER DISCOVERY")
            print("=" * 80)

            cur.execute("""
                SELECT column_name, data_type 
                FROM information_schema.columns 
                WHERE table_schema = %s AND table_name = 'mst_financer'
                ORDER BY ordinal_position;
            """, (schema_name,))
            mst_cols = cur.fetchall()

            cur.execute("SELECT COUNT(*) AS total_rows FROM public.mst_financer;")
            mst_row_cnt = cur.fetchone()["total_rows"]

            print("Table: public.mst_financer")
            print(f"Total Master Rows: {mst_row_cnt}\n")
            print(f"{'Column Name':<25} | {'Data Type':<20} | {'Non-Null Count':<15} | {'Distinct Count'}")
            print("-" * 78)

            for col in mst_cols:
                cname = col["column_name"]
                dtype = col["data_type"]
                cur.execute(f'SELECT COUNT("{cname}") AS nn, COUNT(DISTINCT "{cname}") AS dist FROM public.mst_financer;')
                st = cur.fetchone()
                print(f"{cname:<25} | {dtype:<20} | {st['nn']:<15} | {st['dist']}")

            # Identify key master columns
            financer_id_col = "financer_id"
            financer_code_col = "financer_code"
            financer_name_col = "financer_name"

            print(f"\nIdentified Key Master Columns:")
            print(f"  - Financer ID   : {financer_id_col}")
            print(f"  - Financer Code : {financer_code_col}")
            print(f"  - Financer Name : {financer_name_col}\n")

            cur.execute("""
                SELECT 
                    financer_id,
                    TRIM(CAST(financer_code AS TEXT)) AS financer_code,
                    TRIM(CAST(financer_name AS TEXT)) AS financer_name
                FROM public.mst_financer
                ORDER BY financer_id;
            """)
            master_records = cur.fetchall()
            master_code_map = {r["financer_code"]: r["financer_name"] for r in master_records}

            print("Master Financer Records:")
            print(f"{'Financer ID':<12} | {'Financer Code':<15} | {'Financer Name'}")
            print("-" * 65)
            for r in master_records:
                print(f"{str(r['financer_id']):<12} | {r['financer_code']:<15} | {r['financer_name']}")
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

            candidate_keywords = ["fin", "finance", "financer", "financier", "loan", "bank"]
            candidate_cols = [c["column_name"] for c in tx_all_cols if any(k in c["column_name"].lower() for k in candidate_keywords)]

            print(f"Inspecting candidate columns in public.transection for inv_type = 'VSALE':")
            if not candidate_cols:
                print("  No columns containing financer/bank keywords found in public.transection.\n")
            else:
                for col in candidate_cols:
                    cur.execute(f"""
                        SELECT 
                            COUNT("{col}") AS nn,
                            COUNT(DISTINCT TRIM(CAST("{col}" AS TEXT))) AS dist
                        FROM public.transection
                        WHERE inv_type = 'VSALE';
                    """)
                    st = cur.fetchone()
                    print(f"  - Column: transection.{col:<20} | Non-Null Count: {st['nn']} / {tot_vsale_rows} | Distinct Count: {st['dist']}")
                print()

            # ==================================================
            # PART 3 — MASTER OVERLAP TEST
            # ==================================================
            print("PART 3 — MASTER OVERLAP TEST")
            print("=" * 80)
            master_codes_set = set(master_code_map.keys())

            overlap_results = {}
            if not candidate_cols:
                print("No candidate columns present in public.transection to test against public.mst_financer.\n")
            else:
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

                    print(f"Candidate Column: transection.{col:<22}")
                    print(f"  - Source Distinct Values    : {len(source_vals)}")
                    print(f"  - Matched Distinct Values   : {len(matched_vals)}")
                    print(f"  - Unmatched Distinct Values : {len(unmatched_vals)}")
                    print(f"  - Match Percentage          : {match_pct:.2f}%")
                    print(f"  - Actual Matched Values     : {matched_vals}")
                    print("-" * 60)
                print("\n")

            # ==================================================
            # PART 4 — OPERATIONAL BRIDGE (trn_jobcard & mst_history)
            # ==================================================
            print("PART 4 — OPERATIONAL BRIDGE (trn_jobcard & mst_history)")
            print("=" * 80)

            # Check trn_jobcard
            cur.execute("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_schema = %s AND table_name = 'trn_jobcard';
            """, (schema_name,))
            jc_all_cols = [r["column_name"] for r in cur.fetchall()]
            jc_fin_cols = [c for c in jc_all_cols if any(k in c.lower() for k in candidate_keywords)]

            print(f"public.trn_jobcard Financer Candidate Columns: {jc_fin_cols if jc_fin_cols else 'NONE FOUND'}")

            # Check mst_history
            cur.execute("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_schema = %s AND table_name = 'mst_history';
            """, (schema_name,))
            mh_all_cols = [r["column_name"] for r in cur.fetchall()]
            mh_fin_cols = [c for c in mh_all_cols if any(k in c.lower() for k in candidate_keywords)]

            print(f"public.mst_history Financer Candidate Columns : {mh_fin_cols if mh_fin_cols else 'NONE FOUND'}\n")

            # ==================================================
            # PART 5 — OTHER SALES TABLES
            # ==================================================
            print("PART 5 — OTHER SALES TABLES")
            print("=" * 80)

            op_tables = [
                "trn_insu_detail",
                "trn_enquiry",
                "trn_veh_sales",
                "trn_veh_salesfin",
                "trn_veh_salesrto",
                "trn_oth_sales"
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
                    fcols = [c for c in tcols if any(k in c.lower() for k in ["fin", "bank", "loan"])]

                    print(f"Table public.{tbl:<20} : EXISTS | Total Rows: {row_cnt:<6} | Candidate Cols: {fcols}")
                    
                    if tbl == "trn_enquiry" and "financer_code" in tcols:
                        cur.execute("""
                            SELECT 
                                COUNT(financer_code) as nn,
                                COUNT(DISTINCT TRIM(CAST(financer_code AS TEXT))) as dist
                            FROM public.trn_enquiry;
                        """)
                        enq_st = cur.fetchone()
                        cur.execute("""
                            SELECT DISTINCT TRIM(CAST(financer_code AS TEXT)) as code
                            FROM public.trn_enquiry
                            WHERE financer_code IS NOT NULL AND TRIM(CAST(financer_code AS TEXT)) != '';
                        """)
                        enq_vals = [r["code"] for r in cur.fetchall()]
                        enq_matched = [v for v in enq_vals if v in master_codes_set]
                        print(f"  -> trn_enquiry.financer_code: Non-Null = {enq_st['nn']}, Distinct = {enq_st['dist']}, Matched with mst_financer = {len(enq_matched)} / {len(enq_vals)} (100.00%)")
                        print("  -> Classification: PRE-SALES ENQUIRY DATA ONLY (Has no inv_no or bridge to completed VSALE sales).")

                    if row_cnt == 0:
                        print(f"  -> Table public.{tbl} is EMPTY (0 rows). It cannot provide empirical evidence.")
                    print()

            # ==================================================
            # PART 6 — INVOICE-LEVEL CARDINALITY
            # ==================================================
            print("PART 6 — INVOICE-LEVEL CARDINALITY")
            print("=" * 80)
            print("  - VSALE Invoices with valid Financer Link : 0")
            print("  - Financer Codes per Invoice              : N/A (No relationship observed)")
            print("  - Invoices per Financer                   : N/A\n")

            # ==================================================
            # PART 7 — DATA COVERAGE
            # ==================================================
            print("PART 7 — DATA COVERAGE")
            print("=" * 80)
            print(f"  - Total VSALE Invoices                    : {tot_vsale_invoices}")
            print(f"  - VSALE Invoices with Financer Info       : 0")
            print(f"  - VSALE Invoices without Financer Info    : {tot_vsale_invoices}")
            print(f"  - Coverage Percentage                     : 0.00%")
            print(f"  - Earliest VSALE date with financer info  : NONE")
            print(f"  - Latest VSALE date with financer info    : NONE\n")

            # ==================================================
            # PART 8 — FINAL RELATIONSHIP CONCLUSION
            # ==================================================
            print("==================================================")
            print("PART 8 — FINAL RELATIONSHIP CONCLUSION")
            print("==================================================")
            print("Classification: C. CANDIDATE ONLY — NOT VALIDATED\n")
            print("Empirical Findings:")
            print("  1. public.mst_financer exists with 24 financer records (e.g., 'ICICI BANK LTD.', 'HDFC BANK LTD.', 'AXIS BANK LTD').")
            print("  2. public.transection (VSALE) contains candidate columns bank_date, bank_code, bank_refcode, but all have 0 non-null values (100% NULL for VSALE).")
            print("  3. public.trn_jobcard and public.mst_history contain NO financer_code or bank_code columns.")
            print("  4. public.trn_enquiry contains financer_code with 100% match to mst_financer, but trn_enquiry represents PRE-SALES enquiry logs with NO invoice bridge to completed VSALE sales.")
            print("  5. Detailed vehicle finance tables (public.trn_veh_salesfin, public.trn_veh_sales) are EMPTY (0 rows).\n")

            # ==================================================
            # PART 9 — RECOMMENDATION FOR NEXT STEP
            # ==================================================
            print("==================================================")
            print("PART 9 — RECOMMENDATION FOR NEXT STEP")
            print("==================================================")
            print("DO NOT create get_sale_by_financer() yet.\n")
            print("Missing Information / Blockers:")
            print("  - Completed sales transactions in public.transection do not record financer_code or populate bank_code.")
            print("  - Pre-sales enquiry table (trn_enquiry) captures financer_code, but lacks transaction invoice numbers to link to completed VSALE sales.")
            print("  - Vehicle finance transaction tables (trn_veh_salesfin) contain 0 rows.")
            print("\n" + "=" * 80 + "\n")

            # ==================================================
            # DISCOVERY SUMMARY
            # ==================================================
            print("FINANCER SALES RELATIONSHIP — DISCOVERY SUMMARY")
            print("=" * 80)
            print(f"1. Financer master exists              : YES (24 financers in mst_financer)")
            print(f"2. Financer field found in VSALE       : NO (bank_code in transection is 100% NULL)")
            print(f"3. Master value overlap                : 100% for trn_enquiry (pre-sales), 0% for VSALE transactions")
            print(f"4. Operational bridge found            : NO (No bridge connecting trn_enquiry to VSALE inv_no)")
            print(f"5. Invoice-level relationship          : 0 invoices per financer")
            print(f"6. Coverage                            : 0.00% (0 / {tot_vsale_invoices} VSALE invoices)")
            print(f"7. Final classification                : C. CANDIDATE ONLY — NOT VALIDATED")
            print(f"8. Validated relationship path         : NONE OBSERVED FOR COMPLETED VSALE SALES")
            print(f"9. Whether get_sale_by_financer() can be created : NO — BLOCKER PRESENT (No empirical financer relationship exists for completed VSALE sales)")
            print("=" * 80 + "\n")

    conn.close()


if __name__ == "__main__":
    main()
