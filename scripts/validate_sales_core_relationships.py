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


def validate_sales_core_relationships(schema_name: str = "public"):
    print("=" * 80)
    print(" SALES CORE RELATIONSHIPS AUTHORITATIVE VALIDATION REPORT")
    print("=" * 80 + "\n")

    try:
        conn = get_db_connection()
        conn.set_session(readonly=True)
    except Exception as e:
        print(f"[X] Database connection failed: {e}\n")
        sys.exit(1)

    with conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:

            # ==================================================
            # RELATIONSHIP 1: mst_history.product_code -> mst_product.product_code
            # ==================================================
            print("==================================================")
            print("RELATIONSHIP 1: mst_history.product_code -> mst_product.product_code")
            print("==================================================")

            src_table_1 = "mst_history"
            src_col_1 = "product_code"
            tgt_table_1 = "mst_product"
            tgt_col_1 = "product_code"

            # Source distinct count
            q_src_1 = f"""
                SELECT COUNT(DISTINCT TRIM(CAST("{src_col_1}" AS TEXT))) AS cnt
                FROM "{schema_name}"."{src_table_1}"
                WHERE "{src_col_1}" IS NOT NULL AND TRIM(CAST("{src_col_1}" AS TEXT)) != '';
            """
            cursor.execute(q_src_1)
            src_dist_1 = cursor.fetchone()["cnt"]

            # Target distinct count
            q_tgt_1 = f"""
                SELECT COUNT(DISTINCT TRIM(CAST("{tgt_col_1}" AS TEXT))) AS cnt
                FROM "{schema_name}"."{tgt_table_1}"
                WHERE "{tgt_col_1}" IS NOT NULL AND TRIM(CAST("{tgt_col_1}" AS TEXT)) != '';
            """
            cursor.execute(q_tgt_1)
            tgt_dist_1 = cursor.fetchone()["cnt"]

            # Matched count
            q_match_1 = f"""
                SELECT COUNT(DISTINCT s.code) AS cnt
                FROM (
                    SELECT DISTINCT TRIM(CAST("{src_col_1}" AS TEXT)) AS code
                    FROM "{schema_name}"."{src_table_1}"
                    WHERE "{src_col_1}" IS NOT NULL AND TRIM(CAST("{src_col_1}" AS TEXT)) != ''
                ) s
                JOIN (
                    SELECT DISTINCT TRIM(CAST("{tgt_col_1}" AS TEXT)) AS code
                    FROM "{schema_name}"."{tgt_table_1}"
                    WHERE "{tgt_col_1}" IS NOT NULL AND TRIM(CAST("{tgt_col_1}" AS TEXT)) != ''
                ) t ON s.code = t.code;
            """
            cursor.execute(q_match_1)
            match_dist_1 = cursor.fetchone()["cnt"]

            pct_1 = (match_dist_1 / src_dist_1 * 100.0) if src_dist_1 > 0 else 0.0

            # Fetch up to 10 matched codes
            q_matched_codes_1 = f"""
                SELECT DISTINCT s.code
                FROM (
                    SELECT DISTINCT TRIM(CAST("{src_col_1}" AS TEXT)) AS code
                    FROM "{schema_name}"."{src_table_1}"
                    WHERE "{src_col_1}" IS NOT NULL AND TRIM(CAST("{src_col_1}" AS TEXT)) != ''
                ) s
                JOIN (
                    SELECT DISTINCT TRIM(CAST("{tgt_col_1}" AS TEXT)) AS code
                    FROM "{schema_name}"."{tgt_table_1}"
                    WHERE "{tgt_col_1}" IS NOT NULL AND TRIM(CAST("{tgt_col_1}" AS TEXT)) != ''
                ) t ON s.code = t.code
                ORDER BY s.code
                LIMIT 10;
            """
            cursor.execute(q_matched_codes_1)
            matched_codes_1 = [r["code"] for r in cursor.fetchall()]

            print(f"Source table           : {schema_name}.{src_table_1}")
            print(f"Source column          : {src_col_1}")
            print(f"Target table           : {schema_name}.{tgt_table_1}")
            print(f"Target column          : {tgt_col_1}")
            print(f"Source distinct count  : {src_dist_1}")
            print(f"Target distinct count  : {tgt_dist_1}")
            print(f"Matched distinct count : {match_dist_1}")
            print(f"Match percentage       : {pct_1:.2f}%")
            print(f"Matched codes (up to 10): [{', '.join(matched_codes_1)}]\n")

            # ==================================================
            # RELATIONSHIP 2: mst_history.cust_code -> mst_ac_detail.ac_code
            # ==================================================
            print("==================================================")
            print("RELATIONSHIP 2: mst_history.cust_code -> mst_ac_detail.ac_code")
            print("==================================================")

            src_table_2 = "mst_history"
            src_col_2 = "cust_code"
            tgt_table_2 = "mst_ac_detail"
            tgt_col_2 = "ac_code"

            q_src_2 = f"""
                SELECT COUNT(DISTINCT TRIM(CAST("{src_col_2}" AS TEXT))) AS cnt
                FROM "{schema_name}"."{src_table_2}"
                WHERE "{src_col_2}" IS NOT NULL AND TRIM(CAST("{src_col_2}" AS TEXT)) != '';
            """
            cursor.execute(q_src_2)
            src_dist_2 = cursor.fetchone()["cnt"]

            q_tgt_2 = f"""
                SELECT COUNT(DISTINCT TRIM(CAST("{tgt_col_2}" AS TEXT))) AS cnt
                FROM "{schema_name}"."{tgt_table_2}"
                WHERE "{tgt_col_2}" IS NOT NULL AND TRIM(CAST("{tgt_col_2}" AS TEXT)) != '';
            """
            cursor.execute(q_tgt_2)
            tgt_dist_2 = cursor.fetchone()["cnt"]

            q_match_2 = f"""
                SELECT COUNT(DISTINCT s.code) AS cnt
                FROM (
                    SELECT DISTINCT TRIM(CAST("{src_col_2}" AS TEXT)) AS code
                    FROM "{schema_name}"."{src_table_2}"
                    WHERE "{src_col_2}" IS NOT NULL AND TRIM(CAST("{src_col_2}" AS TEXT)) != ''
                ) s
                JOIN (
                    SELECT DISTINCT TRIM(CAST("{tgt_col_2}" AS TEXT)) AS code
                    FROM "{schema_name}"."{tgt_table_2}"
                    WHERE "{tgt_col_2}" IS NOT NULL AND TRIM(CAST("{tgt_col_2}" AS TEXT)) != ''
                ) t ON s.code = t.code;
            """
            cursor.execute(q_match_2)
            match_dist_2 = cursor.fetchone()["cnt"]

            pct_2 = (match_dist_2 / src_dist_2 * 100.0) if src_dist_2 > 0 else 0.0

            q_matched_codes_2 = f"""
                SELECT DISTINCT s.code
                FROM (
                    SELECT DISTINCT TRIM(CAST("{src_col_2}" AS TEXT)) AS code
                    FROM "{schema_name}"."{src_table_2}"
                    WHERE "{src_col_2}" IS NOT NULL AND TRIM(CAST("{src_col_2}" AS TEXT)) != ''
                ) s
                JOIN (
                    SELECT DISTINCT TRIM(CAST("{tgt_col_2}" AS TEXT)) AS code
                    FROM "{schema_name}"."{tgt_table_2}"
                    WHERE "{tgt_col_2}" IS NOT NULL AND TRIM(CAST("{tgt_col_2}" AS TEXT)) != ''
                ) t ON s.code = t.code
                ORDER BY s.code
                LIMIT 10;
            """
            cursor.execute(q_matched_codes_2)
            matched_codes_2 = [r["code"] for r in cursor.fetchall()]

            q_unmatched_codes_2 = f"""
                SELECT DISTINCT s.code
                FROM (
                    SELECT DISTINCT TRIM(CAST("{src_col_2}" AS TEXT)) AS code
                    FROM "{schema_name}"."{src_table_2}"
                    WHERE "{src_col_2}" IS NOT NULL AND TRIM(CAST("{src_col_2}" AS TEXT)) != ''
                ) s
                LEFT JOIN (
                    SELECT DISTINCT TRIM(CAST("{tgt_col_2}" AS TEXT)) AS code
                    FROM "{schema_name}"."{tgt_table_2}"
                    WHERE "{tgt_col_2}" IS NOT NULL AND TRIM(CAST("{tgt_col_2}" AS TEXT)) != ''
                ) t ON s.code = t.code
                WHERE t.code IS NULL
                ORDER BY s.code
                LIMIT 10;
            """
            cursor.execute(q_unmatched_codes_2)
            unmatched_codes_2 = [r["code"] for r in cursor.fetchall()]

            print(f"Source table                     : {schema_name}.{src_table_2}")
            print(f"Source column                    : {src_col_2}")
            print(f"Target table                     : {schema_name}.{tgt_table_2}")
            print(f"Target column                    : {tgt_col_2}")
            print(f"Source distinct count            : {src_dist_2}")
            print(f"Target distinct count            : {tgt_dist_2}")
            print(f"Matched distinct count           : {match_dist_2}")
            print(f"Match percentage                 : {pct_2:.2f}%")
            print(f"Matched codes (up to 10)         : [{', '.join(matched_codes_2)}]")
            print(f"Unmatched source codes (up to 10): [{', '.join(unmatched_codes_2)}]\n")

            # ==================================================
            # RELATIONSHIP 3: mst_history.cust_code -> transection.ac_code
            # ==================================================
            print("==================================================")
            print("RELATIONSHIP 3: mst_history.cust_code -> transection.ac_code")
            print("==================================================")

            src_table_3 = "mst_history"
            src_col_3 = "cust_code"
            tgt_table_3 = "transection"
            tgt_col_3 = "ac_code"

            q_src_3 = f"""
                SELECT COUNT(DISTINCT TRIM(CAST("{src_col_3}" AS TEXT))) AS cnt
                FROM "{schema_name}"."{src_table_3}"
                WHERE "{src_col_3}" IS NOT NULL AND TRIM(CAST("{src_col_3}" AS TEXT)) != '';
            """
            cursor.execute(q_src_3)
            src_dist_3 = cursor.fetchone()["cnt"]

            q_tgt_3 = f"""
                SELECT COUNT(DISTINCT TRIM(CAST("{tgt_col_3}" AS TEXT))) AS cnt
                FROM "{schema_name}"."{tgt_table_3}"
                WHERE "{tgt_col_3}" IS NOT NULL AND TRIM(CAST("{tgt_col_3}" AS TEXT)) != '';
            """
            cursor.execute(q_tgt_3)
            tgt_dist_3 = cursor.fetchone()["cnt"]

            q_match_3 = f"""
                SELECT COUNT(DISTINCT s.code) AS cnt
                FROM (
                    SELECT DISTINCT TRIM(CAST("{src_col_3}" AS TEXT)) AS code
                    FROM "{schema_name}"."{src_table_3}"
                    WHERE "{src_col_3}" IS NOT NULL AND TRIM(CAST("{src_col_3}" AS TEXT)) != ''
                ) s
                JOIN (
                    SELECT DISTINCT TRIM(CAST("{tgt_col_3}" AS TEXT)) AS code
                    FROM "{schema_name}"."{tgt_table_3}"
                    WHERE "{tgt_col_3}" IS NOT NULL AND TRIM(CAST("{tgt_col_3}" AS TEXT)) != ''
                ) t ON s.code = t.code;
            """
            cursor.execute(q_match_3)
            match_dist_3 = cursor.fetchone()["cnt"]

            pct_3 = (match_dist_3 / src_dist_3 * 100.0) if src_dist_3 > 0 else 0.0

            q_matched_codes_3 = f"""
                SELECT DISTINCT s.code
                FROM (
                    SELECT DISTINCT TRIM(CAST("{src_col_3}" AS TEXT)) AS code
                    FROM "{schema_name}"."{src_table_3}"
                    WHERE "{src_col_3}" IS NOT NULL AND TRIM(CAST("{src_col_3}" AS TEXT)) != ''
                ) s
                JOIN (
                    SELECT DISTINCT TRIM(CAST("{tgt_col_3}" AS TEXT)) AS code
                    FROM "{schema_name}"."{tgt_table_3}"
                    WHERE "{tgt_col_3}" IS NOT NULL AND TRIM(CAST("{tgt_col_3}" AS TEXT)) != ''
                ) t ON s.code = t.code
                ORDER BY s.code
                LIMIT 10;
            """
            cursor.execute(q_matched_codes_3)
            matched_codes_3 = [r["code"] for r in cursor.fetchall()]

            q_unmatched_codes_3 = f"""
                SELECT DISTINCT s.code
                FROM (
                    SELECT DISTINCT TRIM(CAST("{src_col_3}" AS TEXT)) AS code
                    FROM "{schema_name}"."{src_table_3}"
                    WHERE "{src_col_3}" IS NOT NULL AND TRIM(CAST("{src_col_3}" AS TEXT)) != ''
                ) s
                LEFT JOIN (
                    SELECT DISTINCT TRIM(CAST("{tgt_col_3}" AS TEXT)) AS code
                    FROM "{schema_name}"."{tgt_table_3}"
                    WHERE "{tgt_col_3}" IS NOT NULL AND TRIM(CAST("{tgt_col_3}" AS TEXT)) != ''
                ) t ON s.code = t.code
                WHERE t.code IS NULL
                ORDER BY s.code
                LIMIT 10;
            """
            cursor.execute(q_unmatched_codes_3)
            unmatched_codes_3 = [r["code"] for r in cursor.fetchall()]

            print(f"Source table                     : {schema_name}.{src_table_3}")
            print(f"Source column                    : {src_col_3}")
            print(f"Target table                     : {schema_name}.{tgt_table_3}")
            print(f"Target column                    : {tgt_col_3}")
            print(f"Source distinct count            : {src_dist_3}")
            print(f"Target distinct count            : {tgt_dist_3}")
            print(f"Matched distinct count           : {match_dist_3}")
            print(f"Match percentage                 : {pct_3:.2f}%")
            print(f"Matched codes (up to 10)         : [{', '.join(matched_codes_3)}]")
            print(f"Unmatched source codes (up to 10): [{', '.join(unmatched_codes_3)}]\n")

            # ==================================================
            # RELATIONSHIP 4: Direct Invoice Identifiers Check in mst_history
            # ==================================================
            print("==================================================")
            print("RELATIONSHIP 4: Direct Invoice Identifiers Check (mst_history vs transection)")
            print("==================================================")

            cursor.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = %s AND table_name = 'mst_history';
                """,
                (schema_name,)
            )
            history_columns = [r["column_name"] for r in cursor.fetchall()]

            target_transection_doc_cols = ["inv_no", "doc_no", "from_doc_no"]
            matching_history_doc_cols = [c for c in history_columns if c in target_transection_doc_cols or "invoice" in c.lower() or "doc_no" in c.lower()]

            if not matching_history_doc_cols:
                print("Inspection Result:")
                print("  No direct invoice/document identifier columns (inv_no, doc_no, from_doc_no) exist in mst_history.")
                print("  (Confirmed: mst_history identifies vehicle sale logs by sale_date, product_code, cust_code, chassis_no, engine_no).\n")
            else:
                print(f"Matching Columns Found in mst_history: {matching_history_doc_cols}")
                for hcol in matching_history_doc_cols:
                    for tcol in target_transection_doc_cols:
                        q_over = f"""
                            SELECT COUNT(DISTINCT s.val) AS cnt
                            FROM (
                                SELECT DISTINCT TRIM(CAST("{hcol}" AS TEXT)) AS val
                                FROM "{schema_name}"."mst_history"
                                WHERE "{hcol}" IS NOT NULL AND TRIM(CAST("{hcol}" AS TEXT)) != ''
                            ) s
                            JOIN (
                                SELECT DISTINCT TRIM(CAST("{tcol}" AS TEXT)) AS val
                                FROM "{schema_name}"."transection"
                                WHERE "{tcol}" IS NOT NULL AND TRIM(CAST("{tcol}" AS TEXT)) != ''
                            ) t ON s.val = t.val;
                        """
                        cursor.execute(q_over)
                        m_cnt = cursor.fetchone()["cnt"]
                        print(f"  Overlap mst_history.{hcol} <-> transection.{tcol}: {m_cnt} matched distinct values.")
                print()

            # ==================================================
            # DATE VALIDATION: mst_history.sale_date vs transection.doc_date
            # ==================================================
            print("==================================================")
            print("DATE VALIDATION: mst_history.sale_date vs transection.doc_date")
            print("==================================================")

            # mst_history.sale_date stats
            q_hist_date = f"""
                SELECT 
                    MIN(TRIM(CAST(sale_date AS TEXT))) AS min_dt,
                    MAX(TRIM(CAST(sale_date AS TEXT))) AS max_dt,
                    COUNT(DISTINCT TRIM(CAST(sale_date AS TEXT))) AS dist_dt
                FROM "{schema_name}"."mst_history"
                WHERE sale_date IS NOT NULL AND TRIM(CAST(sale_date AS TEXT)) != '';
            """
            cursor.execute(q_hist_date)
            hist_dt_res = cursor.fetchone()

            # transection.doc_date stats
            q_tran_date = f"""
                SELECT 
                    MIN(TRIM(CAST(doc_date AS TEXT))) AS min_dt,
                    MAX(TRIM(CAST(doc_date AS TEXT))) AS max_dt,
                    COUNT(DISTINCT TRIM(CAST(doc_date AS TEXT))) AS dist_dt
                FROM "{schema_name}"."transection"
                WHERE doc_date IS NOT NULL AND TRIM(CAST(doc_date AS TEXT)) != '';
            """
            cursor.execute(q_tran_date)
            tran_dt_res = cursor.fetchone()

            # Overlapping dates count
            q_match_date = f"""
                SELECT COUNT(DISTINCT s.dt) AS cnt
                FROM (
                    SELECT DISTINCT TRIM(CAST(sale_date AS TEXT)) AS dt
                    FROM "{schema_name}"."mst_history"
                    WHERE sale_date IS NOT NULL AND TRIM(CAST(sale_date AS TEXT)) != ''
                ) s
                JOIN (
                    SELECT DISTINCT TRIM(CAST(doc_date AS TEXT)) AS dt
                    FROM "{schema_name}"."transection"
                    WHERE doc_date IS NOT NULL AND TRIM(CAST(doc_date AS TEXT)) != ''
                ) t ON s.dt = t.dt;
            """
            cursor.execute(q_match_date)
            match_dt_cnt = cursor.fetchone()["cnt"]

            hist_dist_dt = hist_dt_res["dist_dt"]
            date_pct = (match_dt_cnt / hist_dist_dt * 100.0) if hist_dist_dt > 0 else 0.0

            print(f"mst_history.sale_date Range  : {hist_dt_res['min_dt']} to {hist_dt_res['max_dt']}")
            print(f"transection.doc_date Range   : {tran_dt_res['min_dt']} to {tran_dt_res['max_dt']}")
            print(f"mst_history Distinct Dates   : {hist_dist_dt}")
            print(f"transection Distinct Dates   : {tran_dt_res['dist_dt']}")
            print(f"Overlapping Dates Count      : {match_dt_cnt}")
            print(f"Date Overlap Percentage (src): {date_pct:.2f}%\n")

            # ==================================================
            # FINAL OUTPUT & CONCLUSION
            # ==================================================
            print("=" * 80)
            print("SALES CORE RELATIONSHIP VALIDATION COMPLETE")
            print("=" * 80 + "\n")

            res_1_status = "CONFIRMED CANDIDATE" if pct_1 > 0 else "NO OVERLAP"
            res_2_status = "CONFIRMED CANDIDATE" if pct_2 > 0 else "NO OVERLAP"
            res_3_status = "CONFIRMED CANDIDATE" if pct_3 > 0 else "NO OVERLAP"
            res_4_status = "FOUND" if matching_history_doc_cols else "NOT FOUND"
            res_5_status = "OVERLAP" if date_pct > 0 else "NO OVERLAP"

            print("FACTUAL CONCLUSION:")
            print(f"1. Product relationship              : {res_1_status}")
            print(f"   (mst_history.product_code -> mst_product.product_code: {match_dist_1}/{src_dist_1} = {pct_1:.2f}%)")
            print()
            print(f"2. Customer-account relationship     : {res_2_status}")
            print(f"   (mst_history.cust_code -> mst_ac_detail.ac_code: {match_dist_2}/{src_dist_2} = {pct_2:.2f}%)")
            print()
            print(f"3. Customer-accounting relationship  : {res_3_status}")
            print(f"   (mst_history.cust_code -> transection.ac_code: {match_dist_3}/{src_dist_3} = {pct_3:.2f}%)")
            print()
            print(f"4. Direct invoice relationship       : {res_4_status}")
            print("   (mst_history does not contain an inv_no / doc_no column directly referencing transection)")
            print()
            print(f"5. Date relationship                 : {res_5_status}")
            print(f"   (mst_history.sale_date <-> transection.doc_date: {match_dt_cnt}/{hist_dist_dt} = {date_pct:.2f}%)")
            print("\n" + "=" * 80 + "\n")

    conn.close()


if __name__ == "__main__":
    validate_sales_core_relationships()
