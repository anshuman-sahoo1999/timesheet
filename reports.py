# Reports module - Enhanced functions for PMS
# This file contains comprehensive report generation functions

from flask import send_file, current_app
import io
from reportlab.lib.pagesizes import letter, landscape
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors
import pandas as pd
from datetime import datetime
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils.dataframe import dataframe_to_rows

def generate_project_progress_pdf(project):
    """Generate comprehensive PDF report for project progress"""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    elements = []
    
    # Add title
    styles = getSampleStyleSheet()
    title = Paragraph(f"Project Progress Report: {project.project_name}", styles['Title'])
    elements.append(title)
    elements.append(Spacer(1, 12))
    
    # Add project information
    project_info = [
        ['Project Name', project.project_name],
        ['Client', project.client_name],
        ['File Number', project.file_number],
        ['Status', project.status],
        ['Contract Value', f"₹{project.contract_value:,.2f}" if project.contract_value else "N/A"],
        ['Start Date', project.contract_start_date.strftime('%d-%b-%Y') if project.contract_start_date else 'N/A'],
        ['End Date', project.contract_end_date.strftime('%d-%b-%Y') if project.contract_end_date else 'N/A'],
        ['Project Manager', project.project_manager.name if project.project_manager else 'N/A']
    ]
    
    table = Table(project_info)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 14),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('GRID', (0, 0), (-1, -1), 1, colors.black)
    ]))
    elements.append(table)
    elements.append(Spacer(1, 20))
    
    # Add tasks information if available
    if project.job_card and project.job_card.tasks:
        elements.append(Paragraph("Task Details", styles['Heading2']))
        elements.append(Spacer(1, 12))
        
        task_data = [['Task', 'Status', 'Man Days', 'Man Hours', 'Start Date', 'End Date', 'Assignees']]
        for task in project.job_card.tasks:
            assignees = ', '.join([a.name for a in task.assignees]) if task.assignees else 'Unassigned'
            task_data.append([
                task.description,
                task.status,
                str(task.man_days or 0),
                str(task.man_hours or 0),
                task.timeline_start.strftime('%d-%b-%Y') if task.timeline_start else 'N/A',
                task.timeline_end.strftime('%d-%b-%Y') if task.timeline_end else 'N/A',
                assignees
            ])
        
        task_table = Table(task_data)
        task_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.lightblue),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 12),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.whitesmoke),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey)
        ]))
        elements.append(task_table)
    
    doc.build(elements)
    buffer.seek(0)
    return send_file(buffer, as_attachment=True, download_name=f"project_progress_{project.id}.pdf", mimetype='application/pdf')

def generate_project_progress_excel(project):
    """Generate comprehensive Excel report for project progress"""
    # Create Excel workbook
    output = io.BytesIO()
    workbook = openpyxl.Workbook()
    
    # Project Information Sheet
    ws1 = workbook.active
    ws1.title = "Project Information"
    
    # Add project details
    project_data = [
        ['Project Name', project.project_name],
        ['Client', project.client_name],
        ['File Number', project.file_number],
        ['Status', project.status],
        ['Contract Value', project.contract_value or 0],
        ['Start Date', project.contract_start_date.strftime('%d-%b-%Y') if project.contract_start_date else 'N/A'],
        ['End Date', project.contract_end_date.strftime('%d-%b-%Y') if project.contract_end_date else 'N/A'],
        ['Project Manager', project.project_manager.name if project.project_manager else 'N/A']
    ]
    
    for row in project_data:
        ws1.append(row)
    
    # Tasks Sheet
    if project.job_card and project.job_card.tasks:
        ws2 = workbook.create_sheet("Tasks")
        
        # Headers
        headers = ['Task Description', 'Status', 'Man Days', 'Man Hours', 'Start Date', 'End Date', 'Assignees']
        ws2.append(headers)
        
        # Data
        for task in project.job_card.tasks:
            assignees = ', '.join([a.name for a in task.assignees]) if task.assignees else 'Unassigned'
            ws2.append([
                task.description,
                task.status,
                task.man_days or 0,
                task.man_hours or 0,
                task.timeline_start.strftime('%d-%b-%Y') if task.timeline_start else 'N/A',
                task.timeline_end.strftime('%d-%b-%Y') if task.timeline_end else 'N/A',
                assignees
            ])
    
    # Budget Sheet
    if project.job_card and project.job_card.budget_items:
        ws3 = workbook.create_sheet("Budget")
        
        # Headers
        budget_headers = ['Category', 'Description', 'Amount']
        ws3.append(budget_headers)
        
        # Data
        for item in project.job_card.budget_items:
            ws3.append([item.category, item.description, item.amount])
    
    workbook.save(output)
    output.seek(0)
    return send_file(output, as_attachment=True, download_name=f"project_progress_{project.id}.xlsx", mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

def generate_budget_report_pdf(project):
    """Generate budget report PDF"""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    elements = []
    
    styles = getSampleStyleSheet()
    title = Paragraph(f"Budget Report: {project.project_name}", styles['Title'])
    elements.append(title)
    elements.append(Spacer(1, 12))
    
    # Project budget summary
    if project.job_card:
        contract_value = project.contract_value or 0
        estimated_value = project.job_card.estimated_value or 0
        overhead = estimated_value * 0.20
        profit = estimated_value * 0.15
        grand_total = estimated_value + overhead + profit
        difference = contract_value - grand_total
        
        budget_summary = [
            ['Item', 'Amount (₹)'],
            ['Contract Value', f"{contract_value:,.2f}"],
            ['Estimated Value', f"{estimated_value:,.2f}"],
            ['Overhead (20%)', f"{overhead:,.2f}"],
            ['Profit (15%)', f"{profit:,.2f}"],
            ['Grand Total', f"{grand_total:,.2f}"],
            ['Difference', f"{difference:,.2f}"]
        ]
        
        table = Table(budget_summary)
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 14),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        elements.append(table)
    
    doc.build(elements)
    buffer.seek(0)
    return send_file(buffer, as_attachment=True, download_name=f"budget_report_{project.id}.pdf", mimetype='application/pdf')

