"""Small CLI for toggling admin status on users, invoked via `make set-admin`
/ `make list-users` rather than exposed through the app itself -- admin
status controls things like triggering an on-demand catalog harvest, and
there's no in-app UI for granting it (avoids a chicken-and-egg bootstrap
problem of needing an admin to create the first admin).

Uses plain sqlite3 directly rather than the app's async SQLAlchemy session,
since this is a one-shot synchronous CLI command, not part of the running app.
"""

import sqlite3
import sys

from app.config import get_settings


def _connect() -> sqlite3.Connection:
    return sqlite3.connect(get_settings().database_path)


def list_users() -> None:
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT id, zenodo_user_id, zenodo_env, display_name, is_admin FROM users ORDER BY id"
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        print("No users yet -- log in via 'Connect with Zenodo' first.")
        return

    for user_id, zenodo_user_id, zenodo_env, display_name, is_admin in rows:
        admin_flag = "admin" if is_admin else "-"
        print(f"id={user_id}\tzenodo_user_id={zenodo_user_id}\tenv={zenodo_env}\t{admin_flag}\t{display_name!r}")


def set_admin(user_id: int, value: bool) -> None:
    conn = _connect()
    try:
        cur = conn.execute("UPDATE users SET is_admin = ? WHERE id = ?", (1 if value else 0, user_id))
        conn.commit()
    finally:
        conn.close()

    if cur.rowcount == 0:
        print(f"No user with id={user_id}. Run 'make list-users' to see valid ids.", file=sys.stderr)
        sys.exit(1)
    print(f"user id={user_id}: is_admin = {value}")


def _usage() -> None:
    print("Usage:", file=sys.stderr)
    print("  python -m app.scripts.manage_users list", file=sys.stderr)
    print("  python -m app.scripts.manage_users set-admin <id> <true|false>", file=sys.stderr)
    sys.exit(2)


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "list":
        list_users()
    elif len(sys.argv) == 4 and sys.argv[1] == "set-admin":
        set_admin(int(sys.argv[2]), sys.argv[3].strip().lower() in ("1", "true", "yes", "y"))
    else:
        _usage()
