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

from scripts.get_sale_by_financial_year import get_sale_by_financial_year, get_db_connection


def run_tests():
    """
    Validates get_sale_by_financial_year() against independent READ-ONLY SQL queries.
    Tests both financial years: '2025-26' and '2026-27'.
    Cross-checks invoice coverage, multi-year invoice distribution, and doc_date alignment.
    """
    conn = get_db_connection()
    conn.set_session(readonly=True)
    all_passed = True

    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            print("=" * 50)
            print("FINANCIAL YEAR SALES VALIDATION")
            print("=" * 50)

            years = ["2025-26", "2026-27"]

            for co_year in years:
                print(f"\nTest {co_year}\n")

                # 1. Independent SQL summary calculation directly from public.transection
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
                      AND co_year IS NOT NULL AND TRIM(CAST(co_year AS TEXT)) = TRIM(CAST(%s AS TEXT));
                """, (co_year,))
                sql_res = cur.fetchone()

                distinct_inv_cnt = sql_res["distinct_invoice_count"]
                total_ac_rows = sql_res["total_accounting_rows"]
                debit_sum = float(sql_res["debit_amount_sum"])
                total_sum = float(sql_res["total_amount_sum"])
                min_date = sql_res["min_doc_date"]
                max_date = sql_res["max_doc_date"]

                print("Independent SQL Summary:")
                print(f"  1. DISTINCT invoice count                   : {distinct_inv_cnt}")
                print(f"  2. COUNT(*) accounting rows                 : {total_ac_rows}")
                print(f"  3. SUM(CASE WHEN cr_dr = 'D' THEN amount)   : {debit_sum:.2f}")
                print(f"  4. SUM(amount) total                        : {total_sum:.2f}")
                print(f"  5. MIN(doc_date)                            : {min_date}")
                print(f"  6. MAX(doc_date)                            : {max_date}")

                # 2. Call get_sale_by_financial_year function
                func_res = get_sale_by_financial_year(co_year)

                # Validations
                validations = []

                # Validation: Financial year exists flag
                v_exists = func_res.get("exists") is True
                validations.append(("Financial year exists flag", v_exists))

                # Validation: Returned invoice count == independent DISTINCT inv_no count
                func_inv_cnt = func_res.get("number_of_invoices", 0)
                v_inv_cnt = func_inv_cnt == distinct_inv_cnt
                validations.append(("Returned invoice count == independent DISTINCT inv_no count", v_inv_cnt))

                # Validation: Returned accounting row count == independent COUNT(*)
                func_ac_rows = func_res.get("number_of_accounting_rows", 0)
                v_ac_rows = func_ac_rows == total_ac_rows
                validations.append(("Returned accounting row count == independent COUNT(*)", v_ac_rows))

                # Validation: Returned total_amount == independent debit-side SUM
                func_tot_amt = func_res.get("total_amount", 0.0)
                v_tot_amt = abs(func_tot_amt - debit_sum) < 0.01
                validations.append(("Returned total_amount == independent debit-side SUM", v_tot_amt))

                # Validation: Returned invoice numbers are unique
                returned_invoices = func_res.get("invoices", [])
                inv_nos = [inv["invoice_no"] for inv in returned_invoices]
                v_unique = len(inv_nos) == len(set(inv_nos))
                validations.append(("Returned invoice numbers are unique", v_unique))

                # Validation: Every returned invoice belongs to requested financial year
                cur.execute("""
                    SELECT DISTINCT TRIM(CAST(inv_no AS TEXT)) AS inv_no
                    FROM public.transection
                    WHERE inv_type = 'VSALE'
                      AND co_year IS NOT NULL AND TRIM(CAST(co_year AS TEXT)) = TRIM(CAST(%s AS TEXT));
                """, (co_year,))
                valid_fy_inv_set = {r["inv_no"] for r in cur.fetchall()}
                v_belongs = set(inv_nos).issubset(valid_fy_inv_set)
                validations.append(("Every returned invoice belongs to requested financial year", v_belongs))

                # Validation: No invoice has duplicated invoice-level summary
                v_no_dup = len(returned_invoices) == len(set(inv_nos))
                validations.append(("No invoice has duplicated invoice-level summary", v_no_dup))

                # Validation: Returned invoice totals equal independent invoice-level debit totals
                cur.execute("""
                    SELECT 
                        TRIM(CAST(inv_no AS TEXT)) AS inv_no,
                        COUNT(*) AS ac_rows,
                        COALESCE(SUM(CASE WHEN cr_dr = 'D' THEN amount ELSE 0 END), 0) AS debit_total
                    FROM public.transection
                    WHERE inv_type = 'VSALE'
                      AND co_year IS NOT NULL AND TRIM(CAST(co_year AS TEXT)) = TRIM(CAST(%s AS TEXT))
                    GROUP BY TRIM(CAST(inv_no AS TEXT));
                """, (co_year,))
                sql_inv_map = {r["inv_no"]: (r["ac_rows"], float(r["debit_total"])) for r in cur.fetchall()}

                inv_totals_match = True
                for inv in returned_invoices:
                    i_no = inv["invoice_no"]
                    exp_rows, exp_amt = sql_inv_map.get(i_no, (0, 0.0))
                    if inv["accounting_row_count"] != exp_rows or abs(inv["invoice_total_amount"] - exp_amt) >= 0.01:
                        inv_totals_match = False
                        break

                validations.append(("Returned invoice totals equal independent invoice-level debit totals", inv_totals_match))

                # Validation: Returned min_doc_date == independent MIN(doc_date)
                v_min_date = func_res.get("min_doc_date") == min_date
                validations.append(("Returned min_doc_date == independent MIN(doc_date)", v_min_date))

                # Validation: Returned max_doc_date == independent MAX(doc_date)
                v_max_date = func_res.get("max_doc_date") == max_date
                validations.append(("Returned max_doc_date == independent MAX(doc_date)", v_max_date))

                print("\nValidation Results:")
                for name, passed in validations:
                    status = "[PASS]" if passed else "[FAIL]"
                    print(f"  {status} {name}")
                    if not passed:
                        all_passed = False

            # --- FINANCIAL YEAR COVERAGE ---
            print("\n" + "=" * 50)
            print("FINANCIAL YEAR COVERAGE")
            print("=" * 50)

            cur.execute("""
                SELECT DISTINCT TRIM(CAST(co_year AS TEXT)) AS co_year
                FROM public.transection
                WHERE inv_type = 'VSALE' AND co_year IS NOT NULL
                ORDER BY co_year;
            """)
            actual_fy_values = [r["co_year"] for r in cur.fetchall()]
            print(f"\nActual VSALE financial years in public.transection: {actual_fy_values}")

            cur.execute("""
                SELECT inv_no, ARRAY_AGG(DISTINCT TRIM(CAST(co_year AS TEXT))) AS year_list
                FROM public.transection
                WHERE inv_type = 'VSALE' AND co_year IS NOT NULL
                GROUP BY inv_no;
            """)
            inv_fy_rows = cur.fetchall()

            y25_only = []
            y26_only = []
            both_years = []

            for r in inv_fy_rows:
                y_set = set(r["year_list"])
                if y_set == {"2025-26"}:
                    y25_only.append(r["inv_no"])
                elif y_set == {"2026-27"}:
                    y26_only.append(r["inv_no"])
                elif "2025-26" in y_set and "2026-27" in y_set:
                    both_years.append(r["inv_no"])

            total_distinct_vsale = len(inv_fy_rows)

            print(f"\nBreakdown:")
            print(f"  - Total distinct VSALE invoices    : {total_distinct_vsale}")
            print(f"  - Invoices only in 2025-26          : {len(y25_only)}")
            print(f"  - Invoices only in 2026-27          : {len(y26_only)}")
            print(f"  - Invoices appearing in both years  : {len(both_years)} ({both_years[:5]}...)")

            v_coverage = (total_distinct_vsale == 696) and (len(y25_only) + len(y26_only) + len(both_years) == 696)
            status_cov = "[PASS]" if v_coverage else "[FAIL]"
            print(f"\n  {status_cov} Financial years ('2025-26', '2026-27') together account for all {total_distinct_vsale}/696 (100%) VSALE invoices")

            if not v_coverage or set(actual_fy_values) != {"2025-26", "2026-27"}:
                all_passed = False

            # --- DATE CROSS-CHECK ---
            print("\n" + "=" * 50)
            print("DATE CROSS-CHECK")
            print("=" * 50)

            cur.execute("""
                SELECT inv_no, co_year, MIN(doc_date) as min_date, MAX(doc_date) as max_date
                FROM public.transection
                WHERE inv_type = 'VSALE' AND co_year IS NOT NULL AND doc_date IS NOT NULL
                GROUP BY inv_no, co_year
                HAVING (co_year = '2025-26' AND (MIN(doc_date) < '20250401' OR MAX(doc_date) > '20260331'))
                    OR (co_year = '2026-27' AND (MIN(doc_date) < '20260401' OR MAX(doc_date) > '20270331'));
            """)
            anomalous_dates = cur.fetchall()

            print(f"\nComparison of co_year vs doc_date alignment:")
            print(f"  - Financial year '2025-26' expected date range : 20250401 to 20260331")
            print(f"  - Financial year '2026-27' expected date range : 20260401 to 20270331")
            print(f"  - Invoices with doc_date outside co_year range: {len(anomalous_dates)}")
            if len(anomalous_dates) == 0:
                print("  [PASS] All invoice doc_dates strictly align with their respective co_year bounds")
            else:
                print(f"  [INFO] Found {len(anomalous_dates)} unusual date invoices")

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