def generate_budget_report_excel(project):
    """Generate budget report Excel"""
    output = io.BytesIO()
    workbook = openpyxl.Workbook()
    ws = workbook.active
    ws.title = "Budget Report"
    
    # Budget summary
    if project.job_card:
        contract_value = project.contract_value or 0
        estimated_value = project.job_card.estimated_value or 0
        overhead = estimated_value * 0.20
        profit = estimated_value * 0.15
        grand_total = estimated_value + overhead + profit
        difference = contract_value - grand_total
        
        budget_data = [
            ['Item', 'Amount (₹)'],
            ['Contract Value', contract_value],
            ['Estimated Value', estimated_value],
            ['Overhead (20%)', overhead],
            ['Profit (15%)', profit],
            ['Grand Total', grand_total],
            ['Difference', difference]
        ]
        
        for row in budget_data:
            ws.append(row)
    
    workbook.save(output)
    output.seek(0)
    return send_file(output, as_attachment=True, download_name=f"budget_report_{project.id}.xlsx", mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

def generate_employee_load_report_excel(app):
    """Generate employee workload report"""
    with app.app_context():
        from app import Employee, Task, WeeklyTimesheet
        
        # Get all employees
        employees = Employee.query.filter_by(is_active=True).all()
        
        output = io.BytesIO()
        workbook = openpyxl.Workbook()
        ws = workbook.active
        ws.title = "Employee Workload"
        
        # Headers
        headers = ['Employee Name', 'Department', 'Role', 'Total Projects', 'Active Tasks', 'Completed Tasks', 'Total Hours', 'Average Hours/Week']
        ws.append(headers)
        
        # Data
        for emp in employees:
            # Get tasks assigned to this employee
            assigned_tasks = Task.query.join(Task.assignees).filter(Employee.id == emp.id).all()
            total_projects = len(set([task.job_card.job_indent_id for task in assigned_tasks if task.job_card]))
            active_tasks = len([task for task in assigned_tasks if task.status in ['To Do', 'In Progress']])
            completed_tasks = len([task for task in assigned_tasks if task.status == 'Completed'])
            
            # Get total hours from timesheets
            timesheets = WeeklyTimesheet.query.filter_by(employee_id=emp.id).all()
            total_hours = sum(ts.total_hours for ts in timesheets)
            avg_hours_per_week = total_hours / max(len(timesheets), 1)
            
            ws.append([
                emp.name,
                emp.department.name if emp.department else 'N/A',
                emp.role,
                total_projects,
                active_tasks,
                completed_tasks,
                total_hours,
                round(avg_hours_per_week, 2)
            ])
        
        workbook.save(output)
        output.seek(0)
        return send_file(output, as_attachment=True, download_name=f"employee_workload_{datetime.now().strftime('%Y%m%d')}.xlsx", mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

def generate_daily_progress_report_excel(app, report_date):
    """Generate daily progress report"""
    with app.app_context():
        from app import WeeklyTimesheet, Employee, Task
        
        # Get timesheets for the specific date
        timesheets = WeeklyTimesheet.query.filter(
            WeeklyTimesheet.week_start_date <= report_date,
            WeeklyTimesheet.week_end_date >= report_date
        ).all()
        
        output = io.BytesIO()
        workbook = openpyxl.Workbook()
        ws = workbook.active
        ws.title = "Daily Progress"
        
        # Headers
        headers = ['Employee', 'Department', 'Project', 'Task', 'Hours', 'Progress Description', 'Status']
        ws.append(headers)
        
        # Data
        for ts in timesheets:
            project_name = "N/A"
            if ts.task and ts.task.job_card and ts.task.job_card.indent:
                project_name = ts.task.job_card.indent.project_name
            
            ws.append([
                ts.employee.name,
                ts.employee.department.name if ts.employee.department else 'N/A',
                project_name,
                ts.task.description if ts.task else 'N/A',
                ts.total_hours,
                ts.progress_description,
                ts.status
            ])
        
        workbook.save(output)
        output.seek(0)
        return send_file(output, as_attachment=True, download_name=f"daily_progress_{report_date.strftime('%Y%m%d')}.xlsx", mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

def generate_deviation_report_excel(project):
    """Generate project deviation report"""
    output = io.BytesIO()
    workbook = openpyxl.Workbook()
    ws = workbook.active
    ws.title = "Project Deviations"
    
    # Headers
    headers = ['Task', 'Planned Days', 'Actual Days', 'Deviation', 'Status', 'Comments']
    ws.append(headers)
    
    if project.job_card:
        for task in project.job_card.tasks:
            planned_days = task.man_days or 0
            # Calculate actual days (simplified - would need actual tracking)
            actual_days = planned_days  # Placeholder
            deviation = actual_days - planned_days
            
            ws.append([
                task.description,
                planned_days,
                actual_days,
                deviation,
                task.status,
                f"Task is {task.status.lower()}"
            ])
    
    workbook.save(output)
    output.seek(0)
    return send_file(output, as_attachment=True, download_name=f"deviation_report_{project.id}.xlsx", mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet') 