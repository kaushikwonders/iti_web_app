from datetime import date
from werkzeug.security import generate_password_hash
from app import create_app
from app.extensions import db
from app.models import Role, User

app = create_app()

with app.app_context():
    db.create_all()
    for role_name, description in [("admin", "Admin team user"), ("enrolment", "Enrolment team user"), ("placement", "Placement team user")]:
        if not Role.query.filter_by(role_name=role_name).first():
            db.session.add(Role(role_name=role_name, description=description))
    db.session.commit()
    admin_role = Role.query.filter_by(role_name="admin").first()
    user = User.query.filter_by(email="admin@example.com").first()
    if not user:
        user = User(full_name="System Admin", email="admin@example.com", password_hash=generate_password_hash("Admin@123"), role_id=admin_role.id, start_date=date.today(), is_active=True)
        db.session.add(user)
        db.session.commit()
        print("Created admin@example.com / Admin@123")
    else:
        print("Admin user already exists")
