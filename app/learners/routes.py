import os
import uuid
from datetime import datetime
import re
from pathlib import Path

import pandas as pd
from flask import send_file, current_app
from sqlalchemy import and_

from app.models import BulkUploadBatch, BulkUploadRow


from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    abort,
    send_from_directory,
)
from flask_login import login_required, current_user
from sqlalchemy import or_

from werkzeug.utils import secure_filename

from app.extensions import db
from app.models import (
    College,
    Learner,
    MasterType,
    MasterOption,
    UserCollegePermission,
    PlacementBulkUpdateBatch,
    PlacementBulkUpdateRow,
    LearnerEvidenceFile,
)
from app.utils import log_action

learners_bp = Blueprint("learners", __name__)




# ---------------------------------------------------------
# Helper: Check whether current user can access this college
# ---------------------------------------------------------
def get_college_permission(college_id):
    """
    Admin users get full permission.
    Enrolment/placement users depend on user_college_permissions.
    """

    if current_user.has_role("admin"):
        return {
            "can_view": True,
            "can_add": True,
            "can_edit": True,
            "can_delete": True,
        }

    permission = UserCollegePermission.query.filter_by(
        user_id=current_user.id,
        college_id=college_id,
    ).first()

    if not permission:
        return {
            "can_view": False,
            "can_add": False,
            "can_edit": False,
            "can_delete": False,
        }

    return {
        "can_view": permission.can_view,
        "can_add": permission.can_add,
        "can_edit": permission.can_edit,
        "can_delete": permission.can_delete,
    }


# ---------------------------------------------------------
# Helper: Load options from master_options table
# ---------------------------------------------------------
def get_master_options(master_key):
    master_type = MasterType.query.filter_by(
        master_key=master_key,
        is_active=True,
    ).first()

    if not master_type:
        return []

    return (
        MasterOption.query
        .filter_by(
            master_type_id=master_type.id,
            is_active=True,
        )
        .order_by(MasterOption.display_order, MasterOption.option_label)
        .all()
    )


# ---------------------------------------------------------
# Main college-wise learner page
# URL: /learners/college/1
# ---------------------------------------------------------
@learners_bp.route("/college/<int:college_id>")
@login_required
def college_learners(college_id):
    college = College.query.get_or_404(college_id)

    permission = get_college_permission(college_id)

    if not permission["can_view"]:
        abort(403)

    search = request.args.get("search", "").strip()
    trade_course = request.args.get("trade_course", "").strip()
    course_completion_status = request.args.get("course_completion_status", "").strip()

    # New filters
    mobile_no = request.args.get("mobile_no", "").strip()
    batch_start_year = request.args.get("batch_start_year", "").strip()
    batch_end_year = request.args.get("batch_end_year", "").strip()
    sector = request.args.get("sector", "").strip()

    query = Learner.query.filter_by(
        college_id=college.id,
        is_deleted=False,
    )

    # Existing generic search
    if search:
        query = query.filter(
            or_(
                Learner.mobile_no.like(f"%{search}%"),
                Learner.email_id.like(f"%{search}%"),
                Learner.first_name.like(f"%{search}%"),
                Learner.last_name.like(f"%{search}%"),
            )
        )

    # Existing filters
    if trade_course:
        query = query.filter(Learner.trade_course == trade_course)

    if course_completion_status:
        query = query.filter(
            Learner.course_completion_status == course_completion_status
        )

    # New filters
    if mobile_no:
        query = query.filter(Learner.mobile_no.like(f"%{mobile_no}%"))

    if batch_start_year:
        query = query.filter(Learner.batch_start_year == batch_start_year)

    if batch_end_year:
        query = query.filter(Learner.batch_end_year == batch_end_year)

    if sector:
        query = query.filter(Learner.sector == sector)

    learners = query.order_by(Learner.created_at.desc()).all()

    trade_courses = get_master_options("trade_course")
    course_statuses = get_master_options("course_completion_status")
    sectors = get_master_options("sector")

    return render_template(
        "learners/college_learners.html",
        college=college,
        learners=learners,
        permission=permission,

        search=search,
        selected_trade_course=trade_course,
        selected_course_completion_status=course_completion_status,

        # New selected filter values
        selected_mobile_no=mobile_no,
        selected_batch_start_year=batch_start_year,
        selected_batch_end_year=batch_end_year,
        selected_sector=sector,

        trade_courses=trade_courses,
        course_statuses=course_statuses,
        sectors=sectors,
    )


ALLOWED_EVIDENCE_EXTENSIONS = {
    # Documents
    "pdf",
    "doc",
    "docx",
    "odt",
    "rtf",
    "txt",

    # Spreadsheets
    "xls",
    "xlsx",
    "csv",
    "ods",

    # Audio
    "mp3",
    "wav",
    "m4a",
    "aac",
    "ogg",

    # Images
    "jpg",
    "jpeg",
    "png",
    "gif",
    "webp",

    # Archives
    "zip",
}


def allowed_evidence_file(filename):
    if not filename or "." not in filename:
        return False

    extension = filename.rsplit(".", 1)[1].lower()

    return extension in ALLOWED_EVIDENCE_EXTENSIONS


def clean_filename_component(value, fallback):
    value = str(value or "").strip()

    if not value:
        value = fallback

    cleaned = secure_filename(value)

    return cleaned or fallback


def get_next_evidence_sequence(learner_id):
    latest_file = (
        LearnerEvidenceFile.query
        .filter_by(learner_id=learner_id)
        .order_by(
            LearnerEvidenceFile.sequence_no.desc()
        )
        .first()
    )

    if latest_file is None:
        return 0

    return latest_file.sequence_no + 1


def cleanup_saved_files(saved_paths):
    """
    Removes files written to disk when the database transaction fails.
    """

    for saved_path in saved_paths:
        try:
            if saved_path and os.path.isfile(saved_path):
                os.remove(saved_path)
        except OSError:
            current_app.logger.exception(
                "Unable to remove evidence file after rollback: %s",
                saved_path,
            )


def save_learner_evidence_files(
    learner,
    college,
    saved_paths,
):
    """
    Saves files uploaded through Single Add or Edit.

    Database records are added to the current SQLAlchemy transaction.
    This function does not call db.session.commit().
    """

    uploaded_files = request.files.getlist(
        "evidence_files"
    )

    uploaded_files = [
        uploaded_file
        for uploaded_file in uploaded_files
        if uploaded_file and uploaded_file.filename
    ]

    if not uploaded_files:
        return

    first_name = clean_filename_component(
        learner.first_name,
        "Learner",
    )

    mobile_no = clean_filename_component(
        learner.mobile_no,
        "NoMobile",
    )

    institute_name = clean_filename_component(
        college.institute_name,
        f"College_{college.id}",
    )

    base_filename = (
        f"{first_name}_{mobile_no}_{institute_name}"
    )

    learner_folder = os.path.join(
        current_app.config["EVIDENCE_UPLOAD_FOLDER"],
        str(learner.id),
    )

    os.makedirs(
        learner_folder,
        exist_ok=True,
    )

    next_sequence = get_next_evidence_sequence(
        learner.id
    )

    for uploaded_file in uploaded_files:
        original_filename = (
            uploaded_file.filename.strip()
        )

        if not allowed_evidence_file(
            original_filename
        ):
            raise ValueError(
                "File type is not allowed for: "
                f"{original_filename}"
            )

        extension = (
            original_filename
            .rsplit(".", 1)[1]
            .lower()
        )

        sequence_no = next_sequence

        while True:
            if sequence_no == 0:
                generated_filename = (
                    f"{base_filename}.{extension}"
                )
            else:
                generated_filename = (
                    f"{base_filename}_"
                    f"{sequence_no}.{extension}"
                )

            generated_filename = secure_filename(
                generated_filename
            )

            absolute_path = os.path.join(
                learner_folder,
                generated_filename,
            )

            if not os.path.exists(absolute_path):
                break

            sequence_no += 1

        uploaded_file.save(absolute_path)

        # Add immediately so it can be removed if commit fails.
        saved_paths.append(absolute_path)

        relative_path = os.path.relpath(
            absolute_path,
            current_app.config[
                "EVIDENCE_UPLOAD_FOLDER"
            ],
        )

        evidence_record = LearnerEvidenceFile(
            learner_id=learner.id,
            uploaded_by=current_user.id,
            sequence_no=sequence_no,
            original_filename=original_filename,
            stored_filename=generated_filename,
            relative_path=relative_path,
            file_extension=extension,
            mime_type=uploaded_file.mimetype,
            file_size=os.path.getsize(
                absolute_path
            ),
        )

        db.session.add(evidence_record)

        next_sequence = sequence_no + 1

