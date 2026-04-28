from __future__ import annotations

import json
import os
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import mysql.connector

from security_utils import (
    hash_password,
    password_hash_needs_upgrade,
    validate_password_strength,
    verify_password,
)


BASE_DIR = Path(__file__).resolve().parent
DB_CONFIG_FILE = BASE_DIR / "db_config.json"
LEGACY_USERS_FILE = BASE_DIR / "users.json"
LEGACY_API_KEY_FILE = BASE_DIR / "api_key.txt"
LEGACY_SYSTEM_PROMPT_FILE = BASE_DIR / "system_prompt.txt"
LEGACY_USAGE_FILE = BASE_DIR / "usage_logs.csv"
DB_HOST_ENV = "COGNISTUDY_DB_HOST"
DB_PORT_ENV = "COGNISTUDY_DB_PORT"
DB_USER_ENV = "COGNISTUDY_DB_USER"
DB_PASSWORD_ENV = "COGNISTUDY_DB_PASSWORD"
DB_NAME_ENV = "COGNISTUDY_DB_NAME"
ADMIN_FULLNAME_ENV = "COGNISTUDY_ADMIN_FULLNAME"
ADMIN_EMAIL_ENV = "COGNISTUDY_ADMIN_EMAIL"
ADMIN_PASSWORD_ENV = "COGNISTUDY_ADMIN_PASSWORD"
ALLOW_INSECURE_SECRET_STORAGE_ENV = "COGNISTUDY_ALLOW_INSECURE_SECRET_STORAGE"

DEFAULT_SYSTEM_PROMPT = (
    "You are the CogniStudy Neural Engine. Convert uploads into concise study material."
)

DEFAULT_ADMIN_FULLNAME = "Admin"
DEFAULT_USERS: list[dict[str, Any]] = []

DEFAULT_DB_CONFIG = {
    "host": "127.0.0.1",
    "port": 3306,
    "user": "root",
    "password": "",
    "database": "cognistudi",
}

DAYS_OF_WEEK = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
MIGRATION_FLAG = "legacy_data_migrated_v1"
SCHEMA_VERSION = "1"


def env_flag_enabled(env_name: str) -> bool:
    return os.getenv(env_name, "").strip().lower() in {"1", "true", "yes", "on"}


def insecure_secret_storage_allowed() -> bool:
    return env_flag_enabled(ALLOW_INSECURE_SECRET_STORAGE_ENV)


def build_secret_storage_error(secret_env_name: str) -> str:
    return (
        "Persistent secret storage is disabled. "
        f"Set {secret_env_name} as an environment variable, or set "
        f"{ALLOW_INSECURE_SECRET_STORAGE_ENV}=true to allow plaintext secret storage."
    )


def load_admin_bootstrap_config() -> tuple[str, str, str]:
    admin_fullname = os.getenv(ADMIN_FULLNAME_ENV, "").strip() or DEFAULT_ADMIN_FULLNAME
    admin_email = os.getenv(ADMIN_EMAIL_ENV, "").strip().lower()
    admin_password = os.getenv(ADMIN_PASSWORD_ENV, "")
    return admin_fullname, admin_email, admin_password


def require_admin_bootstrap_config() -> tuple[str, str, str]:
    admin_fullname, admin_email, admin_password = load_admin_bootstrap_config()
    if not admin_email or "@" not in admin_email or "." not in admin_email:
        raise RuntimeError(
            f"No admin account exists yet. Set a valid {ADMIN_EMAIL_ENV} before the first public startup."
        )

    is_valid_password, password_error = validate_password_strength(admin_password)
    if not is_valid_password:
        raise RuntimeError(
            f"Set a stronger {ADMIN_PASSWORD_ENV} before the first public startup. {password_error}"
        )

    return admin_fullname, admin_email, admin_password


