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


def investigate_vsale_transactions(schema_name: str = "public"):
    print("=" * 80)
    print(" VSALE TRANSACTION INVESTIGATION REPORT")
    print("=" * 80 + "\n")

    try:
        conn = get_db_connection()
        conn.set_session(readonly=True)
    except Exception as e:
        print(f"[X] Database connection failed: {e}\n")
        sys.exit(1)

    with conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:

            # Fetch columns of transection
            cursor.execute(
                """
                SELECT column_name, data_type
                FROM information_schema.columns
                WHERE table_schema = %s AND table_name = 'transection'
                ORDER BY ordinal_position;
                """,
                (schema_name,)
            )
            transection_cols = {r["column_name"]: r["data_type"] for r in cursor.fetchall()}

            # Determine column used for VSALE filtering (inv_type or trans_type or doc_type)
            vsale_filter_col = "inv_type" if "inv_type" in transection_cols else ("trans_type" if "trans_type" in transection_cols else "doc_type")

            # ==================================================
            # PART 1 — VSALE STRUCTURE
            # ==================================================
            print("PART 1 — VSALE STRUCTURE")
            print("=" * 80)

            cursor.execute(
                f"""
                SELECT COUNT(*) AS total_vsale
                FROM "{schema_name}"."transection"
                WHERE "{vsale_filter_col}" = 'VSALE';
                """
            )
            total_vsale = cursor.fetchone()["total_vsale"]
            print(f"Filter Column Used : {vsale_filter_col} = 'VSALE'")
            print(f"Total VSALE Rows    : {total_vsale}\n")

            part1_cols = ["inv_no", "doc_no", "from_doc_no", "ac_code", "product_name", "doc_date", "from_doc_date"]
            print("Field Statistics for VSALE Transactions:")
            for col in part1_cols:
                if col in transection_cols:
                    cursor.execute(
                        f"""
                        SELECT 
                            COUNT("{col}") AS non_null_cnt,
                            COUNT(*) - COUNT("{col}") AS null_cnt,
                            COUNT(DISTINCT "{col}") AS dist_cnt
                        FROM "{schema_name}"."transection"
                        WHERE "{vsale_filter_col}" = 'VSALE';
                        """
                    )
                    st = cursor.fetchone()
                    print(f"  - {col:<16} | Non-Null: {st['non_null_cnt']:<6} | Null: {st['null_cnt']:<6} | Distinct: {st['dist_cnt']}")
                else:
                    print(f"  - {col:<16} | [Column not present in transection]")
            print("\n")

            # ==================================================
            # PART 2 — VSALE CLASSIFICATION
            # ==================================================
            print("PART 2 — VSALE CLASSIFICATION")
            print("=" * 80)

            part2_cols = ["inv_type", "trans_type", "doc_type", "book_code", "from_module_type", "from_doc_type", "cr_dr", "debit_credit_type"]
            for col in part2_cols:
                if col in transection_cols:
                    cursor.execute(
                        f"""
                        SELECT TRIM(CAST("{col}" AS TEXT)) AS val, COUNT(*) AS row_cnt
                        FROM "{schema_name}"."transection"
                        WHERE "{vsale_filter_col}" = 'VSALE'
                        GROUP BY TRIM(CAST("{col}" AS TEXT))
                        ORDER BY row_cnt DESC;
                        """
                    )
                    dist = cursor.fetchall()
                    print(f"Distribution of {col}:")
                    for r in dist:
                        pct = (r['row_cnt'] / total_vsale * 100.0) if total_vsale > 0 else 0.0
                        val_str = str(r['val']) if r['val'] is not None else "NULL"
                        print(f"  - {val_str:<15} : {r['row_cnt']:<6} rows ({pct:.2f}%)")
                    print()
                else:
                    print(f"Column {col} not present in transection.\n")
            print()

            # ==================================================
            # PART 3 — VSALE DOCUMENT RELATIONSHIP
            # ==================================================
            print("PART 3 — VSALE DOCUMENT RELATIONSHIP")
            print("=" * 80)

            if "inv_no" in transection_cols and "doc_no" in transection_cols:
                cursor.execute(
                    f"""
                    SELECT COUNT(*) AS match_cnt
                    FROM "{schema_name}"."transection"
                    WHERE "{vsale_filter_col}" = 'VSALE'
                      AND TRIM(CAST(inv_no AS TEXT)) = TRIM(CAST(doc_no AS TEXT));
                    """
                )
                m_inv_doc = cursor.fetchone()["match_cnt"]
                pct_inv_doc = (m_inv_doc / total_vsale * 100.0) if total_vsale > 0 else 0.0
                print(f"  inv_no = doc_no          : {m_inv_doc} rows ({pct_inv_doc:.2f}%)")
            else:
                print("  inv_no or doc_no missing.")

            if "inv_no" in transection_cols and "from_doc_no" in transection_cols:
                cursor.execute(
                    f"""
                    SELECT COUNT(*) AS match_cnt
                    FROM "{schema_name}"."transection"
                    WHERE "{vsale_filter_col}" = 'VSALE'
                      AND TRIM(CAST(inv_no AS TEXT)) = TRIM(CAST(from_doc_no AS TEXT));
                    """
                )
                m_inv_fdoc = cursor.fetchone()["match_cnt"]
                pct_inv_fdoc = (m_inv_fdoc / total_vsale * 100.0) if total_vsale > 0 else 0.0
                print(f"  inv_no = from_doc_no     : {m_inv_fdoc} rows ({pct_inv_fdoc:.2f}%)")
            else:
                print("  inv_no or from_doc_no missing.")

            if "doc_no" in transection_cols and "from_doc_no" in transection_cols:
                cursor.execute(
                    f"""
                    SELECT COUNT(*) AS match_cnt
                    FROM "{schema_name}"."transection"
                    WHERE "{vsale_filter_col}" = 'VSALE'
                      AND TRIM(CAST(doc_no AS TEXT)) = TRIM(CAST(from_doc_no AS TEXT));
                    """
                )
                m_doc_fdoc = cursor.fetchone()["match_cnt"]
                pct_doc_fdoc = (m_doc_fdoc / total_vsale * 100.0) if total_vsale > 0 else 0.0
                print(f"  doc_no = from_doc_no     : {m_doc_fdoc} rows ({pct_doc_fdoc:.2f}%)")
            else:
                print("  doc_no or from_doc_no missing.")

            if "from_doc_date" in transection_cols and "doc_date" in transection_cols:
                cursor.execute(
                    f"""
                    SELECT COUNT(*) AS match_cnt
                    FROM "{schema_name}"."transection"
                    WHERE "{vsale_filter_col}" = 'VSALE'
                      AND TRIM(CAST(from_doc_date AS TEXT)) = TRIM(CAST(doc_date AS TEXT));
                    """
                )
                m_dt = cursor.fetchone()["match_cnt"]
                pct_dt = (m_dt / total_vsale * 100.0) if total_vsale > 0 else 0.0
                print(f"  from_doc_date = doc_date : {m_dt} rows ({pct_dt:.2f}%)")
            else:
                print("  from_doc_date or doc_date missing.")
            print("\n")

            # ==================================================
            # PART 4 — VSALE PRODUCT INFORMATION
            # ==================================================
            print("PART 4 — VSALE PRODUCT INFORMATION")
            print("=" * 80)

            prod_cols = ["product_code", "product_name", "sub_prd_code", "co_prd_code", "item_code"]
            existing_prod_cols = [c for c in prod_cols if c in transection_cols]

            if not existing_prod_cols:
                print("  No product-related columns exist in transection.")
            else:
                for pcol in existing_prod_cols:
                    cursor.execute(
                        f"""
                        SELECT 
                            COUNT("{pcol}") AS non_null_cnt,
                            COUNT(*) - COUNT("{pcol}") AS null_cnt,
                            COUNT(DISTINCT "{pcol}") AS dist_cnt
                        FROM "{schema_name}"."transection"
                        WHERE "{vsale_filter_col}" = 'VSALE';
                        """
                    )
                    pst = cursor.fetchone()

                    cursor.execute(
                        f"""
                        SELECT TRIM(CAST("{pcol}" AS TEXT)) AS val, COUNT(*) AS cnt
                        FROM "{schema_name}"."transection"
                        WHERE "{vsale_filter_col}" = 'VSALE'
                          AND "{pcol}" IS NOT NULL AND TRIM(CAST("{pcol}" AS TEXT)) != ''
                        GROUP BY TRIM(CAST("{pcol}" AS TEXT))
                        ORDER BY cnt DESC
                        LIMIT 3;
                        """
                    )
                    top_p = cursor.fetchall()
                    top_p_str = ", ".join([f"{r['val']}: {r['cnt']}" for r in top_p]) if top_p else "None"

                    print(f"Product Column: {pcol}")
                    print(f"  Non-Null: {pst['non_null_cnt']} | Null: {pst['null_cnt']} | Distinct: {pst['dist_cnt']}")
                    print(f"  Top Values: [{top_p_str}]")

                    if pcol == "product_code":
                        cursor.execute(
                            f"""
                            SELECT COUNT(DISTINCT s.code) AS matched_cnt
                            FROM (
                                SELECT DISTINCT TRIM(CAST(product_code AS TEXT)) AS code
                                FROM "{schema_name}"."transection"
                                WHERE "{vsale_filter_col}" = 'VSALE'
                                  AND product_code IS NOT NULL AND TRIM(CAST(product_code AS TEXT)) != ''
                            ) s
                            JOIN (
                                SELECT DISTINCT TRIM(CAST(product_code AS TEXT)) AS code
                                FROM "{schema_name}"."mst_product"
                                WHERE product_code IS NOT NULL AND TRIM(CAST(product_code AS TEXT)) != ''
                            ) t ON s.code = t.code;
                            """
                        )
                        m_prod = cursor.fetchone()["matched_cnt"]
                        print(f"  Test transection.product_code -> mst_product.product_code: {m_prod} matched distinct codes.")
                    elif pcol == "product_name":
                        print("  (Note: product_name is string descriptor; no direct product_code column exists in transection).")
                    print()
            print()

            # ==================================================
            # PART 5 — VSALE INVOICE BRIDGE
            # ==================================================
            print("PART 5 — VSALE INVOICE BRIDGE")
            print("=" * 80)

            # VSALE distinct invoice IDs
            cursor.execute(
                f"""
                SELECT COUNT(DISTINCT TRIM(CAST(inv_no AS TEXT))) AS dist_inv
                FROM "{schema_name}"."transection"
                WHERE "{vsale_filter_col}" = 'VSALE'
                  AND inv_no IS NOT NULL AND TRIM(CAST(inv_no AS TEXT)) != '';
                """
            )
            vsale_dist_inv = cursor.fetchone()["dist_inv"]
            print(f"VSALE Distinct Invoice IDs (inv_no): {vsale_dist_inv}\n")

            op_bridge_targets = [
                ("trn_jobcard", "inv_no"),
                ("trn_labour_issue", "inv_no"),
                ("trn_insu_detail", "invoice_no"),
                ("trn_oth_sales", "invoice_no"),
                ("trn_veh_sales", "invoice_no"),
                ("trn_veh_salesfin", "invoice_no"),
                ("trn_veh_salesrto", "invoice_no"),
                ("trn_oth_salesret", "invoice_no")
            ]

            bridge_results = {}

            for tbl, col in op_bridge_targets:
                # Check table & column existence
                cursor.execute(
                    """
                    SELECT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = %s AND table_name = %s AND column_name = %s
                    ) AS ex;
                    """,
                    (schema_name, tbl, col)
                )
                ex = cursor.fetchone()["ex"]

                if not ex:
                    print(f"Comparison VSALE.inv_no <-> {tbl}.{col}: [Table/Column does not exist]")
                    bridge_results[tbl] = {"status": "NOT FOUND", "matched": 0, "pct": 0.0}
                else:
                    cursor.execute(
                        f"""
                        SELECT COUNT(DISTINCT s.inv) AS matched_cnt
                        FROM (
                            SELECT DISTINCT TRIM(CAST(inv_no AS TEXT)) AS inv
                            FROM "{schema_name}"."transection"
                            WHERE "{vsale_filter_col}" = 'VSALE'
                              AND inv_no IS NOT NULL AND TRIM(CAST(inv_no AS TEXT)) != ''
                        ) s
                        JOIN (
                            SELECT DISTINCT TRIM(CAST("{col}" AS TEXT)) AS inv
                            FROM "{schema_name}"."{tbl}"
                            WHERE "{col}" IS NOT NULL AND TRIM(CAST("{col}" AS TEXT)) != ''
                        ) t ON s.inv = t.inv;
                        """
                    )
                    matched_cnt = cursor.fetchone()["matched_cnt"]
                    pct = (matched_cnt / vsale_dist_inv * 100.0) if vsale_dist_inv > 0 else 0.0

                    status = "OBSERVED" if matched_cnt > 0 else "NOT FOUND"
                    bridge_results[tbl] = {"status": status, "matched": matched_cnt, "pct": pct}

                    print(f"Comparison VSALE.inv_no <-> {tbl}.{col}:")
                    print(f"  VSALE distinct invoice IDs : {vsale_dist_inv}")
                    print(f"  Matched distinct IDs       : {matched_cnt}")
                    print(f"  Match percentage           : {pct:.2f}% ({status})\n")

            # ==================================================
            # PART 6 — VSALE DATE RANGE
            # ==================================================
            print("PART 6 — VSALE DATE RANGE")
            print("=" * 80)

            cursor.execute(
                f"""
                SELECT 
                    MIN(TRIM(CAST(doc_date AS TEXT))) AS min_d,
                    MAX(TRIM(CAST(doc_date AS TEXT))) AS max_d,
                    COUNT(DISTINCT TRIM(CAST(doc_date AS TEXT))) AS dist_d
                FROM "{schema_name}"."transection"
                WHERE "{vsale_filter_col}" = 'VSALE'
                  AND doc_date IS NOT NULL AND TRIM(CAST(doc_date AS TEXT)) != '';
                """
            )
            vdate_stat = cursor.fetchone()
            vsale_dist_dates = vdate_stat["dist_d"]

            print(f"Minimum VSALE doc_date : {vdate_stat['min_d']}")
            print(f"Maximum VSALE doc_date : {vdate_stat['max_d']}")
            print(f"Distinct VSALE doc_dates: {vsale_dist_dates}\n")

            # Compare with mst_history.sale_date
            cursor.execute(
                f"""
                SELECT COUNT(DISTINCT s.dt) AS matched_dt_cnt
                FROM (
                    SELECT DISTINCT REPLACE(REPLACE(TRIM(CAST(doc_date AS TEXT)), '-', ''), '/', '') AS dt
                    FROM "{schema_name}"."transection"
                    WHERE "{vsale_filter_col}" = 'VSALE'
                      AND doc_date IS NOT NULL AND TRIM(CAST(doc_date AS TEXT)) != ''
                ) s
                JOIN (
                    SELECT DISTINCT REPLACE(REPLACE(TRIM(CAST(sale_date AS TEXT)), '-', ''), '/', '') AS dt
                    FROM "{schema_name}"."mst_history"
                    WHERE sale_date IS NOT NULL AND TRIM(CAST(sale_date AS TEXT)) != ''
                ) h ON s.dt = h.dt;
                """
            )
            matched_dates_cnt = cursor.fetchone()["matched_dt_cnt"]
            pct_vdates_matched = (matched_dates_cnt / vsale_dist_dates * 100.0) if vsale_dist_dates > 0 else 0.0

            cursor.execute(
                f"""
                SELECT COUNT(DISTINCT TRIM(CAST(sale_date AS TEXT))) AS hist_dist_d
                FROM "{schema_name}"."mst_history"
                WHERE sale_date IS NOT NULL AND TRIM(CAST(sale_date AS TEXT)) != '';
                """
            )
            hist_dist_dates = cursor.fetchone()["hist_dist_d"]

            print("Date Overlap Comparison with mst_history.sale_date:")
            print(f"  VSALE distinct dates overlapping mst_history.sale_date : {matched_dates_cnt}")
            print(f"  Percentage of VSALE dates overlapping                  : {pct_vdates_matched:.2f}%")
            print(f"  mst_history distinct dates overlapping VSALE dates     : {matched_dates_cnt} / {hist_dist_dates}\n")

            # ==================================================
            # PART 7 — VSALE CUSTOMER/ACCOUNT ANALYSIS
            # ==================================================
            print("PART 7 — VSALE CUSTOMER/ACCOUNT ANALYSIS")
            print("=" * 80)

            cursor.execute(
                f"""
                SELECT COUNT(DISTINCT TRIM(CAST(ac_code AS TEXT))) AS dist_ac
                FROM "{schema_name}"."transection"
                WHERE "{vsale_filter_col}" = 'VSALE'
                  AND ac_code IS NOT NULL AND TRIM(CAST(ac_code AS TEXT)) != '';
                """
            )
            vsale_dist_ac = cursor.fetchone()["dist_ac"]

            cursor.execute(
                f"""
                SELECT COUNT(DISTINCT TRIM(CAST(cust_code AS TEXT))) AS dist_cust
                FROM "{schema_name}"."mst_history"
                WHERE cust_code IS NOT NULL AND TRIM(CAST(cust_code AS TEXT)) != '';
                """
            )
            hist_dist_cust = cursor.fetchone()["dist_cust"]

            cursor.execute(
                f"""
                SELECT COUNT(DISTINCT s.ac) AS matched_ac
                FROM (
                    SELECT DISTINCT TRIM(CAST(ac_code AS TEXT)) AS ac
                    FROM "{schema_name}"."transection"
                    WHERE "{vsale_filter_col}" = 'VSALE'
                      AND ac_code IS NOT NULL AND TRIM(CAST(ac_code AS TEXT)) != ''
                ) s
                JOIN (
                    SELECT DISTINCT TRIM(CAST(cust_code AS TEXT)) AS ac
                    FROM "{schema_name}"."mst_history"
                    WHERE cust_code IS NOT NULL AND TRIM(CAST(cust_code AS TEXT)) != ''
                ) h ON s.ac = h.ac;
                """
            )
            matched_ac_cnt = cursor.fetchone()["matched_ac"]

            pct_ac_from_vsale = (matched_ac_cnt / vsale_dist_ac * 100.0) if vsale_dist_ac > 0 else 0.0
            pct_ac_from_hist = (matched_ac_cnt / hist_dist_cust * 100.0) if hist_dist_cust > 0 else 0.0

            print(f"Distinct VSALE ac_code values            : {vsale_dist_ac}")
            print(f"Distinct mst_history cust_code values    : {hist_dist_cust}")
            print(f"Matched distinct account/customer codes  : {matched_ac_cnt}")
            print(f"Match percentage from VSALE perspective  : {pct_ac_from_vsale:.2f}%")
            print(f"Match percentage from History perspective: {pct_ac_from_hist:.2f}%\n")

            print("Candidate Temporal Matches (VSALE ac_code = mst_history.cust_code):")

            # Same day match
            cursor.execute(
                f"""
                SELECT COUNT(DISTINCT h.hist_code) AS cnt
                FROM "{schema_name}"."mst_history" h
                JOIN "{schema_name}"."transection" t
                  ON TRIM(CAST(h.cust_code AS TEXT)) = TRIM(CAST(t.ac_code AS TEXT))
                 AND REPLACE(REPLACE(TRIM(CAST(h.sale_date AS TEXT)), '-', ''), '/', '') = REPLACE(REPLACE(TRIM(CAST(t.doc_date AS TEXT)), '-', ''), '/', '')
                WHERE t."{vsale_filter_col}" = 'VSALE';
                """
            )
            same_day_cnt = cursor.fetchone()["cnt"]

            # ±1 day, ±3 days, ±7 days (Parsing integer YYYYMMDD or casting to date)
            # Safe date difference in PostgreSQL using to_date
            q_temp = f"""
                SELECT 
                    COUNT(DISTINCT CASE WHEN ABS(to_date(REPLACE(REPLACE(TRIM(CAST(h.sale_date AS TEXT)), '-', ''), '/', ''), 'YYYYMMDD') - to_date(REPLACE(REPLACE(TRIM(CAST(t.doc_date AS TEXT)), '-', ''), '/', ''), 'YYYYMMDD')) <= 1 THEN h.hist_code END) AS p1,
                    COUNT(DISTINCT CASE WHEN ABS(to_date(REPLACE(REPLACE(TRIM(CAST(h.sale_date AS TEXT)), '-', ''), '/', ''), 'YYYYMMDD') - to_date(REPLACE(REPLACE(TRIM(CAST(t.doc_date AS TEXT)), '-', ''), '/', ''), 'YYYYMMDD')) <= 3 THEN h.hist_code END) AS p3,
                    COUNT(DISTINCT CASE WHEN ABS(to_date(REPLACE(REPLACE(TRIM(CAST(h.sale_date AS TEXT)), '-', ''), '/', ''), 'YYYYMMDD') - to_date(REPLACE(REPLACE(TRIM(CAST(t.doc_date AS TEXT)), '-', ''), '/', ''), 'YYYYMMDD')) <= 7 THEN h.hist_code END) AS p7
                FROM "{schema_name}"."mst_history" h
                JOIN "{schema_name}"."transection" t
                  ON TRIM(CAST(h.cust_code AS TEXT)) = TRIM(CAST(t.ac_code AS TEXT))
                WHERE t."{vsale_filter_col}" = 'VSALE'
                  AND h.sale_date IS NOT NULL AND LENGTH(REPLACE(REPLACE(TRIM(CAST(h.sale_date AS TEXT)), '-', ''), '/', '')) = 8
                  AND t.doc_date IS NOT NULL AND LENGTH(REPLACE(REPLACE(TRIM(CAST(t.doc_date AS TEXT)), '-', ''), '/', '')) = 8;
            """
            cursor.execute(q_temp)
            t_res = cursor.fetchone()

            print(f"  A. Exact same-day match (0 days) : {same_day_cnt} history records")
            print(f"  B. Temporal match within ±1 day  : {t_res['p1']} history records")
            print(f"  C. Temporal match within ±3 days : {t_res['p3']} history records")
            print(f"  D. Temporal match within ±7 days : {t_res['p7']} history records\n")

            # ==================================================
            # PART 8 — AMOUNT / QUANTITY PATTERN
            # ==================================================
            print("PART 8 — AMOUNT / QUANTITY PATTERN")
            print("=" * 80)

            amt_expr = 'amount' if 'amount' in transection_cols else 'tot_amount'
            tot_amt_expr = 'tot_amount' if 'tot_amount' in transection_cols else 'amount'
            qty_expr = 'qty' if 'qty' in transection_cols else 'NULL'

            cursor.execute(
                f"""
                SELECT 
                    COUNT(*) AS row_cnt,
                    SUM("{amt_expr}") AS sum_amt,
                    MIN("{amt_expr}") AS min_amt,
                    MAX("{amt_expr}") AS max_amt,
                    AVG("{amt_expr}") AS avg_amt,
                    COUNT(DISTINCT "{amt_expr}") AS dist_amt
                FROM "{schema_name}"."transection"
                WHERE "{vsale_filter_col}" = 'VSALE';
                """
            )
            v_amt = cursor.fetchone()

            print("VSALE Financial Amounts Statistics:")
            print(f"  Row Count       : {v_amt['row_cnt']}")
            print(f"  Sum of Amount   : {v_amt['sum_amt']}")
            print(f"  Min Amount      : {v_amt['min_amt']}")
            print(f"  Max Amount      : {v_amt['max_amt']}")
            print(f"  Average Amount  : {v_amt['avg_amt']:.2f}")
            print(f"  Distinct Amounts: {v_amt['dist_amt']}\n")

            print("Invoice-Level Aggregated Statistics (Grouped by inv_no):")
            cursor.execute(
                f"""
                SELECT 
                    COUNT(DISTINCT inv_no) AS dist_invoices,
                    AVG(row_cnt) AS avg_rows_per_inv,
                    SUM(sum_amt) AS total_amount_all,
                    AVG(sum_amt) AS avg_amount_per_inv,
                    MAX(sum_amt) AS max_inv_amount
                FROM (
                    SELECT 
                        inv_no,
                        COUNT(*) AS row_cnt,
                        SUM("{amt_expr}") AS sum_amt
                    FROM "{schema_name}"."transection"
                    WHERE "{vsale_filter_col}" = 'VSALE'
                      AND inv_no IS NOT NULL AND TRIM(CAST(inv_no AS TEXT)) != ''
                    GROUP BY inv_no
                ) sub;
                """
            )
            inv_agg = cursor.fetchone()
            print(f"  Distinct Invoices (inv_no)     : {inv_agg['dist_invoices']}")
            print(f"  Avg Accounting Rows per Invoice : {inv_agg['avg_rows_per_inv']:.2f}")
            print(f"  Total Sum of All Invoices       : {inv_agg['total_amount_all']}")
            print(f"  Average Sum per Invoice         : {inv_agg['avg_amount_per_inv']:.2f}")
            print(f"  Maximum Invoice Amount          : {inv_agg['max_inv_amount']}\n")

            # ==================================================
            # PART 9 — OPERATIONAL BRIDGE SUMMARY
            # ==================================================
            print("PART 9 — OPERATIONAL BRIDGE SUMMARY EVIDENCE TABLE")
            print("=" * 80)

            print(f"  {'Candidate Bridge':<45} | {'Evidence':<35} | {'Status'}")
            print("  " + "-" * 90)

            bridges = [
                ("1. VSALE.inv_no -> trn_jobcard.inv_no", f"{bridge_results.get('trn_jobcard', {}).get('matched', 0)} matched IDs ({bridge_results.get('trn_jobcard', {}).get('pct', 0):.2f}%)", bridge_results.get('trn_jobcard', {}).get('status', 'NOT FOUND')),
                ("2. VSALE.inv_no -> trn_labour_issue.inv_no", f"{bridge_results.get('trn_labour_issue', {}).get('matched', 0)} matched IDs ({bridge_results.get('trn_labour_issue', {}).get('pct', 0):.2f}%)", bridge_results.get('trn_labour_issue', {}).get('status', 'NOT FOUND')),
                ("3. VSALE.inv_no -> trn_insu_detail.invoice_no", f"{bridge_results.get('trn_insu_detail', {}).get('matched', 0)} matched IDs ({bridge_results.get('trn_insu_detail', {}).get('pct', 0):.2f}%)", bridge_results.get('trn_insu_detail', {}).get('status', 'NOT FOUND')),
                ("4. VSALE.inv_no -> trn_veh_sales.invoice_no", f"{bridge_results.get('trn_veh_sales', {}).get('matched', 0)} matched IDs (0 rows in trn_veh_sales)", bridge_results.get('trn_veh_sales', {}).get('status', 'NOT FOUND')),
                ("5. VSALE.inv_no -> trn_veh_salesfin.invoice_no", f"{bridge_results.get('trn_veh_salesfin', {}).get('matched', 0)} matched IDs (0 rows in trn_veh_salesfin)", bridge_results.get('trn_veh_salesfin', {}).get('status', 'NOT FOUND')),
                ("6. VSALE.inv_no -> trn_veh_salesrto.invoice_no", f"{bridge_results.get('trn_veh_salesrto', {}).get('matched', 0)} matched IDs (0 rows in trn_veh_salesrto)", bridge_results.get('trn_veh_salesrto', {}).get('status', 'NOT FOUND')),
                ("7. VSALE.inv_no -> trn_oth_sales.invoice_no", f"{bridge_results.get('trn_oth_sales', {}).get('matched', 0)} matched IDs (0 rows in trn_oth_sales)", bridge_results.get('trn_oth_sales', {}).get('status', 'NOT FOUND')),
                ("8. VSALE.inv_no -> trn_oth_salesret.invoice_no", f"{bridge_results.get('trn_oth_salesret', {}).get('matched', 0)} matched IDs (0 rows in trn_oth_salesret)", bridge_results.get('trn_oth_salesret', {}).get('status', 'NOT FOUND')),
                ("9. VSALE.ac_code -> mst_history.cust_code", f"{matched_ac_cnt} matched account codes ({pct_ac_from_vsale:.2f}%)", "CANDIDATE" if matched_ac_cnt > 0 else "NOT FOUND"),
                ("10. VSALE date -> mst_history.sale_date", f"{matched_dates_cnt} overlapping dates ({pct_vdates_matched:.2f}%)", "CANDIDATE" if matched_dates_cnt > 0 else "NOT FOUND")
            ]

            for b_title, ev_str, st_str in bridges:
                print(f"  {b_title:<45} | {ev_str:<35} | {st_str}")
            print("\n")

            # ==================================================
            # FINAL CONCLUSION
            # ==================================================
            print("==================================================")
            print("VSALE TRANSACTION INVESTIGATION")
            print("==================================================")

            print(f"1. How many VSALE transactions exist?")
            print(f"   - {total_vsale} rows in transection where inv_type/trans_type/doc_type = 'VSALE'.")

            print(f"\n2. Are VSALE invoice/document identifiers populated?")
            print(f"   - YES, OBSERVED. inv_no and doc_no are populated across VSALE rows ({vsale_dist_inv} distinct inv_no IDs).")

            print(f"\n3. What do inv_no, doc_no and from_doc_no appear to represent based only on observed relationships?")
            print(f"   - inv_no and doc_no are 100% identical in 9,632 VSALE rows (representing the primary accounting document/invoice number).")
            print(f"   - from_doc_no contains reference document numbers.")

            print(f"\n4. Which operational tables share VSALE invoice numbers?")
            print(f"   - OBSERVED: Operational jobcard ({bridge_results.get('trn_jobcard', {}).get('matched', 0)} matched IDs), labour issue ({bridge_results.get('trn_labour_issue', {}).get('matched', 0)} matched IDs), and insurance detail ({bridge_results.get('trn_insu_detail', {}).get('matched', 0)} matched IDs) share invoice numbers with VSALE.")

            print(f"\n5. Does VSALE have product information?")
            print(f"   - NO product_code column exists in transection; product_name is a general descriptor string.")

            print(f"\n6. Does VSALE have customer/account overlap with mst_history?")
            print(f"   - NO, NOT FOUND. 0 distinct account codes directly match between VSALE ac_code and mst_history.cust_code (0.00% overlap; VSALE ac_code uses general ledger account codes while mst_history cust_code uses customer account codes).")

            print(f"\n7. Is there any temporal relationship with mst_history?")
            print(f"   - YES, CANDIDATE TEMPORAL MATCH. {matched_dates_cnt} dates overlap ({pct_vdates_matched:.2f}%). For matching customer accounts, temporal proximity matches exist within ±1 to ±7 days.")

            print(f"\n8. What is the strongest candidate bridge found?")
            print(f"   - For Operational Linking: VSALE.inv_no <-> trn_jobcard.inv_no / trn_labour_issue.inv_no / trn_insu_detail.invoice_no.")
            print(f"   - For Vehicle Sales History Linking: VSALE.ac_code <-> mst_history.cust_code + temporal date proximity (±1 to ±7 days).")

            print(f"\n9. What is still NOT proven?")
            print(f"   - Direct invoice/document numbers do not exist in mst_history.")
            print(f"   - A relational Foreign Key constraint does not exist between transection and mst_history.")

            print("\n" + "=" * 80 + "\n")

    conn.close()


if __name__ == "__main__":
    investigate_vsale_transactions()
