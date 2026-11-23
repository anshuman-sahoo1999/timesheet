import sqlite3

DB_PATH = 'instance/pms.db'

conn = sqlite3.connect(DB_PATH)
c = conn.cursor()

# Check if column exists
c.execute("PRAGMA table_info(job_indent)")
columns = [row[1] for row in c.fetchall()]
if 'work_order_pdf' not in columns:
    c.execute("ALTER TABLE job_indent ADD COLUMN work_order_pdf VARCHAR(256)")
    print('Column work_order_pdf added.')
else:
    print('Column work_order_pdf already exists.')

conn.commit()
conn.close() 