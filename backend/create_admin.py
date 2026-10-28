"""Create a knowledge admin account interactively using backend Supabase access."""
from __future__ import annotations

import getpass
import re
import sys

from app.services.admin_auth import hash_password, supabase_admin_client


def main() -> int:
    email = input("Admin email: ").strip().lower()
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email) or len(email) > 254:
        print("Enter a valid email address.")
        return 1
    password = getpass.getpass("New password (minimum 14 characters): ")
    confirmation = getpass.getpass("Confirm password: ")
    if len(password) < 14:
        print("Password must contain at least 14 characters.")
        return 1
    if password != confirmation:
        print("Passwords do not match.")
        return 1
    try:
        supabase_admin_client().table("admin_users").insert({
            "email": email,
            "password_hash": hash_password(password),
            "is_active": True,
        }).execute()
    except Exception as exc:
        print(f"Could not create admin account ({type(exc).__name__}). Check backend configuration and the admin_users table.")
        return 1
    print(f"Admin account created for {email}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
