"""Create officer or admin accounts for the officer portal.

    python create_user.py            ask for a username, role and password
    python create_user.py --demo     create 'admin', 'officer' and 'crew' (crew PW-1) with random passwords, shown once
    python create_user.py --reset admin    choose a new password for an existing account (also unlocks it)

Passwords are stored only as salted hashes, so a lost password cannot be recovered: make a new account instead.
"""
import argparse
import getpass
import secrets
import sys

import auth
import database


def reset_password(conn, username):
    username = username.strip().lower()
    if not database.get_user(conn, username):
        print(f"There is no account called '{username}'.")
        return 1
    password = getpass.getpass("New password (8+ characters): ")
    if password != getpass.getpass("Repeat password: "):
        print("The passwords do not match.")
        return 1
    try:
        auth.set_password(conn, username, password)
    except ValueError as err:
        print(f"Could not change the password: {err}")
        return 1
    print(f"New password set for {username}. The account is unlocked and active.")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="Create CivicSense officer accounts")
    parser.add_argument("--demo", action="store_true", help="create 'admin' and 'officer' with random passwords")
    parser.add_argument("--reset", metavar="USERNAME", help="set a new password for an existing account")
    parser.add_argument("--db", default=database.DEFAULT_PATH, help="database file (default: civicsense.db)")
    args = parser.parse_args(argv)
    conn = database.connect(args.db)
    if args.reset:
        return reset_password(conn, args.reset)
    if args.demo:
        created = False
        for name, role, crew_id in (("admin", "admin", None), ("officer", "officer", None), ("crew", "crew", "PW-1")):
            if database.get_user(conn, name):
                print(f"{name}: already exists, left unchanged")
                continue
            password = secrets.token_urlsafe(9)
            auth.create_user(conn, name, password, role, crew_id=crew_id)
            print(f"{name} ({role}{' ' + crew_id if crew_id else ''}): password {password}")
            created = True
        if created:
            print("Write these down now: passwords are not stored and cannot be shown again.")
        return 0
    username = input("Username: ").strip()
    role = input("Role (officer, admin or crew) [officer]: ").strip() or "officer"
    crew_id = input("Crew id, for example PW-1: ").strip() if role == "crew" else None
    password = getpass.getpass("Password (8+ characters): ")
    if password != getpass.getpass("Repeat password: "):
        print("The passwords do not match.")
        return 1
    try:
        auth.create_user(conn, username, password, role, crew_id=crew_id)
    except ValueError as err:
        print(f"Could not create the account: {err}")
        return 1
    print(f"Created {username.lower()} ({role}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
