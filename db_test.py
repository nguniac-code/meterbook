import psycopg2

print("Connecting to local PostgreSQL on port 5433...", flush=True)

try:
    conn = psycopg2.connect(
        host="localhost",
        port=5433,
        dbname="meter_readings_db",
        user="postgres",
        password="",
        connect_timeout=5
    )
    print("SUCCESS! Database connection works.", flush=True)
    conn.close()
except Exception as e:
    print("FAILED:", e, flush=True)