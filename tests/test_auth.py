"""Tests for officer accounts and permissions. Run:  python tests/test_auth.py   (or: pytest tests)"""
import datetime as dt
import os
import sys
import tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import auth
import database


def new_db():
    path = os.path.join(tempfile.mkdtemp(), "auth.db")
    return database.connect(path), path


def test_password_is_hashed_with_a_random_salt():
    a, b = auth.hash_password("correct horse"), auth.hash_password("correct horse")
    assert a != b and "correct horse" not in a
    assert auth.verify_password("correct horse", a) and auth.verify_password("correct horse", b)
    assert not auth.verify_password("correct horsf", a) and not auth.verify_password("", a)


def test_garbage_hash_never_verifies():
    for bad in ("", "x", "scrypt$1$2", "md5$abc$def", "scrypt$a$b$c$zz$yy"):
        assert auth.verify_password("anything", bad) is False


def test_plain_password_is_not_in_the_database_file():
    conn, path = new_db()
    auth.create_user(conn, "officer1", "S3cret-Phrase!", "officer")
    conn.close()
    assert b"S3cret-Phrase!" not in open(path, "rb").read()


def test_create_user_rules():
    conn, _ = new_db()
    for args in (("ab", "long-enough-1", "officer"), ("Bad Name!", "long-enough-1", "officer"),
                 ("goodname", "short", "officer"), ("goodname", "goodname", "officer"),
                 ("goodname", "long-enough-1", "superuser")):
        try:
            auth.create_user(conn, *args)
            raise AssertionError(f"expected ValueError for {args}")
        except ValueError:
            pass
    auth.create_user(conn, "goodname", "long-enough-1", "officer")
    try:
        auth.create_user(conn, "GOODNAME", "another-long-1", "officer")
        raise AssertionError("duplicate usernames must be rejected, whatever the case")
    except ValueError:
        pass


def test_login_works_and_username_is_case_insensitive():
    conn, _ = new_db()
    auth.create_user(conn, "Admin", "long-enough-1", "admin")
    user = auth.authenticate(conn, "ADMIN", "long-enough-1")
    assert user["username"] == "admin" and user["role"] == "admin" and "password_hash" not in user


def test_wrong_password_and_unknown_user_get_the_same_message():
    conn, _ = new_db()
    auth.create_user(conn, "officer1", "long-enough-1", "officer")
    messages = set()
    for name, pw in (("officer1", "wrong-password"), ("nobody", "long-enough-1"), ("", ""), (None, None)):
        try:
            auth.authenticate(conn, name, pw)
            raise AssertionError("login must fail")
        except auth.AuthError as e:
            messages.add(str(e))
    assert messages == {auth.GENERIC_ERROR}


def test_account_locks_after_repeated_failures_and_unlocks_later():
    conn, _ = new_db()
    auth.create_user(conn, "officer1", "long-enough-1", "officer")
    t0 = dt.datetime(2026, 10, 29, 9, 0, 0)
    for _ in range(auth.MAX_FAILED):
        try:
            auth.authenticate(conn, "officer1", "wrong-password", now=t0)
        except auth.AuthError:
            pass
    try:                                                    # even the right password is refused while locked
        auth.authenticate(conn, "officer1", "long-enough-1", now=t0 + dt.timedelta(minutes=1))
        raise AssertionError("account should be locked")
    except auth.AuthError as e:
        assert "Too many failed attempts" in str(e)
    later = t0 + dt.timedelta(minutes=auth.LOCK_MINUTES + 1)
    assert auth.authenticate(conn, "officer1", "long-enough-1", now=later)["username"] == "officer1"
    assert database.get_user(conn, "officer1")["failed_attempts"] == 0


def test_a_successful_login_resets_the_failure_count():
    conn, _ = new_db()
    auth.create_user(conn, "officer1", "long-enough-1", "officer")
    for _ in range(auth.MAX_FAILED - 1):
        try:
            auth.authenticate(conn, "officer1", "wrong-password")
        except auth.AuthError:
            pass
    auth.authenticate(conn, "officer1", "long-enough-1")
    assert database.get_user(conn, "officer1")["failed_attempts"] == 0


def test_deactivated_account_cannot_log_in():
    conn, _ = new_db()
    auth.create_user(conn, "officer1", "long-enough-1", "officer")
    database.update_user(conn, "officer1", active=0)
    try:
        auth.authenticate(conn, "officer1", "long-enough-1")
        raise AssertionError("deactivated accounts must not log in")
    except auth.AuthError:
        pass