def load_db_config() -> dict[str, Any]:
    config = DEFAULT_DB_CONFIG.copy()

    if DB_CONFIG_FILE.exists():
        try:
            file_config = json.loads(DB_CONFIG_FILE.read_text(encoding="utf-8"))
            if isinstance(file_config, dict):
                config.update(file_config)
        except (OSError, json.JSONDecodeError):
            pass

    config["host"] = os.getenv(DB_HOST_ENV, str(config.get("host", "127.0.0.1")))
    config["port"] = int(os.getenv(DB_PORT_ENV, str(config.get("port", 3306))))
    config["user"] = os.getenv(DB_USER_ENV, str(config.get("user", "root")))
    config["password"] = os.getenv(DB_PASSWORD_ENV, str(config.get("password", "")))
    config["database"] = os.getenv(DB_NAME_ENV, str(config.get("database", "cognistudi")))
    return config


def get_connection(include_database: bool = True) -> mysql.connector.MySQLConnection:
    config = load_db_config()
    connection_kwargs: dict[str, Any] = {
        "host": config["host"],
        "port": config["port"],
        "user": config["user"],
        "password": config["password"],
    }
    if include_database:
        connection_kwargs["database"] = config["database"]
    return mysql.connector.connect(**connection_kwargs)


def initialize_database() -> None:
    config = load_db_config()

    with get_connection(include_database=False) as server_connection:
        with server_connection.cursor() as cursor:
            cursor.execute(
                f"CREATE DATABASE IF NOT EXISTS `{config['database']}` "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
        server_connection.commit()

    ddl_statements = [
        """
        CREATE TABLE IF NOT EXISTS users (
            id INT AUTO_INCREMENT PRIMARY KEY,
            fullname VARCHAR(150) NOT NULL,
            email VARCHAR(190) NOT NULL,
            password_hash VARCHAR(255) NOT NULL,
            role VARCHAR(20) NOT NULL DEFAULT 'user',
            plan VARCHAR(50) NOT NULL DEFAULT 'Free',
            created_at DATE NOT NULL,
            UNIQUE KEY uq_users_fullname (fullname),
            UNIQUE KEY uq_users_email (email)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """,
        """
        CREATE TABLE IF NOT EXISTS usage_logs (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT NULL,
            activity_type VARCHAR(50) NOT NULL DEFAULT 'general',
            source VARCHAR(100) NOT NULL DEFAULT 'system',
            weekday CHAR(3) NOT NULL,
            tokens INT NOT NULL,
            created_at DATETIME NOT NULL,
            CONSTRAINT fk_usage_user
                FOREIGN KEY (user_id) REFERENCES users(id)
                ON DELETE SET NULL
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """,
        """
        CREATE TABLE IF NOT EXISTS app_settings (
            setting_key VARCHAR(100) PRIMARY KEY,
            setting_value MEDIUMTEXT NOT NULL,
            updated_at DATETIME NOT NULL
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """,
        """
        CREATE TABLE IF NOT EXISTS study_modules (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT NOT NULL,
            file_name VARCHAR(255) NOT NULL,
            subject VARCHAR(100) NOT NULL DEFAULT 'General',
            tokens_used INT NOT NULL DEFAULT 0,
            created_at DATETIME NOT NULL,
            CONSTRAINT fk_module_user
                FOREIGN KEY (user_id) REFERENCES users(id)
                ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """,
        """
        CREATE TABLE IF NOT EXISTS audit_logs (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT NULL,
            actor_name VARCHAR(150) NOT NULL,
            actor_role VARCHAR(20) NOT NULL,
            action VARCHAR(100) NOT NULL,
            details TEXT NOT NULL,
            created_at DATETIME NOT NULL,
            CONSTRAINT fk_audit_user
                FOREIGN KEY (user_id) REFERENCES users(id)
                ON DELETE SET NULL
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """,
    ]

    with get_connection() as connection:
        with connection.cursor() as cursor:
            for statement in ddl_statements:
                cursor.execute(statement)
            cursor.execute(
                """
                SELECT CHARACTER_MAXIMUM_LENGTH
                FROM information_schema.columns
                WHERE table_schema = DATABASE()
                  AND table_name = 'users'
                  AND column_name = 'password_hash'
                """
            )
            password_hash_length_row = cursor.fetchone()
            current_hash_length = int(password_hash_length_row[0]) if password_hash_length_row and password_hash_length_row[0] else 0
            if current_hash_length < 255:
                cursor.execute(
                    """
                    ALTER TABLE users
                    MODIFY COLUMN password_hash VARCHAR(255) NOT NULL
                    """
                )
        connection.commit()

    seed_defaults()
    migrate_legacy_data()
    ensure_admin_account()


def seed_defaults() -> None:
    if count_rows("users") == 0:
        for user in read_legacy_users():
            upsert_user(user)

    if not load_setting("system_prompt"):
        prompt = read_legacy_text(LEGACY_SYSTEM_PROMPT_FILE) or DEFAULT_SYSTEM_PROMPT
        save_setting("system_prompt", prompt)

    if insecure_secret_storage_allowed() and load_setting("api_key") is None:
        save_setting("api_key", read_legacy_text(LEGACY_API_KEY_FILE))

    save_setting("schema_version", SCHEMA_VERSION)


def migrate_legacy_data() -> None:
    if load_setting(MIGRATION_FLAG) == "1":
        return

    if count_rows("usage_logs") == 0 and LEGACY_USAGE_FILE.exists():
        try:
            usage_frame = pd.read_csv(LEGACY_USAGE_FILE)
        except Exception:
            usage_frame = pd.DataFrame(columns=["Day", "Tokens"])

        if {"Day", "Tokens"}.issubset(usage_frame.columns):
            with get_connection() as connection:
                with connection.cursor() as cursor:
                    for index, row in usage_frame.fillna(0).iterrows():
                        weekday = str(row["Day"]).strip()[:3].title()
                        if weekday not in DAYS_OF_WEEK:
                            continue
                        tokens = int(row["Tokens"])
                        created_at = datetime.now().replace(
                            hour=9,
                            minute=0,
                            second=0,
                            microsecond=0,
                        )
                        created_at = created_at.replace(day=min(index + 1, 28))
                        cursor.execute(
                            """
                            INSERT INTO usage_logs (
                                user_id, activity_type, source, weekday, tokens, created_at
                            )
                            VALUES (%s, %s, %s, %s, %s, %s)
                            """,
                            (None, "legacy_import", "usage_logs.csv", weekday, tokens, created_at),
                        )
                connection.commit()

    save_setting(MIGRATION_FLAG, "1")


def count_rows(table_name: str) -> int:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
            row = cursor.fetchone()
    return int(row[0]) if row else 0


def read_legacy_users() -> list[dict[str, Any]]:
    if not LEGACY_USERS_FILE.exists():
        return [normalize_user(user) for user in DEFAULT_USERS]

    try:
        raw_users = json.loads(LEGACY_USERS_FILE.read_text(encoding="utf-8"))
        if not isinstance(raw_users, list):
            raise ValueError("User store must be a list.")
    except (OSError, json.JSONDecodeError, ValueError):
        raw_users = DEFAULT_USERS

    return [normalize_user(user) for user in raw_users]


def normalize_user(raw_user: dict[str, Any]) -> dict[str, Any]:
    password_hash = str(raw_user.get("password_hash", "")).strip()
    legacy_password = str(raw_user.get("password", "")).strip()
    if not password_hash and legacy_password:
        password_hash = hash_password(legacy_password)

    created_at = raw_user.get("created_at", datetime.now().strftime("%Y-%m-%d"))
    if isinstance(created_at, (datetime, date)):
        created_value = created_at.isoformat()
    else:
        created_value = str(created_at).strip() or datetime.now().strftime("%Y-%m-%d")

    return {
        "fullname": str(raw_user.get("fullname", "")).strip(),
        "email": str(raw_user.get("email", "")).strip().lower(),
        "password_hash": password_hash,
        "role": str(raw_user.get("role", "user")).strip() or "user",
        "plan": str(raw_user.get("plan", "Free")).strip() or "Free",
        "created_at": created_value[:10],
    }


def upsert_user(user: dict[str, Any]) -> None:
    normalized = normalize_user(user)
    if not normalized["fullname"] or not normalized["email"] or not normalized["password_hash"]:
        return

    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO users (fullname, email, password_hash, role, plan, created_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    email = VALUES(email),
                    password_hash = VALUES(password_hash),
                    role = VALUES(role),
                    plan = VALUES(plan),
                    created_at = VALUES(created_at)
                """,
                (
                    normalized["fullname"],
                    normalized["email"],
                    normalized["password_hash"],
                    normalized["role"],
                    normalized["plan"],
                    normalized["created_at"],
                ),
            )
        connection.commit()


def ensure_admin_account() -> None:
    with get_connection() as connection:
        with connection.cursor(dictionary=True) as cursor:
            cursor.execute(
                """
                SELECT id
                FROM users
                WHERE role = 'admin'
                ORDER BY id
                LIMIT 1
                """
            )
            admin_row = cursor.fetchone()
            if admin_row:
                return

            admin_fullname, admin_email, admin_password = require_admin_bootstrap_config()
            cursor.execute(
                """
                SELECT id
                FROM users
                WHERE LOWER(fullname) = %s OR LOWER(email) = %s
                LIMIT 1
                """,
                (admin_fullname.lower(), admin_email),
            )
            conflicting_user = cursor.fetchone()
            if conflicting_user:
                raise RuntimeError(
                    "No admin account exists yet, but the configured admin name or email is already used by a non-admin account."
                )

            cursor.execute(
                """
                INSERT INTO users (fullname, email, password_hash, role, plan, created_at)
                VALUES (%s, %s, %s, 'admin', 'Root', %s)
                """,
                (
                    admin_fullname,
                    admin_email,
                    hash_password(admin_password),
                    datetime.now().date(),
                ),
            )
        connection.commit()


def read_legacy_text(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def save_setting(key: str, value: str) -> None:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO app_settings (setting_key, setting_value, updated_at)
                VALUES (%s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    setting_value = VALUES(setting_value),
                    updated_at = VALUES(updated_at)
                """,
                (key, value or "", datetime.now()),
            )
        connection.commit()


def load_setting(key: str, default: str | None = None) -> str | None:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT setting_value FROM app_settings WHERE setting_key = %s",
                (key,),
            )
            row = cursor.fetchone()

    if not row:
        return default
    return row[0]


