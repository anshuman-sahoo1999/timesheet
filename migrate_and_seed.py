import os
import re
import csv
import sqlite3
from datetime import datetime, date, timedelta
from werkzeug.security import generate_password_hash

DB_PATH = 'instance/pms.db'

def run_migration():
    print("Step 1: Updating database tables schema...")
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Check job_card columns
    c.execute("PRAGMA table_info(job_card)")
    jc_cols = [row[1] for row in c.fetchall()]
    jc_new_cols = [
        ('overview', 'TEXT'),
        ('actual_start_date', 'DATE'),
        ('actual_end_date', 'DATE'),
        ('milestones_json', 'TEXT'),
        ('resources_json', 'TEXT'),
        ('expenditures_json', 'TEXT'),
        ('resource_total', 'FLOAT DEFAULT 0.0'),
        ('expenditure_total', 'FLOAT DEFAULT 0.0'),
        ('sub_total', 'FLOAT DEFAULT 0.0'),
        ('overhead_cost', 'FLOAT DEFAULT 0.0'),
        ('grand_total', 'FLOAT DEFAULT 0.0'),
        ('budget_status', 'VARCHAR(50) DEFAULT "Pending"'),
        ('submitted_at', 'DATETIME'),
        ('approved_at', 'DATETIME'),
        ('approval_remarks', 'TEXT')
    ]
    for col_name, col_type in jc_new_cols:
        if col_name not in jc_cols:
            try:
                c.execute(f"ALTER TABLE job_card ADD COLUMN {col_name} {col_type}")
                print(f"  Added job_card.{col_name}")
            except Exception as e:
                print(f"  Error adding {col_name}: {e}")

    # Check employee columns
    c.execute("PRAGMA table_info(employee)")
    emp_cols = [row[1] for row in c.fetchall()]
    if 'salary_grade' not in emp_cols:
        try:
            c.execute("ALTER TABLE employee ADD COLUMN salary_grade VARCHAR(50)")
            print("  Added employee.salary_grade")
        except Exception as e:
            print(f"  Error adding employee.salary_grade: {e}")

    # Create expenditure_category table if not exists
    c.execute("""
    CREATE TABLE IF NOT EXISTS expenditure_category (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name VARCHAR(100) UNIQUE NOT NULL,
        description VARCHAR(255),
        is_active BOOLEAN DEFAULT 1,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # Create project_change_request table if not exists
    c.execute("""
    CREATE TABLE IF NOT EXISTS project_change_request (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        job_indent_id INTEGER NOT NULL REFERENCES job_indent(id),
        job_card_id INTEGER REFERENCES job_card(id),
        requested_by_id INTEGER NOT NULL REFERENCES employee(id),
        change_type VARCHAR(50) NOT NULL,
        title VARCHAR(200) NOT NULL,
        description TEXT NOT NULL,
        revised_budget FLOAT,
        revised_end_date DATE,
        status VARCHAR(50) DEFAULT 'Pending',
        ceo_remarks TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        reviewed_at DATETIME
    )
    """)

    conn.commit()
    conn.close()
    print("Step 1 Complete: Schema migrated successfully.")

    # Now load Flask app context for ORM seeding
    from app import app, db, Department, Employee, JobIndent, JobCard, ExpenditureCategory

    with app.app_context():
        print("\nStep 2: Seeding default Expenditure Categories...")
        default_categories = [
            ("Travel & Conveyance", "Official site visits, client meetings, and transit expenses"),
            ("Lodging & Boarding", "Field accommodation, daily allowances, and hotel expenses"),
            ("Site Survey & Field Investigation", "Topographical survey, soil investigation, data collection"),
            ("Printing, Stationery & Documentation", "Project report printing, CAD plots, binding, drawing sets"),
            ("Equipment & Instruments Hire", "Total station, DGPS, drone survey, testing meters rental"),
            ("Software, Cloud & GIS Tools", "Specialized modeling tools, satellite imagery, cloud compute"),
            ("Laboratory Testing & Sample Analysis", "Water, soil, concrete, structural testing lab fees"),
            ("Contingency & Emergency Provisions", "Unforeseen site contingencies and statutory compliances"),
            ("Subcontracting & Expert Advisory", "Domain specialist consultations and third-party vetting"),
            ("Miscellaneous & Incidentals", "General site office and operational sundry expenses")
        ]
        for name, desc in default_categories:
            if not ExpenditureCategory.query.filter_by(name=name).first():
                db.session.add(ExpenditureCategory(name=name, description=desc, is_active=True))
        db.session.commit()
        print("[OK] Expenditure categories seeded successfully.")

        print("\nStep 3: Syncing staff from 'List of Staff_For Mail ID.csv'...")
        csv_file = 'List of Staff_For Mail ID.csv'
        if os.path.exists(csv_file):
            with open(csv_file, mode='r', encoding='utf-8-sig', errors='ignore') as f:
                reader = csv.DictReader(f)
                added_count = 0
                updated_count = 0
                for row in reader:
                    emp_id = row.get('Emp. ID', '').strip()
                    name = row.get('NAME', '').strip()
                    designation = row.get('Designation', '').strip()
                    place = row.get('Place', '').strip()
                    dept_name = row.get('Department', '').strip()
                    email = row.get('Email', '').strip().lower()
                    salary_str = row.get('Monthly Salary', '')
                    pwd = row.get('Password', '').strip() or 'pms123'

                    if not emp_id or not email:
                        continue

                    # Parse salary
                    salary_clean = re.sub(r'[^\d.]', '', salary_str)
                    try:
                        salary = float(salary_clean) if salary_clean else 30000.0
                    except ValueError:
                        salary = 30000.0

                    # Calculate Grade based on salary
                    if salary >= 90000:
                        grade = 'M-1'
                    elif salary >= 70000:
                        grade = 'M-2'
                    elif salary >= 50000:
                        grade = 'M-3'
                    elif salary >= 35000:
                        grade = 'M-4'
                    elif salary >= 25000:
                        grade = 'S-1'
                    else:
                        grade = 'S-2'

                    # Ensure Department
                    dept = None
                    if dept_name:
                        dept = Department.query.filter((Department.name.ilike(dept_name)) | (Department.short_code.ilike(dept_name))).first()
                        if not dept:
                            dept = Department(name=dept_name.title(), short_code=dept_name[:4].upper(), is_general_admin=False)
                            db.session.add(dept)
                            db.session.flush()

                    # Find existing employee by emp_id or email
                    emp = Employee.query.filter((Employee.emp_id == emp_id) | (Employee.email == email)).first()
                    if emp:
                        emp.name = name
                        emp.designation = designation
                        emp.place = place
                        emp.monthly_salary = salary
                        emp.salary_grade = grade
                        if dept and not emp.department_id:
                            emp.department_id = dept.id
                        updated_count += 1
                    else:
                        new_emp = Employee(
                            emp_id=emp_id,
                            name=name,
                            designation=designation,
                            place=place,
                            email=email,
                            monthly_salary=salary,
                            salary_grade=grade,
                            role='EMP',
                            is_active=True,
                            department_id=dept.id if dept else None
                        )
                        new_emp.set_password(pwd)
                        db.session.add(new_emp)
                        added_count += 1

                db.session.commit()
                print(f"[OK] Staff sync complete: {added_count} added, {updated_count} updated.")

        # Step 4: Ensure the demonstration project from Image 2 & 3 exists
        print("\nStep 4: Ensuring demonstration project PMS DEV (EMC/2026-27/GA/IT/1)...")
        pm_user = Employee.query.filter_by(emp_id='150405').first()
        if not pm_user:
            pm_user = Employee.query.filter_by(email='anshuman.sahoo@ecometrix.co.in').first()
        if pm_user:
            pm_user.role = 'PM'  # Allocated as PM!
            if not pm_user.monthly_salary:
                pm_user.monthly_salary = 70000.0
                pm_user.salary_grade = 'M-2'

        admin_user = Employee.query.filter((Employee.email == 'admin@ecometrix.co.in') | (Employee.emp_id == 'ADMIN001')).first()
        creator_id = admin_user.id if admin_user else 1

        ga_dept = Department.query.filter_by(short_code='GA').first()
        if not ga_dept:
            ga_dept = Department.query.filter(Department.name.ilike('%General%')).first()
        if not ga_dept:
            ga_dept = Department(name='General Administration', short_code='GA', is_general_admin=True)
            db.session.add(ga_dept)
            db.session.flush()

        it_dept = Department.query.filter_by(short_code='IT').first()
        if not it_dept:
            it_dept = Department(name='Information Technology', short_code='IT', is_general_admin=False, parent_department_id=ga_dept.id)
            db.session.add(it_dept)
            db.session.flush()

        sample_indent = JobIndent.query.filter_by(file_number='EMC/2026-27/GA/IT/1').first()
        if not sample_indent:
            sample_indent = JobIndent(
                financial_year='2026-27',
                department_id=ga_dept.id,
                sub_department_id=it_dept.id,
                file_number='EMC/2026-27/GA/IT/1',
                project_name='PMS DEV',
                client_name='Internal Solutions - EMC',
                contract_value=2500000.0,
                contract_start_date=date(2026, 10, 2),
                contract_end_date=date(2026, 12, 30),
                project_manager_id=pm_user.id if pm_user else creator_id,
                status='Approved',
                created_by_id=creator_id,
                project_type='Web Application & Timesheet System',
                description='Design and development of advanced Project Monitoring System with Timesheet, Resource Allocation, and Job Card workflows.'
            )
            db.session.add(sample_indent)
            db.session.flush()

            # Create linked JobCard in Draft status
            jc = JobCard(
                job_indent_id=sample_indent.id,
                project_start_date=sample_indent.contract_start_date,
                project_end_date=sample_indent.contract_end_date,
                actual_start_date=sample_indent.contract_start_date,
                actual_end_date=sample_indent.contract_end_date,
                status='Draft',
                budget_status='Pending',
                overview='PMS Development project focused on delivering automated timesheets, dynamic resource estimation, and multi-tier project approval flows.',
                estimated_value=1250000.0
            )
            db.session.add(jc)
            db.session.commit()
            print("[OK] Sample project 'PMS DEV' (EMC/2026-27/GA/IT/1) created and assigned to Mr. Anshuman Sahoo!")
        else:
            if pm_user and sample_indent.project_manager_id != pm_user.id:
                sample_indent.project_manager_id = pm_user.id
                db.session.commit()
            print("[OK] Sample project already exists.")

if __name__ == '__main__':
    run_migration()
