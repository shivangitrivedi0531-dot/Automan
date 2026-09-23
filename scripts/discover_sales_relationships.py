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

# Target tables for relationship discovery
TARGET_TABLES = [
    "trn_veh_sales",
    "trn_veh_salesfin",
    "trn_veh_salesrto",
    "trn_oth_sales",
    "trn_oth_salesret",
    "mst_product",
    "mst_customer_profile",
    "mst_financer",
    "mst_salesman"
]

# Specified key concepts to explore across the target tables
FOCUS_COLUMNS = [
    "product_code",
    "sub_prd_code",
    "salesman_code",
    "salesman_codev",
    "financer_code",
    "customer_code",
    "cust_code",
    "customer_accode",
    "sale_type_code",
    "sale_type",
    "ac_code",
    "invoice_no",
    "customer_profile_id",
    "product_id",
    "salesman_id",
    "financer_id"
]


def get_db_connection():
    """
    Establishes a connection to PostgreSQL using environment variables.
    Reuses standard connection configuration.
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


def build_candidate_pairs(cursor, schema_name: str):
    """
    Discovers actual existing columns in the target tables matching focus concept terms
    and constructs plausible (source_table, source_col, target_table, target_col) pairs.
    """
    cursor.execute(
        """
        SELECT table_name, column_name
        FROM information_schema.columns
        WHERE table_schema = %s AND table_name = ANY(%s);
        """,
        (schema_name, TARGET_TABLES)
    )
    rows = cursor.fetchall()

    table_cols = {}
    for r in rows:
        t = r["table_name"]
        c = r["column_name"]
        if t not in table_cols:
            table_cols[t] = set()
        table_cols[t].add(c)

    pairs = []

    # Map relationships dynamically based on discovered schema columns
    for src_t in TARGET_TABLES:
        for tgt_t in TARGET_TABLES:
            if src_t == tgt_t:
                continue

            src_columns = table_cols.get(src_t, set())
            tgt_columns = table_cols.get(tgt_t, set())

            # 1. Direct column name match across tables
            for col in src_columns:
                if col in FOCUS_COLUMNS and col in tgt_columns:
                    pairs.append((src_t, col, tgt_t, col))

            # 2. Key mapping variations (e.g. salesman_codev -> salesman_code)
            if "salesman_codev" in src_columns and "salesman_code" in tgt_columns:
                pairs.append((src_t, "salesman_codev", tgt_t, "salesman_code"))
            if "cust_code" in src_columns and "customer_code" in tgt_columns:
                pairs.append((src_t, "cust_code", tgt_t, "customer_code"))
            if "customer_accode" in src_columns and "customer_code" in tgt_columns:
                pairs.append((src_t, "customer_accode", tgt_t, "customer_code"))

    # Remove duplicates while preserving order
    unique_pairs = []
    seen = set()
    for p in pairs:
        if p not in seen:
            seen.add(p)
            unique_pairs.append(p)

    return unique_pairs, table_cols


def discover_logical_relationships(schema_name: str = "public"):
    """
    Empirically tests logical foreign key relationships by calculating
    distinct value overlaps between source and target tables.
    """
    try:
        conn = get_db_connection()
        conn.set_session(readonly=True)
    except Exception as e:
        print(f"\n[X] Could not connect to PostgreSQL database: {e}\n")
        sys.exit(1)

    print("\n" + "=" * 80)
    print(f" LOGICAL RELATIONSHIP DISCOVERY REPORT (Schema: '{schema_name}')")
    print("=" * 80 + "\n")

    tested_count = 0
    confirmed_count = 0

    with conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            pairs, table_cols = build_candidate_pairs(cursor, schema_name)

            for source_table, source_col, target_table, target_col in pairs:
                tested_count += 1

                # 1. Count distinct non-null source values
                query_source_count = f"""
                    SELECT COUNT(DISTINCT "{source_col}") AS src_cnt
                    FROM "{source_table}"
                    WHERE "{source_col}" IS NOT NULL AND CAST("{source_col}" AS TEXT) != '';
                """
                cursor.execute(query_source_count)
                source_distinct_count = cursor.fetchone()["src_cnt"]

                if source_distinct_count == 0:
                    print(f"Relationship candidate:")
                    print(f"  {source_table}.{source_col} -> {target_table}.{target_col}")
                    print(f"  Source distinct values: 0")
                    print(f"  Matched values: 0")
                    print(f"  Match percentage: 0.0%")
                    print(f"  Sample matches: None (No distinct source values)\n")
                    print("-" * 80)
                    continue

                # 2. Calculate distinct value overlap between source and target
                query_overlap = f"""
                    SELECT COUNT(DISTINCT s."{source_col}") AS matched_cnt
                    FROM (
                        SELECT DISTINCT "{source_col}"
                        FROM "{source_table}"
                        WHERE "{source_col}" IS NOT NULL AND CAST("{source_col}" AS TEXT) != ''
                    ) s
                    JOIN (
                        SELECT DISTINCT "{target_col}"
                        FROM "{target_table}"
                        WHERE "{target_col}" IS NOT NULL AND CAST("{target_col}" AS TEXT) != ''
                    ) t ON CAST(s."{source_col}" AS TEXT) = CAST(t."{target_col}" AS TEXT);
                """
                cursor.execute(query_overlap)
                matched_count = cursor.fetchone()["matched_cnt"]

                match_pct = (matched_count / source_distinct_count) * 100.0

                # 3. Fetch up to 3 sample matching values
                query_samples = f"""
                    SELECT DISTINCT CAST(s."{source_col}" AS TEXT) AS sample_val
                    FROM "{source_table}" s
                    JOIN "{target_table}" t 
                      ON CAST(s."{source_col}" AS TEXT) = CAST(t."{target_col}" AS TEXT)
                    WHERE s."{source_col}" IS NOT NULL AND CAST(s."{source_col}" AS TEXT) != ''
                    LIMIT 3;
                """
                cursor.execute(query_samples)
                sample_rows = cursor.fetchall()
                sample_values = [str(r["sample_val"]) for r in sample_rows]

                sample_str = ", ".join(sample_values) if sample_values else "None"

                if match_pct > 0:
                    confirmed_count += 1

                print(f"Relationship candidate:")
                print(f"  {source_table}.{source_col} -> {target_table}.{target_col}")
                print(f"  Source distinct values: {source_distinct_count}")
                print(f"  Matched values: {matched_count}")
                print(f"  Match percentage: {match_pct:.2f}%")
                print(f"  Sample matches: {sample_str}\n")
                print("-" * 80)

    conn.close()
    print(f"\nLogical Relationship Discovery Completed.")
    print(f"Tested Candidates: {tested_count} | Active Relationships Confirmed (>0% match): {confirmed_count}\n")


if __name__ == "__main__":
    discover_logical_relationships()
