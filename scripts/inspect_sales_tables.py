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

# High-priority Sales candidate tables to inspect
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


def inspect_sales_tables(schema_name: str = "public"):
    """
    Retrieves metadata for the 9 selected high-priority Sales tables:
    Column name, data type, nullability, default value, primary keys, and foreign keys.
    """
    try:
        conn = get_db_connection()
        conn.set_session(readonly=True)
    except Exception as e:
        print(f"\n[X] Could not connect to PostgreSQL database: {e}")
        print("\nPlease verify your PostgreSQL service is running and environment variables are set.\n")
        sys.exit(1)

    print("\n" + "=" * 80)
    print(f" HIGH-PRIORITY SALES TABLES METADATA INSPECTION (Schema: '{schema_name}')")
    print("=" * 80 + "\n")

    with conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            for table in TARGET_TABLES:
                # Check if table exists
                cursor.execute(
                    """
                    SELECT EXISTS (
                        SELECT 1 FROM information_schema.tables 
                        WHERE table_schema = %s AND table_name = %s
                    );
                    """,
                    (schema_name, table)
                )
                exists = cursor.fetchone()["exists"]

                if not exists:
                    print(f"Table: {table} [NOT FOUND IN SCHEMA]")
                    print("-" * 80)
                    continue

                # 1. Fetch column metadata
                cursor.execute(
                    """
                    SELECT column_name, data_type, is_nullable, column_default
                    FROM information_schema.columns
                    WHERE table_schema = %s AND table_name = %s
                    ORDER BY ordinal_position;
                    """,
                    (schema_name, table)
                )
                columns = cursor.fetchall()

                # 2. Fetch Primary Keys
                cursor.execute(
                    """
                    SELECT kcu.column_name
                    FROM information_schema.table_constraints tc
                    JOIN information_schema.key_column_usage kcu
                      ON tc.constraint_name = kcu.constraint_name
                      AND tc.table_schema = kcu.table_schema
                    WHERE tc.constraint_type = 'PRIMARY KEY'
                      AND tc.table_schema = %s
                      AND tc.table_name = %s
                    ORDER BY kcu.ordinal_position;
                    """,
                    (schema_name, table)
                )
                pk_columns = {row["column_name"] for row in cursor.fetchall()}

                # 3. Fetch Foreign Keys and referenced tables/columns
                cursor.execute(
                    """
                    SELECT
                        kcu.column_name,
                        ccu.table_name AS referenced_table,
                        ccu.column_name AS referenced_column,
                        tc.constraint_name
                    FROM information_schema.table_constraints AS tc
                    JOIN information_schema.key_column_usage AS kcu
                      ON tc.constraint_name = kcu.constraint_name
                      AND tc.table_schema = kcu.table_schema
                    JOIN information_schema.constraint_column_usage AS ccu
                      ON ccu.constraint_name = tc.constraint_name
                      AND ccu.table_schema = tc.table_schema
                    WHERE tc.constraint_type = 'FOREIGN KEY'
                      AND tc.table_schema = %s
                      AND tc.table_name = %s;
                    """,
                    (schema_name, table)
                )
                fk_rows = cursor.fetchall()
                fk_map = {
                    row["column_name"]: f"FK -> {row['referenced_table']}({row['referenced_column']})"
                    for row in fk_rows
                }

                print(f"Table: {table} ({len(columns)} columns)")
                print("-" * 80)

                header = f"  {'Column':<30} | {'Data Type':<20} | {'Nullable':<8} | {'Default':<15} | {'Constraints/Keys'}"
                print(header)
                print("  " + "-" * (len(header) - 2))

                for col in columns:
                    name = col["column_name"]
                    dtype = col["data_type"]
                    nullable = col["is_nullable"]
                    default_val = str(col["column_default"]) if col["column_default"] is not None else "-"
                    if len(default_val) > 15:
                        default_val = default_val[:12] + "..."

                    key_info = []
                    if name in pk_columns:
                        key_info.append("PRIMARY KEY")
                    if name in fk_map:
                        key_info.append(fk_map[name])

                    key_str = ", ".join(key_info) if key_info else "-"

                    print(f"  {name:<30} | {dtype:<20} | {nullable:<8} | {default_val:<15} | {key_str}")

                print("\n" + "=" * 80 + "\n")

    conn.close()
    print("High-priority Sales tables metadata inspection completed.\n")


if __name__ == "__main__":
    inspect_sales_tables()
