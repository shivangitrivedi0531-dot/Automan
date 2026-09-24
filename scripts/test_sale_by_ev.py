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

from scripts.get_sale_by_ev import get_sale_by_ev, get_db_connection


def run_tests():
    """
    Validates get_sale_by_ev() against independent READ-ONLY SQL queries.
    Tests both EV values (ev=0 for NON-EV, ev=1 for EV).
    Cross-checks invoice coverage and multi-EV invoice distribution.
    """
    conn = get_db_connection()
    conn.set_session(readonly=True)
    all_passed = True

    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            print("=" * 50)
            print("EV SALES VALIDATION")
            print("=" * 50)

            ev_values = [0, 1]

            for ev in ev_values:
                print(f"\nTest EV={ev}\n")

                expected_label = "EV" if ev == 1 else "NON-EV"

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
                      AND ev IS NOT NULL AND CAST(ev AS INTEGER) = %s;
                """, (ev,))
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

                # 2. Call get_sale_by_ev function
                func_res = get_sale_by_ev(ev)

                # Validations
                validations = []

                # Validation: EV exists/valid
                v_exists = func_res.get("exists") is True
                validations.append(("EV exists/valid", v_exists))

                # Validation: EV label is correct
                v_label = func_res.get("ev_label") == expected_label
                validations.append(("EV label is correct", v_label))

                # Validation: Returned invoice count equals independent DISTINCT inv_no count
                func_inv_cnt = func_res.get("number_of_invoices", 0)
                v_inv_cnt = func_inv_cnt == distinct_inv_cnt
                validations.append(("Returned invoice count equals independent DISTINCT inv_no count", v_inv_cnt))

                # Validation: Returned accounting rows equals independent COUNT(*)
                func_ac_rows = func_res.get("number_of_accounting_rows", 0)
                v_ac_rows = func_ac_rows == total_ac_rows
                validations.append(("Returned accounting rows equals independent COUNT(*)", v_ac_rows))

                # Validation: Returned total_amount equals independent debit-side SUM
                func_tot_amt = func_res.get("total_amount", 0.0)
                v_tot_amt = abs(func_tot_amt - debit_sum) < 0.01
                validations.append(("Returned total_amount equals independent debit-side SUM", v_tot_amt))

                # Validation: Returned invoice numbers are unique
                returned_invoices = func_res.get("invoices", [])
                inv_nos = [inv["invoice_no"] for inv in returned_invoices]
                v_unique = len(inv_nos) == len(set(inv_nos))
                validations.append(("Returned invoice numbers are unique", v_unique))

                # Validation: Every returned invoice belongs to the requested EV value
                cur.execute("""
                    SELECT DISTINCT TRIM(CAST(inv_no AS TEXT)) AS inv_no
                    FROM public.transection
                    WHERE inv_type = 'VSALE'
                      AND ev IS NOT NULL AND CAST(ev AS INTEGER) = %s;
                """, (ev,))
                valid_ev_inv_set = {r["inv_no"] for r in cur.fetchall()}
                v_belongs = set(inv_nos).issubset(valid_ev_inv_set)
                validations.append(("Every returned invoice belongs to the requested EV value", v_belongs))

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
                      AND ev IS NOT NULL AND CAST(ev AS INTEGER) = %s
                    GROUP BY TRIM(CAST(inv_no AS TEXT));
                """, (ev,))
                sql_inv_map = {r["inv_no"]: (r["ac_rows"], float(r["debit_total"])) for r in cur.fetchall()}

                inv_totals_match = True
                for inv in returned_invoices:
                    i_no = inv["invoice_no"]
                    exp_rows, exp_amt = sql_inv_map.get(i_no, (0, 0.0))
                    if inv["accounting_row_count"] != exp_rows or abs(inv["invoice_total_amount"] - exp_amt) >= 0.01:
                        inv_totals_match = False
                        break

                validations.append(("Returned invoice totals equal independent invoice-level debit totals", inv_totals_match))

                print("\nValidation Results:")
                for name, passed in validations:
                    status = "[PASS]" if passed else "[FAIL]"
                    print(f"  {status} {name}")
                    if not passed:
                        all_passed = False

            # --- CROSS-CHECK & MIXED INVOICE COVERAGE CHECK ---
            print("\n" + "=" * 50)
            print("EV COVERAGE / MIXED-INVOICE CHECK")
            print("=" * 50)

            cur.execute("""
                SELECT DISTINCT CAST(ev AS INTEGER) AS ev
                FROM public.transection
                WHERE inv_type = 'VSALE' AND ev IS NOT NULL
                ORDER BY ev;
            """)
            actual_ev_values = [r["ev"] for r in cur.fetchall()]
            print(f"\nActual VSALE EV values in transection: {actual_ev_values}")

            cur.execute("""
                SELECT inv_no, ARRAY_AGG(DISTINCT CAST(ev AS INTEGER)) as ev_list
                FROM public.transection
                WHERE inv_type = 'VSALE' AND ev IS NOT NULL
                GROUP BY inv_no;
            """)
            inv_ev_rows = cur.fetchall()

            ev0_only = []
            ev1_only = []
            both_ev = []

            for r in inv_ev_rows:
                ev_set = set(r["ev_list"])
                if ev_set == {0}:
                    ev0_only.append(r["inv_no"])
                elif ev_set == {1}:
                    ev1_only.append(r["inv_no"])
                elif 0 in ev_set and 1 in ev_set:
                    both_ev.append(r["inv_no"])

            total_distinct_vsale = len(inv_ev_rows)

            print(f"\nBreakdown:")
            print(f"  - Invoices with only EV=0       : {len(ev0_only)}")
            print(f"  - Invoices with only EV=1       : {len(ev1_only)}")
            print(f"  - Invoices containing both EV=0/1: {len(both_ev)} ({both_ev})")
            print(f"  - Total distinct VSALE invoices : {total_distinct_vsale}")

            v_coverage = (total_distinct_vsale == 696) and (len(ev0_only) + len(ev1_only) + len(both_ev) == 696)
            status_cov = "[PASS]" if v_coverage else "[FAIL]"
            print(f"\n  {status_cov} EV=0 and EV=1 together account for all {total_distinct_vsale}/696 (100%) VSALE invoices")

            if not v_coverage or set(actual_ev_values) != {0, 1}:
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
