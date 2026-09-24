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

# Import existing deterministic query functions
from scripts.test_sale_by_invoice import get_sale_by_invoice, get_db_connection
from scripts.test_sale_by_customer import get_sale_by_customer
from scripts.test_sale_by_product import get_sale_by_product
from scripts.test_sale_by_date import get_sale_by_date
from scripts.get_sale_by_series import get_sale_by_series
from scripts.get_sale_by_ev import get_sale_by_ev
from scripts.get_sale_by_financial_year import get_sale_by_financial_year
from scripts.get_sale_by_gl_account import get_sale_by_gl_account


def run_integration_tests():
    """
    Final Integration Validation of all 8 Sales query dimensions.
    Reuses existing query functions and validates them against independent READ-ONLY SQL.
    Performs cross-dimension integration testing on a single VSALE invoice across all dimensions.
    """
    conn = get_db_connection()
    conn.set_session(readonly=True)

    results_summary = {}
    details = {}

    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:

            # ==================================================
            # TEST 1 - INVOICE
            # ==================================================
            cur.execute("""
                SELECT DISTINCT TRIM(CAST(t.inv_no AS TEXT)) AS inv_no
                FROM public.transection t
                JOIN public.trn_jobcard j ON TRIM(CAST(t.inv_no AS TEXT)) = TRIM(CAST(j.inv_no AS TEXT))
                WHERE t.inv_type = 'VSALE' AND t.inv_no IS NOT NULL AND TRIM(CAST(t.inv_no AS TEXT)) != ''
                ORDER BY inv_no LIMIT 1;
            """)
            test_inv_no = cur.fetchone()["inv_no"]

            cur.execute("""
                SELECT 
                    COUNT(*) AS ac_rows,
                    COALESCE(SUM(CASE WHEN cr_dr = 'D' THEN amount ELSE 0 END), 0) AS total_amt
                FROM public.transection
                WHERE inv_type = 'VSALE' AND TRIM(CAST(inv_no AS TEXT)) = TRIM(CAST(%s AS TEXT));
            """, (test_inv_no,))
            sql_inv = cur.fetchone()

            res_1 = get_sale_by_invoice(test_inv_no)

            p1_exists = res_1.get("exists") is True
            p1_inv = res_1.get("invoice_no") == test_inv_no
            p1_rows = res_1.get("number_of_accounting_rows") == sql_inv["ac_rows"]
            p1_amt = abs(res_1.get("transaction_summary", {}).get("total_amount", 0.0) - float(sql_inv["total_amt"])) < 0.01

            pass_1 = p1_exists and p1_inv and p1_rows and p1_amt
            results_summary["TEST 1 - INVOICE"] = pass_1
            if not pass_1:
                details["TEST 1 - INVOICE"] = (
                    f"Expected: inv={test_inv_no}, rows={sql_inv['ac_rows']}, amt={sql_inv['total_amt']} | "
                    f"Returned: exists={res_1.get('exists')}, inv={res_1.get('invoice_no')}, "
                    f"rows={res_1.get('number_of_accounting_rows')}, amt={res_1.get('transaction_summary', {}).get('total_amount')}"
                )

            # ==================================================
            # TEST 2 - CUSTOMER
            # ==================================================
            cur.execute("""
                SELECT DISTINCT TRIM(CAST(h.cust_code AS TEXT)) AS cust_code
                FROM public.mst_history h
                JOIN public.trn_jobcard j ON TRIM(CAST(h.hist_code AS TEXT)) = TRIM(CAST(j.hist_code AS TEXT))
                JOIN public.transection t ON TRIM(CAST(j.inv_no AS TEXT)) = TRIM(CAST(t.inv_no AS TEXT))
                WHERE t.inv_type = 'VSALE' AND h.cust_code IS NOT NULL AND TRIM(CAST(h.cust_code AS TEXT)) != ''
                ORDER BY cust_code LIMIT 1;
            """)
            test_cust_code = cur.fetchone()["cust_code"]

            cur.execute("""
                SELECT DISTINCT TRIM(CAST(j.inv_no AS TEXT)) AS inv_no
                FROM public.trn_jobcard j
                JOIN public.mst_history h ON TRIM(CAST(h.hist_code AS TEXT)) = TRIM(CAST(j.hist_code AS TEXT))
                JOIN public.transection t ON TRIM(CAST(j.inv_no AS TEXT)) = TRIM(CAST(t.inv_no AS TEXT))
                WHERE t.inv_type = 'VSALE' AND TRIM(CAST(h.cust_code AS TEXT)) = TRIM(CAST(%s AS TEXT));
            """, (test_cust_code,))
            cust_inv_nos = [r["inv_no"] for r in cur.fetchall()]

            cur.execute("""
                SELECT 
                    COUNT(*) AS ac_rows,
                    COALESCE(SUM(CASE WHEN cr_dr = 'D' THEN amount ELSE 0 END), 0) AS total_amt
                FROM public.transection
                WHERE inv_type = 'VSALE' AND TRIM(CAST(inv_no AS TEXT)) = ANY(%s);
            """, (cust_inv_nos,))
            sql_cust = cur.fetchone()

            res_2 = get_sale_by_customer(test_cust_code)

            ret_invs_2 = [inv["invoice_no"] for inv in res_2.get("invoices", [])]
            p2_exists = res_2.get("exists") is True
            p2_unique = len(ret_invs_2) == len(set(ret_invs_2))
            p2_cnt = res_2.get("number_of_invoices") == len(cust_inv_nos)
            p2_rows = res_2.get("number_of_accounting_rows") == sql_cust["ac_rows"]
            p2_amt = abs(res_2.get("total_amount", 0.0) - float(sql_cust["total_amt"])) < 0.01

            pass_2 = p2_exists and p2_unique and p2_cnt and p2_rows and p2_amt
            results_summary["TEST 2 - CUSTOMER"] = pass_2
            if not pass_2:
                details["TEST 2 - CUSTOMER"] = (
                    f"Expected: inv_cnt={len(cust_inv_nos)}, rows={sql_cust['ac_rows']}, amt={sql_cust['total_amt']} | "
                    f"Returned: exists={res_2.get('exists')}, inv_cnt={res_2.get('number_of_invoices')}, "
                    f"rows={res_2.get('number_of_accounting_rows')}, amt={res_2.get('total_amount')}"
                )

            # ==================================================
            # TEST 3 - PRODUCT
            # ==================================================
            cur.execute("""
                SELECT DISTINCT TRIM(CAST(h.product_code AS TEXT)) AS product_code
                FROM public.mst_history h
                JOIN public.trn_jobcard j ON TRIM(CAST(h.hist_code AS TEXT)) = TRIM(CAST(j.hist_code AS TEXT))
                JOIN public.transection t ON TRIM(CAST(j.inv_no AS TEXT)) = TRIM(CAST(t.inv_no AS TEXT))
                WHERE t.inv_type = 'VSALE' AND h.product_code IS NOT NULL AND TRIM(CAST(h.product_code AS TEXT)) != ''
                ORDER BY product_code LIMIT 1;
            """)
            test_product_code = cur.fetchone()["product_code"]

            cur.execute("""
                SELECT DISTINCT TRIM(CAST(j.inv_no AS TEXT)) AS inv_no
                FROM public.trn_jobcard j
                JOIN public.mst_history h ON TRIM(CAST(h.hist_code AS TEXT)) = TRIM(CAST(j.hist_code AS TEXT))
                JOIN public.transection t ON TRIM(CAST(j.inv_no AS TEXT)) = TRIM(CAST(t.inv_no AS TEXT))
                WHERE t.inv_type = 'VSALE' AND TRIM(CAST(h.product_code AS TEXT)) = TRIM(CAST(%s AS TEXT));
            """, (test_product_code,))
            prod_inv_nos = [r["inv_no"] for r in cur.fetchall()]

            cur.execute("""
                SELECT 
                    COUNT(*) AS ac_rows,
                    COALESCE(SUM(CASE WHEN cr_dr = 'D' THEN amount ELSE 0 END), 0) AS total_amt
                FROM public.transection
                WHERE inv_type = 'VSALE' AND TRIM(CAST(inv_no AS TEXT)) = ANY(%s);
            """, (prod_inv_nos,))
            sql_prod = cur.fetchone()

            res_3 = get_sale_by_product(test_product_code)

            ret_invs_3 = [inv["invoice_no"] for inv in res_3.get("invoices", [])]
            p3_exists = res_3.get("exists") is True
            p3_unique = len(ret_invs_3) == len(set(ret_invs_3))
            p3_cnt = res_3.get("number_of_invoices") == len(prod_inv_nos)
            p3_rows = res_3.get("number_of_accounting_rows") == sql_prod["ac_rows"]
            p3_amt = abs(res_3.get("total_amount", 0.0) - float(sql_prod["total_amt"])) < 0.01

            pass_3 = p3_exists and p3_unique and p3_cnt and p3_rows and p3_amt
            results_summary["TEST 3 - PRODUCT"] = pass_3
            if not pass_3:
                details["TEST 3 - PRODUCT"] = (
                    f"Expected: inv_cnt={len(prod_inv_nos)}, rows={sql_prod['ac_rows']}, amt={sql_prod['total_amt']} | "
                    f"Returned: exists={res_3.get('exists')}, inv_cnt={res_3.get('number_of_invoices')}, "
                    f"rows={res_3.get('number_of_accounting_rows')}, amt={res_3.get('total_amount')}"
                )

            # ==================================================
            # TEST 4 - DATE
            # ==================================================
            start_date = "20250711"
            end_date = "20250720"

            cur.execute("""
                SELECT DISTINCT TRIM(CAST(inv_no AS TEXT)) AS inv_no
                FROM public.transection
                WHERE inv_type = 'VSALE'
                  AND doc_date IS NOT NULL AND TRIM(CAST(doc_date AS TEXT)) != ''
                  AND TRIM(CAST(doc_date AS TEXT)) >= %s
                  AND TRIM(CAST(doc_date AS TEXT)) <= %s;
            """, (start_date, end_date))
            date_inv_nos = [r["inv_no"] for r in cur.fetchall()]

            cur.execute("""
                SELECT 
                    COUNT(*) AS ac_rows,
                    COALESCE(SUM(CASE WHEN cr_dr = 'D' THEN amount ELSE 0 END), 0) AS total_amt
                FROM public.transection
                WHERE inv_type = 'VSALE' AND TRIM(CAST(inv_no AS TEXT)) = ANY(%s);
            """, (date_inv_nos,))
            sql_date = cur.fetchone()

            res_4 = get_sale_by_date(start_date, end_date)

            ret_invs_4 = [inv["invoice_no"] for inv in res_4.get("invoices", [])]
            p4_exists = res_4.get("exists") is True
            p4_unique = len(ret_invs_4) == len(set(ret_invs_4))
            p4_cnt = res_4.get("number_of_invoices") == len(date_inv_nos)
            p4_rows = res_4.get("number_of_accounting_rows") == sql_date["ac_rows"]
            p4_amt = abs(res_4.get("total_amount", 0.0) - float(sql_date["total_amt"])) < 0.01

            pass_4 = p4_exists and p4_unique and p4_cnt and p4_rows and p4_amt
            results_summary["TEST 4 - DATE"] = pass_4
            if not pass_4:
                details["TEST 4 - DATE"] = (
                    f"Expected: inv_cnt={len(date_inv_nos)}, rows={sql_date['ac_rows']}, amt={sql_date['total_amt']} | "
                    f"Returned: exists={res_4.get('exists')}, inv_cnt={res_4.get('number_of_invoices')}, "
                    f"rows={res_4.get('number_of_accounting_rows')}, amt={res_4.get('total_amount')}"
                )

            # ==================================================
            # TEST 5 - VOUCHER SERIES
            # ==================================================
            test_series = "0000001"

            cur.execute("""
                SELECT 
                    COUNT(DISTINCT TRIM(CAST(inv_no AS TEXT))) AS inv_cnt,
                    COUNT(*) AS ac_rows,
                    COALESCE(SUM(CASE WHEN cr_dr = 'D' THEN amount ELSE 0 END), 0) AS total_amt
                FROM public.transection
                WHERE inv_type = 'VSALE' AND TRIM(CAST(series AS TEXT)) = TRIM(CAST(%s AS TEXT));
            """, (test_series,))
            sql_series = cur.fetchone()

            res_5 = get_sale_by_series(test_series)

            ret_invs_5 = [inv["invoice_no"] for inv in res_5.get("invoices", [])]
            p5_exists = res_5.get("exists") is True
            p5_unique = len(ret_invs_5) == len(set(ret_invs_5))
            p5_cnt = res_5.get("number_of_invoices") == sql_series["inv_cnt"]
            p5_rows = res_5.get("number_of_accounting_rows") == sql_series["ac_rows"]
            p5_amt = abs(res_5.get("total_amount", 0.0) - float(sql_series["total_amt"])) < 0.01

            pass_5 = p5_exists and p5_unique and p5_cnt and p5_rows and p5_amt
            results_summary["TEST 5 - VOUCHER SERIES"] = pass_5
            if not pass_5:
                details["TEST 5 - VOUCHER SERIES"] = (
                    f"Expected: inv_cnt={sql_series['inv_cnt']}, rows={sql_series['ac_rows']}, amt={sql_series['total_amt']} | "
                    f"Returned: exists={res_5.get('exists')}, inv_cnt={res_5.get('number_of_invoices')}, "
                    f"rows={res_5.get('number_of_accounting_rows')}, amt={res_5.get('total_amount')}"
                )

            # ==================================================
            # TEST 6 - EV
            # ==================================================
            test_ev = 1

            cur.execute("""
                SELECT 
                    COUNT(DISTINCT TRIM(CAST(inv_no AS TEXT))) AS inv_cnt,
                    COUNT(*) AS ac_rows,
                    COALESCE(SUM(CASE WHEN cr_dr = 'D' THEN amount ELSE 0 END), 0) AS total_amt
                FROM public.transection
                WHERE inv_type = 'VSALE' AND ev IS NOT NULL AND CAST(ev AS INTEGER) = %s;
            """, (test_ev,))
            sql_ev = cur.fetchone()

            res_6 = get_sale_by_ev(test_ev)

            ret_invs_6 = [inv["invoice_no"] for inv in res_6.get("invoices", [])]
            p6_exists = res_6.get("exists") is True
            p6_unique = len(ret_invs_6) == len(set(ret_invs_6))
            p6_cnt = res_6.get("number_of_invoices") == sql_ev["inv_cnt"]
            p6_rows = res_6.get("number_of_accounting_rows") == sql_ev["ac_rows"]
            p6_amt = abs(res_6.get("total_amount", 0.0) - float(sql_ev["total_amt"])) < 0.01

            pass_6 = p6_exists and p6_unique and p6_cnt and p6_rows and p6_amt
            results_summary["TEST 6 - EV"] = pass_6
            if not pass_6:
                details["TEST 6 - EV"] = (
                    f"Expected: inv_cnt={sql_ev['inv_cnt']}, rows={sql_ev['ac_rows']}, amt={sql_ev['total_amt']} | "
                    f"Returned: exists={res_6.get('exists')}, inv_cnt={res_6.get('number_of_invoices')}, "
                    f"rows={res_6.get('number_of_accounting_rows')}, amt={res_6.get('total_amount')}"
                )

            # ==================================================
            # TEST 7 - FINANCIAL YEAR
            # ==================================================
            test_fy = "2025-26"

            cur.execute("""
                SELECT 
                    COUNT(DISTINCT TRIM(CAST(inv_no AS TEXT))) AS inv_cnt,
                    COUNT(*) AS ac_rows,
                    COALESCE(SUM(CASE WHEN cr_dr = 'D' THEN amount ELSE 0 END), 0) AS total_amt
                FROM public.transection
                WHERE inv_type = 'VSALE' AND TRIM(CAST(co_year AS TEXT)) = TRIM(CAST(%s AS TEXT));
            """, (test_fy,))
            sql_fy = cur.fetchone()

            res_7 = get_sale_by_financial_year(test_fy)

            ret_invs_7 = [inv["invoice_no"] for inv in res_7.get("invoices", [])]
            p7_exists = res_7.get("exists") is True
            p7_unique = len(ret_invs_7) == len(set(ret_invs_7))
            p7_cnt = res_7.get("number_of_invoices") == sql_fy["inv_cnt"]
            p7_rows = res_7.get("number_of_accounting_rows") == sql_fy["ac_rows"]
            p7_amt = abs(res_7.get("total_amount", 0.0) - float(sql_fy["total_amt"])) < 0.01

            pass_7 = p7_exists and p7_unique and p7_cnt and p7_rows and p7_amt
            results_summary["TEST 7 - FINANCIAL YEAR"] = pass_7
            if not pass_7:
                details["TEST 7 - FINANCIAL YEAR"] = (
                    f"Expected: inv_cnt={sql_fy['inv_cnt']}, rows={sql_fy['ac_rows']}, amt={sql_fy['total_amt']} | "
                    f"Returned: exists={res_7.get('exists')}, inv_cnt={res_7.get('number_of_invoices')}, "
                    f"rows={res_7.get('number_of_accounting_rows')}, amt={res_7.get('total_amount')}"
                )

            # ==================================================
            # TEST 8 - GL ACCOUNT
            # ==================================================
            test_ac = "9100579"

            cur.execute("""
                SELECT 
                    COUNT(DISTINCT TRIM(CAST(inv_no AS TEXT))) AS inv_cnt,
                    COUNT(*) AS ac_rows,
                    COALESCE(SUM(CASE WHEN cr_dr = 'D' THEN amount ELSE 0 END), 0) AS total_amt
                FROM public.transection
                WHERE inv_type = 'VSALE' AND TRIM(CAST(ac_code AS TEXT)) = TRIM(CAST(%s AS TEXT));
            """, (test_ac,))
            sql_ac = cur.fetchone()

            res_8 = get_sale_by_gl_account(test_ac)

            ret_invs_8 = [inv["invoice_no"] for inv in res_8.get("invoices", [])]
            p8_exists = res_8.get("exists") is True
            p8_unique = len(ret_invs_8) == len(set(ret_invs_8))
            p8_cnt = res_8.get("number_of_invoices") == sql_ac["inv_cnt"]
            p8_rows = res_8.get("number_of_accounting_rows") == sql_ac["ac_rows"]
            p8_amt = abs(res_8.get("total_amount", 0.0) - float(sql_ac["total_amt"])) < 0.01

            pass_8 = p8_exists and p8_unique and p8_cnt and p8_rows and p8_amt
            results_summary["TEST 8 - GL ACCOUNT"] = pass_8
            if not pass_8:
                details["TEST 8 - GL ACCOUNT"] = (
                    f"Expected: inv_cnt={sql_ac['inv_cnt']}, rows={sql_ac['ac_rows']}, amt={sql_ac['total_amt']} | "
                    f"Returned: exists={res_8.get('exists')}, inv_cnt={res_8.get('number_of_invoices')}, "
                    f"rows={res_8.get('number_of_accounting_rows')}, amt={res_8.get('total_amount')}"
                )

            # ==================================================
            # CROSS-DIMENSION INTEGRATION
            # ==================================================
            cur.execute("""
                SELECT 
                    TRIM(CAST(t.inv_no AS TEXT)) AS inv_no,
                    TRIM(CAST(MIN(t.doc_date) AS TEXT)) AS doc_date,
                    TRIM(CAST(MIN(t.series) AS TEXT)) AS series,
                    CAST(MIN(t.ev) AS INTEGER) AS ev,
                    TRIM(CAST(MIN(t.co_year) AS TEXT)) AS co_year,
                    TRIM(CAST(MIN(t.ac_code) AS TEXT)) AS ac_code,
                    TRIM(CAST(MIN(h.cust_code) AS TEXT)) AS cust_code,
                    TRIM(CAST(MIN(h.product_code) AS TEXT)) AS product_code
                FROM public.transection t
                JOIN public.trn_jobcard j ON TRIM(CAST(t.inv_no AS TEXT)) = TRIM(CAST(j.inv_no AS TEXT))
                JOIN public.mst_history h ON TRIM(CAST(j.hist_code AS TEXT)) = TRIM(CAST(h.hist_code AS TEXT))
                WHERE t.inv_type = 'VSALE'
                  AND t.inv_no IS NOT NULL AND TRIM(CAST(t.inv_no AS TEXT)) != ''
                  AND h.cust_code IS NOT NULL AND TRIM(CAST(h.cust_code AS TEXT)) != ''
                  AND h.product_code IS NOT NULL AND TRIM(CAST(h.product_code AS TEXT)) != ''
                GROUP BY TRIM(CAST(t.inv_no AS TEXT))
                ORDER BY inv_no LIMIT 1;
            """)
            target_invoice = cur.fetchone()

            target_inv_no = target_invoice["inv_no"]
            target_cust = target_invoice["cust_code"]
            target_prod = target_invoice["product_code"]
            target_dt = target_invoice["doc_date"]
            target_series = target_invoice["series"]
            target_ev = target_invoice["ev"]
            target_year = target_invoice["co_year"]
            target_ac = target_invoice["ac_code"]

            cd_inv = get_sale_by_invoice(target_inv_no)
            cd_cust = get_sale_by_customer(target_cust)
            cd_prod = get_sale_by_product(target_prod)
            cd_date = get_sale_by_date(target_dt, target_dt)
            cd_series = get_sale_by_series(target_series)
            cd_ev = get_sale_by_ev(target_ev)
            cd_year = get_sale_by_financial_year(target_year)
            cd_ac = get_sale_by_gl_account(target_ac)

            def has_inv(res, target):
                if res.get("invoice_no") == target and res.get("exists"):
                    return True
                invs = res.get("invoices", [])
                return any(i.get("invoice_no") == target for i in invs)

            checks_cd = {
                "get_sale_by_invoice": has_inv(cd_inv, target_inv_no),
                "get_sale_by_customer": has_inv(cd_cust, target_inv_no),
                "get_sale_by_product": has_inv(cd_prod, target_inv_no),
                "get_sale_by_date": has_inv(cd_date, target_inv_no),
                "get_sale_by_series": has_inv(cd_series, target_inv_no),
                "get_sale_by_ev": has_inv(cd_ev, target_inv_no),
                "get_sale_by_financial_year": has_inv(cd_year, target_inv_no),
                "get_sale_by_gl_account": has_inv(cd_ac, target_inv_no),
            }

            pass_cd = all(checks_cd.values())
            results_summary["CROSS-DIMENSION INTEGRATION"] = pass_cd
            if not pass_cd:
                details["CROSS-DIMENSION INTEGRATION"] = f"Target invoice {target_inv_no} missing in dimensions: {[k for k, v in checks_cd.items() if not v]}"

            # ==================================================
            # FINAL PRINT REPORT
            # ==================================================
            print("=" * 50)
            print("SALES QUERY INTEGRATION VALIDATION")
            print("=" * 50 + "\n")

            test_order = [
                ("TEST 1 - INVOICE", "TEST 1 - INVOICE"),
                ("TEST 2 - CUSTOMER", "TEST 2 - CUSTOMER"),
                ("TEST 3 - PRODUCT", "TEST 3 - PRODUCT"),
                ("TEST 4 - DATE", "TEST 4 - DATE"),
                ("TEST 5 - VOUCHER SERIES", "TEST 5 - VOUCHER SERIES"),
                ("TEST 6 - EV", "TEST 6 - EV"),
                ("TEST 7 - FINANCIAL YEAR", "TEST 7 - FINANCIAL YEAR"),
                ("TEST 8 - GL ACCOUNT", "TEST 8 - GL ACCOUNT"),
            ]

            for label, key in test_order:
                status = "[PASS]" if results_summary.get(key) else "[FAIL]"
                print(f"{label}\n{status}\n")
                if not results_summary.get(key):
                    print(f"Details: {details.get(key)}\n")

            print("=" * 50)
            print("CROSS-DIMENSION INTEGRATION")
            print("=" * 50)
            cd_status = "[PASS]" if results_summary.get("CROSS-DIMENSION INTEGRATION") else "[FAIL]"
            print(f"\n{cd_status}\n")
            if not results_summary.get("CROSS-DIMENSION INTEGRATION"):
                print(f"Details: {details.get('CROSS-DIMENSION INTEGRATION')}\n")

            print("=" * 50)
            print("OVERALL RESULT")
            print("=" * 50)

            all_ok = all(results_summary.values())
            if all_ok:
                print("\nALL VALIDATIONS PASSED [PASS]\n")
            else:
                print("\nSOME VALIDATIONS FAILED [FAIL]\n")

    finally:
        conn.close()


if __name__ == "__main__":
    run_integration_tests()