# ---------------------------------------------------------
# Add learner
# URL: /learners/college/1/add
# ---------------------------------------------------------
@learners_bp.route("/college/<int:college_id>/add", methods=["GET", "POST"])
@login_required
def add_learner(college_id):
    college = College.query.get_or_404(college_id)

    permission = get_college_permission(college_id)

    if not permission["can_add"]:
        abort(403)

    if request.method == "POST":
        mobile_no = request.form.get("mobile_no", "").strip() or None
        email_id = request.form.get("email_id", "").strip() or None
        first_name = request.form.get("first_name", "").strip()
        gender = request.form.get("gender", "").strip()
        trade_course = request.form.get("trade_course", "").strip()

        if not mobile_no and not email_id:
            flash("Either Mobile No or Email Id is required.", "danger")
            return redirect(url_for("learners.add_learner", college_id=college_id))
        

        if mobile_no:
            if len(mobile_no) != 10 or not mobile_no.isdigit():
                flash("Mobile No must be exactly 10 digits.", "danger")
                return redirect(url_for("learners.add_learner", college_id=college_id))

        if email_id:
            if "@" not in email_id:
                flash("Please enter a valid Email Id.", "danger")
                return redirect(url_for("learners.add_learner", college_id=college_id))

        if not first_name:
            flash("First Name is required.", "danger")
            return redirect(url_for("learners.add_learner", college_id=college_id))
        if not gender:
            flash("Gender is required.", "danger")
            return redirect(url_for("learners.add_learner", college_id=college_id))
        if not trade_course:
            flash("Trade/Course is required.", "danger")
            return redirect(url_for("learners.add_learner", college_id=college_id))
        
        existing = Learner.query.filter(
            Learner.mobile_no.is_(None) if mobile_no is None else Learner.mobile_no == mobile_no,
            Learner.email_id.is_(None) if email_id is None else Learner.email_id == email_id,
            Learner.is_deleted == False
        ).first()

        if existing:
            flash("Learner with this Mobile No and Email Id combination already exists in the system.", "danger")
            return redirect(url_for("learners.add_learner", college_id=college_id))

        learner = Learner(
            college_id=college.id,

            mobile_no=mobile_no,
            email_id=email_id,

            first_name=first_name,
            last_name=request.form.get("last_name", "").strip(),

            gender=gender,
            date_of_birth=request.form.get("date_of_birth") or None,

            trade_course=trade_course,

            batch_start_month=request.form.get("batch_start_month", "").strip(),
            batch_start_year=request.form.get("batch_start_year") or None,
            batch_end_month=request.form.get("batch_end_month", "").strip(),
            batch_end_year=request.form.get("batch_end_year") or None,

            educational_qualification=request.form.get("educational_qualification", "").strip(),
            marital_status=request.form.get("marital_status", "").strip(),
            work_experience=request.form.get("work_experience", "").strip(),
            annual_family_income=request.form.get("annual_family_income", "").strip(),

            course_completion_status=request.form.get("course_completion_status", "").strip(),

            company_name=request.form.get("company_name", "").strip(),
            sector=request.form.get("sector", "").strip(),
            designation=request.form.get("designation", "").strip(),
            job_location_district=request.form.get("job_location_district", "").strip(),
            monthly_salary=request.form.get("monthly_salary") or None,

            ladder_current_step=get_int_or_none("ladder_current_step"),
            ladder_future_step=get_int_or_none("ladder_future_step"),

            status_after_3_months=request.form.get("status_after_3_months", "").strip() or None,
            company_name_3_months=request.form.get("company_name_3_months", "").strip() or None,
            designation_3_months=request.form.get("designation_3_months", "").strip() or None,
            gross_income_3_months=get_int_or_none("gross_income_3_months"),
            sector_3_months=request.form.get("sector_3_months", "").strip() or None,

            status_after_6_months=request.form.get("status_after_6_months", "").strip() or None,
            company_name_6_months=request.form.get("company_name_6_months", "").strip() or None,
            designation_6_months=request.form.get("designation_6_months", "").strip() or None,
            gross_income_6_months=get_int_or_none("gross_income_6_months"),
            sector_6_months=request.form.get("sector_6_months", "").strip() or None,

            project_phase=request.form.get("project_phase", "").strip() or None,
            cits_cts=request.form.get("cits_cts", "").strip() or None,
            project=request.form.get("project", "").strip() or None,
            phase=request.form.get("phase", "").strip() or None,

            working_days_per_week=get_int_or_none("working_days_per_week"),
            working_hours_per_day=get_int_or_none("working_hours_per_day"),
            evidence_type=get_multi_values("evidence_type"),
            evidence_drive_link=request.form.get("evidence_drive_link", "").strip() or None,

            apprenticeship_duration_months=get_int_or_none("apprenticeship_duration_months"),
            registered_on_apprenticeship_portal=request.form.get("registered_on_apprenticeship_portal", "").strip() or None,

            self_employment_type=request.form.get("self_employment_type", "").strip() or None,

            job_type_looking_for=request.form.get("job_type_looking_for", "").strip() or None,
            preferred_work_start_time=request.form.get("preferred_work_start_time", "").strip() or None,

            reason_not_interested_working=get_multi_values("reason_not_interested_working"),

            higher_education_course=request.form.get("higher_education_course", "").strip() or None,

            dropout_reason=request.form.get("dropout_reason", "").strip() or None,
            employer_offerings=get_multi_values("employer_offerings"),
            gross_income_per_month=get_int_or_none("gross_income_per_month"),

            business_establishment_year=get_int_or_none("business_establishment_year"),
            business_description=request.form.get("business_description", "").strip() or None,

            green_or_technology_related=request.form.get("green_or_technology_related", "").strip() or None,
            workplace_location=request.form.get("workplace_location", "").strip() or None,
            business_registration_type=request.form.get("business_registration_type", "").strip() or None,
            uses_digital_platforms_for_marketing=request.form.get("uses_digital_platforms_for_marketing", "").strip() or None,

            number_of_paid_employees=get_int_or_none("number_of_paid_employees"),
            income_happiness_score=request.form.get("income_happiness_score", "").strip() or None,

            business_conditions=get_multi_values("business_conditions"),

            gig_work_nature=get_multi_values("gig_work_nature"),
            gig_platforms_used=get_multi_values("gig_platforms_used"),
            other_gig_platforms=request.form.get("other_gig_platforms", "").strip() or None,

            receives_wages_or_profit_share=request.form.get("receives_wages_or_profit_share", "").strip() or None,

            permanent_address_state=request.form.get("permanent_address_state", "").strip() or None,
            permanent_address_district=request.form.get("permanent_address_district", "").strip() or None,
            parent_guardian_name=request.form.get("parent_guardian_name", "").strip() or None,
            parent_guardian_contact_no=request.form.get("parent_guardian_contact_no", "").strip() or None,

            created_by=current_user.id,
            updated_by=current_user.id,
        )

        saved_paths = []

        try:
            db.session.add(learner)
            # Required because the evidence table needs learner.id
            db.session.flush()
            save_learner_evidence_files(
                learner=learner,
                college=college,
                saved_paths=saved_paths,
            )
            db.session.commit()
        except ValueError as exc:
            db.session.rollback()
            cleanup_saved_files(saved_paths)
            flash(str(exc), "danger")
            return redirect(
                url_for("learners.add_learner",college_id=college.id,)
            )
        except Exception:
            db.session.rollback()
            cleanup_saved_files(saved_paths)
            current_app.logger.exception(
                "Error while creating learner or saving "
                "learner evidence files"
            )
            flash(
                "The learner could not be saved because "
                "an evidence-file upload failed.",
                "danger",
            )
            return redirect(
                url_for(
                    "learners.add_learner",
                    college_id=college.id,
                )
            )
        log_action(
             "CREATE_LEARNER",
             "learners",
             learner.id,new_value={
                 "college_id": college.id,
                 "mobile_no": mobile_no,
                  "email_id": email_id,
             },
        )
        flash(
             "Learner added successfully.",
             "success",
        )
        return redirect(
            url_for(
                 "learners.college_learners",
                 college_id=college.id,
            )
        )

    dropdowns = {
        "gender": get_master_options("gender"),
        "trade_course": get_master_options("trade_course"),
        "educational_qualification": get_master_options("qualification"),
        "marital_status": get_master_options("marital_status"),
        "work_experience": get_master_options("work_experience"),
        "annual_family_income": get_master_options("annual_family_income"),
        "course_completion_status": get_master_options("course_completion_status"),
        "sector": get_master_options("sector"),
        "sector_3_months": get_master_options("sector"),
        "sector_6_months": get_master_options("sector"),
        "designation": get_master_options("designation"),
        "job_location_district": get_master_options("district"),
        "job_category": get_master_options("job_category"),
        "placement_type": get_master_options("placement_type"),
        "employer_offerings": get_master_options("employer_offerings"),
        "evidence_type": get_master_options("evidence_type"),
        "self_employment_type": get_master_options("self_employment_type"),
        "green_or_technology_related": get_master_options("green_or_technology_related"),
        "workplace_location": get_master_options("workplace_location"),
        "business_registration_type": get_master_options("business_registration_type"),
        "uses_digital_platforms_for_marketing": get_master_options("uses_digital_platforms_for_marketing"),
        "income_happiness_score": get_master_options("income_happiness_score"),
        "business_conditions": get_master_options("business_conditions"),
        "gig_work_nature": get_master_options("gig_work_nature"),
        "gig_platforms_used": get_master_options("gig_platforms_used"),
        "receives_wages_or_profit_share": get_master_options("receives_wages_or_profit_share"),
        "evidence_type_self_employed_employer": get_master_options("evidence_type_self_employed_employer"),
        "evidence_type_self_employed_own_account": get_master_options("evidence_type_self_employed_own_account"),
        "evidence_type_self_employed_gig_worker": get_master_options("evidence_type_self_employed_gig_worker"),
        "evidence_type_self_employed_household_family": get_master_options("evidence_type_self_employed_household_family"),
        "state": get_master_options("state"),
        "district": get_master_options("district"),
        "registered_on_apprenticeship_portal": get_master_options("registered_on_apprenticeship_portal"),
        "cits_cts": get_master_options("cits_cts"),
    }

    return render_template(
        "learners/learner_form.html",
        college=college,
        learner=None,
        dropdowns=dropdowns,
        evidence_files=[],
        mode="add",
    )