def load_users() -> list[dict[str, Any]]:
    with get_connection() as connection:
        with connection.cursor(dictionary=True) as cursor:
            cursor.execute(
                """
                SELECT id, fullname, email, password_hash, role, plan, created_at
                FROM users
                ORDER BY created_at DESC, fullname ASC
                """
            )
            rows = cursor.fetchall()
    return [serialize_record(row) for row in rows]


def register_user(fullname: str, email: str, password: str) -> tuple[bool, str]:
    fullname = fullname.strip()
    email = email.strip().lower()

    if not fullname or not email or not password:
        return False, "Please complete every field."

    if "@" not in email or "." not in email:
        return False, "Please enter a valid email address."
    is_valid_password, password_error = validate_password_strength(password)
    if not is_valid_password:
        return False, password_error

    with get_connection() as connection:
        with connection.cursor(dictionary=True) as cursor:
            cursor.execute(
                "SELECT id, fullname, email FROM users WHERE fullname = %s OR email = %s",
                (fullname, email),
            )
            existing = cursor.fetchall()
            for user in existing:
                if str(user["fullname"]).strip().lower() == fullname.lower():
                    return False, "That fullname is already registered."
                if str(user["email"]).strip().lower() == email:
                    return False, "That email is already registered."

            cursor.execute(
                """
                INSERT INTO users (fullname, email, password_hash, role, plan, created_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    fullname,
                    email,
                    hash_password(password),
                    "user",
                    "Free",
                    datetime.now().date(),
                ),
            )
        connection.commit()

    return True, "Account created. You can sign in now."


def update_user_password_hash(user_id: int, password_hash_value: str) -> None:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE users
                SET password_hash = %s
                WHERE id = %s
                """,
                (password_hash_value, int(user_id)),
            )
        connection.commit()


