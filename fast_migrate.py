import sqlite3
import psycopg2
from psycopg2.extras import execute_values
from app import app, db

NEON_URL = "postgresql://neondb_owner:npg_GRCyKtOID8V1@ep-empty-base-be7tfogx-pooler.c-9.us-east-2.aws.neon.tech/neondb?sslmode=require&channel_binding=require"
SQLITE_DB = "instance/pms.db"

# Strict dependency order
MIGRATION_ORDER = [
    'holiday_master',
    'expenditure_category',
    'otp',
    'department',
    'grade_salary_master',
    'employee',
    'client',
    'hr_delegation',
    'audit_log',
    'notification',
    'timesheet_draft',
    'job_indent',
    'job_card',
    'budget_item',
    'project_actual_expense',
    'project_change_request',
    'task',
    'task_assignees',
    'weekly_timesheet',
    'timesheet',
    'timesheet_approval',
    'timesheet_comment',
    'timesheet_attachment'
]

def migrate_all():
    print("[INFO] Connecting to SQLite source...")
    sq_conn = sqlite3.connect(SQLITE_DB)
    sq_conn.row_factory = sqlite3.Row
    sq_cur = sq_conn.cursor()

    print("[INFO] Connecting to Neon DB...")
    pg_conn = psycopg2.connect(NEON_URL)
    pg_cur = pg_conn.cursor()

    with app.app_context():
        # First, truncate all tables in reverse dependency order with CASCADE to ensure clean slate
        print("[INFO] Cleaning tables in Neon DB...")
        for t in reversed(MIGRATION_ORDER):
            pg_cur.execute(f'TRUNCATE TABLE "{t}" CASCADE;')
        pg_conn.commit()
        print("[SUCCESS] Neon DB tables truncated clean.")

        dept_heads = {}
        emp_managers = {}
        total_migrated = 0

        for table_name in MIGRATION_ORDER:
            table = db.metadata.tables[table_name]
            col_names = [c.name for c in table.columns]
            cols_sql = ", ".join([f'"{c}"' for c in col_names])

            # Fetch rows from SQLite
            sq_cur.execute(f'SELECT {cols_sql} FROM "{table_name}" ORDER BY 1;')
            rows = sq_cur.fetchall()
            count = len(rows)

            if count > 0:
                values_list = []
                for r in rows:
                    val_dict = dict(r)
                    
                    # Convert booleans
                    for c in table.columns:
                        if str(c.type) == 'BOOLEAN' and val_dict[c.name] is not None:
                            val_dict[c.name] = bool(val_dict[c.name])
                    
                    # Temporarily hold department_head_id
                    if table_name == 'department' and val_dict.get('department_head_id') is not None:
                        dept_heads[val_dict['id']] = val_dict['department_head_id']
                        val_dict['department_head_id'] = None

                    # Temporarily hold manager_id to avoid self-referencing FK issue on employee
                    if table_name == 'employee' and val_dict.get('manager_id') is not None:
                        emp_managers[val_dict['id']] = val_dict['manager_id']
                        val_dict['manager_id'] = None
                        
                    values_list.append(tuple(val_dict[c.name] for c in table.columns))

                # Insert into Neon PostgreSQL
                insert_sql = f'INSERT INTO "{table_name}" ({cols_sql}) VALUES %s'
                execute_values(pg_cur, insert_sql, values_list)
                pg_conn.commit()
                total_migrated += count
                print(f"  [MIGRATED] {table_name:25s}: {count:4d} rows")

                # Restore manager_id once all employees are in table
                if table_name == 'employee' and emp_managers:
                    for e_id, m_id in emp_managers.items():
                        pg_cur.execute(
                            'UPDATE "employee" SET "manager_id" = %s WHERE "id" = %s;',
                            (m_id, e_id)
                        )
                    pg_conn.commit()
                    print(f"  [RESTORED] Updated {len(emp_managers)} employee manager_id foreign keys.")

                # Restore department heads once employee table is loaded
                if table_name == 'employee' and dept_heads:
                    for d_id, h_id in dept_heads.items():
                        pg_cur.execute(
                            'UPDATE "department" SET "department_head_id" = %s WHERE "id" = %s;',
                            (h_id, d_id)
                        )
                    pg_conn.commit()
                    print(f"  [RESTORED] Updated {len(dept_heads)} department_head foreign keys.")
            else:
                print(f"  [EMPTY]    {table_name:25s}:    0 rows")

        print(f"\n[SUCCESS] All data inserted! Total rows migrated: {total_migrated}")

        # Reset sequences
        print("\n[INFO] Synchronizing PostgreSQL serial sequences...")
        for table_name in MIGRATION_ORDER:
            table = db.metadata.tables[table_name]
            if 'id' in table.c:
                pg_cur.execute(f"""
                    DO $$
                    DECLARE
                        seq_name text;
                        max_id bigint;
                    BEGIN
                        seq_name := pg_get_serial_sequence('{table_name}', 'id');
                        IF seq_name IS NOT NULL THEN
                            EXECUTE 'SELECT COALESCE(MAX(id), 0) FROM "{table_name}"' INTO max_id;
                            IF max_id > 0 THEN
                                EXECUTE 'SELECT setval(''' || seq_name || ''', ' || max_id || ')';
                            END IF;
                        END IF;
                    END $$;
                """)
        pg_conn.commit()
        print("[SUCCESS] All primary key auto-increment sequences updated.")

        # Verification
        print("\n[INFO] Verifying row counts between SQLite and Neon DB...")
        all_matched = True
        for table_name in MIGRATION_ORDER:
            sq_cur.execute(f'SELECT COUNT(*) FROM "{table_name}";')
            sq_cnt = sq_cur.fetchone()[0]
            pg_cur.execute(f'SELECT COUNT(*) FROM "{table_name}";')
            pg_cnt = pg_cur.fetchone()[0]
            status = "MATCH" if sq_cnt == pg_cnt else "MISMATCH!"
            if sq_cnt != pg_cnt:
                all_matched = False
            if sq_cnt > 0 or pg_cnt > 0:
                print(f"  {table_name:25s} -> SQLite: {sq_cnt:4d} | Neon: {pg_cnt:4d} [{status}]")

        if all_matched:
            print("\n[SUCCESS] 100% PERFECT MATCH across all 23 tables!")
        else:
            print("\n[ERROR] Row count mismatch detected!")

    pg_conn.close()
    sq_conn.close()

    if all_matched:
        # Update .env
        env_path = '.env'
        with open(env_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        new_lines = []
        replaced = False
        for line in lines:
            if line.startswith('DATABASE_URL='):
                new_lines.append(f'DATABASE_URL={NEON_URL}\n')
                replaced = True
            else:
                new_lines.append(line)
        if not replaced:
            new_lines.insert(0, f'DATABASE_URL={NEON_URL}\n')
            
        with open(env_path, 'w', encoding='utf-8') as f:
            f.writelines(new_lines)
        print("[SUCCESS] .env file updated to point to Neon DB!")
        return True
    return False

if __name__ == '__main__':
    migrate_all()
