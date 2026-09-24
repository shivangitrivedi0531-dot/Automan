import os
import sys

# Ensure project root directory is in sys.path for importing scripts module
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

try:
    from dotenv import load_dotenv
    env_path = os.path.join(os.getcwd(), ".env")
    if os.path.exists(env_path):
        load_dotenv(dotenv_path=env_path)
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

from scripts.get_sale_by_gl_account import get_sale_by_gl_account, get_db_connection


def run_tests():
    """
    Validates get_sale_by_gl_account() against independent READ-ONLY SQL queries.
    Tests master-matching accounts, non-master VSALE accounts, and invalid accounts.
    Calculates overall GL account master coverage metrics.
    """
    conn = get_db_connection()
    conn.set_session(readonly=True)
    all_passed = True

    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            print("=" * 50)
            print("GL ACCOUNT SALES VALIDATION")
            print("=" * 50)

            # STEP 1 — SELECT TEST ACCOUNTS AUTOMATICALLY
            cur.execute("""
                SELECT DISTINCT TRIM(CAST(ac_code AS TEXT)) AS ac_code
                FROM public.transection
                WHERE inv_type = 'VSALE'
                  AND ac_code IS NOT NULL AND TRIM(CAST(ac_code AS TEXT)) != ''
                  AND TRIM(CAST(ac_code AS TEXT)) IN (
                      SELECT DISTINCT TRIM(CAST(ac_code AS TEXT)) FROM public.mst_ac_detail WHERE ac_code IS NOT NULL
                  )
                ORDER BY ac_code
                LIMIT 1;
            """)
            code_master = cur.fetchone()["ac_code"]

            cur.execute("""
                SELECT DISTINCT TRIM(CAST(ac_code AS TEXT)) AS ac_code
                FROM public.transection
                WHERE inv_type = 'VSALE'
                  AND ac_code IS NOT NULL AND TRIM(CAST(ac_code AS TEXT)) != ''
                  AND TRIM(CAST(ac_code AS TEXT)) NOT IN (
                      SELECT DISTINCT TRIM(CAST(ac_code AS TEXT)) FROM public.mst_ac_detail WHERE ac_code IS NOT NULL
                  )
                ORDER BY ac_code
                LIMIT 1;
            """)
            code_no_master = cur.fetchone()["ac_code"]

            code_invalid = "9999999"

            print(f"\nDiscovered Test Values:")
            print(f"  - Master-Matching Account: {code_master}")
            print(f"  - Non-Master Account     : {code_no_master}")
            print(f"  - Invalid Account        : {code_invalid}")

            # STEP 2 — TEST MASTER-MATCHING ACCOUNT
            print(f"\nTEST 1 - MASTER-MATCHING ACCOUNT ({code_master})\n")

            cur.execute("""
                SELECT 
                    COUNT(DISTINCT TRIM(CAST(inv_no AS TEXT))) AS distinct_invoice_count,
                    COUNT(*) AS total_accounting_rows,
                    COALESCE(SUM(CASE WHEN cr_dr = 'D' THEN amount ELSE 0 END), 0) AS debit_amount_sum,
                    COALESCE(SUM(amount), 0) AS total_amount_sum,
                    MIN(TRIM(CAST(doc_date AS TEXT))) AS min_doc_date,
                    MAX(TRIM(CAST(doc_date AS TEXT))) AS max_doc_date
                FROM public.transection
                WHERE inv_type = 'VSALE'
                  AND ac_code IS NOT NULL AND TRIM(CAST(ac_code AS TEXT)) = TRIM(CAST(%s AS TEXT));
            """, (code_master,))
            sql_res_1 = cur.fetchone()

            inv_cnt_1 = sql_res_1["distinct_invoice_count"]
            ac_rows_1 = sql_res_1["total_accounting_rows"]
            debit_sum_1 = float(sql_res_1["debit_amount_sum"])
            tot_sum_1 = float(sql_res_1["total_amount_sum"])
            min_date_1 = sql_res_1["min_doc_date"]
            max_date_1 = sql_res_1["max_doc_date"]

            print("Independent SQL Summary:")
            print(f"  1. DISTINCT invoice count                   : {inv_cnt_1}")
            print(f"  2. COUNT(*) accounting rows                 : {ac_rows_1}")
            print(f"  3. SUM(CASE WHEN cr_dr = 'D' THEN amount)   : {debit_sum_1:.2f}")
            print(f"  4. SUM(amount) total                        : {tot_sum_1:.2f}")
            print(f"  5. MIN(doc_date)                            : {min_date_1}")
            print(f"  6. MAX(doc_date)                            : {max_date_1}")

            func_res_1 = get_sale_by_gl_account(code_master)

            validations_1 = []
            v_exists_1 = func_res_1.get("exists") is True
            validations_1.append(("Account exists", v_exists_1))

            v_name_1 = func_res_1.get("account_name") is None  # mst_ac_detail has no text name column
            validations_1.append(("Account name matches", v_name_1))

            v_inv_1 = func_res_1.get("number_of_invoices") == inv_cnt_1
            validations_1.append(("Invoice count", v_inv_1))

            v_ac_1 = func_res_1.get("number_of_accounting_rows") == ac_rows_1
            validations_1.append(("Accounting row count", v_ac_1))

            v_deb_1 = abs(func_res_1.get("total_amount", 0.0) - debit_sum_1) < 0.01
            validations_1.append(("Debit-side total", v_deb_1))

            v_tot_1 = abs(func_res_1.get("sum_amount", 0.0) - tot_sum_1) < 0.01
            validations_1.append(("SUM(amount)", v_tot_1))

            v_min_1 = func_res_1.get("min_doc_date") == min_date_1
            validations_1.append(("Min date", v_min_1))

            v_max_1 = func_res_1.get("max_doc_date") == max_date_1
            validations_1.append(("Max date", v_max_1))

            ret_invs_1 = func_res_1.get("invoices", [])
            inv_nos_1 = [i["invoice_no"] for i in ret_invs_1]
            v_uniq_1 = len(inv_nos_1) == len(set(inv_nos_1))
            validations_1.append(("Invoice numbers unique", v_uniq_1))

            cur.execute("""
                SELECT DISTINCT TRIM(CAST(inv_no AS TEXT)) AS inv_no
                FROM public.transection
                WHERE inv_type = 'VSALE'
                  AND ac_code IS NOT NULL AND TRIM(CAST(ac_code AS TEXT)) = TRIM(CAST(%s AS TEXT));
            """, (code_master,))
            valid_set_1 = {r["inv_no"] for r in cur.fetchall()}
            v_bel_1 = set(inv_nos_1).issubset(valid_set_1)
            validations_1.append(("Every returned invoice belongs to requested ac_code", v_bel_1))

            v_dup_1 = len(ret_invs_1) == len(set(inv_nos_1))
            validations_1.append(("No duplicated invoice summary", v_dup_1))

            cur.execute("""
                SELECT 
                    TRIM(CAST(inv_no AS TEXT)) AS inv_no,
                    COUNT(*) AS ac_rows,
                    COALESCE(SUM(CASE WHEN cr_dr = 'D' THEN amount ELSE 0 END), 0) AS debit_total
                FROM public.transection
                WHERE inv_type = 'VSALE'
                  AND ac_code IS NOT NULL AND TRIM(CAST(ac_code AS TEXT)) = TRIM(CAST(%s AS TEXT))
                GROUP BY TRIM(CAST(inv_no AS TEXT));
            """, (code_master,))
            sql_inv_map_1 = {r["inv_no"]: (r["ac_rows"], float(r["debit_total"])) for r in cur.fetchall()}

            match_inv_tot_1 = True
            for inv in ret_invs_1:
                i_no = inv["invoice_no"]
                erows, eamt = sql_inv_map_1.get(i_no, (0, 0.0))
                if inv["accounting_row_count"] != erows or abs(inv["invoice_total_amount"] - eamt) >= 0.01:
                    match_inv_tot_1 = False
                    break
            validations_1.append(("Invoice totals equal independent SQL totals", match_inv_tot_1))

            print("\nValidation Results:")
            for name, passed in validations_1:
                status = "[PASS]" if passed else "[FAIL]"
                print(f"  {status} {name}")
                if not passed:
                    all_passed = False

            # STEP 3 — TEST NON-MASTER VSALE ACCOUNT
            print(f"\nTEST 2 - VSALE ACCOUNT WITHOUT MASTER ({code_no_master})\n")

            cur.execute("""
                SELECT 
                    COUNT(DISTINCT TRIM(CAST(inv_no AS TEXT))) AS distinct_invoice_count,
                    COUNT(*) AS total_accounting_rows,
                    COALESCE(SUM(CASE WHEN cr_dr = 'D' THEN amount ELSE 0 END), 0) AS debit_amount_sum,
                    COALESCE(SUM(amount), 0) AS total_amount_sum,
                    MIN(TRIM(CAST(doc_date AS TEXT))) AS min_doc_date,
                    MAX(TRIM(CAST(doc_date AS TEXT))) AS max_doc_date
                FROM public.transection
                WHERE inv_type = 'VSALE'
                  AND ac_code IS NOT NULL AND TRIM(CAST(ac_code AS TEXT)) = TRIM(CAST(%s AS TEXT));
            """, (code_no_master,))
            sql_res_2 = cur.fetchone()

            inv_cnt_2 = sql_res_2["distinct_invoice_count"]
            ac_rows_2 = sql_res_2["total_accounting_rows"]
            debit_sum_2 = float(sql_res_2["debit_amount_sum"])
            tot_sum_2 = float(sql_res_2["total_amount_sum"])
            min_date_2 = sql_res_2["min_doc_date"]
            max_date_2 = sql_res_2["max_doc_date"]

            print("Independent SQL Summary:")
            print(f"  1. DISTINCT invoice count                   : {inv_cnt_2}")
            print(f"  2. COUNT(*) accounting rows                 : {ac_rows_2}")
            print(f"  3. SUM(CASE WHEN cr_dr = 'D' THEN amount)   : {debit_sum_2:.2f}")
            print(f"  4. SUM(amount) total                        : {tot_sum_2:.2f}")
            print(f"  5. MIN(doc_date)                            : {min_date_2}")
            print(f"  6. MAX(doc_date)                            : {max_date_2}")

            func_res_2 = get_sale_by_gl_account(code_no_master)

            validations_2 = []
            v_exists_2 = func_res_2.get("exists") is True
            validations_2.append(("Function returns exists=True", v_exists_2))

            v_name_2 = func_res_2.get("account_name") is None
            validations_2.append(("account_name is None", v_name_2))

            v_inv_2 = func_res_2.get("number_of_invoices") == inv_cnt_2
            validations_2.append(("Invoice count matches", v_inv_2))

            v_ac_2 = func_res_2.get("number_of_accounting_rows") == ac_rows_2
            validations_2.append(("Accounting row count matches", v_ac_2))

            v_deb_2 = abs(func_res_2.get("total_amount", 0.0) - debit_sum_2) < 0.01
            validations_2.append(("Debit total matches", v_deb_2))

            v_tot_2 = abs(func_res_2.get("sum_amount", 0.0) - tot_sum_2) < 0.01
            validations_2.append(("SUM(amount) matches", v_tot_2))

            v_dates_2 = (func_res_2.get("min_doc_date") == min_date_2) and (func_res_2.get("max_doc_date") == max_date_2)
            validations_2.append(("Dates match", v_dates_2))

            ret_invs_2 = func_res_2.get("invoices", [])
            inv_nos_2 = [i["invoice_no"] for i in ret_invs_2]
            v_uniq_2 = len(inv_nos_2) == len(set(inv_nos_2))
            validations_2.append(("Returned invoices are unique", v_uniq_2))

            cur.execute("""
                SELECT DISTINCT TRIM(CAST(inv_no AS TEXT)) AS inv_no
                FROM public.transection
                WHERE inv_type = 'VSALE'
                  AND ac_code IS NOT NULL AND TRIM(CAST(ac_code AS TEXT)) = TRIM(CAST(%s AS TEXT));
            """, (code_no_master,))
            valid_set_2 = {r["inv_no"] for r in cur.fetchall()}
            v_bel_2 = set(inv_nos_2).issubset(valid_set_2)
            validations_2.append(("Returned invoices belong to requested ac_code", v_bel_2))

            print("\nValidation Results:")
            for name, passed in validations_2:
                status = "[PASS]" if passed else "[FAIL]"
                print(f"  {status} {name}")
                if not passed:
                    all_passed = False

            # STEP 4 — TEST INVALID ACCOUNT
            print(f"\nTEST 3 - INVALID ACCOUNT ({code_invalid})\n")

            func_res_3 = get_sale_by_gl_account(code_invalid)

            validations_3 = []
            v_ex_3 = func_res_3.get("exists") is False
            validations_3.append(("exists=False", v_ex_3))

            v_inv_3 = func_res_3.get("number_of_invoices") == 0
            validations_3.append(("number_of_invoices=0", v_inv_3))

            v_ac_3 = func_res_3.get("number_of_accounting_rows") == 0
            validations_3.append(("number_of_accounting_rows=0", v_ac_3))

            v_tot_3 = func_res_3.get("total_amount") == 0
            validations_3.append(("total_amount=0", v_tot_3))

            v_list_3 = func_res_3.get("invoices") == []
            validations_3.append(("invoices=[]", v_list_3))

            print("Validation Results:")
            for name, passed in validations_3:
                status = "[PASS]" if passed else "[FAIL]"
                print(f"  {status} {name}")
                if not passed:
                    all_passed = False

            # STEP 5 — OVERALL GL ACCOUNT COVERAGE
            print("\n" + "=" * 50)
            print("GL ACCOUNT MASTER COVERAGE")
            print("=" * 50)

            cur.execute("""
                SELECT COUNT(DISTINCT TRIM(CAST(ac_code AS TEXT))) AS total_vsale_codes
                FROM public.transection
                WHERE inv_type = 'VSALE' AND ac_code IS NOT NULL AND TRIM(CAST(ac_code AS TEXT)) != '';
            """)
            total_vsale_codes = cur.fetchone()["total_vsale_codes"]

            cur.execute("""
                SELECT COUNT(DISTINCT s.code) AS matched_codes
                FROM (
                    SELECT DISTINCT TRIM(CAST(ac_code AS TEXT)) AS code
                    FROM public.transection
                    WHERE inv_type = 'VSALE' AND ac_code IS NOT NULL AND TRIM(CAST(ac_code AS TEXT)) != ''
                ) s
                JOIN (
                    SELECT DISTINCT TRIM(CAST(ac_code AS TEXT)) AS code
                    FROM public.mst_ac_detail
                    WHERE ac_code IS NOT NULL AND TRIM(CAST(ac_code AS TEXT)) != ''
                ) m ON s.code = m.code;
            """)
            matched_codes = cur.fetchone()["matched_codes"]
            unmatched_codes = total_vsale_codes - matched_codes
            match_pct = (matched_codes / float(total_vsale_codes)) * 100.0 if total_vsale_codes > 0 else 0.0

            print(f"\nCoverage Summary:")
            print(f"  - Total distinct VSALE ac_codes          : {total_vsale_codes}")
            print(f"  - VSALE ac_codes matched to mst_ac_detail: {matched_codes}")
            print(f"  - VSALE ac_codes without master match    : {unmatched_codes}")
            print(f"  - Match percentage                       : {match_pct:.2f}%")

            v_cov = (matched_codes == 736) and (match_pct >= 96.0)
            status_cov = "[PASS]" if v_cov else "[FAIL]"
            print(f"\n  {status_cov} Coverage matches expected discovery (~736 matched, ~96.97%)")

            if not v_cov:
                all_passed = False

            print("\n" + "=" * 50)
            print("OVERALL RESULT")
            print("=" * 50)

            if all_passed:
                print("\nALL VALIDATIONS PASSED [PASS]\n")
            else:
                print("\nVALIDATION FAILED [FAIL]\n")

    finally:
        conn.close()


if __name__ == "__main__":
    run_tests()
