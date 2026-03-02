import psycopg2
import csv
import os
import sys
from dotenv import load_dotenv

def get_db_credentials():
    # Attempt to load from the adjacent database-helpers project if .env is not local
    helper_env_staging = r"C:\Users\KennethSearles\AppData\Local\Temp\database-helpers\PythonScripts\BulkUserCreate\.env.staging"
    helper_env_prod = r"C:\Users\KennethSearles\AppData\Local\Temp\database-helpers\PythonScripts\BulkUserCreate\.env.prod"
    helper_env_dev = r"C:\Users\KennethSearles\AppData\Local\Temp\database-helpers\PythonScripts\BulkUserCreate\.env"
    
    # Try looking for a local .env file first
    load_dotenv()
    
    if not os.environ.get('PG_HOST'):
        if os.path.exists(helper_env_prod):
            load_dotenv(helper_env_prod)
        elif os.path.exists(helper_env_staging):
            load_dotenv(helper_env_staging)
        elif os.path.exists(helper_env_dev):
            load_dotenv(helper_env_dev)

    host = os.environ.get('PG_HOST')
    port = os.environ.get('PG_PORT', 5432)
    dbname = os.environ.get('PG_DBNAME')
    user = os.environ.get('PG_USER')
    password = os.environ.get('PG_PASSWORD')

    if not all([host, dbname, user, password]):
        print("Error: Incomplete PostgreSQL credentials in environment variables.")
        print(f"Host: {host}, DB: {dbname}, User: {user}")
        sys.exit(1)

    return {
        'host': host,
        'port': int(port),
        'dbname': dbname,
        'user': user,
        'password': password
    }

def fetch_and_write_users():
    db_config = get_db_credentials()
    
    print(f"Connecting to {db_config['host']}/{db_config['dbname']}...")
    try:
        conn = psycopg2.connect(**db_config)
    except Exception as e:
        print(f"Failed to connect to database: {e}")
        sys.exit(1)

    cur = conn.cursor()
    
    query = """
        SELECT 
            id, f3_name, first_name, last_name, email, phone, home_region_id, status 
        FROM users
    """
    
    print("Executing query...")
    try:
        cur.execute(query)
        rows = cur.fetchall()
        
        # Get column names from the cursor description
        colnames = [desc[0] for desc in cur.description]
        
    except psycopg2.Error as e:
        print(f"Database query failed: {e}")
        sys.exit(1)
    finally:
        cur.close()
        conn.close()

    output_dir = 'import'
    os.makedirs(output_dir, exist_ok=True)
    output_file = os.path.join(output_dir, 'user_master.csv')

    print(f"Retrieved {len(rows)} users. Writing to {output_file}...")
    
    try:
        with open(output_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(colnames)
            writer.writerows(rows)
            
        print("Successfully exported user master records!")
    except Exception as e:
        print(f"Failed to write to file: {e}")

if __name__ == "__main__":
    fetch_and_write_users()
