import sqlite3

db_path = 'instance/pms.db'
con = sqlite3.connect(db_path)
cur = con.cursor()

print("1. Disabling foreign keys temporarily for clean wipe...")
cur.execute("PRAGMA foreign_keys = OFF;")

print("2. Clearing all timesheet records...")
cur.execute("DELETE FROM timesheet;")
cur.execute("DELETE FROM weekly_timesheet;")
cur.execute("DELETE FROM timesheet_draft;")
cur.execute("DELETE FROM timesheet_comment;")
cur.execute("DELETE FROM timesheet_attachment;")
cur.execute("DELETE FROM timesheet_approval;")

print("3. Clearing all project, task, card, and client records...")
cur.execute("DELETE FROM task_assignees;")
cur.execute("DELETE FROM task;")
cur.execute("DELETE FROM budget_item;")
cur.execute("DELETE FROM job_card;")
cur.execute("DELETE FROM job_indent;")
cur.execute("DELETE FROM client;")

print("4. Clearing logs, notifications, and OTPs...")
cur.execute("DELETE FROM audit_log;")
cur.execute("DELETE FROM notification;")
cur.execute("DELETE FROM otp;")

print("5. Clearing master records (Grade & Salary, Holiday)...")
cur.execute("DELETE FROM grade_salary_master;")
cur.execute("DELETE FROM holiday_master;")

print("6. Clearing all demo employees except Admin and HR...")
# Unlink departments and managers for the retained accounts
cur.execute("UPDATE employee SET department_id = NULL, manager_id = NULL, monthly_salary = 0 WHERE email IN ('hr@ecometrix.co.in', 'admin@ecometrix.co.in');")
# Delete all other employees
cur.execute("DELETE FROM employee WHERE email NOT IN ('hr@ecometrix.co.in', 'admin@ecometrix.co.in');")

print("7. Clearing all department and sub-department records...")
cur.execute("DELETE FROM department;")

print("8. Resetting sqlite sequence counters for wiped tables...")
wiped_tables = [
    'timesheet', 'weekly_timesheet', 'timesheet_draft', 'timesheet_comment', 
    'timesheet_attachment', 'timesheet_approval', 'task_assignees', 'task', 
    'budget_item', 'job_card', 'job_indent', 'client', 'audit_log', 
    'notification', 'otp', 'grade_salary_master', 'holiday_master', 'department'
]
for tbl in wiped_tables:
    try:
        cur.execute("DELETE FROM sqlite_sequence WHERE name = ?", (tbl,))
    except Exception:
        pass

con.commit()

print("9. Re-enabling foreign keys...")
cur.execute("PRAGMA foreign_keys = ON;")

print("\n--- Verification of Record Counts ---")
tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
for t in sorted(tables):
    if t != 'sqlite_sequence':
        cnt = cur.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"Table '{t}': {cnt} records")

con.close()
print("\nAll demo and dummy data wiped successfully to zero!")
