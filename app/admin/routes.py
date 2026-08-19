from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required
from werkzeug.security import generate_password_hash
from app.extensions import db
from app.models import Role, User, College, UserCollegePermission, MasterType, MasterOption, AuditLog
from app.utils import admin_required, log_action

admin_bp = Blueprint("admin", __name__, template_folder="../templates")

def get_master_options(master_key):
    master_type = MasterType.query.filter_by(
        master_key=master_key,
        is_active=True
    ).first()

    if not master_type:
        return []

    return (
        MasterOption.query
        .filter_by(
            master_type_id=master_type.id,
            is_active=True
        )
        .order_by(MasterOption.display_order, MasterOption.option_label)
        .all()
    )

@admin_bp.route("/dashboard")
@login_required
@admin_required
def dashboard():
    return render_template("admin/dashboard.html",
        users=User.query.count(), colleges=College.query.count(), logs=AuditLog.query.count())

@admin_bp.route("/users", methods=["GET", "POST"])
@login_required
@admin_required
def users():
    roles = Role.query.all()
    if request.method == "POST":
        user = User(
            full_name=request.form["full_name"],
            email=request.form["email"].strip().lower(),
            password_hash=generate_password_hash(request.form["password"]),
            role_id=int(request.form["role_id"]),
            start_date=request.form.get("start_date") or None,
            expiry_date=request.form.get("expiry_date") or None,
            is_active=bool(request.form.get("is_active")),
        )
        db.session.add(user)
        db.session.commit()
        log_action("CREATE_USER", "users", user.id, new_value={"email": user.email})
        flash("User created", "success")
        return redirect(url_for("admin.users"))
    return render_template("admin/users.html", users=User.query.order_by(User.id.desc()).all(), roles=roles)

@admin_bp.route("/users/<int:user_id>/edit", methods=["GET", "POST"])
@login_required
@admin_required
def edit_user(user_id):
    user = User.query.get_or_404(user_id)
    roles = Role.query.all()
    if request.method == "POST":
        old = {"full_name": user.full_name, "email": user.email, "role_id": user.role_id, "is_active": user.is_active}
        user.full_name = request.form["full_name"]
        user.email = request.form["email"].strip().lower()
        user.role_id = int(request.form["role_id"])
        user.start_date = request.form.get("start_date") or None
        user.expiry_date = request.form.get("expiry_date") or None
        user.is_active = bool(request.form.get("is_active"))

        new_password = request.form.get( "password","",)
        confirm_password = request.form.get("confirm_password", "",)
        password_was_reset = False

        if new_password:
            if len(new_password) < 8:
                flash(
                    "New password must contain at least "
                    "8 characters.",
                    "danger",
                )

                return render_template(
                    "admin/user_edit.html",
                    user=user,
                    roles=roles,
                )

            if new_password != confirm_password:
                flash(
                    "New password and confirmation "
                    "do not match.",
                    "danger",
                )

                return render_template(
                    "admin/user_edit.html",
                    user=user,
                    roles=roles,
                )

            user.password_hash = generate_password_hash(
                new_password
            )

            password_was_reset = True

        db.session.commit()
        log_action("UPDATE_USER", "users", user.id, old_value=old, new_value={"email": user.email, "password_reset": password_was_reset,},)
        flash("User updated", "success")
        return redirect(url_for("admin.users"))
    return render_template("admin/user_edit.html", user=user, roles=roles)

@admin_bp.route("/colleges", methods=["GET", "POST"])
@login_required
@admin_required
def colleges():
    if request.method == "POST":
        c = College(
            institute_name=request.form["institute_name"],
            state=request.form["state"],
            district=request.form["district"],
            college_code=request.form.get("college_code"),
            is_active=bool(request.form.get("is_active")),
        )

        db.session.add(c)
        db.session.commit()

        log_action(
            "CREATE_COLLEGE",
            "colleges",
            c.id,
            new_value={"name": c.institute_name}
        )

        flash("College created", "success")
        return redirect(url_for("admin.colleges"))

    # This must be outside POST block, before render_template
    state_options = get_master_options("state")

    search_filters = {
        "institute": request.args.get("institute", "").strip(),
        "state": request.args.get("state", "").strip(),
        "district": request.args.get("district", "").strip(),
        "code": request.args.get("code", "").strip(),
    }

    colleges_query = College.query

    if search_filters["institute"]:
        colleges_query = colleges_query.filter(
            College.institute_name.ilike(
                f'%{search_filters["institute"]}%'
            )
        )

    if search_filters["state"]:
        colleges_query = colleges_query.filter(
            College.state.ilike(f'%{search_filters["state"]}%')
        )

    if search_filters["district"]:
        colleges_query = colleges_query.filter(
            College.district.ilike(
                f'%{search_filters["district"]}%'
            )
        )

    if search_filters["code"]:
        colleges_query = colleges_query.filter(
            College.college_code.ilike(
                f'%{search_filters["code"]}%'
            )
        )

    colleges_list = (
        colleges_query
        .order_by(College.institute_name)
        .all()
    )

    return render_template(
        "admin/colleges.html",
        colleges=colleges_list,
        state_options=state_options,
        search_filters=search_filters,
    )