# ---------------------------------------------------------
# Edit learner
# URL: /learners/college/1/learner/10/edit
# ---------------------------------------------------------
@learners_bp.route("/college/<int:college_id>/learner/<int:learner_id>/edit", methods=["GET", "POST"])
@login_required
def edit_learner(college_id, learner_id):
    college = College.query.get_or_404(college_id)

    learner = Learner.query.filter_by(
        id=learner_id,
        college_id=college.id,
        is_deleted=False,
    ).first_or_404()

    permission = get_college_permission(college_id)

    if not permission["can_edit"]:
        abort(403)

    if request.method == "POST":
        old_value = {
            "mobile_no": learner.mobile_no,
            "email_id": learner.email_id,
            "first_name": learner.first_name,
            "last_name": learner.last_name,
            "trade_course": learner.trade_course,
            "course_completion_status": learner.course_completion_status,
        }

        mobile_no = request.form.get("mobile_no", "").strip() or None
        email_id = request.form.get("email_id", "").strip() or None
        first_name = request.form.get("first_name", "").strip()
        gender = request.form.get("gender", "").strip()
        trade_course = request.form.get("trade_course", "").strip()

        if not mobile_no and not email_id:
            flash("Either Mobile No or Email Id is required.", "danger")
            return redirect(
                url_for(
                    "learners.edit_learner",
                    college_id=college.id,
                    learner_id=learner.id,
                )
            )


        if mobile_no:
            if len(mobile_no) != 10 or not mobile_no.isdigit():
                flash("Mobile No must be exactly 10 digits.", "danger")
                return redirect(
                    url_for(
                        "learners.edit_learner",
                        college_id=college.id,
                        learner_id=learner.id,
                )
            )

        if email_id:
            if "@" not in email_id:
                flash("Please enter a valid Email Id.", "danger")
                return redirect(
                    url_for(
                        "learners.edit_learner",
                        college_id=college.id,
                        learner_id=learner.id,
                )
            )


        if not first_name:
            flash("First Name is required.", "danger")
            return redirect(
                url_for(
                    "learners.edit_learner",
                    college_id=college.id,
                    learner_id=learner.id,
                )
            )

        if not gender:
            flash("Gender is required.", "danger")
            return redirect(
                url_for(
                    "learners.edit_learner",
                    college_id=college.id,
                    learner_id=learner.id,
                )
            )

        if not trade_course:
            flash("Trade/Course is required.", "danger")
            return redirect(
                url_for(
                    "learners.edit_learner",
                    college_id=college.id,
                    learner_id=learner.id,
                )
            )
        

        duplicate = Learner.query.filter(
            Learner.mobile_no.is_(None) if mobile_no is None else Learner.mobile_no == mobile_no,
            Learner.email_id.is_(None) if email_id is None else Learner.email_id == email_id,
            Learner.id != learner.id,
            Learner.is_deleted == False,
        ).first()

        if duplicate:
            flash("Another learner with this Mobile No and Email Id combination already exists.", "danger")
            return redirect(
                url_for(
                    "learners.edit_learner",
                    college_id=college.id,
                    learner_id=learner.id,
                )
            )

        learner.mobile_no = mobile_no
        learner.email_id = email_id

        learner.first_name = first_name
        learner.last_name = request.form.get("last_name", "").strip()

        learner.gender = gender
        learner.date_of_birth = request.form.get("date_of_birth") or None

        learner.trade_course = trade_course

        learner.batch_start_month = request.form.get("batch_start_month", "").strip()
        learner.batch_start_year = request.form.get("batch_start_year") or None
        learner.batch_end_month = request.form.get("batch_end_month", "").strip()
        learner.batch_end_year = request.form.get("batch_end_year") or None

        learner.educational_qualification = request.form.get("educational_qualification", "").strip()
        learner.marital_status = request.form.get("marital_status", "").strip()
        learner.work_experience = request.form.get("work_experience", "").strip()
        learner.annual_family_income = request.form.get("annual_family_income", "").strip()

        learner.course_completion_status = request.form.get("course_completion_status", "").strip()

        learner.company_name = request.form.get("company_name", "").strip()
        learner.sector = request.form.get("sector", "").strip()
        learner.designation = request.form.get("designation", "").strip()
        learner.job_location_district = request.form.get("job_location_district", "").strip()
        learner.monthly_salary = request.form.get("monthly_salary") or None

        learner.ladder_current_step = get_int_or_none("ladder_current_step")
        learner.ladder_future_step = get_int_or_none("ladder_future_step")

        learner.status_after_3_months = request.form.get("status_after_3_months", "").strip() or None
        learner.company_name_3_months = request.form.get("company_name_3_months", "").strip() or None
        learner.designation_3_months = request.form.get("designation_3_months", "").strip() or None
        learner.gross_income_3_months = get_int_or_none("gross_income_3_months")
        learner.sector_3_months = request.form.get("sector_3_months", "").strip() or None

        learner.status_after_6_months = request.form.get("status_after_6_months", "").strip() or None
        learner.company_name_6_months = request.form.get("company_name_6_months", "").strip() or None
        learner.designation_6_months = request.form.get("designation_6_months", "").strip() or None
        learner.gross_income_6_months = get_int_or_none("gross_income_6_months")
        learner.sector_6_months = request.form.get("sector_6_months", "").strip() or None

        learner.project_phase = request.form.get("project_phase", "").strip() or None
        learner.cits_cts = request.form.get("cits_cts", "").strip() or None
        learner.project = request.form.get("project", "").strip() or None
        learner.phase = request.form.get("phase", "").strip() or None

        learner.working_days_per_week = get_int_or_none("working_days_per_week")
        learner.working_hours_per_day = get_int_or_none("working_hours_per_day")
        learner.evidence_type = get_multi_values("evidence_type")
        learner.evidence_drive_link = request.form.get("evidence_drive_link", "").strip() or None

        learner.apprenticeship_duration_months = get_int_or_none("apprenticeship_duration_months")
        learner.registered_on_apprenticeship_portal = request.form.get("registered_on_apprenticeship_portal", "").strip() or None

        learner.self_employment_type = request.form.get("self_employment_type", "").strip() or None

        learner.job_type_looking_for = request.form.get("job_type_looking_for", "").strip() or None
        learner.preferred_work_start_time = request.form.get("preferred_work_start_time", "").strip() or None

        learner.reason_not_interested_working = get_multi_values("reason_not_interested_working")

        learner.higher_education_course = request.form.get("higher_education_course", "").strip() or None

        learner.dropout_reason = request.form.get("dropout_reason", "").strip() or None
        learner.employer_offerings = get_multi_values("employer_offerings")
        learner.gross_income_per_month = get_int_or_none("gross_income_per_month")

        learner.business_establishment_year = get_int_or_none("business_establishment_year")
        learner.business_description = request.form.get("business_description", "").strip() or None

        learner.green_or_technology_related = request.form.get("green_or_technology_related", "").strip() or None
        learner.workplace_location = request.form.get("workplace_location", "").strip() or None
        learner.business_registration_type = request.form.get("business_registration_type", "").strip() or None
        learner.uses_digital_platforms_for_marketing = request.form.get("uses_digital_platforms_for_marketing", "").strip() or None

        learner.number_of_paid_employees = get_int_or_none("number_of_paid_employees")
        learner.income_happiness_score = request.form.get("income_happiness_score", "").strip() or None

        learner.business_conditions = get_multi_values("business_conditions")

        learner.gig_work_nature = get_multi_values("gig_work_nature")
        learner.gig_platforms_used = get_multi_values("gig_platforms_used")
        learner.other_gig_platforms = request.form.get("other_gig_platforms", "").strip() or None

        learner.receives_wages_or_profit_share = request.form.get("receives_wages_or_profit_share", "").strip() or None

        parent_guardian_contact_no = request.form.get("parent_guardian_contact_no", "").strip() or None

        if parent_guardian_contact_no:
            if len(parent_guardian_contact_no) != 10 or not parent_guardian_contact_no.isdigit():
                flash("Parent/Guardian Contact Number must be exactly 10 digits.", "danger")
                return redirect(
                    url_for(
                    "learners.edit_learner",
                    college_id=college.id,
                    learner_id=learner.id,
            )
        )
            
        learner.permanent_address_state = request.form.get("permanent_address_state", "").strip() or None
        learner.permanent_address_district = request.form.get("permanent_address_district", "").strip() or None
        learner.parent_guardian_name = request.form.get("parent_guardian_name", "").strip() or None
        learner.parent_guardian_contact_no = parent_guardian_contact_no

        learner.updated_by = current_user.id

        saved_paths = []

        try:
            save_learner_evidence_files(
                learner=learner,
                college=college,
                saved_paths=saved_paths,
            )

            db.session.commit()

        except ValueError as exc:
            db.session.rollback()
            cleanup_saved_files(saved_paths)

            flash(str(exc), "danger")

            return redirect(
                url_for(
                    "learners.edit_learner",
                    college_id=college.id,
                    learner_id=learner.id,
                )
            )

        except Exception:
            db.session.rollback()
            cleanup_saved_files(saved_paths)

            current_app.logger.exception(
                "Error while updating learner or saving "
                "learner evidence files"
            )

            flash(
                "The learner could not be updated because "
                "an evidence-file upload failed.",
                "danger",
            )

            return redirect(
                url_for(
                    "learners.edit_learner",
                    college_id=college.id,
                    learner_id=learner.id,
                )
            )

        log_action(
            "UPDATE_LEARNER",
            "learners",
            learner.id,
            old_value=old_value,
            new_value={
                "mobile_no": learner.mobile_no,
                "email_id": learner.email_id,
                "first_name": learner.first_name,
                "last_name": learner.last_name,
                "trade_course": learner.trade_course,
                "course_completion_status": learner.course_completion_status,
            },
        )

        flash("Learner updated successfully.", "success")
        return redirect(url_for("learners.college_learners", college_id=college.id))

    dropdowns = {
        "gender": get_master_options("gender"),
        "trade_course": get_master_options("trade_course"),
        "educational_qualification": get_master_options("qualification"),
        "marital_status": get_master_options("marital_status"),
        "work_experience": get_master_options("work_experience"),
        "annual_family_income": get_master_options("annual_family_income"),
        "course_completion_status": get_master_options("course_completion_status"),

        "status_after_3_months": get_master_options("status_after_3_months"),
        "status_after_6_months": get_master_options("status_after_6_months"),
        
        "sector": get_master_options("sector"),
        "sector_3_months": get_master_options("sector"),
        "sector_6_months": get_master_options("sector"),

        "designation": get_master_options("designation"),
        
        "job_location_district": get_master_options("district"),
        "job_category": get_master_options("job_category"),
        "placement_type": get_master_options("placement_type"),
           
        "employer_offerings": get_master_options("employer_offerings"),
        "evidence_type": get_master_options("evidence_type"),

        "cits_cts": get_master_options("cits_cts"),
        "registered_on_apprenticeship_portal": get_master_options("registered_on_apprenticeship_portal"),

        "self_employment_type": get_master_options("self_employment_type"),
        "job_type_looking_for": get_master_options("job_type_looking_for"),
        "preferred_work_start_time": get_master_options("preferred_work_start_time"),
        "reason_not_interested_working": get_master_options("reason_not_interested_working"),
        "higher_education_course": get_master_options("higher_education_course"),
        "dropout_reason": get_master_options("dropout_reason"),
        "green_or_technology_related": get_master_options("green_or_technology_related"),
        "workplace_location": get_master_options("workplace_location"),
        "business_registration_type": get_master_options("business_registration_type"),
        "uses_digital_platforms_for_marketing": get_master_options("uses_digital_platforms_for_marketing"),
        "income_happiness_score": get_master_options("income_happiness_score"),
        "business_conditions": get_master_options("business_conditions"),
        "gig_work_nature": get_master_options("gig_work_nature"),
        "gig_platforms_used": get_master_options("gig_platforms_used"),
        "receives_wages_or_profit_share": get_master_options("receives_wages_or_profit_share"),
        "evidence_type_self_employed_employer": get_master_options("evidence_type_self_employed_employer"),
        "evidence_type_self_employed_own_account": get_master_options("evidence_type_self_employed_own_account"),
        "evidence_type_self_employed_gig_worker": get_master_options("evidence_type_self_employed_gig_worker"),
        "evidence_type_self_employed_household_family": get_master_options("evidence_type_self_employed_household_family"),
        "state": get_master_options("state"),
        "district": get_master_options("district"),
    }

    evidence_files = (
    LearnerEvidenceFile.query
    .filter_by(learner_id=learner.id)
    .order_by(
        LearnerEvidenceFile.sequence_no.asc()
    )
    .all())

    return render_template(
        "learners/learner_form.html",
        college=college,
        learner=learner,
        dropdowns=dropdowns,
        evidence_files=evidence_files,
        mode="edit",
    )