def authenticate_user(identifier: str, password: str) -> dict[str, Any] | None:
    identifier = identifier.strip().lower()

    with get_connection() as connection:
        with connection.cursor(dictionary=True) as cursor:
            cursor.execute(
                """
                SELECT id, fullname, email, password_hash, role, plan, created_at
                FROM users
                WHERE LOWER(fullname) = %s OR LOWER(email) = %s
                LIMIT 1
                """,
                (identifier, identifier),
            )
            row = cursor.fetchone()

    if not row or not verify_password(password, str(row.get("password_hash", ""))):
        return None
    if password_hash_needs_upgrade(str(row.get("password_hash", ""))):
        upgraded_hash = hash_password(password)
        update_user_password_hash(int(row["id"]), upgraded_hash)
        row["password_hash"] = upgraded_hash
    return serialize_record(row)


def save_key_permanently(key: str) -> None:
    if not insecure_secret_storage_allowed():
        raise RuntimeError(build_secret_storage_error("COGNISTUDY_API_KEY"))
    save_setting("api_key", key.strip())


def load_key_permanently() -> str:
    env_value = os.getenv("COGNISTUDY_API_KEY", "").strip()
    if env_value:
        return env_value
    if not insecure_secret_storage_allowed():
        return ""
    return load_setting("api_key", "") or ""