@admin_bp.route("/colleges/<int:college_id>/edit", methods=["GET", "POST"])
@login_required
@admin_required
def edit_college(college_id):
    c = College.query.get_or_404(college_id)

    if request.method == "POST":
        old = {
            "institute_name": c.institute_name,
            "state": c.state,
            "district": c.district,
        }

        c.institute_name = request.form["institute_name"]
        c.state = request.form["state"]
        c.district = request.form["district"]
        c.college_code = request.form.get("college_code")
        c.is_active = bool(request.form.get("is_active"))

        db.session.commit()

        log_action(
            "UPDATE_COLLEGE",
            "colleges",
            c.id,
            old_value=old,
            new_value={"name": c.institute_name}
        )

        flash("College updated", "success")
        return redirect(url_for("admin.colleges"))

    state_options = get_master_options("state")

    return render_template(
        "admin/college_edit.html",
        college=c,
        state_options=state_options,
    )

@admin_bp.route("/permissions", methods=["GET", "POST"])
@login_required
@admin_required
def permissions():
    users = (
        User.query
        .filter(User.is_active == True)
        .order_by(User.full_name)
        .all()
    )
    colleges = (
        College.query
        .filter_by(is_active=True)
        .order_by(College.institute_name)
        .all()
    )
    if request.method == "POST":
        user_id = int(request.form["user_id"])
        college_id = int(request.form["college_id"])
        perm = UserCollegePermission.query.filter_by(user_id=user_id, college_id=college_id).first()
        if not perm:
            perm = UserCollegePermission(user_id=user_id, college_id=college_id)
            db.session.add(perm)
        perm.can_view = bool(request.form.get("can_view"))
        perm.can_add = bool(request.form.get("can_add"))
        perm.can_edit = bool(request.form.get("can_edit"))
        perm.can_delete = bool(request.form.get("can_delete"))
        db.session.commit()
        log_action("ASSIGN_PERMISSION", "user_college_permissions", perm.id)
        flash("Permission saved", "success")
        return redirect(url_for("admin.permissions"))
    search_filters = {
        "user": request.args.get("user", "").strip(),
        "college": request.args.get("college", "").strip(),
    }

    permissions_query = (
        UserCollegePermission.query
        .join(User, UserCollegePermission.user_id == User.id)
        .join(College, UserCollegePermission.college_id == College.id)
    )

    if search_filters["user"]:
        user_pattern = f'%{search_filters["user"]}%'
        permissions_query = permissions_query.filter(
            User.full_name.ilike(user_pattern)
            | User.email.ilike(user_pattern)
        )

    if search_filters["college"]:
        college_pattern = f'%{search_filters["college"]}%'
        permissions_query = permissions_query.filter(
            College.institute_name.ilike(college_pattern)
            | College.college_code.ilike(college_pattern)
        )

    perms = (
        permissions_query
        .order_by(UserCollegePermission.id.desc())
        .all()
    )

    return render_template(
        "admin/permissions.html",
        users=users,
        colleges=colleges,
        perms=perms,
        search_filters=search_filters,
    )

@admin_bp.route("/masters")
@login_required
@admin_required
def masters():
    master_types = (
        MasterType.query
        .order_by(MasterType.master_name)
        .all()
    )

    return render_template(
        "admin/masters.html",
        master_types=master_types
    )