@learners_bp.route(
    "/college/<int:college_id>"
    "/learner/<int:learner_id>"
    "/evidence/<int:evidence_id>/download"
)
@login_required
def download_learner_evidence(
    college_id,
    learner_id,
    evidence_id,
):
    college = College.query.get_or_404(
        college_id
    )

    learner = Learner.query.filter_by(
        id=learner_id,
        college_id=college.id,
        is_deleted=False,
    ).first_or_404()

    permission = get_college_permission(
        college_id
    )

    if not permission["can_view"]:
        abort(403)

    evidence_file = (
        LearnerEvidenceFile.query.filter_by(
            id=evidence_id,
            learner_id=learner.id,
        ).first_or_404()
    )

    learner_folder = os.path.join(
        current_app.config[
            "EVIDENCE_UPLOAD_FOLDER"
        ],
        str(learner.id),
    )

    return send_from_directory(
        learner_folder,
        evidence_file.stored_filename,
        as_attachment=True,
        download_name=(
            evidence_file.original_filename
        ),
    )

@learners_bp.route(
    "/college/<int:college_id>"
    "/learner/<int:learner_id>"
    "/evidence/<int:evidence_id>/delete",
    methods=["POST"],
)
@login_required
def delete_learner_evidence(
    college_id,
    learner_id,
    evidence_id,
):
    college = College.query.get_or_404(
        college_id
    )

    learner = Learner.query.filter_by(
        id=learner_id,
        college_id=college.id,
        is_deleted=False,
    ).first_or_404()

    permission = get_college_permission(
        college_id
    )

    if not permission["can_edit"]:
        abort(403)

    evidence_file = (
        LearnerEvidenceFile.query.filter_by(
            id=evidence_id,
            learner_id=learner.id,
        ).first_or_404()
    )

    absolute_path = os.path.join(
        current_app.config[
            "EVIDENCE_UPLOAD_FOLDER"
        ],
        evidence_file.relative_path,
    )

    try:
        if os.path.isfile(absolute_path):
            os.remove(absolute_path)

        db.session.delete(evidence_file)
        db.session.commit()

        flash(
            "Evidence file deleted successfully.",
            "success",
        )

    except Exception:
        db.session.rollback()

        current_app.logger.exception(
            "Unable to delete learner evidence file"
        )

        flash(
            "Evidence file could not be deleted.",
            "danger",
        )

    return redirect(
        url_for(
            "learners.edit_learner",
            college_id=college.id,
            learner_id=learner.id,
        )
    )

