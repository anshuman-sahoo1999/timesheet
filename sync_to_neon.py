import os
import sys
from dotenv import load_dotenv

load_dotenv()

def sync_neon(db_url=None):
    if not db_url:
        db_url = os.environ.get('DATABASE_URL')
    
    if not db_url or 'sqlite' in db_url:
        print("[ERROR] No remote PostgreSQL / Neon DATABASE_URL provided.")
        print("Usage: python sync_to_neon.py <NEON_DATABASE_URL>")
        print("Example: python sync_to_neon.py postgresql://user:password@ep-xyz.us-east-2.aws.neon.tech/neondb?sslmode=require")
        print("Or set DATABASE_URL in your .env file.")
        return False
        
    if db_url.startswith('postgres://'):
        db_url = db_url.replace('postgres://', 'postgresql://', 1)
        
    print(f"[INFO] Connecting to Neon DB: {db_url.split('@')[-1] if '@' in db_url else 'specified URL'}")
    
    # Override app database URI to point to Neon DB
    from app import app, db, Employee, Department
    app.config['SQLALCHEMY_DATABASE_URI'] = db_url
    
    with app.app_context():
        try:
            print("[INFO] Creating tables on Neon DB if not present...")
            db.create_all()
            print("[SUCCESS] Tables verified/created on Neon DB.")
            
            # 1. Standalone Unmapped Department Accounts
            dept_accounts = [
                {
                    'emp_id': 'DEPT_HR',
                    'name': 'HR Department',
                    'email': 'hr@ecometrix.co.in',
                    'role': 'HR',
                    'employment_type': 'DEPARTMENT',
                    'password': 'PMS@HR_2026'
                },
                {
                    'emp_id': 'DEPT_IT',
                    'name': 'IT Department',
                    'email': 'itsupport@ecometrix.co.in',
                    'role': 'IT',
                    'employment_type': 'DEPARTMENT',
                    'password': 'PMS@IT_2026'
                },
                {
                    'emp_id': 'DEPT_FIN',
                    'name': 'Accounts Department',
                    'email': 'accounts@ecometrix.co.in',
                    'role': 'FINANCE',
                    'employment_type': 'DEPARTMENT',
                    'password': 'PMS@FIN_2026'
                }
            ]
            
            for dept in dept_accounts:
                acc = Employee.query.filter(
                    (Employee.emp_id == dept['emp_id']) | (Employee.email == dept['email'])
                ).first()
                if acc:
                    acc.name = dept['name']
                    acc.email = dept['email']
                    acc.role = dept['role']
                    acc.employment_type = 'DEPARTMENT'
                    acc.is_active = True
                    acc.set_password(dept['password'])
                    print(f"[UPDATED DEPT] {dept['name']}: {dept['email']} (Password: {dept['password']})")
                else:
                    new_acc = Employee(
                        emp_id=dept['emp_id'],
                        name=dept['name'],
                        email=dept['email'],
                        role=dept['role'],
                        employment_type='DEPARTMENT',
                        is_active=True
                    )
                    new_acc.set_password(dept['password'])
                    db.session.add(new_acc)
                    print(f"[CREATED DEPT] {dept['name']}: {dept['email']} (Password: {dept['password']})")

            # 2. CEO / Super Admin Account
            ceo = Employee.query.filter(
                (Employee.emp_id == '15M006') | (Employee.email == 'chinmay.tripathy@ecometrix.co.in')
            ).first()
            if ceo:
                ceo.name = 'Mr. Chinmaya Tripathy'
                ceo.email = 'chinmay.tripathy@ecometrix.co.in'
                ceo.role = 'MD'
                ceo.is_active = True
                ceo.set_password('PMS@CEO_2026')
                print(f"[UPDATED CEO] Mr. Chinmaya Tripathy: chinmay.tripathy@ecometrix.co.in (Password: PMS@CEO_2026)")
            else:
                new_ceo = Employee(
                    emp_id='15M006',
                    name='Mr. Chinmaya Tripathy',
                    email='chinmay.tripathy@ecometrix.co.in',
                    role='MD',
                    employment_type='EMPLOYEE',
                    is_active=True
                )
                new_ceo.set_password('PMS@CEO_2026')
                db.session.add(new_ceo)
                print(f"[CREATED CEO] Mr. Chinmaya Tripathy: chinmay.tripathy@ecometrix.co.in (Password: PMS@CEO_2026)")

            # 3. Individual Staff Members (Restored to EMP role with personal emails)
            individual_staff = [
                {
                    'emp_id': '150076',
                    'name': 'Ms. Ananyaa Patnaik',
                    'email': 'ananyaa.patnaik@ecometrix.co.in',
                    'role': 'EMP',
                    'employment_type': 'EMPLOYEE',
                    'password': 'pms123'
                },
                {
                    'emp_id': '150007',
                    'name': 'Mr. Jnananjay Sankhua',
                    'email': 'jnananjaya.sankhua@ecometrix.co.in',
                    'role': 'EMP',
                    'employment_type': 'EMPLOYEE',
                    'password': 'pms123'
                },
                {
                    'emp_id': '150325',
                    'name': 'Mr. Ajaya Kumar Sahoo',
                    'email': 'ajayakumar.sahoo@ecometrix.co.in',
                    'role': 'EMP',
                    'employment_type': 'CONSULTANT',
                    'password': 'pms123'
                }
            ]
            
            for staff in individual_staff:
                emp = Employee.query.filter_by(emp_id=staff['emp_id']).first()
                if emp:
                    emp.email = staff['email']
                    emp.role = staff['role']
                    emp.set_password(staff['password'])
                    print(f"[RESTORED STAFF] {emp.name} ({staff['emp_id']}) -> {staff['email']} (role: EMP, Password: {staff['password']})")

            db.session.commit()
            total_workforce = Employee.query.filter(Employee.employment_type != 'DEPARTMENT').count()
            print(f"[SUCCESS] All credentials successfully synced to Neon DB! Total non-dept workforce: {total_workforce}")
            return True
        except Exception as e:
            db.session.rollback()
            print(f"[ERROR] Failed to sync with Neon DB: {e}")
            return False

if __name__ == '__main__':
    url_arg = sys.argv[1] if len(sys.argv) > 1 else None
    sync_neon(url_arg)
