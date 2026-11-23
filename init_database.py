#!/usr/bin/env python3
"""
Database initialization script for the Project Management System.
This script creates all database tables and adds initial data.
"""

from app import app, db, Department, Employee
from datetime import datetime

def init_database():
    """Initialize the database with all tables and initial data."""
    with app.app_context():
        print("Creating database tables...")
        
        # Create all tables
        db.create_all()
        print("✓ All database tables created successfully!")
        
        # Check if departments already exist
        if Department.query.count() == 0:
            print("Adding initial departments...")
            
            # Create main departments
            departments = [
                Department(name='Business Development', short_code='BD', is_general_admin=False),
                Department(name='Project Management', short_code='PM', is_general_admin=False),
                Department(name='Human Resources', short_code='HR', is_general_admin=False),
                Department(name='Finance', short_code='FIN', is_general_admin=False),
                Department(name='General Administration', short_code='GA', is_general_admin=True),
                Department(name='Information Technology', short_code='IT', is_general_admin=False),
                Department(name='Operations', short_code='OPS', is_general_admin=False),
                Department(name='Quality Assurance', short_code='QA', is_general_admin=False),
                Department(name='Research & Development', short_code='R&D', is_general_admin=False),
                Department(name='Marketing', short_code='MKT', is_general_admin=False),
            ]
            
            for dept in departments:
                db.session.add(dept)
            
            db.session.commit()
            print("✓ Initial departments added successfully!")
        else:
            print("✓ Departments already exist, skipping...")
        
        # Check if admin user exists
        if Employee.query.filter_by(email='admin@ecometrix.co.in').first() is None:
            print("Creating admin user...")
            
            admin_dept = Department.query.filter_by(short_code='GA').first()
            if admin_dept:
                admin = Employee(
                    emp_id='ADMIN001',
                    name='Mr. Chinmay Tripathy, CEO',
                    designation='CEO',
                    place='Bhubaneswar',
                    department_id=admin_dept.id,
                    email='admin@ecometrix.co.in',
                    role='MD',
                    is_active=True
                )
                admin.set_password('admin123')
                db.session.add(admin)
                db.session.commit()
                print("✓ Admin user created successfully!")
                print("  Email: admin@ecometrix.co.in")
                print("  Password: admin123")
            else:
                print("⚠ Warning: General Administration department not found!")
        else:
            print("✓ Admin user already exists, skipping...")
        
        print("\n🎉 Database initialization completed successfully!")
        print("\nYou can now run the application with: python app.py")

if __name__ == '__main__':
    init_database() 