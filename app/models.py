from datetime import datetime
from flask_login import UserMixin
from app.extensions import db, login_manager


class Role(db.Model):
    __tablename__ = "roles"
    id = db.Column(db.Integer, primary_key=True)
    role_name = db.Column(db.String(50), unique=True, nullable=False)
    description = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class User(UserMixin, db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(150), nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role_id = db.Column(db.Integer, db.ForeignKey("roles.id"), nullable=False)
    start_date = db.Column(db.Date)
    expiry_date = db.Column(db.Date)
    is_active = db.Column(db.Boolean, default=True)
    last_login_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, onupdate=datetime.utcnow)

    role = db.relationship("Role")

    def has_role(self, role_name):
        return self.role and self.role.role_name == role_name


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


class College(db.Model):
    __tablename__ = "colleges"
    id = db.Column(db.Integer, primary_key=True)
    institute_name = db.Column(db.String(255), nullable=False)
    state = db.Column(db.String(100), nullable=False)
    district = db.Column(db.String(100), nullable=False)
    college_code = db.Column(db.String(100))
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, onupdate=datetime.utcnow)


class UserCollegePermission(db.Model):
    __tablename__ = "user_college_permissions"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    college_id = db.Column(db.Integer, db.ForeignKey("colleges.id"), nullable=False)
    can_view = db.Column(db.Boolean, default=True)
    can_add = db.Column(db.Boolean, default=False)
    can_edit = db.Column(db.Boolean, default=False)
    can_delete = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, onupdate=datetime.utcnow)
    user = db.relationship("User")
    college = db.relationship("College")


class MasterType(db.Model):
    __tablename__ = "master_types"
    id = db.Column(db.Integer, primary_key=True)
    master_key = db.Column(db.String(150), unique=True, nullable=False)
    master_name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.String(255))
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, onupdate=datetime.utcnow)


class MasterOption(db.Model):
    __tablename__ = "master_options"
    id = db.Column(db.Integer, primary_key=True)
    master_type_id = db.Column(db.Integer, db.ForeignKey("master_types.id"), nullable=False)
    parent_option_id = db.Column(db.Integer, db.ForeignKey("master_options.id"), nullable=True)
    option_value = db.Column(db.String(255), nullable=False)
    option_label = db.Column(db.String(255))
    display_order = db.Column(db.Integer, default=0)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, onupdate=datetime.utcnow)
    master_type = db.relationship("MasterType")
    parent = db.relationship("MasterOption", remote_side=[id], backref="children")


class FieldConfig(db.Model):
    __tablename__ = "field_config"
    id = db.Column(db.Integer, primary_key=True)
    field_label = db.Column(db.String(255), nullable=False)
    db_column_name = db.Column(db.String(150), unique=True, nullable=False)
    field_type = db.Column(db.Enum('text','number','decimal','date','email','mobile','dropdown','textarea','file','boolean'), default='text')
    master_key = db.Column(db.String(150))
    is_required = db.Column(db.Boolean, default=False)
    visible_to_admin = db.Column(db.Boolean, default=True)
    editable_by_admin = db.Column(db.Boolean, default=True)
    visible_to_enrolment = db.Column(db.Boolean, default=True)
    editable_by_enrolment = db.Column(db.Boolean, default=False)
    visible_to_placement = db.Column(db.Boolean, default=True)
    editable_by_placement = db.Column(db.Boolean, default=False)
    display_order = db.Column(db.Integer, default=0)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, onupdate=datetime.utcnow)


