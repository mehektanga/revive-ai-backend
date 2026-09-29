import sys
import os

# Ensure backend root is in sys.path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.database.session import SessionLocal, engine, Base
from app.simulator.generator import seed_database

if __name__ == "__main__":
    print("Initializing database tables...")
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed_database(db, 10500)
        print("Database seeding completed successfully.")
    finally:
        db.close()
