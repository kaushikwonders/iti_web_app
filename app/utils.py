import re
from functools import wraps
from datetime import date
from flask import abort, request
from flask_login import current_user
from app.extensions import db
from app.models import AuditLog, UserCollegePermission

LEARNER_COLUMNS = [
    "mobile_no", "email_id", "first_name", "middle_name", "last_name", "gender",
    "date_of_birth", "trade_course", "batch_start_month", "batch_start_year",
    "batch_end_month", "batch_end_year", "qualification", "marital_status",
    "work_experience", "annual_family_income", "course_completion_status",
    "company_name", "sector", "designation", "job_location_district", "job_category",
    "gross_income_per_month", "placement_type", "employer_offerings"
]

EXCEL_COLUMN_MAP = {
    "Mobile No": "mobile_no", "Mobile Number": "mobile_no", "Phone": "mobile_no",
    "Email Id": "email_id", "Email ID": "email_id", "Email": "email_id",
    "First Name": "first_name", "Middle Name": "middle_name", "Last Name": "last_name",
    "Gender": "gender", "Date of Birth": "date_of_birth", "Trade/Course": "trade_course",
    "Trade/Course (new)": "trade_course", "Educational Qualification": "qualification",
    "Educational Qualification (new)": "qualification", "Marital Status": "marital_status",
    "Work Experience in Years": "work_experience", "Annual Family Income": "annual_family_income",
    "Course completion status": "course_completion_status", "Name of Company": "company_name",
    "Sector (new)": "sector", "Designation": "designation",
    "Job Location(district)": "job_location_district", "Job Category": "job_category",
    "Gross Income per Month": "gross_income_per_month", "Employer Offerings": "employer_offerings",
}

def admin_required(view_func):
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.has_role("admin"):
            abort(403)
        return view_func(*args, **kwargs)
    return wrapper


def check_college_permission(user_id, college_id, action="view"):
    if current_user.has_role("admin"):
        return True
    perm = UserCollegePermission.query.filter_by(user_id=user_id, college_id=college_id).first()
    if not perm:
        return False
    return bool(getattr(perm, f"can_{action}", False))


def log_action(action_type, entity_type=None, entity_id=None, old_value=None, new_value=None, remarks=None):
    log = AuditLog(
        user_id=current_user.id if current_user.is_authenticated else None,
        action_type=action_type,
        entity_type=entity_type,
        entity_id=entity_id,
        old_value=old_value,
        new_value=new_value,
        remarks=remarks,
        ip_address=request.remote_addr,
        user_agent=request.headers.get("User-Agent"),
    )
    db.session.add(log)
    db.session.commit()


def is_valid_mobile(value):
    value = "" if value is None else str(value).strip()
    return bool(re.fullmatch(r"\d{10}", value))


def is_valid_email(value):
    value = "" if value is None else str(value).strip()
    return bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value))


def normalize_excel_row(row):
    output = {}
    extra = {}
    for key, value in row.items():
        if value is None or str(value).lower() == "nan":
            value = None
        mapped = EXCEL_COLUMN_MAP.get(str(key).strip(), str(key).strip())
        if mapped in LEARNER_COLUMNS:
            output[mapped] = value
        else:
            extra[str(key).strip()] = value
    output["additional_data"] = extra
    return output


def learner_to_dict(learner):
    return {col: getattr(learner, col, None) for col in LEARNER_COLUMNS}
