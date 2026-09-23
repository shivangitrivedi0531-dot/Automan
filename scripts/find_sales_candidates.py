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

# Business keywords associated with the Sales domain
SALES_KEYWORDS = [
    "sale",
    "sales",
    "invoice",
    "revenue",
    "payment",
    "profit",
    "product",
    "item",
    "customer",
    "finance",
    "debit",
    "credit"
]


def get_db_connection():
    """
    Establishes a connection to the PostgreSQL database using environment variables.
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


def find_sales_candidates(schema_name: str = "public"):
    """
    Queries PostgreSQL information_schema metadata to discover candidate tables
    and columns relevant to the Sales domain based on target business keywords.
    """
    try:
        conn = get_db_connection()
        conn.set_session(readonly=True)
    except Exception as e:
        print(f"\n[X] Could not connect to PostgreSQL database: {e}")
        print("\nPlease verify your PostgreSQL service is running and environment variables are set.\n")
        sys.exit(1)

    with conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            # 1. Retrieve base table names
            cursor.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = %s AND table_type = 'BASE TABLE'
                ORDER BY table_name;
                """,
                (schema_name,)
            )
            tables = [row["table_name"] for row in cursor.fetchall()]

            # 2. Retrieve column names for all base tables in schema
            cursor.execute(
                """
                SELECT table_name, column_name
                FROM information_schema.columns
                WHERE table_schema = %s
                ORDER BY table_name, ordinal_position;
                """,
                (schema_name,)
            )
            all_columns = cursor.fetchall()

    conn.close()

    # Map columns by table
    columns_by_table = {}
    for col in all_columns:
        t_name = col["table_name"]
        c_name = col["column_name"]
        if t_name not in columns_by_table:
            columns_by_table[t_name] = []
        columns_by_table[t_name].append(c_name)

    candidate_results = []

    for table in tables:
        t_lower = table.lower()
        # Find matching table name keywords
        table_matched_terms = [kw for kw in SALES_KEYWORDS if kw in t_lower]

        # Find matching column keywords
        matched_columns = {}
        cols = columns_by_table.get(table, [])
        for col in cols:
            c_lower = col.lower()
            col_matched_terms = [kw for kw in SALES_KEYWORDS if kw in c_lower]
            if col_matched_terms:
                matched_columns[col] = col_matched_terms

        # Record table if table name or any column matches keyword criteria
        if table_matched_terms or matched_columns:
            candidate_results.append({
                "table_name": table,
                "table_matched_terms": table_matched_terms,
                "matched_columns": matched_columns
            })

    # Print Candidate Discovery Report
    print("\n" + "=" * 70)
    print(" SALES MODULE CANDIDATE DISCOVERY REPORT")
    print(f" Target Schema: '{schema_name}' | Keywords: {', '.join(SALES_KEYWORDS)}")
    print("=" * 70 + "\n")

    for candidate in candidate_results:
        t_name = candidate["table_name"]
        t_terms = candidate["table_matched_terms"]
        c_matches = candidate["matched_columns"]

        print(f"Table: {t_name}")
        if t_terms:
            print(f"  |- Table Name Match: {', '.join(t_terms)}")
        else:
            print(f"  |- Table Name Match: None")

        if c_matches:
            print(f"  |- Column Match(es): ({len(c_matches)} column(s))")
            for col_name, terms in c_matches.items():
                print(f"       * {col_name:<30} -> matched: {', '.join(terms)}")
        else:
            print(f"  |- Column Match(es): None")

        print("-" * 70)

    print(f"\nTotal Candidate Tables Found: {len(candidate_results)} out of {len(tables)} total base tables")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    find_sales_candidates()