class Learner(db.Model):
    __tablename__ = "learners"
    id = db.Column(db.BigInteger, primary_key=True)
    college_id = db.Column(db.Integer, db.ForeignKey("colleges.id"), nullable=False)
    mobile_no = db.Column(db.String(15), nullable=True)
    email_id = db.Column(db.String(150), nullable=True)
    first_name = db.Column(db.String(150))
    last_name = db.Column(db.String(150))
    gender = db.Column(db.String(50))
    date_of_birth = db.Column(db.Date)
    trade_course = db.Column(db.String(255))
    batch_start_month = db.Column(db.String(50))
    batch_start_year = db.Column(db.Integer)
    batch_end_month = db.Column(db.String(50))
    batch_end_year = db.Column(db.Integer)
    educational_qualification = db.Column(db.String(150))
    marital_status = db.Column(db.String(100))
    work_experience = db.Column(db.String(100))
    annual_family_income = db.Column(db.String(100))
    course_completion_status = db.Column(db.String(150))
    company_name = db.Column(db.String(255))
    sector = db.Column(db.String(255))
    designation = db.Column(db.String(255))
    job_location_district = db.Column(db.String(150))
    monthly_salary = db.Column(db.Numeric(12, 2))
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    updated_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    is_deleted = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, server_default=db.func.now(),onupdate=db.func.now())
    ladder_current_step = db.Column(db.Integer)
    ladder_future_step = db.Column(db.Integer)
    status_after_3_months = db.Column(db.String(150))
    company_name_3_months = db.Column(db.String(255))
    designation_3_months = db.Column(db.String(255))
    gross_income_3_months = db.Column(db.Integer)
    sector_3_months = db.Column(db.String(255))

    status_after_6_months = db.Column(db.String(150))
    company_name_6_months = db.Column(db.String(255))
    designation_6_months = db.Column(db.String(255))
    gross_income_6_months = db.Column(db.Integer)
    sector_6_months = db.Column(db.String(255))

    project_phase = db.Column(db.String(255))
    cits_cts = db.Column(db.String(100))
    project = db.Column(db.String(255))
    phase = db.Column(db.String(255))

    working_days_per_week = db.Column(db.Integer)
    working_hours_per_day = db.Column(db.Integer)
    evidence_type = db.Column(db.JSON)
    evidence_drive_link = db.Column(db.Text)

    apprenticeship_duration_months = db.Column(db.Integer)
    registered_on_apprenticeship_portal = db.Column(db.String(100))

    self_employment_type = db.Column(db.String(150))

    job_type_looking_for = db.Column(db.String(150))
    preferred_work_start_time = db.Column(db.String(150))

    reason_not_interested_working = db.Column(db.JSON)

    higher_education_course = db.Column(db.String(150))

    dropout_reason = db.Column(db.String(150))
    job_category = db.Column(db.String(150))
    gross_income_per_month = db.Column(db.Integer)
    employer_offerings = db.Column(db.JSON)

    business_establishment_year = db.Column(db.Integer)
    business_description = db.Column(db.Text)

    green_or_technology_related = db.Column(db.String(100))
    workplace_location = db.Column(db.String(150))
    business_registration_type = db.Column(db.String(255))
    uses_digital_platforms_for_marketing = db.Column(db.String(100))

    number_of_paid_employees = db.Column(db.Integer)
    income_happiness_score = db.Column(db.String(50))

    business_conditions = db.Column(db.JSON)

    gig_work_nature = db.Column(db.JSON)
    gig_platforms_used = db.Column(db.JSON)
    other_gig_platforms = db.Column(db.Text)

    receives_wages_or_profit_share = db.Column(db.String(100))

    permanent_address_state = db.Column(db.String(150))
    permanent_address_district = db.Column(db.String(150))
    parent_guardian_name = db.Column(db.String(255))
    parent_guardian_contact_no = db.Column(db.String(15))

    contactable = db.Column(db.String(10))
    not_contactable_reason = db.Column(db.String(255))
    remarks = db.Column(db.Text)

    college = db.relationship("College", backref="learners")

    evidence_files = db.relationship(
    "LearnerEvidenceFile",
    backref="learner",
    lazy="dynamic",
    cascade="all, delete-orphan",
    order_by="LearnerEvidenceFile.sequence_no",
)


class BulkUploadBatch(db.Model):
    __tablename__ = "bulk_upload_batches"
    id = db.Column(db.BigInteger, primary_key=True)
    college_id = db.Column(db.Integer, db.ForeignKey("colleges.id"), nullable=False)
    uploaded_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    original_file_name = db.Column(db.String(255))
    stored_file_name = db.Column(db.String(255))
    file_path = db.Column(db.String(500))
    status = db.Column(db.Enum('uploaded','validated','ready','submitted','failed'), default='uploaded')
    total_records = db.Column(db.Integer, default=0)
    valid_records = db.Column(db.Integer, default=0)
    invalid_records = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, onupdate=datetime.utcnow)
    college = db.relationship("College")