@admin_bp.route("/masters/create", methods=["GET", "POST"])
@login_required
@admin_required
def create_master_type():
    if request.method == "POST":
        master_name = request.form.get("master_name", "").strip()
        master_key = request.form.get("master_key", "").strip()
        description = request.form.get("description", "").strip()

        if not master_name or not master_key:
            flash("Master name and master key are required.", "danger")
            return redirect(url_for("admin.create_master_type"))

        existing = MasterType.query.filter_by(master_key=master_key).first()

        if existing:
            flash("Master key already exists.", "danger")
            return redirect(url_for("admin.create_master_type"))

        master_type = MasterType(
            master_name=master_name,
            master_key=master_key,
            description=description,
            is_active=True
        )

        db.session.add(master_type)
        db.session.commit()

        log_action(
            "CREATE_MASTER_TYPE",
            "master_types",
            master_type.id,
            new_value={
                "master_name": master_name,
                "master_key": master_key
            }
        )

        flash("Master type created successfully.", "success")
        return redirect(url_for("admin.masters"))

    return render_template("admin/master_type_form.html")

@admin_bp.route("/masters/<master_key>")
@login_required
@admin_required
def master_options(master_key):
    master_type = MasterType.query.filter_by(master_key=master_key).first_or_404()

    options = (
        MasterOption.query
        .filter_by(master_type_id=master_type.id)
        .order_by(MasterOption.display_order, MasterOption.option_value)
        .all()
    )

    return render_template(
        "admin/master_options.html",
        master_type=master_type,
        options=options
    )

@admin_bp.route("/masters/<master_key>/options/create", methods=["GET", "POST"])
@login_required
@admin_required
def create_master_option(master_key):
    master_type = MasterType.query.filter_by(master_key=master_key).first_or_404()

    # Load parent options only when this master depends on another master.
    # Currently: District depends on State.
    parent_options = []

    if master_type.master_key == "district":
        state_master = MasterType.query.filter_by(master_key="state").first()

        if state_master:
            parent_options = (
                MasterOption.query
                .filter_by(master_type_id=state_master.id, is_active=True)
                .order_by(MasterOption.display_order, MasterOption.option_label)
                .all()
            )

    if request.method == "POST":
        option_value = request.form.get("option_value", "").strip()
        option_label = request.form.get("option_label", "").strip()
        display_order = request.form.get("display_order", 0)

        # Only district requires parent state
        parent_option_id = request.form.get("parent_option_id") or None

        if not option_value:
            flash("Option value is required.", "danger")
            return redirect(
                url_for("admin.create_master_option", master_key=master_key)
            )

        if master_type.master_key == "district" and not parent_option_id:
            flash("Please select State for the District.", "danger")
            return redirect(
                url_for("admin.create_master_option", master_key=master_key)
            )

        try:
            display_order = int(display_order)
        except ValueError:
            display_order = 0

        # Duplicate check
        # For normal masters: duplicate is checked within same master.
        # For district: same district name may exist under different states,
        # so duplicate is checked within same master + same parent state.
        duplicate_query = MasterOption.query.filter(
            MasterOption.master_type_id == master_type.id,
            MasterOption.option_value == option_value
        )

        if master_type.master_key == "district":
            duplicate_query = duplicate_query.filter(
                MasterOption.parent_option_id == parent_option_id
            )

        existing = duplicate_query.first()

        if existing:
            if master_type.master_key == "district":
                flash("This district already exists under the selected state.", "danger")
            else:
                flash("This option already exists for the selected master.", "danger")

            return redirect(
                url_for("admin.create_master_option", master_key=master_key)
            )

        option = MasterOption(
            master_type_id=master_type.id,
            parent_option_id=parent_option_id,
            option_value=option_value,
            option_label=option_label or option_value,
            display_order=display_order,
            is_active=True
        )

        db.session.add(option)
        db.session.commit()

        log_action(
            "CREATE_MASTER_OPTION",
            "master_options",
            option.id,
            new_value={
                "master_key": master_key,
                "parent_option_id": parent_option_id,
                "option_value": option_value,
                "option_label": option.option_label,
                "display_order": display_order,
                "is_active": True
            }
        )

        flash("Master option added successfully.", "success")

        return redirect(
            url_for("admin.master_options", master_key=master_key)
        )

    return render_template(
        "admin/master_option_form.html",
        master_type=master_type,
        option=None,
        parent_options=parent_options
    )

