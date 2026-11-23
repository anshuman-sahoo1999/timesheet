import os
from app import db, Employee, Department, JobIndent, JobCard, Task, WeeklyTimesheet
from werkzeug.security import generate_password_hash
from datetime import datetime, timedelta

# Wipe all data
print('Wiping all data...')
db.session.query(WeeklyTimesheet).delete()
db.session.query(Task).delete()
db.session.query(JobCard).delete()
db.session.query(JobIndent).delete()
db.session.query(Employee).delete()
db.session.query(Department).delete()
db.session.commit()

# Departments
print('Creating departments...')
d1 = Department(name='Engineering')
d2 = Department(name='Sales')
d3 = Department(name='HR')
d4 = Department(name='Finance')
db.session.add_all([d1, d2, d3, d4])
db.session.commit()

# Users
print('Creating users...')
ceo = Employee(name='CEO User', email='ceo@demo.com', password=generate_password_hash('password'), role='MD', is_active=True, department=d1)
pm1 = Employee(name='PM One', email='pm1@demo.com', password=generate_password_hash('password'), role='PM', is_active=True, department=d1)
pm2 = Employee(name='PM Two', email='pm2@demo.com', password=generate_password_hash('password'), role='PM', is_active=True, department=d2)
emp1 = Employee(name='Employee One', email='emp1@demo.com', password=generate_password_hash('password'), role='EMP', is_active=True, department=d1)
emp2 = Employee(name='Employee Two', email='emp2@demo.com', password=generate_password_hash('password'), role='EMP', is_active=True, department=d2)
bd = Employee(name='BD User', email='bd@demo.com', password=generate_password_hash('password'), role='BD', is_active=True, department=d2)
hr = Employee(name='HR User', email='hr@demo.com', password=generate_password_hash('password'), role='HR', is_active=True, department=d3)
fin = Employee(name='Finance User', email='fin@demo.com', password=generate_password_hash('password'), role='FINANCE', is_active=True, department=d4)
db.session.add_all([ceo, pm1, pm2, emp1, emp2, bd, hr, fin])
db.session.commit()

# Projects/Job Indents
print('Creating projects/job indents...')
proj1 = JobIndent(
    financial_year='2025-26',
    department_id=d1.id,
    file_number='ENG-001',
    project_name='Bridge Construction',
    client_name='ABC Infra',
    contract_value=1000000,
    contract_start_date=datetime.now().date() - timedelta(days=60),
    contract_end_date=datetime.now().date() + timedelta(days=120),
    project_manager_id=pm1.id,
    status='In Progress',
    created_by_id=bd.id
)
proj2 = JobIndent(
    financial_year='2025-26',
    department_id=d2.id,
    file_number='SAL-002',
    project_name='Sales CRM',
    client_name='XYZ Corp',
    contract_value=500000,
    contract_start_date=datetime.now().date() - timedelta(days=30),
    contract_end_date=datetime.now().date() + timedelta(days=90),
    project_manager_id=pm2.id,
    status='Pending Approval',
    created_by_id=bd.id
)
db.session.add_all([proj1, proj2])
db.session.commit()

# Job Cards
print('Creating job cards...')
jc1 = JobCard(job_indent_id=proj1.id, project_start_date=proj1.contract_start_date, project_end_date=proj1.contract_end_date, estimated_value=900000, status='Approved')
jc2 = JobCard(job_indent_id=proj2.id, project_start_date=proj2.contract_start_date, project_end_date=proj2.contract_end_date, estimated_value=450000, status='Draft')
db.session.add_all([jc1, jc2])
db.session.commit()

# Tasks
print('Creating tasks and assignments...')
task1 = Task(job_card_id=jc1.id, description='Site Survey', man_days=10, man_hours=80, timeline_start=datetime.now().date() - timedelta(days=50), timeline_end=datetime.now().date() - timedelta(days=40), status='Completed')
task2 = Task(job_card_id=jc1.id, description='Foundation Work', man_days=20, man_hours=160, timeline_start=datetime.now().date() - timedelta(days=39), timeline_end=datetime.now().date() - timedelta(days=20), status='In Progress')
task3 = Task(job_card_id=jc2.id, description='Requirement Gathering', man_days=5, man_hours=40, timeline_start=datetime.now().date() - timedelta(days=10), timeline_end=datetime.now().date() + timedelta(days=5), status='To Do')
task1.assignees.append(emp1)
task2.assignees.append(emp2)
task3.assignees.append(emp1)
db.session.add_all([task1, task2, task3])
db.session.commit()

# Timesheets
print('Creating timesheets...')
ts1 = WeeklyTimesheet(employee_id=emp1.id, task_id=task1.id, week_start_date=datetime.now().date() - timedelta(days=49), week_end_date=datetime.now().date() - timedelta(days=43), total_hours=40, progress_description='Completed site survey', status='Approved')
ts2 = WeeklyTimesheet(employee_id=emp2.id, task_id=task2.id, week_start_date=datetime.now().date() - timedelta(days=38), week_end_date=datetime.now().date() - timedelta(days=32), total_hours=32, progress_description='Started foundation work', status='Submitted')
db.session.add_all([ts1, ts2])
db.session.commit()

print('Demo data seeded successfully!') 