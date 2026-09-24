import os
import sys

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


def get_db_connection():
    """
    Establishes a PostgreSQL database connection using standard environment variables.
    Reuses standard database connection configuration across deterministic scripts.
    """
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


def get_sale_by_gl_account(ac_code: str) -> dict:
    """
    Deterministic query function to retrieve Sales (VSALE) transactions by GL Account Code (ac_code).

    Authoritative relationship:
        public.transection.ac_code -> public.mst_ac_detail.ac_code

    Authoritative Operational context path:
        transection.inv_no -> trn_jobcard.inv_no -> trn_jobcard.hist_code -> mst_history.hist_code
        mst_history.product_code -> mst_product.product_code
    """
    if ac_code is None:
        return {
            "ac_code": None,
            "account_name": None,
            "exists": False,
            "number_of_invoices": 0,
            "number_of_accounting_rows": 0,
            "total_amount": 0,
            "sum_amount": 0,
            "min_doc_date": None,
            "max_doc_date": None,
            "invoices": []
        }

    ac_code_clean = str(ac_code).strip()

    conn = get_db_connection()
    try:
        conn.set_session(readonly=True)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # STEP 1 — ACCOUNT MASTER LOOKUP
            cur.execute("""
                SELECT TRIM(CAST(ac_code AS TEXT)) AS ac_code
                FROM public.mst_ac_detail
                WHERE ac_code IS NOT NULL AND TRIM(CAST(ac_code AS TEXT)) = TRIM(CAST(%s AS TEXT));
            """, (ac_code_clean,))
            m_row = cur.fetchone()

            has_master = bool(m_row)
            account_name = None  # mst_ac_detail schema does not contain an account name text column

            # STEP 2 — VSALE FILTER IN TRANSECTION
            cur.execute("""
                SELECT DISTINCT TRIM(CAST(inv_no AS TEXT)) AS inv_no
                FROM public.transection
                WHERE inv_type = 'VSALE'
                  AND ac_code IS NOT NULL AND TRIM(CAST(ac_code AS TEXT)) = TRIM(CAST(%s AS TEXT))
                  AND inv_no IS NOT NULL AND TRIM(CAST(inv_no AS TEXT)) != ''
                ORDER BY inv_no;
            """, (ac_code_clean,))
            inv_rows = cur.fetchall()
            inv_nos = [r["inv_no"] for r in inv_rows]

            has_tx = len(inv_nos) > 0

            if not has_master and not has_tx:
                return {
                    "ac_code": ac_code_clean,
                    "account_name": None,
                    "exists": False,
                    "number_of_invoices": 0,
                    "number_of_accounting_rows": 0,
                    "total_amount": 0,
                    "sum_amount": 0,
                    "min_doc_date": None,
                    "max_doc_date": None,
                    "invoices": []
                }

            if not inv_nos:
                return {
                    "ac_code": ac_code_clean,
                    "account_name": account_name,
                    "exists": True,
                    "number_of_invoices": 0,
                    "number_of_accounting_rows": 0,
                    "total_amount": 0.0,
                    "sum_amount": 0.0,
                    "min_doc_date": None,
                    "max_doc_date": None,
                    "invoices": []
                }

            # STEP 3 — ACCOUNTING SUMMARY (Calculated directly from transection before joins)
            cur.execute("""
                SELECT 
                    COUNT(*) AS number_of_accounting_rows,
                    COALESCE(SUM(CASE WHEN cr_dr = 'D' THEN amount ELSE 0 END), 0) AS total_amount,
                    COALESCE(SUM(amount), 0) AS sum_amount,
                    MIN(TRIM(CAST(doc_date AS TEXT))) AS min_doc_date,
                    MAX(TRIM(CAST(doc_date AS TEXT))) AS max_doc_date
                FROM public.transection
                WHERE inv_type = 'VSALE'
                  AND ac_code IS NOT NULL AND TRIM(CAST(ac_code AS TEXT)) = TRIM(CAST(%s AS TEXT));
            """, (ac_code_clean,))
            ac_summary = cur.fetchone()

            num_accounting_rows = ac_summary["number_of_accounting_rows"] if ac_summary else 0
            total_ac_amount = float(ac_summary["total_amount"]) if ac_summary else 0.0
            sum_ac_amount = float(ac_summary["sum_amount"]) if ac_summary else 0.0
            min_doc_date = ac_summary["min_doc_date"] if ac_summary and ac_summary["min_doc_date"] else None
            max_doc_date = ac_summary["max_doc_date"] if ac_summary and ac_summary["max_doc_date"] else None

            # STEP 4 — INVOICE-LEVEL SUMMARY
            cur.execute("""
                SELECT 
                    TRIM(CAST(inv_no AS TEXT)) AS inv_no,
                    COUNT(*) AS accounting_row_count,
                    COALESCE(SUM(CASE WHEN cr_dr = 'D' THEN amount ELSE 0 END), 0) AS invoice_total_amount,
                    MIN(TRIM(CAST(doc_date AS TEXT))) AS doc_date
                FROM public.transection
                WHERE inv_type = 'VSALE'
                  AND ac_code IS NOT NULL AND TRIM(CAST(ac_code AS TEXT)) = TRIM(CAST(%s AS TEXT))
                  AND inv_no = ANY(%s)
                GROUP BY TRIM(CAST(inv_no AS TEXT))
                ORDER BY inv_no;
            """, (ac_code_clean, inv_nos))
            inv_summary_rows = {r["inv_no"]: r for r in cur.fetchall()}

            # STEP 5 — OPERATIONAL VEHICLE / HISTORY CONTEXT (Preserve complete invoice context)
            cur.execute("""
                SELECT DISTINCT
                    TRIM(CAST(j.inv_no AS TEXT)) AS inv_no,
                    TRIM(CAST(h.hist_code AS TEXT)) AS hist_code,
                    TRIM(CAST(h.chassis_no AS TEXT)) AS chassis_no,
                    TRIM(CAST(h.engine_no AS TEXT)) AS engine_no,
                    TRIM(CAST(h.reg_no AS TEXT)) AS reg_no,
                    TRIM(CAST(h.product_code AS TEXT)) AS product_code,
                    TRIM(CAST(p.product_name AS TEXT)) AS product_name,
                    TRIM(CAST(h.cust_code AS TEXT)) AS cust_code,
                    TRIM(CAST(h.customer_name AS TEXT)) AS customer_name,
                    TRIM(CAST(h.sale_date AS TEXT)) AS sale_date
                FROM public.trn_jobcard j
                JOIN public.mst_history h ON TRIM(CAST(j.hist_code AS TEXT)) = TRIM(CAST(h.hist_code AS TEXT))
                LEFT JOIN public.mst_product p ON TRIM(CAST(h.product_code AS TEXT)) = TRIM(CAST(p.product_code AS TEXT))
                WHERE TRIM(CAST(j.inv_no AS TEXT)) = ANY(%s)
                ORDER BY inv_no, hist_code;
            """, (inv_nos,))
            vehicle_rows = cur.fetchall()

            # Group vehicle records by invoice
            inv_vehicles_map = {}
            for v in vehicle_rows:
                i_no = v["inv_no"]
                if i_no not in inv_vehicles_map:
                    inv_vehicles_map[i_no] = []
                inv_vehicles_map[i_no].append({
                    "hist_code": v["hist_code"] if v["hist_code"] else None,
                    "chassis_no": v["chassis_no"] if v["chassis_no"] else None,
                    "engine_no": v["engine_no"] if v["engine_no"] else None,
                    "reg_no": v["reg_no"] if v["reg_no"] else None,
                    "product_code": v["product_code"] if v["product_code"] else None,
                    "product_name": v["product_name"] if v["product_name"] else None,
                    "cust_code": v["cust_code"] if v["cust_code"] else None,
                    "customer_name": v["customer_name"] if v["customer_name"] else None,
                    "sale_date": v["sale_date"] if v["sale_date"] else None
                })

            # Assemble invoice list
            invoices = []
            for inv_no in inv_nos:
                s_info = inv_summary_rows.get(inv_no, {})
                ac_count = s_info.get("accounting_row_count", 0)
                inv_amt = float(s_info.get("invoice_total_amount", 0.0))
                doc_dt = s_info.get("doc_date") if s_info.get("doc_date") else None

                vehs = inv_vehicles_map.get(inv_no, [])

                invoices.append({
                    "invoice_no": inv_no,
                    "invoice_total_amount": inv_amt,
                    "accounting_row_count": ac_count,
                    "doc_date": doc_dt,
                    "number_of_history_records": len(vehs),
                    "vehicles": vehs
                })

            # RESULT CONTRACT
            return {
                "ac_code": ac_code_clean,
                "account_name": account_name,
                "exists": True,
                "number_of_invoices": len(invoices),
                "number_of_accounting_rows": num_accounting_rows,
                "total_amount": total_ac_amount,
                "sum_amount": sum_ac_amount,
                "min_doc_date": min_doc_date,
                "max_doc_date": max_doc_date,
                "invoices": invoices
            }
    finally:
        conn.close()


if __name__ == "__main__":
    result = get_sale_by_gl_account("9100579")
    print(f"GL Account: {result.get('ac_code')}")
    print(f"Account Name: {result.get('account_name')}")
    print(f"Exists: {result.get('exists')}")
    print(f"Invoices: {result.get('number_of_invoices')}")
    print(f"Accounting Rows: {result.get('number_of_accounting_rows')}")
    print(f"Total Amount: {result.get('total_amount')}")
    print(f"Sum Amount: {result.get('sum_amount')}")
    print(f"Min Doc Date: {result.get('min_doc_date')}")
    print(f"Max Doc Date: {result.get('max_doc_date')}")

    if result.get("invoices"):
        first_inv = result["invoices"][0]
        print(f"\nFirst invoice: {first_inv.get('invoice_no')}")
        print(f"First invoice amount: {first_inv.get('invoice_total_amount')}")
        print(f"First invoice history records: {first_inv.get('number_of_history_records')}")