# ---------------------------------------------------------
# Delete learner - soft delete
# URL: /learners/college/1/learner/10/delete
# ---------------------------------------------------------
@learners_bp.route("/college/<int:college_id>/learner/<int:learner_id>/delete", methods=["POST"])
@login_required
def delete_learner(college_id, learner_id):
    college = College.query.get_or_404(college_id)

    learner = Learner.query.filter_by(
        id=learner_id,
        college_id=college.id,
        is_deleted=False,
    ).first_or_404()

    permission = get_college_permission(college_id)

    if not permission["can_delete"]:
        abort(403)

    old_value = {
        "mobile_no": learner.mobile_no,
        "email_id": learner.email_id,
        "first_name": learner.first_name,
        "last_name": learner.last_name,
    }

    learner.is_deleted = True
    learner.updated_by = current_user.id

    db.session.commit()

    log_action(
        "DELETE_LEARNER",
        "learners",
        learner.id,
        old_value=old_value,
        new_value={"is_deleted": True},
    )

    flash("Learner deleted successfully.", "success")
    return redirect(url_for("learners.college_learners", college_id=college.id))

@learners_bp.route("/select-college")
@login_required
def select_college():
    """
    Shows colleges accessible to the current user.
    Admin can see all active colleges.
    Non-admin users see only mapped colleges.
    """

    if current_user.has_role("admin"):
        colleges = (
            College.query
            .filter_by(is_active=True)
            .order_by(College.institute_name)
            .all()
        )
    else:
        colleges = (
            College.query
            .join(UserCollegePermission, UserCollegePermission.college_id == College.id)
            .filter(
                UserCollegePermission.user_id == current_user.id,
                UserCollegePermission.can_view == True,
                College.is_active == True
            )
            .order_by(College.institute_name)
            .all()
        )

    return render_template(
        "learners/select_college.html",
        colleges=colleges
    )


@learners_bp.route(
    "/college/<int:college_id>/placement-bulk-update",
    methods=["GET"],
)
@login_required
def placement_bulk_update(college_id):
    college = College.query.get_or_404(college_id)

    if not can_placement_bulk_update(college.id):
        abort(403)

    batches = (
        PlacementBulkUpdateBatch.query
        .filter_by(
            college_id=college.id,
            created_by=current_user.id,
        )
        .order_by(PlacementBulkUpdateBatch.created_at.desc())
        .all()
    )

    return render_template(
        "learners/placement_bulk_update.html",
        college=college,
        batches=batches,
    )

@learners_bp.route(
    "/college/<int:college_id>/placement-bulk-update/create",
    methods=["POST"],
)
@login_required
def create_placement_update_template(college_id):
    college = College.query.get_or_404(college_id)

    if not can_placement_bulk_update(college.id):
        abort(403)

    learners = (
        Learner.query
        .filter_by(
            college_id=college.id,
            is_deleted=False,
        )
        .order_by(Learner.id)
        .all()
    )

    if not learners:
        flash("No learners found for this college.", "warning")
        return redirect(
            url_for(
                "learners.placement_bulk_update",
                college_id=college.id,
            )
        )

    batch = PlacementBulkUpdateBatch(
        college_id=college.id,
        created_by=current_user.id,
        status="template_created",
        total_records=len(learners),
    )

    db.session.add(batch)
    db.session.flush()

    excel_rows = []

    for excel_row_num, learner in enumerate(learners, start=2):
        snapshot_row = PlacementBulkUpdateRow(
            batch_id=batch.id,
            learner_id=learner.id,
            row_num=excel_row_num,

            original_mobile_no=learner.mobile_no,
            original_email_id=learner.email_id,
            original_first_name=learner.first_name,
            original_last_name=learner.last_name,

            course_completion_status=learner.course_completion_status,

            company_name=learner.company_name,
            sector=learner.sector,
            designation=learner.designation,
            job_location_district=learner.job_location_district,
            gross_income_per_month=learner.gross_income_per_month,
        )

        db.session.add(snapshot_row)

        excel_rows.append({
            "mobile_no": learner.mobile_no or "",
            "email_id": learner.email_id or "",
            "first_name": learner.first_name or "",
            "last_name": learner.last_name or "",
            "course_completion_status": (learner.course_completion_status or ""),
            "company_name": learner.company_name or "",
            "sector": learner.sector or "",
            "designation": learner.designation or "",
            "job_location_district": (
                learner.job_location_district or ""
            ),
            "gross_income_per_month": (
                learner.gross_income_per_month
                if learner.gross_income_per_month is not None
                else ""
            ),
        })

    output_dir = os.path.join(
        current_app.root_path,
        "..",
        "uploads",
        "placement_update_templates",
    )
    os.makedirs(output_dir, exist_ok=True)

    file_name = (
        f"placement_bulk_update_"
        f"college_{college.id}_batch_{batch.id}.xlsx"
    )

    file_path = os.path.join(output_dir, file_name)

    df = pd.DataFrame(
        excel_rows,
        columns=PLACEMENT_BULK_UPDATE_COLUMNS,
    )

    reference_data = pd.DataFrame({
        "course_completion_status": pd.Series(
            get_ordered_active_master_values(
                "course_completion_status"
            )
        ),
        "sector": pd.Series(
            get_ordered_active_master_values("sector")
        ),
        "job_location_district": pd.Series(
            get_ordered_active_master_values("district")
        ),
    })

    with pd.ExcelWriter(file_path, engine="openpyxl") as writer:
        df.to_excel(
            writer,
            sheet_name="Sheet1",
            index=False,
        )
        reference_data.to_excel(
            writer,
            sheet_name="Sheet2",
            index=False,
        )

    batch.stored_file_name = file_name
    batch.file_path = file_path

    db.session.commit()

    return redirect(
        url_for(
            "learners.placement_bulk_update_batch",
            batch_id=batch.id,
        )
    )

@learners_bp.route(
    "/placement-bulk-update/<int:batch_id>",
    methods=["GET"],
)
@login_required
def placement_bulk_update_batch(batch_id):
    batch = PlacementBulkUpdateBatch.query.get_or_404(batch_id)
    college = College.query.get_or_404(batch.college_id)

    if not can_placement_bulk_update(college.id):
        abort(403)

    rows = (
        PlacementBulkUpdateRow.query
        .filter_by(batch_id=batch.id)
        .order_by(PlacementBulkUpdateRow.row_num)
        .all()
    )

    return render_template(
        "learners/placement_bulk_update_batch.html",
        batch=batch,
        college=college,
        rows=rows,
    )

@learners_bp.route(
    "/placement-bulk-update/<int:batch_id>/template",
    methods=["GET"],
)
@login_required
def download_placement_update_template(batch_id):
    batch = PlacementBulkUpdateBatch.query.get_or_404(batch_id)
    college = College.query.get_or_404(batch.college_id)

    if not can_placement_bulk_update(college.id):
        abort(403)

    if not batch.file_path or not os.path.exists(batch.file_path):
        flash("Template file not found.", "danger")
        return redirect(
            url_for(
                "learners.placement_bulk_update_batch",
                batch_id=batch.id,
            )
        )

    return send_file(
        batch.file_path,
        as_attachment=True,
        download_name=batch.stored_file_name,
        mimetype=(
            "application/vnd.openxmlformats-officedocument."
            "spreadsheetml.sheet"
        ),
    )

