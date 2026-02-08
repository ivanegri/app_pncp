from app import create_app, db
from app.models import User
import sys

app = create_app()

def make_admin(email):
    with app.app_context():
        user = User.query.filter_by(email=email).first()
        if user:
            user.role = 'admin'
            user.tier = 'full'
            db.session.commit()
            print(f"User {email} is now an Admin (and Full tier).")
        else:
            print(f"User {email} not found.")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python make_admin.py <email>")
    else:
        make_admin(sys.argv[1])
