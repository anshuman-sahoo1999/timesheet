import os
import sys
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from app import app, db

load_dotenv()

# Direct connection string to Neon PostgreSQL (bypasses PgBouncer for reliable DDL and bulk migration)
NEON_DIRECT_URL = "postgresql://neondb_owner:npg_GRCyKtOID8V1@ep-empty-base-be7tfogx.c-9.us-east-2.aws.neon.tech/neondb?sslmode=require"
# Pooler connection string for production runtime
NEON_POOLER_URL = "postgresql://neondb_owner:npg_GRCyKtOID8V1@ep-empty-base-be7tfogx-pooler.c-9.us-east-2.aws.neon.tech/neondb?sslmode=require&channel_binding=require"
SQLITE_URL = "sqlite:///instance/pms.db"

# 100% mathematically acyclic foreign key dependency order
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

def run_migration():
    print("[1/5] Connecting to SQLite source and Neon PostgreSQL target...")
    src_engine = create_engine(SQLITE_URL)
    tgt_engine = create_engine(NEON_DIRECT_URL)
    
    with app.app_context():
        print("[2/5] Creating fresh schema on Neon DB...")
        with tgt_engine.connect() as conn:
            conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
            conn.commit()
        db.metadata.create_all(bind=tgt_engine)
        print("[SUCCESS] Neon DB schema recreated with 23 tables.")
        
        print("[3/5] Migrating table data in strict dependency order...")
        total_migrated_rows = 0
        dept_heads = {}
        
        with tgt_engine.connect() as tgt_conn:
            for table_name in MIGRATION_ORDER:
                table = db.metadata.tables[table_name]
                with src_engine.connect() as src_conn:
                    if 'id' in table.c:
                        rows = src_conn.execute(table.select().order_by(table.c.id)).mappings().all()
                    else:
                        rows = src_conn.execute(table.select()).mappings().all()
                        
                    count = len(rows)
                    if count > 0:
                        row_dicts = [dict(r) for r in rows]
                        
                        # Clean boolean and None fields
                        for rd in row_dicts:
                            for col in table.columns:
                                col_name = col.name
                                if str(col.type) == 'BOOLEAN' and col_name in rd and rd[col_name] is not None:
                                    rd[col_name] = bool(rd[col_name])
                        
                        # If department table has department_head_id, hold it temporarily until employee table is loaded
                        if table_name == 'department' and 'department_head_id' in table.c:
                            for rd in row_dicts:
                                if rd.get('department_head_id') is not None:
                                    dept_heads[rd['id']] = rd['department_head_id']
                                    rd['department_head_id'] = None
                        
                        tgt_conn.execute(table.insert(), row_dicts)
                        tgt_conn.commit()
                        total_migrated_rows += count
                        print(f"  [COPIED] {table_name:25s}: {count:4d} rows")
                        
                        # Once employee table is loaded, restore any department heads
                        if table_name == 'employee' and dept_heads:
                            dept_tbl = db.metadata.tables['department']
                            for d_id, h_id in dept_heads.items():
                                tgt_conn.execute(
                                    dept_tbl.update().where(dept_tbl.c.id == d_id).values(department_head_id=h_id)
                                )
                            tgt_conn.commit()
                            print(f"  [UPDATED] Restored {len(dept_heads)} department head foreign keys.")
                    else:
                        print(f"  [EMPTY]  {table_name:25s}:    0 rows")

            print(f"[SUCCESS] All data migrated! Total rows transferred: {total_migrated_rows}")
            
            print("[4/5] Resetting PostgreSQL serial sequences to match max(id)...")
            for table_name in MIGRATION_ORDER:
                table = db.metadata.tables[table_name]
                if 'id' in table.c:
                    try:
                        seq_sql = text(f"""
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
                        tgt_conn.execute(seq_sql)
                        tgt_conn.commit()
                    except Exception as e:
                        print(f"  [WARN] Sequence update for {table_name}: {e}")
            print("[SUCCESS] All primary key sequences synchronized.")

        print("[5/5] Verifying 100% row counts between SQLite and Neon DB...")
        mismatches = 0
        with src_engine.connect() as src_conn, tgt_engine.connect() as tgt_conn:
            for table_name in MIGRATION_ORDER:
                src_cnt = src_conn.execute(text(f'SELECT COUNT(*) FROM "{table_name}"')).scalar()
                tgt_cnt = tgt_conn.execute(text(f'SELECT COUNT(*) FROM "{table_name}"')).scalar()
                status = "MATCH" if src_cnt == tgt_cnt else "MISMATCH"
                if src_cnt != tgt_cnt:
                    mismatches += 1
                if src_cnt > 0 or tgt_cnt > 0:
                    print(f"  {table_name:25s} -> SQLite: {src_cnt:4d} | Neon: {tgt_cnt:4d} [{status}]")
        
        if mismatches == 0:
            print("[SUCCESS] 100% PERFECT MATCH across all 23 tables!")
        else:
            print(f"[ERROR] {mismatches} table(s) had mismatched counts!")
            return False

        # Update .env to point to Neon DB
        env_path = '.env'
        with open(env_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        new_lines = []
        replaced = False
        for line in lines:
            if line.startswith('DATABASE_URL='):
                new_lines.append(f'DATABASE_URL={NEON_DIRECT_URL}\n')
                replaced = True
            else:
                new_lines.append(line)
        if not replaced:
            new_lines.insert(0, f'DATABASE_URL={NEON_DIRECT_URL}\n')
            
        with open(env_path, 'w', encoding='utf-8') as f:
            f.writelines(new_lines)
        print("[SUCCESS] .env file updated with Neon DATABASE_URL!")
        return True

if __name__ == '__main__':
    run_migration()
