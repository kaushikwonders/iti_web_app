# Learner CRUD App - Flask + MySQL

## Setup

```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` with your MySQL credentials.

## Create database

Create the database in MySQL:

```sql
CREATE DATABASE learner_crud_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

You can either run your SQL schema manually or let SQLAlchemy create the tables for this starter:

```bash
python -m scripts.create_admin
```

Default admin:

- Email: admin@example.com
- Password: Admin@123

## Run

```bash
python run.py
```

Open http://127.0.0.1:5000/login

## Notes

This is an Admin-first starter implementation. It includes login, users, colleges, permissions, master data, learner CRUD, bulk upload, validation, and audit logs.

Extend `Learner` model and `LEARNER_COLUMNS` in `app/utils.py` when you finalize all fields from the Data Input sheet.
