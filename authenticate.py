import secrets
from werkzeug.security import generate_password_hash, check_password_hash
from database import get_connection


def create_user(email, password):
    """Creates a new user with a hashed password. Returns the new user's id,
    or None if the email is already taken."""
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT id FROM users WHERE email = %s", (email,))
    existing = cursor.fetchone()
    if existing:
        cursor.close()
        conn.close()
        return None

    password_hash = generate_password_hash(password)
    cursor.execute(
        "INSERT INTO users (email, password_hash) VALUES (%s, %s)",
        (email, password_hash)
    )
    conn.commit()
    user_id = cursor.lastrowid
    cursor.close()
    conn.close()
    return user_id

def find_or_create_google_user(email):
    """Finds a user by email, or creates a new passwordless account for
    them if this is their first time signing in with Google."""
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
    user = cursor.fetchone()

    if user:
        cursor.close()
        conn.close()
        return user

    cursor.execute(
        "INSERT INTO users (email, password_hash, auth_provider) VALUES (%s, %s, %s)",
        (email, None, "google")
    )
    conn.commit()
    user_id = cursor.lastrowid
    cursor.close()
    conn.close()

    return {"id": user_id, "email": email, "is_paid": 0}

def verify_user(email, password):
    """Checks email/password against the database. Returns the user row
    if correct, or None if email doesn't exist, has no password (Google
    account), or the password is wrong."""
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
    user = cursor.fetchone()
    cursor.close()
    conn.close()

    if not user:
        return None
    if not user["password_hash"]:
        return None
    if not check_password_hash(user["password_hash"], password):
        return None
    return user


def create_session(user_id):
    """Generates a random token and stores it in the sessions table, so
    the frontend can include this token on future requests instead of
    resending the password every time. Sessions now persist across
    server restarts since they live in the database."""
    token = secrets.token_hex(32)

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO sessions (token, user_id) VALUES (%s, %s)",
        (token, user_id)
    )
    conn.commit()
    cursor.close()
    conn.close()

    return token


def get_user_from_token(token):
    """Looks up which user a session token belongs to, by checking the
    sessions table in the database instead of an in-memory dictionary."""
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT user_id FROM sessions WHERE token = %s", (token,))
    session = cursor.fetchone()

    if not session:
        cursor.close()
        conn.close()
        return None

    cursor.execute("SELECT * FROM users WHERE id = %s", (session["user_id"],))
    user = cursor.fetchone()
    cursor.close()
    conn.close()
    return user