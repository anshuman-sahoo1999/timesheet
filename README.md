# PMS - Timesheet & Project Management System

Enterprise Timesheet and Project Management portal for **Ecometrix Resource Management**.

---

## Features
- **Role-Based Access Control (RBAC):** CEO/Super Admin, HR Department, IT Support, Finance/Accounts, Project Managers, and Employees.
- **Standalone Departmental Accounts:** Dedicated unmapped departmental accounts for HR, IT, and Finance with dynamic Delegation of Power (DoP).
- **Timesheet Management:** Daily logs, weekly submissions, verification workflow, multi-level approvals, and Excel reporting.
- **Interactive Dashboards:** Real-time analytics with Chart.js, department headcount classification, submission compliance share, and period filtering.
- **Cloud Database:** Backed by **Neon PostgreSQL** serverless database.

---

## Local Setup

1. **Clone the repository:**
   ```bash
   git clone https://github.com/anshuman-sahoo1999/timesheet.git
   cd timesheet
   ```

2. **Create and activate a virtual environment:**
   ```bash
   python -m venv venv
   # Windows:
   venv\Scripts\activate
   # Linux/macOS:
   source venv/bin/activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure Environment Variables:**
   Copy `.env.example` to `.env` and fill in your credentials:
   ```bash
   cp .env.example .env
   ```

5. **Run the Application:**
   ```bash
   python app.py
   ```
   Open [http://127.0.0.1:5000](http://127.0.0.1:5000) in your browser.

---

## Deploying to Vercel

1. **Import the Git Repository into Vercel.**
2. Set Framework Preset to **Other** (Vercel automatically detects `vercel.json` and `@vercel/python`).
3. Add the following **Environment Variables** in the Vercel Dashboard (*Project Settings > Environment Variables*):
   - `DATABASE_URL`: Your Neon PostgreSQL connection string (`postgresql://...`)
   - `SECRET_KEY`: A secure random secret key
   - `SMTP_HOST`: `smtppro.zoho.com`
   - `SMTP_PORT`: `465`
   - `SMTP_USER`: `noreply@ecometrix.co.in`
   - `SMTP_PASSWORD`: Your Zoho SMTP password
   - `SMTP_FROM`: `noreply@ecometrix.co.in`
   - `SMTP_USE_SSL`: `True`
4. Click **Deploy**!