def test_roles_and_permissions():
    officer, admin = {"role": "officer"}, {"role": "admin"}
    for perm in ("view", "review", "resolve"):
        assert auth.can(officer, perm) and auth.can(admin, perm)
    for perm in ("reset", "seed", "manage_users", "export", "audit"):
        assert not auth.can(officer, perm) and auth.can(admin, perm)
    assert not auth.can(None, "view") and not auth.can({}, "view") and not auth.can({"role": "hacker"}, "view")
    try:
        auth.require(officer, "reset")
        raise AssertionError("officers must not reset the database")
    except PermissionError:
        pass
    auth.require(admin, "reset")


def test_session_expiry():
    now = dt.datetime(2026, 10, 29, 12, 0, 0)
    fresh = (now - dt.timedelta(minutes=auth.SESSION_MINUTES - 1)).isoformat()
    stale = (now - dt.timedelta(minutes=auth.SESSION_MINUTES + 1)).isoformat()
    assert not auth.session_expired(fresh, now) and auth.session_expired(stale, now)


def test_long_and_unicode_passwords_work():
    conn, _ = new_db()
    pw = "pässwörd-密码-" + "x" * 200
    auth.create_user(conn, "officer1", pw, "officer")
    assert auth.authenticate(conn, "officer1", pw)["username"] == "officer1"


def test_create_user_script_demo_accounts_work_and_are_not_overwritten():
    import contextlib, io, re
    import create_user
    conn, path = new_db()
    conn.close()
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        assert create_user.main(["--demo", "--db", path]) == 0
    passwords = dict(re.findall(r"^(\w+) \([^)]*\): password (\S+)$", out.getvalue(), re.M))
    assert set(passwords) == {"admin", "officer", "crew"}
    conn = database.connect(path)
    assert auth.authenticate(conn, "admin", passwords["admin"])["role"] == "admin"
    assert auth.authenticate(conn, "officer", passwords["officer"])["role"] == "officer"
    crew = auth.authenticate(conn, "crew", passwords["crew"])
    assert crew["role"] == "crew" and crew["crew_id"] == "PW-1"
    again = io.StringIO()
    with contextlib.redirect_stdout(again):
        create_user.main(["--demo", "--db", path])
    assert "already exists" in again.getvalue() and "password" not in again.getvalue().replace("passwords are not", "")
    assert auth.authenticate(conn, "admin", passwords["admin"])                       # the old password still works


def test_reset_password_unlocks_and_replaces_the_old_password():
    conn, _ = new_db()
    auth.create_user(conn, "officer1", "old-password-1", "officer")
    for _ in range(auth.MAX_FAILED):
        try:
            auth.authenticate(conn, "officer1", "wrong-password")
        except auth.AuthError:
            pass
    database.update_user(conn, "officer1", active=0)
    auth.set_password(conn, "OFFICER1", "brand-new-pass-2")
    assert auth.authenticate(conn, "officer1", "brand-new-pass-2")["username"] == "officer1"
    try:
        auth.authenticate(conn, "officer1", "old-password-1")
        raise AssertionError("the old password must stop working")
    except auth.AuthError:
        pass
    assert database.audit_entries(conn)[0]["action"] == "password_reset"
    for bad in (("nobody", "long-enough-1"), ("officer1", "short"), ("officer1", "officer1")):
        try:
            auth.set_password(conn, *bad)
            raise AssertionError(f"expected ValueError for {bad}")
        except ValueError:
            pass


def test_reset_command_line(monkeypatch=None):
    import create_user, io, contextlib
    conn, path = new_db()
    auth.create_user(conn, "admin", "old-password-1", "admin")
    conn.close()
    answers = iter(["new-password-12", "new-password-12"])
    real = create_user.getpass.getpass
    create_user.getpass.getpass = lambda prompt="": next(answers)
    try:
        with contextlib.redirect_stdout(io.StringIO()) as out:
            assert create_user.main(["--reset", "admin", "--db", path]) == 0
            assert create_user.main(["--reset", "ghost", "--db", path]) == 1
    finally:
        create_user.getpass.getpass = real
    assert auth.authenticate(database.connect(path), "admin", "new-password-12")["role"] == "admin"


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    failed = 0
    for name, fn in tests:
        try:
            fn(); print("PASS", name)
        except Exception as e:
            failed += 1; print("FAIL", name, type(e).__name__, e)
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
