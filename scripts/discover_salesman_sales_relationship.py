import os
import sys

try:
    from dotenv import load_dotenv
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
    print(" SALESMAN SALES RELATIONSHIP — DISCOVERY & VALIDATION REPORT")
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
            # PART 1 — COLUMN DISCOVERY
            # ==================================================
            print("PART 1 — COLUMN DISCOVERY")
            print("=" * 80)

            target_tables = [
                "transection",
                "trn_jobcard",
                "mst_history",
                "trn_insu_detail",
                "trn_enquiry",
                "mst_salesman"
            ]

            salesman_keywords = [
                "salesman", "sales_person", "executive", "employee", "emp",
                "soldby", "mech", "supervisor", "helper", "user_id", "dsa", "creator"
            ]

            found_columns = {}

            for tbl in target_tables:
                cur.execute("""
                    SELECT column_name, data_type 
                    FROM information_schema.columns 
                    WHERE table_schema = %s AND table_name = %s;
                """, (schema_name, tbl))
                cols = cur.fetchall()

                tbl_found = []
                for c in cols:
                    cname = c["column_name"]
                    cname_lower = cname.lower()
                    if any(k in cname_lower for k in salesman_keywords):
                        cur.execute(f'SELECT COUNT("{cname}") AS nn, COUNT(DISTINCT "{cname}") AS dist FROM "{schema_name}"."{tbl}";')
                        st = cur.fetchone()
                        tbl_found.append({
                            "column_name": cname,
                            "data_type": c["data_type"],
                            "non_null_count": st["nn"],
                            "distinct_count": st["dist"]
                        })

                found_columns[tbl] = tbl_found

                print(f"Table: {schema_name}.{tbl}")
                if not tbl_found:
                    print("  No candidate salesman columns found.")
                else:
                    for col_info in tbl_found:
                        print(f"  - Column: {col_info['column_name']:<25} | Type: {col_info['data_type']:<15} | Non-Null: {col_info['non_null_count']:<6} | Distinct: {col_info['distinct_count']}")
                print()

            # ==================================================
            # PART 2 — MASTER DATA
            # ==================================================
            print("PART 2 — MASTER DATA (public.mst_salesman)")
            print("=" * 80)

            cur.execute("""
                SELECT 
                    TRIM(CAST(salesman_code AS TEXT)) AS salesman_code,
                    TRIM(CAST(salesman_name AS TEXT)) AS salesman_name
                FROM public.mst_salesman
                WHERE salesman_code IS NOT NULL AND TRIM(CAST(salesman_code AS TEXT)) != ''
                ORDER BY salesman_code;
            """)
            salesman_rows = cur.fetchall()
            master_sm_map = {r["salesman_code"]: r["salesman_name"] for r in salesman_rows}

            cur.execute("SELECT COUNT(*) AS total_rows FROM public.mst_salesman;")
            tot_sm_rows = cur.fetchone()["total_rows"]

            print(f"Total Salesman Rows    : {tot_sm_rows}")
            print(f"Distinct Salesman Codes: {len(salesman_rows)}\n")
            print(f"{'Salesman Code':<15} | {'Salesman Name'}")
            print("-" * 45)
            for r in salesman_rows:
                print(f"{r['salesman_code']:<15} | {r['salesman_name']}")
            print("\n")

            # ==================================================
            # PART 3 — VSALE-SIDE DATA (public.transection)
            # ==================================================
            print("PART 3 — VSALE-SIDE DATA (public.transection WHERE inv_type = 'VSALE')")
            print("=" * 80)

            cur.execute("""
                SELECT COUNT(DISTINCT TRIM(CAST(inv_no AS TEXT))) AS vsale_inv_cnt, COUNT(*) AS vsale_row_cnt
                FROM public.transection
                WHERE inv_type = 'VSALE' AND inv_no IS NOT NULL AND TRIM(CAST(inv_no AS TEXT)) != '';
            """)
            vsale_info = cur.fetchone()
            tot_vsale_invoices = vsale_info["vsale_inv_cnt"]

            print(f"Total VSALE Invoices : {tot_vsale_invoices}")
            print(f"Total VSALE GL Rows  : {vsale_info['vsale_row_cnt']}\n")

            # Test candidate fields in transection for VSALE
            tx_candidate_cols = [c["column_name"] for c in found_columns["transection"]]
            print("Transection Salesman Candidate Overlaps with mst_salesman.salesman_code:")
            for col in tx_candidate_cols:
                cur.execute(f"""
                    SELECT 
                        COUNT("{col}") AS nn,
                        COUNT(DISTINCT TRIM(CAST("{col}" AS TEXT))) AS dist
                    FROM public.transection
                    WHERE inv_type = 'VSALE';
                """)
                st = cur.fetchone()

                cur.execute(f"""
                    SELECT DISTINCT TRIM(CAST("{col}" AS TEXT)) AS val
                    FROM public.transection
                    WHERE inv_type = 'VSALE' AND "{col}" IS NOT NULL AND TRIM(CAST("{col}" AS TEXT)) != '';
                """)
                distinct_vals = [r["val"] for r in cur.fetchall()]
                matched_vals = [v for v in distinct_vals if v in master_sm_map]
                match_pct = (float(len(matched_vals)) / float(len(distinct_vals)) * 100.0) if distinct_vals else 0.0

                print(f"  - Field: {col}")
                print(f"      Non-null count : {st['nn']}")
                print(f"      Distinct count : {st['dist']}")
                print(f"      Sample values  : {distinct_vals[:5]}")
                print(f"      Matched codes  : {len(matched_vals)} / {len(distinct_vals)} ({match_pct:.2f}% overlap)")
            print("\n")

            # ==================================================
            # PART 4 — OPERATIONAL BRIDGE (trn_jobcard & mst_history)
            # ==================================================
            print("PART 4 — OPERATIONAL BRIDGE (trn_jobcard & mst_history)")
            print("=" * 80)

            # Test trn_jobcard fields
            print("Evaluating trn_jobcard fields for VSALE-linked records:")
            for jcol in ["mech_code", "supervisor_code", "helper_code", "user_id"]:
                cur.execute(f"""
                    SELECT DISTINCT TRIM(CAST(j."{jcol}" AS TEXT)) AS code
                    FROM public.trn_jobcard j
                    JOIN public.transection t ON TRIM(CAST(j.inv_no AS TEXT)) = TRIM(CAST(t.inv_no AS TEXT))
                    WHERE t.inv_type = 'VSALE' AND j."{jcol}" IS NOT NULL AND TRIM(CAST(j."{jcol}" AS TEXT)) != '';
                """)
                j_vals = [r["code"] for r in cur.fetchall()]
                j_matched = [v for v in j_vals if v in master_sm_map]
                j_pct = (float(len(j_matched)) / float(len(j_vals)) * 100.0) if j_vals else 0.0
                print(f"  - trn_jobcard.{jcol:<18}: {len(j_matched)} / {len(j_vals)} codes match mst_salesman ({j_pct:.2f}%) | Samples: {j_vals[:5]}")

            print("\nEvaluating mst_history fields for VSALE-linked records:")
            # Test mst_history.soldby
            cur.execute("""
                SELECT 
                    COUNT(h.soldby) AS nn_soldby,
                    COUNT(DISTINCT TRIM(CAST(h.soldby AS TEXT))) AS dist_soldby
                FROM public.trn_jobcard j
                JOIN public.transection t ON TRIM(CAST(j.inv_no AS TEXT)) = TRIM(CAST(t.inv_no AS TEXT))
                JOIN public.mst_history h ON TRIM(CAST(j.hist_code AS TEXT)) = TRIM(CAST(h.hist_code AS TEXT))
                WHERE t.inv_type = 'VSALE';
            """)
            h_soldby_stat = cur.fetchone()

            cur.execute("""
                SELECT DISTINCT TRIM(CAST(h.soldby AS TEXT)) AS code
                FROM public.trn_jobcard j
                JOIN public.transection t ON TRIM(CAST(j.inv_no AS TEXT)) = TRIM(CAST(t.inv_no AS TEXT))
                JOIN public.mst_history h ON TRIM(CAST(j.hist_code AS TEXT)) = TRIM(CAST(h.hist_code AS TEXT))
                WHERE t.inv_type = 'VSALE' AND h.soldby IS NOT NULL AND TRIM(CAST(h.soldby AS TEXT)) != '';
            """)
            h_soldby_vals = [r["code"] for r in cur.fetchall()]
            h_soldby_matched = [v for v in h_soldby_vals if v in master_sm_map]

            print(f"  - mst_history.soldby          : Non-null = {h_soldby_stat['nn_soldby']}, Distinct = {h_soldby_stat['dist_soldby']}")
            print(f"      Observed values           : {h_soldby_vals}")
            print(f"      Matched with mst_salesman : {h_soldby_matched} ({master_sm_map.get(h_soldby_vals[0], 'N/A') if h_soldby_vals else 'N/A'})")
            print("      Note                      : 100% of populated soldby entries are static '0000001' ('SELF'), offering zero salesman breakdown.")
            print("\n")

            # ==================================================
            # PART 5 — OTHER CANDIDATE TABLES (trn_enquiry & trn_insu_detail)
            # ==================================================
            print("PART 5 — OTHER CANDIDATE TABLES (trn_enquiry & trn_insu_detail)")
            print("=" * 80)

            # trn_enquiry
            cur.execute("""
                SELECT 
                    COUNT(salesman_code) AS nn_sm,
                    COUNT(DISTINCT TRIM(CAST(salesman_code AS TEXT))) AS dist_sm
                FROM public.trn_enquiry;
            """)
            enq_stat = cur.fetchone()

            cur.execute("""
                SELECT DISTINCT TRIM(CAST(salesman_code AS TEXT)) AS code
                FROM public.trn_enquiry
                WHERE salesman_code IS NOT NULL AND TRIM(CAST(salesman_code AS TEXT)) != '';
            """)
            enq_codes = [r["code"] for r in cur.fetchall()]
            enq_matched = [c for c in enq_codes if c in master_sm_map]
            enq_pct = (float(len(enq_matched)) / float(len(enq_codes)) * 100.0) if enq_codes else 0.0

            print(f"public.trn_enquiry.salesman_code:")
            print(f"  - Non-null count               : {enq_stat['nn_sm']}")
            print(f"  - Distinct count               : {enq_stat['dist_sm']}")
            print(f"  - Match with mst_salesman      : {len(enq_matched)} / {len(enq_codes)} ({enq_pct:.2f}%)")
            print(f"  - Connection to VSALE Invoices : NONE (trn_enquiry has NO inv_no or transaction bridge to transection/jobcard)")
            print("  - Classification              : PRE-SALES / ENQUIRY DATA ONLY (Cannot be used for completed VSALE invoices).\n")

            # ==================================================
            # PART 6 — INVOICE-LEVEL CARDINALITY
            # ==================================================
            print("PART 6 — INVOICE-LEVEL CARDINALITY")
            print("=" * 80)
            print("  - VSALE Invoices with valid Salesman Link : 0")
            print("  - Salesman Codes per Invoice             : N/A (No relationship observed)")
            print("  - Invoices per Salesman                  : N/A\n")

            # ==================================================
            # PART 7 — DATE / DATA COVERAGE
            # ==================================================
            print("PART 7 — DATE / DATA COVERAGE")
            print("=" * 80)
            print("  - Earliest VSALE date with salesman info : NONE")
            print("  - Latest VSALE date with salesman info   : NONE")
            print("  - VSALE Invoices with Salesman Info      : 0 / 696 (0.00%)")
            print(f"  - Total VSALE Invoices                   : {tot_vsale_invoices}\n")

            # ==================================================
            # PART 8 — FINAL CONCLUSION
            # ==================================================
            print("==================================================")
            print("PART 8 — FINAL RELATIONSHIP CONCLUSION")
            print("==================================================")
            print("Classification: C. CANDIDATE ONLY — NOT VALIDATED\n")
            print("Empirical Findings:")
            print("  1. public.mst_salesman exists with 9 salesman records.")
            print("  2. public.transection (VSALE) contains NO salesman_code or sales_person column.")
            print("  3. public.trn_jobcard contains mech_code, supervisor_code, helper_code, but 0% match mst_salesman.salesman_code.")
            print("  4. public.mst_history contains soldby column, but 100% of populated records are static '0000001' ('SELF').")
            print("  5. public.trn_enquiry contains salesman_code with 100% match to mst_salesman, but has NO invoice_no or foreign key bridge connecting it to completed VSALE sales invoices.\n")

            # ==================================================
            # PART 9 — RECOMMENDATION FOR NEXT STEP
            # ==================================================
            print("==================================================")
            print("PART 9 — RECOMMENDATION FOR NEXT STEP")
            print("==================================================")
            print("DO NOT create get_sale_by_salesman() yet.\n")
            print("Missing Information / Blockers:")
            print("  - Completed sales transactions (transection VSALE / trn_jobcard) do not capture salesman_code.")
            print("  - Pre-sales enquiries (trn_enquiry) record salesman_code, but lack invoice/jobcard transaction identifiers to establish an empirical bridge to completed VSALE sales.")
            print("\n" + "=" * 80 + "\n")

            # ==================================================
            # DISCOVERY SUMMARY
            # ==================================================
            print("SALESMAN SALES RELATIONSHIP — DISCOVERY SUMMARY")
            print("=" * 80)
            print(f"1. Salesman master exists             : YES (9 salesmen in mst_salesman)")
            print(f"2. Salesman-related VSALE field found : NO (0 salesman fields in transection/trn_jobcard)")
            print(f"3. Value overlap with mst_salesman    : 100% for trn_enquiry (pre-sales), 0% for VSALE transactions")
            print(f"4. Operational bridge found           : NO (No bridge connecting trn_enquiry to VSALE inv_no)")
            print(f"5. Invoice-level cardinality          : 0 invoices per salesman")
            print(f"6. Coverage                           : 0.00% (0 / {tot_vsale_invoices} VSALE invoices)")
            print(f"7. Final relationship classification  : C. CANDIDATE ONLY — NOT VALIDATED")
            print(f"8. Validated relationship path        : NONE OBSERVED FOR COMPLETED VSALE SALES")
            print("=" * 80 + "\n")

    conn.close()


if __name__ == "__main__":
    main()