class BulkUploadRow(db.Model):
    __tablename__ = "bulk_upload_rows"
    id = db.Column(db.BigInteger, primary_key=True)
    batch_id = db.Column(db.BigInteger, db.ForeignKey("bulk_upload_batches.id"), nullable=False)
    row_num = db.Column(db.Integer, nullable=False)
    row_data = db.Column(db.JSON, nullable=False)
    validation_status = db.Column(db.Enum('pending','valid','invalid'), default='pending')
    validation_errors = db.Column(db.JSON)
    is_submitted = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, onupdate=datetime.utcnow)
    batch = db.relationship("BulkUploadBatch", backref="rows")


class AuditLog(db.Model):
    __tablename__ = "audit_logs"
    id = db.Column(db.BigInteger, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    action_type = db.Column(db.String(100), nullable=False)
    entity_type = db.Column(db.String(100))
    entity_id = db.Column(db.BigInteger)
    old_value = db.Column(db.JSON)
    new_value = db.Column(db.JSON)
    remarks = db.Column(db.Text)
    ip_address = db.Column(db.String(50))
    user_agent = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user = db.relationship("User")

class PlacementBulkUpdateBatch(db.Model):
    __tablename__ = "placement_bulk_update_batches"

    id = db.Column(db.Integer, primary_key=True)
    college_id = db.Column(
        db.Integer,
        db.ForeignKey("colleges.id"),
        nullable=False,
    )
    created_by = db.Column(
        db.Integer,
        db.ForeignKey("users.id"),
        nullable=False,
    )

    original_file_name = db.Column(db.String(255))
    stored_file_name = db.Column(db.String(255))
    file_path = db.Column(db.String(500))

    status = db.Column(
        db.String(50),
        nullable=False,
        default="template_created",
    )

    total_records = db.Column(db.Integer, default=0)
    valid_records = db.Column(db.Integer, default=0)
    invalid_records = db.Column(db.Integer, default=0)
    updated_records = db.Column(db.Integer, default=0)

    created_at = db.Column(
        db.DateTime,
        server_default=db.func.now(),
    )
    updated_at = db.Column(
        db.DateTime,
        server_default=db.func.now(),
        onupdate=db.func.now(),
    )


class PlacementBulkUpdateRow(db.Model):
    __tablename__ = "placement_bulk_update_rows"

    id = db.Column(db.Integer, primary_key=True)

    batch_id = db.Column(
        db.Integer,
        db.ForeignKey(
            "placement_bulk_update_batches.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )

    learner_id = db.Column(
        db.Integer,
        db.ForeignKey("learners.id"),
        nullable=False,
    )

    row_num = db.Column(db.Integer, nullable=False)

    original_mobile_no = db.Column(db.String(15))
    original_email_id = db.Column(db.String(150))
    original_first_name = db.Column(db.String(150))
    original_last_name = db.Column(db.String(150))
    course_completion_status = db.Column(db.String(150))

    company_name = db.Column(db.String(255))
    sector = db.Column(db.String(255))
    designation = db.Column(db.String(255))
    job_location_district = db.Column(db.String(255))
    gross_income_per_month = db.Column(db.Integer)

    validation_status = db.Column(db.String(30))
    validation_errors = db.Column(db.JSON)
    is_submitted = db.Column(db.Boolean, default=False)

    created_at = db.Column(
        db.DateTime,
        server_default=db.func.now(),
    )
    updated_at = db.Column(
        db.DateTime,
        server_default=db.func.now(),
        onupdate=db.func.now(),
    )

class LearnerEvidenceFile(db.Model):
    __tablename__ = "learner_evidence_files"

    id = db.Column(db.BigInteger, primary_key=True)

    learner_id = db.Column(
        db.BigInteger,
        db.ForeignKey("learners.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    uploaded_by = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    sequence_no = db.Column(
        db.Integer,
        nullable=False,
    )

    original_filename = db.Column(
        db.String(255),
        nullable=False,
    )

    stored_filename = db.Column(
        db.String(500),
        nullable=False,
    )

    relative_path = db.Column(
        db.String(1000),
        nullable=False,
    )

    file_extension = db.Column(db.String(30))
    mime_type = db.Column(db.String(150))
    file_size = db.Column(db.BigInteger)

    created_at = db.Column(
        db.DateTime,
        nullable=False,
        server_default=db.func.now(),
    )

    __table_args__ = (
        db.UniqueConstraint(
            "learner_id",
            "sequence_no",
            name="uq_learner_evidence_sequence",
        ),
    )