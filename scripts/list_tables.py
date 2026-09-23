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
    Reuses the standard connection configuration (DATABASE_URL or DB_* / POSTGRES_* / PG* parameters).
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


def list_tables(schema_name: str = "public"):
    """
    Retrieves and prints a clean numbered list of all base tables in the specified schema,
    along with the total table count.
    """
    try:
        conn = get_db_connection()
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

            print("\n" + "=" * 50)
            print(f" POSTGRESQL TABLES LIST (Schema: '{schema_name}')")
            print("=" * 50)

            if not tables:
                print(f"No base tables found in schema '{schema_name}'.\n")
            else:
                for idx, table_name in enumerate(tables, start=1):
                    print(f"  {idx}. {table_name}")
                print("-" * 50)
                print(f"Total tables: {len(tables)}")

    conn.close()
    print("=" * 50 + "\n")


if __name__ == "__main__":
    list_tables()
