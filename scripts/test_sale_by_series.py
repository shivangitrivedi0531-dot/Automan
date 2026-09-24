import os
import sys

# Ensure parent directory is in sys.path for importing scripts module
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

from scripts.get_sale_by_series import get_sale_by_series, get_db_connection


def run_tests():
    """
    Validates get_sale_by_series() against independent READ-ONLY SQL queries.
    Tests both valid series: '0000001' (RETAIL SALES) and '0000002' (TAX SALES).
    """
    conn = get_db_connection()
    conn.set_session(readonly=True)
    all_passed = True

    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            print("=" * 80)
            print(" VALIDATING GET_SALE_BY_SERIES AGAINST INDEPENDENT READ-ONLY SQL QUERIES")
            print("=" * 80)

            series_codes = ["0000001", "0000002"]

            for series_code in series_codes:
                print(f"\n" + "-" * 40)
                print(f" TESTING VOUCHER SERIES: {series_code}")
                print("-" * 40)

                # 1. Independent Master Series lookup
                cur.execute("""
                    SELECT TRIM(CAST("NAME" AS TEXT)) AS series_name
                    FROM public.mst_series
                    WHERE ser_code IS NOT NULL AND TRIM(CAST(ser_code AS TEXT)) = TRIM(CAST(%s AS TEXT));
                """, (series_code,))
                s_row = cur.fetchone()
                expected_series_name = s_row["series_name"] if s_row else None

                # 2. Independent SQL calculation directly from public.transection
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
                      AND series IS NOT NULL AND TRIM(CAST(series AS TEXT)) = TRIM(CAST(%s AS TEXT));
                """, (series_code,))
                sql_res = cur.fetchone()

                distinct_inv_cnt = sql_res["distinct_invoice_count"]
                total_ac_rows = sql_res["total_accounting_rows"]
                debit_sum = float(sql_res["debit_amount_sum"])
                total_sum = float(sql_res["total_amount_sum"])
                min_date = sql_res["min_doc_date"]
                max_date = sql_res["max_doc_date"]

                print(f"\nIndependent SQL Summary for Series {series_code} ({expected_series_name}):")
                print(f"  1. DISTINCT invoice count                   : {distinct_inv_cnt}")
                print(f"  2. COUNT(*) accounting rows                 : {total_ac_rows}")
                print(f"  3. SUM(CASE WHEN cr_dr = 'D' THEN amount)   : {debit_sum:.2f}")
                print(f"  4. SUM(amount) total                        : {total_sum:.2f}")
                print(f"  5. MIN(doc_date)                            : {min_date}")
                print(f"  6. MAX(doc_date)                            : {max_date}")

                # 3. Call get_sale_by_series function
                func_res = get_sale_by_series(series_code)

                # Validations list
                validations = []

                # Validation: Series exists
                v_exists = func_res.get("exists") is True
                validations.append(("Series exists flag is True", v_exists))

                # Validation: Series name correctness
                v_name = func_res.get("series_name") == expected_series_name
                validations.append((f"Series name matches '{expected_series_name}'", v_name))

                # Validation: Returned invoice count equals independent DISTINCT inv_no count
                func_inv_cnt = func_res.get("number_of_invoices", 0)
                v_inv_cnt = func_inv_cnt == distinct_inv_cnt
                validations.append((f"Returned invoice count ({func_inv_cnt}) == DISTINCT inv_no count ({distinct_inv_cnt})", v_inv_cnt))

                # Validation: Returned accounting row count equals independent COUNT(*)
                func_ac_cnt = func_res.get("number_of_accounting_rows", 0)
                v_ac_cnt = func_ac_cnt == total_ac_rows
                validations.append((f"Returned accounting row count ({func_ac_cnt}) == COUNT(*) ({total_ac_rows})", v_ac_cnt))

                # Validation: Returned total_amount equals independent debit-side SUM
                func_amt = func_res.get("total_amount", 0.0)
                v_total_amt = abs(func_amt - debit_sum) < 0.01
                validations.append((f"Returned total_amount ({func_amt:.2f}) == debit-side SUM ({debit_sum:.2f})", v_total_amt))

                # Validation: Returned invoice numbers are unique
                returned_invoices = func_res.get("invoices", [])
                inv_nos = [inv["invoice_no"] for inv in returned_invoices]
                v_inv_unique = len(inv_nos) == len(set(inv_nos))
                validations.append(("Returned invoice numbers are unique", v_inv_unique))

                # Validation: Every returned invoice belongs to requested series
                cur.execute("""
                    SELECT DISTINCT TRIM(CAST(inv_no AS TEXT)) AS inv_no
                    FROM public.transection
                    WHERE inv_type = 'VSALE'
                      AND series IS NOT NULL AND TRIM(CAST(series AS TEXT)) = TRIM(CAST(%s AS TEXT));
                """, (series_code,))
                valid_series_inv_set = {r["inv_no"] for r in cur.fetchall()}
                v_series_belong = set(inv_nos).issubset(valid_series_inv_set)
                validations.append(("Every returned invoice belongs to the requested series in public.transection", v_series_belong))

                # Validation: No invoice has a duplicated invoice-level summary
                v_no_dup_summary = len(returned_invoices) == len(set(inv_nos))
                validations.append(("No invoice has a duplicated invoice-level summary", v_no_dup_summary))

                # Validation: Returned invoice totals equal independently calculated invoice-level debit totals
                cur.execute("""
                    SELECT 
                        TRIM(CAST(inv_no AS TEXT)) AS inv_no,
                        COUNT(*) AS ac_rows,
                        COALESCE(SUM(CASE WHEN cr_dr = 'D' THEN amount ELSE 0 END), 0) AS debit_total
                    FROM public.transection
                    WHERE inv_type = 'VSALE'
                      AND series IS NOT NULL AND TRIM(CAST(series AS TEXT)) = TRIM(CAST(%s AS TEXT))
                    GROUP BY TRIM(CAST(inv_no AS TEXT));
                """, (series_code,))
                sql_invoice_map = {r["inv_no"]: (r["ac_rows"], float(r["debit_total"])) for r in cur.fetchall()}

                invoice_totals_match = True
                for inv in returned_invoices:
                    i_no = inv["invoice_no"]
                    exp_rows, exp_amt = sql_invoice_map.get(i_no, (0, 0.0))
                    if inv["accounting_row_count"] != exp_rows or abs(inv["invoice_total_amount"] - exp_amt) >= 0.01:
                        invoice_totals_match = False
                        break

                validations.append(("Returned invoice totals equal independently calculated invoice-level debit totals", invoice_totals_match))

                print("\n  Validation Results:")
                for name, passed in validations:
                    status = "[PASS]" if passed else "[FAIL]"
                    print(f"    {status} {name}")
                    if not passed:
                        all_passed = False

            # --- COMBINED SERIES COVERAGE VALIDATION ---
            print("\n" + "=" * 80)
            print(" COMBINED SERIES COVERAGE VALIDATION")
            print("=" * 80)

            cur.execute("""
                SELECT DISTINCT TRIM(CAST(series AS TEXT)) AS series
                FROM public.transection
                WHERE inv_type = 'VSALE' AND series IS NOT NULL
                ORDER BY series;
            """)
            all_vsale_series = [r["series"] for r in cur.fetchall()]
            print(f"DISTINCT series in public.transection (inv_type = 'VSALE'): {all_vsale_series}")

            cur.execute("""
                SELECT COUNT(DISTINCT TRIM(CAST(inv_no AS TEXT))) AS total_cnt
                FROM public.transection
                WHERE inv_type = 'VSALE';
            """)
            total_vsale_invoices = cur.fetchone()["total_cnt"]

            cur.execute("""
                SELECT COUNT(DISTINCT TRIM(CAST(inv_no AS TEXT))) AS covered_cnt
                FROM public.transection
                WHERE inv_type = 'VSALE' AND TRIM(CAST(series AS TEXT)) IN ('0000001', '0000002');
            """)
            covered_invoices = cur.fetchone()["covered_cnt"]

            print(f"Total VSALE Invoices in Database : {total_vsale_invoices}")
            print(f"Covered Invoices by ('0000001', '0000002') : {covered_invoices}")

            v_series_set = set(all_vsale_series) == {"0000001", "0000002"}
            validations_coverage_series = "[PASS]" if v_series_set else "[FAIL]"
            print(f"  {validations_coverage_series} Database VSALE series set strictly equals {{'0000001', '0000002'}}")

            v_100_coverage = (total_vsale_invoices == 696) and (covered_invoices == 696)
            validations_coverage_100 = "[PASS]" if v_100_coverage else "[FAIL]"
            print(f"  {validations_coverage_100} Series '0000001' and '0000002' account for all {covered_invoices}/{total_vsale_invoices} (100%) VSALE invoices")

            if not v_series_set or not v_100_coverage:
                all_passed = False

            print("\n" + "=" * 80)
            if all_passed:
                print(" OVERALL RESULT: ALL VALIDATIONS PASSED [PASS]")
            else:
                print(" OVERALL RESULT: SOME VALIDATIONS FAILED [FAIL]")
            print("=" * 80)

    finally:
        conn.close()


if __name__ == "__main__":
    run_tests()