@admin_bp.route("/masters/options/<int:option_id>/edit", methods=["GET", "POST"])
@login_required
@admin_required
def edit_master_option(option_id):
    option = MasterOption.query.get_or_404(option_id)
    master_type = option.master_type

    # Load parent options only when this master depends on another master.
    # Currently: District depends on State.
    parent_options = []

    if master_type.master_key == "district":
        state_master = MasterType.query.filter_by(master_key="state").first()

        if state_master:
            parent_options = (
                MasterOption.query
                .filter_by(master_type_id=state_master.id, is_active=True)
                .order_by(MasterOption.display_order, MasterOption.option_label)
                .all()
            )

    if request.method == "POST":
        old_value = {
            "parent_option_id": option.parent_option_id,
            "option_value": option.option_value,
            "option_label": option.option_label,
            "display_order": option.display_order,
            "is_active": option.is_active
        }

        option_value = request.form.get("option_value", "").strip()
        option_label = request.form.get("option_label", "").strip()
        display_order = request.form.get("display_order", 0)
        is_active = bool(request.form.get("is_active"))

        # Only district requires parent state
        parent_option_id = request.form.get("parent_option_id") or None

        if not option_value:
            flash("Option value is required.", "danger")
            return redirect(
                url_for("admin.edit_master_option", option_id=option.id)
            )

        if master_type.master_key == "district" and not parent_option_id:
            flash("Please select State for the District.", "danger")
            return redirect(
                url_for("admin.edit_master_option", option_id=option.id)
            )

        try:
            display_order = int(display_order)
        except ValueError:
            display_order = 0

        # Duplicate check
        # For normal masters: duplicate is checked within same master.
        # For district: same district name may exist under different states,
        # so duplicate is checked within same master + same parent state.
        duplicate_query = MasterOption.query.filter(
            MasterOption.master_type_id == master_type.id,
            MasterOption.option_value == option_value,
            MasterOption.id != option.id
        )

        if master_type.master_key == "district":
            duplicate_query = duplicate_query.filter(
                MasterOption.parent_option_id == parent_option_id
            )

        duplicate = duplicate_query.first()

        if duplicate:
            if master_type.master_key == "district":
                flash("Another district with this value already exists under the selected state.", "danger")
            else:
                flash("Another option with this value already exists.", "danger")

            return redirect(
                url_for("admin.edit_master_option", option_id=option.id)
            )

        option.parent_option_id = parent_option_id
        option.option_value = option_value
        option.option_label = option_label or option_value
        option.display_order = display_order
        option.is_active = is_active

        db.session.commit()

        log_action(
            "UPDATE_MASTER_OPTION",
            "master_options",
            option.id,
            old_value=old_value,
            new_value={
                "parent_option_id": option.parent_option_id,
                "option_value": option.option_value,
                "option_label": option.option_label,
                "display_order": option.display_order,
                "is_active": option.is_active
            }
        )

        flash("Master option updated successfully.", "success")

        return redirect(
            url_for("admin.master_options", master_key=master_type.master_key)
        )

    return render_template(
        "admin/master_option_form.html",
        master_type=master_type,
        option=option,
        parent_options=parent_options
    )

@admin_bp.route("/masters/options/<int:option_id>/delete", methods=["POST"])
@login_required
@admin_required
def delete_master_option(option_id):
    option = MasterOption.query.get_or_404(option_id)
    master_type = option.master_type

    old_value = {
        "option_value": option.option_value,
        "option_label": option.option_label,
        "is_active": option.is_active
    }

    option.is_active = False
    db.session.commit()

    log_action(
        "DELETE_MASTER_OPTION",
        "master_options",
        option.id,
        old_value=old_value,
        new_value={
            "is_active": False
        }
    )

    flash("Master option deactivated successfully.", "success")
    return redirect(url_for("admin.master_options", master_key=master_type.master_key))


@admin_bp.route("/audit-logs")
@login_required
@admin_required
def audit_logs():
    logs = AuditLog.query.order_by(AuditLog.created_at.desc()).limit(200).all()
    return render_template("admin/audit_logs.html", logs=logs)

@admin_bp.route("/api/districts")
@login_required
def get_districts_by_state():
    state_value = request.args.get("state", "").strip()

    if not state_value:
        return {"districts": []}

    state_master = MasterType.query.filter_by(
        master_key="state",
        is_active=True
    ).first()

    district_master = MasterType.query.filter_by(
        master_key="district",
        is_active=True
    ).first()

    if not state_master or not district_master:
        return {"districts": []}

    state_option = MasterOption.query.filter_by(
        master_type_id=state_master.id,
        option_value=state_value,
        is_active=True
    ).first()

    if not state_option:
        return {"districts": []}

    districts = (
        MasterOption.query
        .filter_by(
            master_type_id=district_master.id,
            parent_option_id=state_option.id,
            is_active=True
        )
        .order_by(MasterOption.display_order, MasterOption.option_label)
        .all()
    )

    return {
        "districts": [
            {
                "value": d.option_value,
                "label": d.option_label or d.option_value
            }
            for d in districts
        ]
    }