@learners_bp.route(
    "/placement-bulk-update/<int:batch_id>/upload",
    methods=["POST"],
)
@login_required
def upload_placement_bulk_update(batch_id):
    batch = PlacementBulkUpdateBatch.query.get_or_404(batch_id)
    college = College.query.get_or_404(batch.college_id)

    if not can_placement_bulk_update(college.id):
        abort(403)

    file = request.files.get("bulk_file")

    if not file or not file.filename:
        flash("Please select an Excel file.", "danger")
        return redirect(
            url_for(
                "learners.placement_bulk_update_batch",
                batch_id=batch.id,
            )
        )

    if not file.filename.lower().endswith(".xlsx"):
        flash("Only .xlsx files are allowed.", "danger")
        return redirect(
            url_for(
                "learners.placement_bulk_update_batch",
                batch_id=batch.id,
            )
        )

    upload_dir = os.path.join(
        current_app.root_path,
        "..",
        "uploads",
        "placement_updates",
    )
    os.makedirs(upload_dir, exist_ok=True)

    stored_file_name = f"{uuid.uuid4()}_{file.filename}"
    file_path = os.path.join(upload_dir, stored_file_name)

    file.save(file_path)

    try:
        df = pd.read_excel(
            file_path,
            dtype={
                "mobile_no": str,
                "email_id": str,
                "first_name": str,
                "last_name": str,
            },
        )
    except Exception as exc:
        flash(f"Unable to read Excel file: {exc}", "danger")
        return redirect(
            url_for(
                "learners.placement_bulk_update_batch",
                batch_id=batch.id,
            )
        )

    missing_columns = [
        col
        for col in PLACEMENT_BULK_UPDATE_COLUMNS
        if col not in df.columns
    ]

    if missing_columns:
        flash(
            "Missing columns: " + ", ".join(missing_columns),
            "danger",
        )
        return redirect(
            url_for(
                "learners.placement_bulk_update_batch",
                batch_id=batch.id,
            )
        )

    batch.original_file_name = file.filename
    batch.stored_file_name = stored_file_name
    batch.file_path = file_path
    batch.status = "uploaded"

    db.session.commit()

    flash("File uploaded. Please validate it.", "success")

    return redirect(
        url_for(
            "learners.placement_bulk_update_batch",
            batch_id=batch.id,
        )
    )


BULK_UPLOAD_COLUMNS = [
    "mobile_no",
    "email_id",
    "trade_course",
    "batch_start_month",
    "batch_start_year",
    "batch_end_month",
    "batch_end_year",
    "first_name",
    "last_name",
    "gender",
    "date_of_birth",
    "educational_qualification",
    "marital_status",
    "work_experience",
    "annual_family_income",
]

PLACEMENT_BULK_UPDATE_COLUMNS = [
    "mobile_no",
    "email_id",
    "first_name",
    "last_name",
    "course_completion_status",
    "company_name",
    "sector",
    "designation",
    "job_location_district",
    "gross_income_per_month",
]


def can_bulk_upload(college_id):
    """
    Bulk upload allowed for:
    1. Admin
    2. Enrolment user with can_add permission for that college
    """

    if current_user.has_role("admin"):
        return True

    if not current_user.has_role("enrolment"):
        return False

    permission = UserCollegePermission.query.filter_by(
        user_id=current_user.id,
        college_id=college_id,
        can_add=True,
    ).first()

    return permission is not None

def can_placement_bulk_update(college_id):
    permission = get_college_permission(college_id)

    if not permission["can_view"]:
        return False

    if current_user.has_role("admin"):
        return True

    return (
        current_user.has_role("placement")
        and permission["can_edit"]
    )


def normalize_cell_value(value):
    """
    Converts NaN/blank values to None.
    Keeps actual values as clean strings unless numeric/date.
    """

    if pd.isna(value):
        return None

    if isinstance(value, str):
        value = value.strip()
        return value if value else None

    return value


def normalize_mobile(value):
    if value is None:
        return None

    value = str(value).strip()

    # Handles Excel values like 9876543210.0
    if value.endswith(".0"):
        value = value[:-2]

    return value or None


def normalize_email(value):
    if value is None:
        return None

    value = str(value).strip().lower()
    return value or None


def normalize_year(value):
    if value is None:
        return None

    value = str(value).strip()

    if value == "" or value.lower() == "nan":
        return None

    # Handles Excel values like 2025.0
    try:
        numeric_value = float(value)

        if numeric_value.is_integer():
            return int(numeric_value)
    except Exception:
        pass

    # Return original invalid value so validation can show an error
    return value


def normalize_date(value):
    if value is None:
        return None

    if isinstance(value, datetime):
        return value.date().isoformat()

    value = str(value).strip()

    # Accept YYYY-MM-DD directly
    try:
        parsed = pd.to_datetime(value, errors="coerce")
        if pd.isna(parsed):
            return value
        return parsed.date().isoformat()
    except Exception:
        return value


def get_ordered_active_master_values(master_key):
    master_type = MasterType.query.filter_by(
        master_key=master_key,
        is_active=True,
    ).first()

    if not master_type:
        return []

    options = (
        MasterOption.query
        .filter_by(
            master_type_id=master_type.id,
            is_active=True,
        )
        .order_by(
            MasterOption.display_order,
            MasterOption.option_label,
            MasterOption.option_value,
        )
        .all()
    )

    return [option.option_value for option in options]


def get_active_master_values(master_key):
    master_type = MasterType.query.filter_by(
        master_key=master_key,
        is_active=True,
    ).first()

    if not master_type:
        return set()

    options = MasterOption.query.filter_by(
        master_type_id=master_type.id,
        is_active=True,
    ).all()

    return {o.option_value for o in options}


def validate_bulk_row(row_data, existing_combos_in_file):
    """
    Validates one uploaded learner row.
    Returns list of errors.
    """

    errors = []

    mobile_no = row_data.get("mobile_no")
    email_id = row_data.get("email_id")
    
    first_name = row_data.get("first_name")
    gender = row_data.get("gender")
    trade_course = row_data.get("trade_course")
    batch_start_year = row_data.get("batch_start_year")
    batch_end_year = row_data.get("batch_end_year")

    if not mobile_no and not email_id:
        errors.append("Either mobile_no or email_id is required.")

    if not first_name:
        errors.append("first_name is required.")

    if not gender:
        errors.append("gender is required.")

    if not trade_course:
        errors.append("trade_course is required.")

    if mobile_no:
        if not str(mobile_no).isdigit() or len(str(mobile_no)) != 10:
            errors.append("mobile_no must be exactly 10 digits.")

    if email_id:
        if "@" not in email_id:
            errors.append("email_id must be valid and contain @.")

    if batch_start_year:
        if not isinstance(batch_start_year, int):
            errors.append("batch_start_year must be a valid 4-digit year.")
        elif batch_start_year < 1900 or batch_start_year > 2100:
            errors.append("batch_start_year must be between 1900 and 2100.")

    if batch_end_year:
        if not isinstance(batch_end_year, int):
            errors.append("batch_end_year must be a valid 4-digit year.")
        elif batch_end_year < 1900 or batch_end_year > 2100:
            errors.append("batch_end_year must be between 1900 and 2100.")

    combo = (
        mobile_no if mobile_no else "__NULL__",
        email_id if email_id else "__NULL__",
    )

    if combo in existing_combos_in_file:
        errors.append("Duplicate mobile_no + email_id combination found within uploaded file.")
    else:
        existing_combos_in_file.add(combo)

    existing = Learner.query.filter(
        Learner.mobile_no.is_(None) if mobile_no is None else Learner.mobile_no == mobile_no,
        Learner.email_id.is_(None) if email_id is None else Learner.email_id == email_id,
        Learner.is_deleted == False,
    ).first()

    if existing:
        errors.append("Learner with this mobile_no + email_id combination already exists in the system.")

    # Master validations
    master_field_map = {
        "trade_course": "trade_course",
        "gender": "gender",
        "educational_qualification": "qualification",
        "marital_status": "marital_status",
        "work_experience": "work_experience",
        "annual_family_income": "annual_family_income",
    }

    for upload_field, master_key in master_field_map.items():
        value = row_data.get(upload_field)

        if value:
            valid_values = get_active_master_values(master_key)

            if valid_values and value not in valid_values:
                errors.append(f"{upload_field} value '{value}' is not configured in master data.")

    return errors

