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
    Establishes a connection to the PostgreSQL database using environment variables.
    Checks DATABASE_URL / POSTGRES_URL or individual DB connection parameters.
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


def inspect_database(schema_name: str = "public"):
    """
    Performs a read-only schema inspection of the target PostgreSQL database.
    Displays table names, column names, data types, nullability, primary keys, and foreign keys.
    """
    try:
        conn = get_db_connection()
        # Enforce read-only session to guarantee safety
        conn.set_session(readonly=True)
    except Exception as e:
        print(f"\n[X] Could not connect to PostgreSQL database: {e}")
        print("\nPlease verify your PostgreSQL service is running and environment variables are set.")
        print("Supported environment variables:")
        print("  - DB_HOST (default: localhost)")
        print("  - DB_PORT (default: 5432)")
        print("  - DB_NAME (default: postgres)")
        print("  - DB_USER (default: postgres)")
        print("  - DB_PASSWORD")
        print("  - DATABASE_URL (optional alternative connection string)\n")
        sys.exit(1)

    with conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            # 1. Fetch all base table names in the specified schema
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

            if not tables:
                print(f"\n[!] No base tables found in schema '{schema_name}'.")
                return

            print("\n" + "=" * 70)
            print(f" POSTGRESQL DATABASE SCHEMA INSPECTION (Schema: '{schema_name}')")
            print("=" * 70)
            print(f"Total Base Tables Found: {len(tables)}\n")

            for table in tables:
                print(f"Table: {table}")
                print("-" * (len(table) + 7))

                # 2 & 3 & 4. Fetch column details (name, data type, nullability)
                cursor.execute(
                    """
                    SELECT column_name, data_type, is_nullable
                    FROM information_schema.columns
                    WHERE table_schema = %s AND table_name = %s
                    ORDER BY ordinal_position;
                    """,
                    (schema_name, table)
                )
                columns = cursor.fetchall()

                # 5. Fetch Primary Keys
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

                # 6. Fetch Foreign Keys
                cursor.execute(
                    """
                    SELECT
                        kcu.column_name,
                        ccu.table_name AS foreign_table_name,
                        ccu.column_name AS foreign_column_name
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
                    row["column_name"]: f"{row['foreign_table_name']}({row['foreign_column_name']})"
                    for row in fk_rows
                }

                # Display table schema details
                header = f"  {'Column':<25} | {'Data Type':<20} | {'Nullable':<8} | {'Key Info'}"
                print(header)
                print("  " + "-" * (len(header) - 2))

                for col in columns:
                    name = col["column_name"]
                    dtype = col["data_type"]
                    nullable = col["is_nullable"]

                    key_info = []
                    if name in pk_columns:
                        key_info.append("PRIMARY KEY")
                    if name in fk_map:
                        key_info.append(f"FOREIGN KEY -> {fk_map[name]}")

                    key_str = ", ".join(key_info) if key_info else "-"
                    print(f"  {name:<25} | {dtype:<20} | {nullable:<8} | {key_str}")

                print()

    conn.close()
    print("=" * 70)
    print(" Database inspection completed.")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    inspect_database()
