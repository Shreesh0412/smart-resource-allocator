"""
scripts/create_admin.py  — S10 Admin Bootstrap Script

Run this once to create the first admin account in MongoDB.
Never hardcode credentials — this script prompts for them interactively.

Requirements:
    pip install pymongo python-dotenv werkzeug
"""

import os
import sys
import getpass
from pathlib import Path

# Allow imports from the project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()

from pymongo import MongoClient
import certifi
from werkzeug.security import generate_password_hash


def main():
    print("=" * 50)
    print("  Saarthi — Admin Account Bootstrap")
    print("=" * 50)
    print()

    mongo_uri = os.environ.get("MONGO_URI", "mongodb://localhost:27017/")
    db_name   = os.environ.get("DB_NAME",   "volunteer_platform")

    client = MongoClient(mongo_uri, tlsCAFile=certifi.where())
    db     = client[db_name]

    existing = db.admins.count_documents({})
    if existing > 0:
        print(f"⚠️  {existing} admin account(s) already exist in the database.")
        proceed = input("Create another anyway? [y/N]: ").strip().lower()
        if proceed != "y":
            print("Aborted.")
            return

    print("Enter details for the new admin account:")
    print()

    name = input("Full name: ").strip()
    if not name:
        print("Error: Name cannot be empty.")
        sys.exit(1)

    email = input("Email address: ").strip().lower()
    if not email or "@" not in email:
        print("Error: Invalid email address.")
        sys.exit(1)

    if db.admins.find_one({"email": email}):
        print(f"Error: An admin with email '{email}' already exists.")
        sys.exit(1)

    password = getpass.getpass("Password (hidden): ")
    if len(password) < 10:
        print("Error: Password must be at least 10 characters.")
        sys.exit(1)

    confirm = getpass.getpass("Confirm password (hidden): ")
    if password != confirm:
        print("Error: Passwords do not match.")
        sys.exit(1)

    from datetime import datetime
    admin_doc = {
        "type":          "admin",
        "name":          name,
        "email":         email,
        "password_hash": generate_password_hash(password),
        "status":        "active",
        "created_at":    datetime.utcnow().isoformat(),
        "updated_at":    datetime.utcnow().isoformat(),
    }

    result = db.admins.insert_one(admin_doc)
    print()
    print(f"✅ Admin account created successfully!")
    print(f"   ID:    {result.inserted_id}")
    print(f"   Name:  {name}")
    print(f"   Email: {email}")
    print()
    print("You can now log in via the admin API endpoints.")


if __name__ == "__main__":
    main()