@learners_bp.route("/college/<int:college_id>/bulk-upload/template")
@login_required
def download_bulk_template(college_id):
    college = College.query.get_or_404(college_id)

    if not can_bulk_upload(college.id):
        abort(403)

    template_path = os.path.join(
        current_app.root_path,
        "static",
        "templates",
        "bulk_upload_template.xlsx"
    )

    if not os.path.exists(template_path):
        flash("Bulk upload template file not found. Please contact admin.", "danger")
        return redirect(url_for("learners.bulk_upload", college_id=college.id))

    return send_file(
        template_path,
        as_attachment=True,
        download_name=f"bulk_upload_template_{college.id}.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

@learners_bp.route("/college/<int:college_id>/bulk-upload", methods=["GET", "POST"])
@login_required
def bulk_upload(college_id):
    college = College.query.get_or_404(college_id)

    if not can_bulk_upload(college.id):
        abort(403)

    if request.method == "POST":
        file = request.files.get("bulk_file")

        if not file:
            flash("Please select an Excel file.", "danger")
            return redirect(url_for("learners.bulk_upload", college_id=college.id))

        if not file.filename.endswith((".xlsx", ".xls")):
            flash("Only Excel files are allowed.", "danger")
            return redirect(url_for("learners.bulk_upload", college_id=college.id))

        upload_dir = os.path.join(current_app.root_path, "..", "uploads", "bulk")
        os.makedirs(upload_dir, exist_ok=True)

        stored_file_name = f"{uuid.uuid4()}_{file.filename}"
        file_path = os.path.join(upload_dir, stored_file_name)
        file.save(file_path)

        try:
            df = pd.read_excel(file_path)
        except Exception as e:
            flash(f"Unable to read Excel file: {str(e)}", "danger")
            return redirect(url_for("learners.bulk_upload", college_id=college.id))

        missing_columns = [col for col in BULK_UPLOAD_COLUMNS if col not in df.columns]

        if missing_columns:
            flash(
                "Missing columns in uploaded file: " + ", ".join(missing_columns),
                "danger",
            )
            return redirect(url_for("learners.bulk_upload", college_id=college.id))

        batch = BulkUploadBatch(
            college_id=college.id,
            uploaded_by=current_user.id,
            original_file_name=file.filename,
            stored_file_name=stored_file_name,
            file_path=file_path,
            status="uploaded",
            total_records=len(df),
            valid_records=0,
            invalid_records=0,
        )

        db.session.add(batch)
        db.session.commit()

        for index, row in df.iterrows():
            row_data = {}

            for col in BULK_UPLOAD_COLUMNS:
                value = normalize_cell_value(row.get(col))

                if col == "mobile_no":
                    value = normalize_mobile(value)

                if col == "email_id":
                    value = normalize_email(value)

                if col in ["batch_start_year", "batch_end_year"]:
                    value = normalize_year(value)

                if col == "date_of_birth":
                    value = normalize_date(value)

                row_data[col] = value

            upload_row = BulkUploadRow(
                batch_id=batch.id,
                row_num=index + 2,  # Excel row number, considering header row
                row_data=row_data,
                validation_status="pending",
                validation_errors=None,
                is_submitted=False,
            )

            db.session.add(upload_row)

        db.session.commit()

        log_action(
            "BULK_UPLOAD",
            "bulk_upload_batches",
            batch.id,
            new_value={
                "college_id": college.id,
                "file_name": file.filename,
                "total_records": len(df),
            },
        )

        flash("File uploaded successfully. Please validate the data.", "success")
        return redirect(url_for("learners.bulk_upload_new_data", batch_id=batch.id))

    batches = (
        BulkUploadBatch.query
        .filter_by(college_id=college.id)
        .order_by(BulkUploadBatch.created_at.desc())
        .all()
    )

    return render_template(
        "learners/bulk_upload.html",
        college=college,
        batches=batches,
    )

@learners_bp.route("/bulk/<int:batch_id>/new-data")
@login_required
def bulk_upload_new_data(batch_id):
    batch = BulkUploadBatch.query.get_or_404(batch_id)
    college = College.query.get_or_404(batch.college_id)

    if not can_bulk_upload(college.id):
        abort(403)

    rows = (
        BulkUploadRow.query
        .filter_by(batch_id=batch.id)
        .order_by(BulkUploadRow.row_num)
        .all()
    )

    return render_template(
        "learners/bulk_new_data.html",
        batch=batch,
        college=college,
        rows=rows,
        columns=BULK_UPLOAD_COLUMNS,
    )

@learners_bp.route("/bulk/<int:batch_id>/validate", methods=["POST"])
@login_required
def validate_bulk_upload(batch_id):
    batch = BulkUploadBatch.query.get_or_404(batch_id)
    college = College.query.get_or_404(batch.college_id)

    if not can_bulk_upload(college.id):
        abort(403)

    rows = BulkUploadRow.query.filter_by(batch_id=batch.id).all()

    valid_count = 0
    invalid_count = 0
    existing_combos_in_file = set()

    for row in rows:
        errors = validate_bulk_row(row.row_data, existing_combos_in_file)

        if errors:
            row.validation_status = "invalid"
            row.validation_errors = errors
            invalid_count += 1
        else:
            row.validation_status = "valid"
            row.validation_errors = None
            valid_count += 1

    batch.status = "validated"
    batch.valid_records = valid_count
    batch.invalid_records = invalid_count

    db.session.commit()

    log_action(
        "BULK_VALIDATE",
        "bulk_upload_batches",
        batch.id,
        new_value={
            "valid_records": valid_count,
            "invalid_records": invalid_count,
        },
    )

    flash("Bulk data validation completed.", "success")
    return redirect(url_for("learners.bulk_upload_new_data", batch_id=batch.id))

@learners_bp.route("/bulk/<int:batch_id>/submit", methods=["POST"])
@login_required
def submit_bulk_upload(batch_id):
    batch = BulkUploadBatch.query.get_or_404(batch_id)
    college = College.query.get_or_404(batch.college_id)

    if not can_bulk_upload(college.id):
        abort(403)

    if batch.status != "validated":
        flash("Please validate the uploaded data before submitting.", "danger")
        return redirect(url_for("learners.bulk_upload_new_data", batch_id=batch.id))

    if batch.invalid_records > 0:
        flash("Please fix invalid records before submitting.", "danger")
        return redirect(url_for("learners.bulk_upload_new_data", batch_id=batch.id))

    rows = BulkUploadRow.query.filter_by(
        batch_id=batch.id,
        validation_status="valid",
        is_submitted=False,
    ).all()

    inserted_count = 0

    for row in rows:
        data = row.row_data

        learner = Learner(
            college_id=college.id,

            mobile_no=data.get("mobile_no"),
            email_id=data.get("email_id"),

            trade_course=data.get("trade_course"),
            batch_start_month=data.get("batch_start_month"),
            batch_start_year=data.get("batch_start_year"),
            batch_end_month=data.get("batch_end_month"),
            batch_end_year=data.get("batch_end_year"),

            first_name=data.get("first_name"),
            last_name=data.get("last_name"),
            gender=data.get("gender"),
            date_of_birth=data.get("date_of_birth"),

            educational_qualification=data.get("educational_qualification"),
            marital_status=data.get("marital_status"),
            work_experience=data.get("work_experience"),
            annual_family_income=data.get("annual_family_income"),

            created_by=current_user.id,
            updated_by=current_user.id,
        )

        db.session.add(learner)
        row.is_submitted = True
        inserted_count += 1

    batch.status = "submitted"

    db.session.commit()

    log_action(
        "BULK_SUBMIT",
        "bulk_upload_batches",
        batch.id,
        new_value={
            "inserted_records": inserted_count,
            "college_id": college.id,
        },
    )

    flash(f"{inserted_count} learners inserted successfully.", "success")
    return redirect(url_for("learners.college_learners", college_id=college.id))

@learners_bp.route(
    "/placement-bulk-update/<int:batch_id>/validate",
    methods=["POST"],
)
@login_required
def validate_placement_bulk_update(batch_id):
    batch = PlacementBulkUpdateBatch.query.get_or_404(batch_id)
    college = College.query.get_or_404(batch.college_id)

    if not can_placement_bulk_update(college.id):
        abort(403)

    if not batch.file_path or not os.path.exists(batch.file_path):
        flash("Please upload the completed template first.", "danger")
        return redirect(
            url_for(
                "learners.placement_bulk_update_batch",
                batch_id=batch.id,
            )
        )

    try:
        df = pd.read_excel(
            batch.file_path,
            dtype={
                "mobile_no": str,
                "email_id": str,
                "first_name": str,
                "last_name": str,
            },
        )
    except Exception as exc:
        flash(f"Unable to read Excel file: {exc}", "danger")
        return redirect(
            url_for(
                "learners.placement_bulk_update_batch",
                batch_id=batch.id,
            )
        )

    expected_columns = PLACEMENT_BULK_UPDATE_COLUMNS

    missing_columns = [
        col for col in expected_columns
        if col not in df.columns
    ]

    if missing_columns:
        flash(
            "Missing columns: " + ", ".join(missing_columns),
            "danger",
        )
        return redirect(
            url_for(
                "learners.placement_bulk_update_batch",
                batch_id=batch.id,
            )
        )

    extra_columns = [
        col for col in df.columns
        if col not in expected_columns
    ]

    if extra_columns:
        flash(
            "Unexpected columns: " + ", ".join(extra_columns),
            "danger",
        )
        return redirect(
            url_for(
                "learners.placement_bulk_update_batch",
                batch_id=batch.id,
            )
        )

    snapshot_rows = (
        PlacementBulkUpdateRow.query
        .filter_by(batch_id=batch.id)
        .order_by(PlacementBulkUpdateRow.row_num)
        .all()
    )

    # Prevent adding or removing rows
    if len(df) != len(snapshot_rows):
        batch.status = "validation_failed"
        batch.valid_records = 0
        batch.invalid_records = abs(len(df) - len(snapshot_rows))

        db.session.commit()

        flash(
            (
                f"Row count mismatch. The downloaded template had "
                f"{len(snapshot_rows)} learner rows, but the uploaded "
                f"file contains {len(df)} rows. Adding or deleting rows "
                f"is not allowed."
            ),
            "danger",
        )

        return redirect(
            url_for(
                "learners.placement_bulk_update_batch",
                batch_id=batch.id,
            )
        )

    valid_course_statuses = get_active_master_values("course_completion_status")
    valid_sectors = get_active_master_values("sector")
    valid_districts = get_active_master_values("district")

    valid_count = 0
    invalid_count = 0

    for index, snapshot in enumerate(snapshot_rows):
        uploaded = df.iloc[index]
        errors = []

        uploaded_mobile = normalise_mobile_for_comparison(
            uploaded.get("mobile_no")
        )
        original_mobile = normalise_mobile_for_comparison(
            snapshot.original_mobile_no
        )

        uploaded_email = normalise_email_for_comparison(
            uploaded.get("email_id")
        )
        original_email = normalise_email_for_comparison(
            snapshot.original_email_id
        )

        uploaded_first_name = normalise_protected_value(
            uploaded.get("first_name")
        )
        original_first_name = normalise_protected_value(
            snapshot.original_first_name
        )

        uploaded_last_name = normalise_protected_value(
            uploaded.get("last_name")
        )
        original_last_name = normalise_protected_value(
            snapshot.original_last_name
        )

        if uploaded_mobile != original_mobile:
            errors.append(
                "Mobile No cannot be changed."
            )

        if uploaded_email != original_email:
            errors.append(
                "Email Id cannot be changed."
            )

        if uploaded_first_name != original_first_name:
            errors.append(
                "First Name cannot be changed."
            )

        if uploaded_last_name != original_last_name:
            errors.append(
                "Last Name cannot be changed."
            )

        course_completion_status = normalise_optional_text(
            uploaded.get("course_completion_status")
        )

        company_name = normalise_optional_text(
            uploaded.get("company_name")
        )
        sector = normalise_optional_text(
            uploaded.get("sector")
        )
        designation = normalise_optional_text(
            uploaded.get("designation")
        )
        district = normalise_optional_text(
            uploaded.get("job_location_district")
        )
        income = normalise_income(
            uploaded.get("gross_income_per_month")
        )

        dependent_placement_values = {
            "company_name": company_name,
            "sector": sector,
            "designation": designation,
            "job_location_district": district,
            "gross_income_per_month": income,
        }

        populated_dependent_fields = [
            field_name
            for field_name, field_value
            in dependent_placement_values.items()
            if field_value is not None
        ]

        if (
            course_completion_status is None
            and populated_dependent_fields
        ):
            errors.append(
                (
                    "When course_completion_status is blank, the "
                    "following fields must also be blank: "
                    + ", ".join(populated_dependent_fields)
                    + "."
                )
            )

        if ( course_completion_status and course_completion_status not in valid_course_statuses):
            errors.append(
                (
                    f"Course Completion Status "
                    f"'{course_completion_status}' is not configured "
                    f"in master data."
                )
            )

        if sector and sector not in valid_sectors:
            errors.append(
                f"Sector '{sector}' is not configured in master data."
            )

        if district and district not in valid_districts:
            errors.append(
                (
                    f"Job Location District '{district}' is not "
                    f"configured in district master data."
                )
            )

        if income is not None:
            if not isinstance(income, int):
                errors.append(
                    "Gross Income per Month must be a whole number."
                )
            elif income < 0:
                errors.append(
                    "Gross Income per Month cannot be negative."
                )

        snapshot.course_completion_status = course_completion_status
        snapshot.company_name = company_name
        snapshot.sector = sector
        snapshot.designation = designation
        snapshot.job_location_district = district

        snapshot.gross_income_per_month = (
            income if isinstance(income, int) else None
        )

        if errors:
            snapshot.validation_status = "invalid"
            snapshot.validation_errors = errors
            invalid_count += 1
        else:
            snapshot.validation_status = "valid"
            snapshot.validation_errors = None
            valid_count += 1

    batch.valid_records = valid_count
    batch.invalid_records = invalid_count
    batch.status = (
        "validated"
        if invalid_count == 0
        else "validation_failed"
    )

    db.session.commit()

    if invalid_count:
        flash(
            f"Validation completed with {invalid_count} invalid row(s).",
            "danger",
        )
    else:
        flash(
            f"All {valid_count} rows are valid.",
            "success",
        )

    return redirect(
        url_for(
            "learners.placement_bulk_update_batch",
            batch_id=batch.id,
        )
    )

@learners_bp.route(
    "/placement-bulk-update/<int:batch_id>/submit",
    methods=["POST"],
)
@login_required
def submit_placement_bulk_update(batch_id):
    batch = PlacementBulkUpdateBatch.query.get_or_404(batch_id)
    college = College.query.get_or_404(batch.college_id)

    if not can_placement_bulk_update(college.id):
        abort(403)

    if batch.status != "validated":
        flash(
            "Please validate the file successfully before submitting.",
            "danger",
        )
        return redirect(
            url_for(
                "learners.placement_bulk_update_batch",
                batch_id=batch.id,
            )
        )

    if batch.invalid_records > 0:
        flash(
            "Invalid rows must be corrected before submission.",
            "danger",
        )
        return redirect(
            url_for(
                "learners.placement_bulk_update_batch",
                batch_id=batch.id,
            )
        )

    rows = (
        PlacementBulkUpdateRow.query
        .filter_by(
            batch_id=batch.id,
            validation_status="valid",
            is_submitted=False,
        )
        .all()
    )

    updated_count = 0

    try:
        for row in rows:
            learner = Learner.query.filter_by(
                id=row.learner_id,
                college_id=college.id,
                is_deleted=False,
            ).first()

            if not learner:
                raise ValueError(
                    f"Learner for Excel row {row.row_num} no longer exists."
                )


            learner.course_completion_status = (row.course_completion_status)
            learner.company_name = row.company_name
            learner.sector = row.sector
            learner.designation = row.designation
            learner.job_location_district = (
                row.job_location_district
            )
            learner.gross_income_per_month = (
                row.gross_income_per_month
            )

            learner.updated_by = current_user.id

            row.is_submitted = True
            updated_count += 1

        batch.status = "submitted"
        batch.updated_records = updated_count

        db.session.commit()

    except Exception as exc:
        db.session.rollback()

        flash(
            f"Bulk update failed. No records were updated: {exc}",
            "danger",
        )

        return redirect(
            url_for(
                "learners.placement_bulk_update_batch",
                batch_id=batch.id,
            )
        )

    log_action(
        "PLACEMENT_BULK_UPDATE",
        "learners",
        None,
        new_value={
            "college_id": college.id,
            "batch_id": batch.id,
            "updated_records": updated_count,
        },
    )

    flash(
        f"{updated_count} learner records updated successfully.",
        "success",
    )

    return redirect(
        url_for(
            "learners.college_learners",
            college_id=college.id,
        )
    )

def get_int_or_none(field_name):
    value = request.form.get(field_name, "").strip()
    if value == "":
        return None
    try:
        return int(value)
    except ValueError:
        return None


def get_multi_values(field_name):
    values = request.form.getlist(field_name)
    cleaned = [v for v in values if v]
    return cleaned if cleaned else None

def normalise_protected_value(value):
    if value is None or pd.isna(value):
        return ""

    return str(value).strip()


def normalise_email_for_comparison(value):
    return normalise_protected_value(value).lower()


def normalise_mobile_for_comparison(value):
    value = normalise_protected_value(value)

    if value.endswith(".0"):
        value = value[:-2]

    return value


def normalise_optional_text(value):
    if value is None or pd.isna(value):
        return None

    value = str(value).strip()
    return value or None


def normalise_income(value):
    if value is None or pd.isna(value) or str(value).strip() == "":
        return None

    try:
        numeric_value = float(value)

        if not numeric_value.is_integer():
            return value

        return int(numeric_value)

    except (TypeError, ValueError):
        return value
