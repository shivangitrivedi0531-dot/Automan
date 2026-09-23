import json
import os
import sys

# Load environment variables from .env file if available
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
    sys.exit(1)


def generate_inventory():
    """
    Connects to PostgreSQL, fetches all base tables in the public schema,
    and outputs schema/table_inventory.json.
    """
    database_url = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL")
    if database_url:
        conn = psycopg2.connect(database_url)
    else:
        host = os.getenv("DB_HOST") or os.getenv("POSTGRES_HOST") or os.getenv("PGHOST", "localhost")
        port = os.getenv("DB_PORT") or os.getenv("POSTGRES_PORT") or os.getenv("PGPORT", "5432")
        dbname = os.getenv("DB_NAME") or os.getenv("POSTGRES_DB") or os.getenv("PGDATABASE", "postgres")
        user = os.getenv("DB_USER") or os.getenv("POSTGRES_USER") or os.getenv("PGUSER", "postgres")
        password = os.getenv("DB_PASSWORD") or os.getenv("POSTGRES_PASSWORD") or os.getenv("PGPASSWORD", "")

        conn = psycopg2.connect(
            host=host,
            port=port,
            dbname=dbname,
            user=user,
            password=password
        )

    conn.set_session(readonly=True)

    with conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
                ORDER BY table_name;
                """
            )
            rows = cursor.fetchall()
            tables = [{"table_name": row["table_name"]} for row in rows]

    conn.close()

    inventory_data = {
        "schema": "public",
        "table_count": len(tables),
        "tables": tables
    }

    output_dir = "schema"
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, "table_inventory.json")

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(inventory_data, f, indent=2)

    print(f"Successfully generated table inventory with {len(tables)} tables at '{output_path}'.")


if __name__ == "__main__":
    generate_inventory()