def save_system_prompt_permanently(prompt: str) -> None:
    save_setting("system_prompt", prompt)


def load_system_prompt_permanently() -> str:
    return load_setting("system_prompt", DEFAULT_SYSTEM_PROMPT) or DEFAULT_SYSTEM_PROMPT


def append_usage(
    tokens: int,
    user: dict[str, Any] | None = None,
    activity_type: str = "general",
    source: str = "system",
) -> None:
    timestamp = datetime.now()
    weekday = timestamp.strftime("%a")[:3]
    user_id = int(user["id"]) if user and user.get("id") else None

    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO usage_logs (user_id, activity_type, source, weekday, tokens, created_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (user_id, activity_type, source, weekday, int(tokens), timestamp),
            )
        connection.commit()


def get_actual_usage() -> pd.DataFrame:
    with get_connection() as connection:
        with connection.cursor(dictionary=True) as cursor:
            cursor.execute(
                """
                SELECT weekday AS Day, SUM(tokens) AS Tokens
                FROM usage_logs
                GROUP BY weekday
                """
            )
            rows = cursor.fetchall()

    usage_lookup = {
        str(row["Day"]).strip(): int(row["Tokens"] or 0)
        for row in rows
        if str(row["Day"]).strip() in DAYS_OF_WEEK
    }
    return pd.DataFrame(
        {
            "Day": DAYS_OF_WEEK,
            "Tokens": [usage_lookup.get(day, 0) for day in DAYS_OF_WEEK],
        }
    )


def record_study_module(
    user: dict[str, Any],
    file_name: str,
    subject: str = "General",
    tokens_used: int = 0,
) -> None:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO study_modules (user_id, file_name, subject, tokens_used, created_at)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (int(user["id"]), file_name.strip(), subject.strip() or "General", int(tokens_used), datetime.now()),
            )
        connection.commit()


def get_study_modules_for_user(user_id: int) -> list[dict[str, Any]]:
    with get_connection() as connection:
        with connection.cursor(dictionary=True) as cursor:
            cursor.execute(
                """
                SELECT id, file_name, subject, tokens_used, created_at
                FROM study_modules
                WHERE user_id = %s
                ORDER BY created_at DESC
                """,
                (user_id,),
            )
            rows = cursor.fetchall()
    return [serialize_record(row) for row in rows]


def count_study_modules() -> int:
    return count_rows("study_modules")


def log_audit_event(
    action: str,
    details: str,
    user: dict[str, Any] | None = None,
) -> None:
    user_id = int(user["id"]) if user and user.get("id") else None
    actor_name = user["fullname"] if user else "System"
    actor_role = user["role"] if user else "system"

    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO audit_logs (user_id, actor_name, actor_role, action, details, created_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (user_id, actor_name, actor_role, action, details.strip(), datetime.now()),
            )
        connection.commit()


def get_audit_logs(limit: int = 50) -> list[dict[str, Any]]:
    with get_connection() as connection:
        with connection.cursor(dictionary=True) as cursor:
            cursor.execute(
                """
                SELECT id, actor_name, actor_role, action, details, created_at
                FROM audit_logs
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (int(limit),),
            )
            rows = cursor.fetchall()
    return [serialize_record(row) for row in rows]


def serialize_record(record: dict[str, Any]) -> dict[str, Any]:
    serialized = {}
    for key, value in record.items():
        if isinstance(value, datetime):
            serialized[key] = value.strftime("%Y-%m-%d %H:%M:%S")
        elif isinstance(value, date):
            serialized[key] = value.isoformat()
        else:
            serialized[key] = value
    return serialized
