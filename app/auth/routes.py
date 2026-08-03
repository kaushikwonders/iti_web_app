from datetime import datetime, date
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import ( check_password_hash, generate_password_hash,)
from app.extensions import db
from app.models import User
from app.utils import log_action

auth_bp = Blueprint("auth", __name__, template_folder="../templates")

@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("admin.dashboard"))
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = User.query.filter_by(email=email).first()
        if not user or not check_password_hash(user.password_hash, password):
            flash("Invalid email or password", "danger")
            return render_template("auth/login.html")
        if not user.is_active:
            flash("Your account is inactive", "danger")
            return render_template("auth/login.html")
        if user.expiry_date and user.expiry_date < date.today():
            flash("Your account has expired", "danger")
            return render_template("auth/login.html")
        login_user(user)
        user.last_login_at = datetime.utcnow()
        db.session.commit()
        log_action("LOGIN", "users", user.id)
        return redirect(url_for("admin.dashboard" if user.has_role("admin") else "learners.select_college"))
    return render_template("auth/login.html")

@auth_bp.route("/logout")
@login_required
def logout():
    log_action("LOGOUT", "users", current_user.id)
    logout_user()
    flash("Logged out successfully", "success")
    return redirect(url_for("auth.login"))

@auth_bp.route(
    "/change-password",
    methods=["GET", "POST"],
)
@login_required
def change_password():
    if request.method == "POST":
        current_password = request.form.get(
            "current_password",
            "",
        )

        new_password = request.form.get(
            "new_password",
            "",
        )

        confirm_password = request.form.get(
            "confirm_password",
            "",
        )

        if not current_password:
            flash(
                "Current password is required.",
                "danger",
            )
            return render_template(
                "auth/change_password.html"
            )

        if not new_password:
            flash(
                "New password is required.",
                "danger",
            )
            return render_template(
                "auth/change_password.html"
            )

        if not confirm_password:
            flash(
                "Please confirm the new password.",
                "danger",
            )
            return render_template(
                "auth/change_password.html"
            )

        if not check_password_hash(
            current_user.password_hash,
            current_password,
        ):
            flash(
                "Current password is incorrect.",
                "danger",
            )
            return render_template(
                "auth/change_password.html"
            )

        if new_password != confirm_password:
            flash(
                "New password and confirmation do not match.",
                "danger",
            )
            return render_template(
                "auth/change_password.html"
            )

        if len(new_password) < 8:
            flash(
                "New password must contain at least 8 characters.",
                "danger",
            )
            return render_template(
                "auth/change_password.html"
            )

        if check_password_hash(
            current_user.password_hash,
            new_password,
        ):
            flash(
                "New password cannot be the same as "
                "your current password.",
                "danger",
            )
            return render_template(
                "auth/change_password.html"
            )

        user_id = current_user.id

        try:
            current_user.password_hash = (
                generate_password_hash(
                    new_password
                )
            )

            db.session.commit()

            log_action(
                "CHANGE_PASSWORD",
                "users",
                user_id,
                new_value={
                    "change_type": "self_service",
                },
            )

        except Exception:
            db.session.rollback()

            flash(
                "Password could not be changed. "
                "Please try again.",
                "danger",
            )

            return render_template(
                "auth/change_password.html"
            )

        # Require login again with the new password.
        logout_user()

        flash(
            "Password changed successfully. "
            "Please log in using your new password.",
            "success",
        )

        return redirect(
            url_for("auth.login")
        )

    return render_template(
        "auth/change_password.html"
    )
