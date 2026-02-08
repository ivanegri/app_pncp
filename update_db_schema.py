from app import create_app, db
from sqlalchemy import text

app = create_app()

def update_schema():
    with app.app_context():
        # Check if columns exist
        inspector = db.inspect(db.engine)
        columns = [col['name'] for col in inspector.get_columns('users')]
        
        if 'role' not in columns:
            print("Adding 'role' column...")
            with db.engine.connect() as conn:
                conn.execute(text("ALTER TABLE users ADD COLUMN role VARCHAR(20) DEFAULT 'user'"))
                conn.commit()
        else:
            print("'role' column already exists.")
            
        if 'tier' not in columns:
            print("Adding 'tier' column...")
            with db.engine.connect() as conn:
                conn.execute(text("ALTER TABLE users ADD COLUMN tier VARCHAR(20) DEFAULT 'free'"))
                conn.commit()
        else:
            print("'tier' column already exists.")

        print("Schema update complete.")

if __name__ == "__main__":
    update_schema()
