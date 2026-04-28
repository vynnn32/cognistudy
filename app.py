from __future__ import annotations

import base64
import html
import io
import json
import os
import re
import secrets
import smtplib
import time
import textwrap
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timedelta
from email.message import EmailMessage
from email.utils import make_msgid
from pathlib import Path
from xml.etree import ElementTree as ET

import mysql.connector
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st
import streamlit.components.v1 as components

from security_utils import (
    hash_password,
    password_hash_needs_upgrade,
    validate_password_strength,
    verify_password,
)


BASE_DIR = Path(__file__).resolve().parent
LOGO_FILE = BASE_DIR / "cnlogo.png"
DB_CONFIG_FILE = BASE_DIR / "db_config.json"
LEGACY_API_KEY_FILE = BASE_DIR / "api_key.txt"
LEGACY_SYSTEM_PROMPT_FILE = BASE_DIR / "system_prompt.txt"
DRAG_HIGHLIGHTER_COMPONENT_PATH = BASE_DIR / "components" / "drag_text_highlighter"

GMAIL_SMTP_HOST = "smtp.gmail.com"
GMAIL_SMTP_PORT = 587
API_KEY_ENV = "COGNISTUDY_API_KEY"
SYSTEM_PROMPT_ENV = "COGNISTUDY_SYSTEM_PROMPT"
GMAIL_SENDER_EMAIL_ENV = "COGNISTUDY_GMAIL_SENDER_EMAIL"
GMAIL_APP_PASSWORD_ENV = "COGNISTUDY_GMAIL_APP_PASSWORD"
DB_HOST_ENV = "COGNISTUDY_DB_HOST"
DB_PORT_ENV = "COGNISTUDY_DB_PORT"
DB_USER_ENV = "COGNISTUDY_DB_USER"
DB_PASSWORD_ENV = "COGNISTUDY_DB_PASSWORD"
DB_NAME_ENV = "COGNISTUDY_DB_NAME"
ADMIN_FULLNAME_ENV = "COGNISTUDY_ADMIN_FULLNAME"
ADMIN_EMAIL_ENV = "COGNISTUDY_ADMIN_EMAIL"
ADMIN_PASSWORD_ENV = "COGNISTUDY_ADMIN_PASSWORD"
ALLOW_INSECURE_SECRET_STORAGE_ENV = "COGNISTUDY_ALLOW_INSECURE_SECRET_STORAGE"
QUIZ_GENERATION_SYSTEM_PROMPT = (
    "You are an expert academic quiz generator. "
    "Follow the provided quiz-generation instructions exactly and return valid JSON only."
)

DEFAULT_SYSTEM_PROMPT = (
    LEGACY_SYSTEM_PROMPT_FILE.read_text(encoding="utf-8").strip()
    if LEGACY_SYSTEM_PROMPT_FILE.exists() and LEGACY_SYSTEM_PROMPT_FILE.read_text(encoding="utf-8").strip()
    else "You are the CogniStudy Neural Engine. Convert uploads into concise study material."
)
DEFAULT_ADMIN_FULLNAME = "Admin"
DEFAULT_ADMIN_EMAIL = "admin@cognistudi.local"
GEMINI_MODEL_CANDIDATES = [
    "gemini-2.5-flash-lite",
    "gemini-flash-lite-latest",
    "gemini-flash-latest",
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
]
MODULE_SUBJECT_OPTIONS = [
    "Select Subject",
    "General",
    "Mathematics",
    "Biology",
    "Chemistry",
    "Physics",
    "History",
    "English",
    "Computer Science",
    "Arts",
    "Business",
    "Custom",
]


drag_text_highlighter_component = components.declare_component(
    "drag_text_highlighter",
    path=str(DRAG_HIGHLIGHTER_COMPONENT_PATH),
)


st.set_page_config(
    page_title="CogniStudy Portal",
    page_icon=str(LOGO_FILE) if LOGO_FILE.exists() else None,
    layout="wide",
    initial_sidebar_state="expanded",
)


def render_drag_text_highlighter(statement: str, selected_phrase: str, key: str, disabled: bool = False) -> str:
    value = drag_text_highlighter_component(
        statement=statement,
        value=selected_phrase or "",
        disabled=disabled,
        key=key,
        default=selected_phrase or "",
    )
    return str(value or "").strip()


def get_base64(path: Path) -> str:
    if path.exists():
        return base64.b64encode(path.read_bytes()).decode("utf-8")
    return ""


def read_legacy_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="ignore").strip()


def read_json_file(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


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


def load_db_config() -> dict[str, object]:
    file_config = read_json_file(DB_CONFIG_FILE)
    config = {
        "host": os.getenv(DB_HOST_ENV, str(file_config.get("host", "127.0.0.1"))).strip() or "127.0.0.1",
        "port": int(os.getenv(DB_PORT_ENV, str(file_config.get("port", 3306)) or "3306")),
        "user": os.getenv(DB_USER_ENV, str(file_config.get("user", "root"))).strip() or "root",
        "password": os.getenv(DB_PASSWORD_ENV, str(file_config.get("password", ""))),
        "database": os.getenv(DB_NAME_ENV, str(file_config.get("database", "cognistudi"))).strip() or "cognistudi",
    }
    return config


def render_sidebar_brand(title_html: str) -> None:
    logo_b64 = get_base64(LOGO_FILE)
    logo_markup = (
        f'<img src="data:image/png;base64,{logo_b64}" style="width:72px; height:72px; margin:0 auto 10px auto; display:block;">'
        if logo_b64
        else ""
    )
    st.markdown(
        f"""
        <div style="text-align:center; margin-bottom:18px;">
            {logo_markup}
            {title_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def get_db_connection() -> mysql.connector.MySQLConnection:
    return mysql.connector.connect(**load_db_config())

def initialize_database() -> None:
    connection = get_db_connection()
    cursor = connection.cursor()

    try:
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INT AUTO_INCREMENT PRIMARY KEY,
                fullname VARCHAR(255) NOT NULL UNIQUE,
                email VARCHAR(255) NOT NULL UNIQUE,
                password_hash VARCHAR(255) NOT NULL,
                role VARCHAR(20) NOT NULL DEFAULT 'user',
                plan VARCHAR(50) NOT NULL DEFAULT 'Free',
                account_status VARCHAR(20) NOT NULL DEFAULT 'active',
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS app_settings (
                setting_key VARCHAR(100) PRIMARY KEY,
                setting_value LONGTEXT NOT NULL,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                    ON UPDATE CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS password_reset_codes (
                id INT AUTO_INCREMENT PRIMARY KEY,
                user_id INT NOT NULL,
                email VARCHAR(255) NOT NULL,
                reset_code CHAR(6) NOT NULL,
                expires_at DATETIME NOT NULL,
                consumed_at DATETIME NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT fk_password_reset_codes_user
                    FOREIGN KEY (user_id) REFERENCES users(id)
                    ON DELETE CASCADE,
                INDEX idx_password_reset_email (email),
                INDEX idx_password_reset_code (reset_code),
                INDEX idx_password_reset_expires (expires_at)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS usage_logs (
                id INT AUTO_INCREMENT PRIMARY KEY,
                day CHAR(3) NOT NULL,
                tokens INT NOT NULL DEFAULT 0,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS system_activity_logs (
                id INT AUTO_INCREMENT PRIMARY KEY,
                actor_id INT NULL,
                actor_name VARCHAR(255) NOT NULL,
                actor_role VARCHAR(20) NOT NULL,
                activity VARCHAR(255) NOT NULL,
                details LONGTEXT NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS user_documents (
                id INT AUTO_INCREMENT PRIMARY KEY,
                user_id INT NOT NULL,
                file_name VARCHAR(255) NOT NULL,
                subject VARCHAR(100) NOT NULL DEFAULT 'General',
                uploaded_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT fk_user_documents_user
                    FOREIGN KEY (user_id) REFERENCES users(id)
                    ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS generated_reviewers (
                id INT AUTO_INCREMENT PRIMARY KEY,
                user_id INT NOT NULL,
                document_id INT NOT NULL,
                file_name VARCHAR(255) NOT NULL,
                subject VARCHAR(100) NOT NULL DEFAULT 'General',
                summary_preference VARCHAR(100) NOT NULL,
                quiz_preference VARCHAR(100) NOT NULL,
                reviewer_title VARCHAR(255) NOT NULL,
                reviewer_body LONGTEXT NOT NULL,
                quiz_payload LONGTEXT NOT NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT fk_generated_reviewers_user
                    FOREIGN KEY (user_id) REFERENCES users(id)
                    ON DELETE CASCADE,
                CONSTRAINT fk_generated_reviewers_document
                    FOREIGN KEY (document_id) REFERENCES user_documents(id)
                    ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS quiz_attempts (
                id INT AUTO_INCREMENT PRIMARY KEY,
                user_id INT NOT NULL,
                reviewer_id INT NOT NULL,
                file_name VARCHAR(255) NOT NULL,
                subject VARCHAR(100) NOT NULL DEFAULT 'General',
                score INT NOT NULL DEFAULT 0,
                total_questions INT NOT NULL DEFAULT 0,
                percentage DECIMAL(5,2) NOT NULL DEFAULT 0,
                attempted_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT fk_quiz_attempts_user
                    FOREIGN KEY (user_id) REFERENCES users(id)
                    ON DELETE CASCADE,
                CONSTRAINT fk_quiz_attempts_reviewer
                    FOREIGN KEY (reviewer_id) REFERENCES generated_reviewers(id)
                    ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """
        )

        cursor.execute(
            """
            SELECT COUNT(*)
            FROM information_schema.columns
            WHERE table_schema = DATABASE()
              AND table_name = 'users'
              AND column_name = 'account_status'
            """
        )
        if cursor.fetchone()[0] == 0:
            cursor.execute(
                """
                ALTER TABLE users
                ADD COLUMN account_status VARCHAR(20) NOT NULL DEFAULT 'active'
                """
            )

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

        cursor.execute("SELECT id FROM users WHERE role = 'admin' ORDER BY id LIMIT 1")
        admin_row = cursor.fetchone()
        if not admin_row:
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
                INSERT INTO users (fullname, email, password_hash, role, plan, account_status)
                VALUES (%s, %s, %s, 'admin', 'Root', 'active')
                """,
                (admin_fullname, admin_email, hash_password(admin_password)),
            )

        cursor.execute(
            """
            INSERT IGNORE INTO app_settings (setting_key, setting_value)
            VALUES (%s, %s)
            """,
            ("system_prompt", DEFAULT_SYSTEM_PROMPT),
        )

        connection.commit()
    finally:
        cursor.close()
        connection.close()


def fetch_all(query: str, params: tuple | None = None) -> list[dict]:
    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    try:
        cursor.execute(query, params or ())
        return cursor.fetchall()
    finally:
        cursor.close()
        connection.close()


def fetch_one(query: str, params: tuple | None = None) -> dict | None:
    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    try:
        cursor.execute(query, params or ())
        return cursor.fetchone()
    finally:
        cursor.close()
        connection.close()


def execute_query(query: str, params: tuple | None = None) -> int:
    connection = get_db_connection()
    cursor = connection.cursor()

    try:
        cursor.execute(query, params or ())
        connection.commit()
        return cursor.lastrowid
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()
        connection.close()


def load_users(include_admin: bool = True) -> list[dict]:
    query = """
        SELECT id, fullname, email, password_hash, role, plan, account_status, created_at
        FROM users
    """
    if not include_admin:
        query += " WHERE role <> 'admin'"
    query += " ORDER BY created_at DESC, id DESC"
    return fetch_all(query)


def load_user_by_id(user_id: int) -> dict | None:
    return fetch_one(
        """
        SELECT id, fullname, email, password_hash, role, plan, account_status, created_at
        FROM users
        WHERE id = %s
        LIMIT 1
        """,
        (user_id,),
    )


def log_system_activity(
    actor_name: str,
    actor_role: str,
    activity: str,
    details: str = "",
    actor_id: int | None = None,
) -> None:
    try:
        execute_query(
            """
            INSERT INTO system_activity_logs (actor_id, actor_name, actor_role, activity, details)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (actor_id, actor_name.strip() or "Unknown", actor_role.strip().lower() or "system", activity.strip(), details.strip()),
        )
    except Exception:
        # Activity logging should never block sign-up, sign-in, or generation flows.
        return


def load_system_activities(actor_role: str | None = None, limit: int = 50) -> list[dict]:
    query = """
        SELECT actor_name, actor_role, activity, details, created_at
        FROM system_activity_logs
    """
    params: tuple = ()
    if actor_role:
        query += " WHERE actor_role = %s"
        params = (actor_role.lower(),)
    query += " ORDER BY created_at DESC, id DESC LIMIT %s"
    params = params + (int(limit),)
    return fetch_all(query, params)


def load_system_activities_for_user(actor_id: int, limit: int = 25) -> list[dict]:
    return fetch_all(
        """
        SELECT actor_name, actor_role, activity, details, created_at
        FROM system_activity_logs
        WHERE actor_id = %s
        ORDER BY created_at DESC, id DESC
        LIMIT %s
        """,
        (int(actor_id), int(limit)),
    )


def update_user_account_status(user_id: int, account_status: str) -> None:
    execute_query(
        """
        UPDATE users
        SET account_status = %s
        WHERE id = %s AND role <> 'admin'
        """,
        (account_status, user_id),
    )


def delete_user_account(user_id: int) -> None:
    execute_query(
        """
        DELETE FROM users
        WHERE id = %s AND role <> 'admin'
        """,
        (user_id,),
    )


def build_signup_welcome_email_html(fullname: str, logo_cid: str | None, sender_email: str) -> str:
    safe_name = html.escape(fullname.strip() or "Scholar")
    logo_markup = (
        f'<img src="cid:{logo_cid}" alt="CogniStudy.ai" width="132" style="display:block; border:0; outline:none; text-decoration:none;">'
        if logo_cid
        else '<div style="font-size:26px; font-weight:800; color:#112240;">CogniStudy.ai</div>'
    )
    support_email = sender_email.strip() or "support@cognistudy.ai"
    support_link = f"mailto:{support_email}?subject=CogniStudy.ai%20Support"
    return f"""
<!DOCTYPE html>
<html>
  <body style="margin:0; padding:0; background:#e8edf5; font-family:Arial,Helvetica,sans-serif;">
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#e8edf5; padding:24px 0;">
      <tr>
        <td align="center">
          <table role="presentation" width="640" cellspacing="0" cellpadding="0" style="width:640px; max-width:640px; background:#ffffff; border-collapse:collapse; box-shadow:0 10px 24px rgba(15,23,42,0.12);">
            <tr>
              <td style="padding:18px 28px; background:#ffffff; border-bottom:1px solid #e5e7eb;">
                <table role="presentation" width="100%" cellspacing="0" cellpadding="0">
                  <tr>
                    <td align="left" style="vertical-align:middle;">{logo_markup}</td>
                    <td align="right" style="font-size:13px; color:#475569; font-weight:600;">CyberNauts</td>
                  </tr>
                </table>
              </td>
            </tr>
            <tr>
              <td style="background:linear-gradient(135deg,#0f5ec7 0%,#1d4ed8 55%,#0f3f8f 100%); padding:38px 40px; color:#ffffff;">
                <table role="presentation" width="100%" cellspacing="0" cellpadding="0">
                  <tr>
                    <td style="width:62%; vertical-align:top;">
                      <div style="font-size:44px; line-height:1.08; font-weight:800; margin:0 0 14px 0;">Welcome to<br>CogniStudy.ai!</div>
                      <div style="font-size:18px; line-height:1.5; color:#dbeafe;">Thank you for signing up, {safe_name}.</div>
                    </td>
                    <td align="right" style="width:38%; vertical-align:middle;">
                      <div style="font-size:84px; line-height:1;">🎓</div>
                    </td>
                  </tr>
                </table>
              </td>
            </tr>
            <tr>
              <td style="padding:34px 36px 18px 36px; text-align:center;">
                <div style="font-size:34px; line-height:1.2; font-weight:800; color:#1e293b; margin-bottom:10px;">We're excited to have you on board!</div>
                <div style="font-size:17px; line-height:1.6; color:#64748b;">Here are a few things you can do next inside CogniStudy.ai.</div>
              </td>
            </tr>
            <tr>
              <td style="padding:10px 28px 28px 28px;">
                <table role="presentation" width="100%" cellspacing="0" cellpadding="0">
                  <tr>
                    <td width="33.33%" style="padding:14px 12px; text-align:center; border-right:1px solid #e5e7eb;">
                      <div style="font-size:38px; margin-bottom:10px;">📘</div>
                      <div style="font-size:18px; font-weight:800; color:#1e293b; margin-bottom:6px;">Upload Modules</div>
                      <div style="font-size:14px; line-height:1.6; color:#64748b;">Turn classroom materials into reviewer-ready study content.</div>
                    </td>
                    <td width="33.33%" style="padding:14px 12px; text-align:center; border-right:1px solid #e5e7eb;">
                      <div style="font-size:38px; margin-bottom:10px;">🧠</div>
                      <div style="font-size:18px; font-weight:800; color:#1e293b; margin-bottom:6px;">Generate Reviewers</div>
                      <div style="font-size:14px; line-height:1.6; color:#64748b;">Create structured reviewers and adaptive summaries from your lessons.</div>
                    </td>
                    <td width="33.33%" style="padding:14px 12px; text-align:center;">
                      <div style="font-size:38px; margin-bottom:10px;">📝</div>
                      <div style="font-size:18px; font-weight:800; color:#1e293b; margin-bottom:6px;">Take Quizzes</div>
                      <div style="font-size:14px; line-height:1.6; color:#64748b;">Practice with timed quizzes that reinforce active recall.</div>
                    </td>
                  </tr>
                </table>
              </td>
            </tr>
            <tr>
              <td style="padding:24px 36px 36px 36px; text-align:center;">
                <div style="font-size:28px; line-height:1.2; font-weight:800; color:#1e293b; margin-bottom:10px;">Need Assistance?</div>
                <div style="font-size:15px; line-height:1.7; color:#64748b; margin-bottom:22px;">If you have any questions, feel free to reach out to us at any time.</div>
                <a href="{support_link}" style="display:inline-block; background:#0f5ec7; color:#ffffff; text-decoration:none; font-size:16px; font-weight:700; padding:14px 28px; border-radius:8px;">Contact Support</a>
              </td>
            </tr>
            <tr>
              <td style="padding:30px 36px; background:#f8fafc; text-align:center; border-top:1px solid #e5e7eb;">
                <div style="font-size:15px; line-height:1.8; color:#475569;">Welcome aboard! We're glad to have you with us.</div>
                <div style="font-size:15px; line-height:1.8; color:#475569; margin-top:14px;">Best regards,<br><strong>The CogniStudy.ai Team</strong><br>by CyberNauts</div>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>
""".strip()


def build_signup_welcome_email_html(fullname: str, logo_cid: str | None, sender_email: str) -> str:
    display_name = fullname.strip() or "Scholar"
    first_name = html.escape(display_name.split()[0].title() if display_name.split() else "Scholar")
    logo_markup = (
        f'<img src="cid:{logo_cid}" alt="CogniStudy.ai" width="96" style="display:block; border:0; outline:none; text-decoration:none;">'
        if logo_cid
        else '<div style="font-size:24px; font-weight:800; color:#ffffff;">CogniStudy.ai</div>'
    )
    support_email = sender_email.strip() or "support@cognistudy.ai"
    support_link = f"mailto:{support_email}?subject=CogniStudy.ai%20Support"
    return f"""
<!DOCTYPE html>
<html>
  <body style="margin:0; padding:0; background:#101813; font-family:Arial,Helvetica,sans-serif;">
    <div style="display:none; max-height:0; overflow:hidden; opacity:0; color:transparent;">
      Welcome to CogniStudy.ai. Your study workspace is ready.
    </div>
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#101813; padding:24px 0;">
      <tr>
        <td align="center">
          <table role="presentation" width="640" cellspacing="0" cellpadding="0" style="width:640px; max-width:640px; background:#12161c; border-collapse:separate; border-spacing:0; border-radius:24px; overflow:hidden; box-shadow:0 18px 42px rgba(0,0,0,0.3);">
            <tr>
              <td style="padding:22px 28px 16px 28px; background:#12161c;">
                <table role="presentation" width="100%" cellspacing="0" cellpadding="0">
                  <tr>
                    <td align="left" style="vertical-align:middle;">{logo_markup}</td>
                    <td align="right" style="font-size:13px; color:#c4d1ea; font-weight:700; line-height:1.5;">CogniStudy.ai by CyberNauts</td>
                  </tr>
                </table>
              </td>
            </tr>
            <tr>
              <td style="padding:0 28px 0 28px; background:#12161c;">
                <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:linear-gradient(135deg,#0d1e44 0%,#123a8d 55%,#2157e6 100%); border-radius:20px 20px 0 0;">
                  <tr>
                    <td style="padding:28px 26px 42px 26px; color:#ffffff;">
                      <div style="font-size:11px; line-height:1.4; letter-spacing:1.6px; font-weight:800; color:#ffad7d; text-transform:uppercase; margin-bottom:10px;">Welcome to CogniStudy.ai</div>
                      <div style="font-size:42px; line-height:1.06; font-weight:800; margin:0 0 14px 0;">Hello, {first_name}.</div>
                      <div style="max-width:430px; font-size:16px; line-height:1.7; color:#d7e6ff;">
                        Your account is ready. You can now upload learning modules, generate structured reviewers, and answer adaptive quizzes inside the CogniStudy.ai system.
                      </div>
                    </td>
                  </tr>
                </table>
              </td>
            </tr>
            <tr>
              <td style="padding:0 28px 0 28px; background:#12161c;">
                <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#ffffff; border-radius:0 0 20px 20px;">
                  <tr>
                    <td style="padding:36px 34px 12px 34px; text-align:center; background:#ffffff; border-top:1px solid #eef2f8;">
                      <div style="font-size:28px; line-height:1.25; font-weight:800; color:#1f2937; margin-bottom:8px;">Your study workspace is ready</div>
                      <div style="font-size:15px; line-height:1.7; color:#64748b; max-width:470px; margin:0 auto;">Everything below is tailored to the same reviewer and quiz workflow inside the system.</div>
                    </td>
                  </tr>
                  <tr>
                    <td style="padding:16px 26px 8px 26px; background:#ffffff;">
                      <table role="presentation" width="100%" cellspacing="0" cellpadding="0">
                        <tr>
                          <td width="33.33%" style="padding:0 8px; vertical-align:top;">
                            <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#f8fafc; border:1px solid #e2e8f0; border-radius:16px;">
                              <tr><td style="padding:18px 16px 16px 16px;">
                                <div style="font-size:26px; line-height:1; margin-bottom:12px;">Upload</div>
                                <div style="font-size:18px; font-weight:800; color:#1f2937; margin-bottom:8px;">Upload Modules</div>
                                <div style="font-size:13px; line-height:1.6; color:#64748b;">Add your teacher's lessons first and let the system extract the key learning content.</div>
                              </td></tr>
                            </table>
                          </td>
                          <td width="33.33%" style="padding:0 8px; vertical-align:top;">
                            <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#f8fafc; border:1px solid #e2e8f0; border-radius:16px;">
                              <tr><td style="padding:18px 16px 16px 16px;">
                                <div style="font-size:26px; line-height:1; margin-bottom:12px;">Review</div>
                                <div style="font-size:18px; font-weight:800; color:#1f2937; margin-bottom:8px;">Generate Reviewers</div>
                                <div style="font-size:13px; line-height:1.6; color:#64748b;">Turn dense modules into a clear reviewer with the summary style that fits your study goal.</div>
                              </td></tr>
                            </table>
                          </td>
                          <td width="33.33%" style="padding:0 8px; vertical-align:top;">
                            <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#f8fafc; border:1px solid #e2e8f0; border-radius:16px;">
                              <tr><td style="padding:18px 16px 16px 16px;">
                                <div style="font-size:26px; line-height:1; margin-bottom:12px;">Quiz</div>
                                <div style="font-size:18px; font-weight:800; color:#1f2937; margin-bottom:8px;">Take Smart Quizzes</div>
                                <div style="font-size:13px; line-height:1.6; color:#64748b;">Practice with difficulty-based quizzes and keep building your mastery with every attempt.</div>
                              </td></tr>
                            </table>
                          </td>
                        </tr>
                      </table>
                    </td>
                  </tr>
                  <tr>
                    <td style="padding:18px 34px 18px 34px; background:#ffffff;">
                      <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#fff4ec; border:1px solid #ffd2bd; border-radius:18px;">
                        <tr>
                          <td style="padding:24px 20px; text-align:center;">
                            <div style="font-size:18px; line-height:1.25; font-weight:800; color:#1f2937; margin-bottom:8px;">Need help getting started?</div>
                            <div style="font-size:13px; line-height:1.7; color:#7c8ba4; margin-bottom:18px;">If you have any questions about your account or the platform, CyberNauts is ready to help.</div>
                            <a href="{support_link}" style="display:inline-block; background:#ff6b35; color:#ffffff; text-decoration:none; font-size:14px; font-weight:800; padding:12px 24px; border-radius:10px;">Contact Support</a>
                          </td>
                        </tr>
                      </table>
                    </td>
                  </tr>
                  <tr>
                    <td style="padding:2px 34px 34px 34px; background:#ffffff; text-align:center;">
                      <div style="width:72px; height:1px; background:#e7edf5; margin:0 auto 16px auto;"></div>
                      <div style="font-size:13px; line-height:1.8; color:#7c8ba4;">Questions? Contact <a href="mailto:{support_email}" style="color:#ff8a57; text-decoration:none; font-weight:700;">{support_email}</a></div>
                    </td>
                  </tr>
                </table>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>
""".strip()


def send_signup_welcome_email(fullname: str, recipient_email: str) -> tuple[bool, str]:
    sender_email = load_gmail_sender_email_permanently()
    app_password = load_gmail_app_password_permanently()
    if not sender_email or not app_password:
        return False, "Email delivery settings are not configured in Admin API Settings."

    logo_cid = make_msgid(domain="cognistudy.ai")[1:-1] if LOGO_FILE.exists() else None
    message = EmailMessage()
    message["Subject"] = "Welcome to CogniStudy.ai"
    message["From"] = f"CyberNauts <{sender_email}>"
    message["To"] = recipient_email.strip().lower()
    message.set_content(
        f"""Hello {fullname},

Welcome to CogniStudy.ai.

Your account has been created successfully. You can now sign in using your registered email address and start uploading modules, generating reviewers, and taking quizzes.

If you need help, reply to this email and the CyberNauts team will assist you.

Best regards,
CyberNauts
The CogniStudy.ai Team
""".strip()
    )
    message.add_alternative(build_signup_welcome_email_html(fullname, logo_cid, sender_email), subtype="html")

    html_part = message.get_body(preferencelist=("html",))
    if html_part and logo_cid and LOGO_FILE.exists():
        html_part.add_related(
            LOGO_FILE.read_bytes(),
            maintype="image",
            subtype=(LOGO_FILE.suffix.lower().lstrip(".") or "png"),
            cid=f"<{logo_cid}>",
        )

    try:
        with smtplib.SMTP(GMAIL_SMTP_HOST, GMAIL_SMTP_PORT, timeout=30) as server:
            server.starttls()
            server.login(sender_email, app_password)
            server.send_message(message)
        return True, "Welcome email sent successfully."
    except smtplib.SMTPAuthenticationError as error:
        return False, (
            "SMTP authentication failed. Update the Gmail app password for the sender account."
        )
    except Exception as error:
        return False, f"{type(error).__name__}: {error}"


def mask_email_address(email: str) -> str:
    normalized = email.strip().lower()
    if "@" not in normalized:
        return normalized
    local_part, domain = normalized.split("@", 1)
    if len(local_part) <= 2:
        masked_local = local_part[0] + "*" * max(1, len(local_part) - 1)
    else:
        masked_local = local_part[:2] + "*" * max(2, len(local_part) - 2)
    return f"{masked_local}@{domain}"


def build_password_reset_email_html(fullname: str, reset_code: str, logo_cid: str | None, sender_email: str) -> str:
    display_name = fullname.strip() or "Scholar"
    first_name = html.escape(display_name.split()[0].title() if display_name.split() else "Scholar")
    safe_code = "".join(ch for ch in str(reset_code) if ch.isdigit())[:6]
    code_digits = list(safe_code) if safe_code else list("000000")
    code_cells = "".join(
        f'<td style="padding:0 10px; font-size:32px; line-height:1; font-weight:800; color:#0f172a; text-align:center;">{html.escape(digit)}</td>'
        for digit in code_digits
    )
    logo_markup = (
        f'<img src="cid:{logo_cid}" alt="CogniStudy.ai" width="92" style="display:block; border:0; outline:none; text-decoration:none;">'
        if logo_cid
        else '<div style="font-size:24px; font-weight:800; color:#ffffff;">CogniStudy.ai</div>'
    )
    support_email = sender_email.strip() or "support@cognistudy.ai"
    return f"""
<!DOCTYPE html>
<html>
  <head>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
  </head>
  <body style="margin:0; padding:0; background:#101813; font-family:Arial,Helvetica,sans-serif;">
    <div style="display:none; max-height:0; overflow:hidden; opacity:0; color:transparent;">
      Your CogniStudy.ai password reset code is {safe_code}. This code expires in 30 minutes.
    </div>
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#101813; padding:24px 0;">
      <tr>
        <td align="center">
          <table role="presentation" width="640" cellspacing="0" cellpadding="0" style="width:640px; max-width:640px; background:#ffffff; border-collapse:separate; border-spacing:0; border-radius:24px; overflow:hidden; box-shadow:0 18px 42px rgba(0,0,0,0.3);">
            <tr>
              <td style="padding:22px 28px 16px 28px; background:#12161c;">
                <table role="presentation" width="100%" cellspacing="0" cellpadding="0">
                  <tr>
                    <td align="left" style="vertical-align:middle;">{logo_markup}</td>
                    <td align="right" style="font-size:13px; color:#c4d1ea; font-weight:700; line-height:1.5;">CogniStudy.ai by CyberNauts</td>
                  </tr>
                </table>
              </td>
            </tr>
            <tr>
              <td style="padding:0 28px 0 28px; background:#12161c;">
                <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:linear-gradient(135deg,#0d1e44 0%,#123a8d 55%,#2157e6 100%); border-radius:20px 20px 0 0;">
                  <tr>
                    <td style="padding:28px 26px 42px 26px; color:#ffffff;">
                      <div style="font-size:11px; line-height:1.4; letter-spacing:1.6px; font-weight:800; color:#ffad7d; text-transform:uppercase; margin-bottom:10px;">Password Reset Request</div>
                      <div style="font-size:42px; line-height:1.06; font-weight:800; margin:0 0 12px 0;">Reset Your Password</div>
                      <div style="max-width:430px; font-size:16px; line-height:1.7; color:#d7e6ff;">
                        Hi {first_name}, use the verification code below to continue resetting your CogniStudy.ai password.
                      </div>
                    </td>
                  </tr>
                </table>
              </td>
            </tr>
            <tr>
              <td style="padding:0 28px 0 28px; background:#12161c;">
                <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#ffffff; border-radius:0 0 20px 20px;">
                  <tr>
                    <td style="padding:36px 34px 16px 34px; text-align:center; background:#ffffff; border-top:1px solid #eef2f8;">
                      <div style="font-size:28px; line-height:1.25; font-weight:800; color:#1f2937; margin-bottom:8px;">Here is your 6-digit verification code</div>
                      <div style="font-size:15px; line-height:1.7; color:#64748b; margin-bottom:24px;">Enter this code on the password reset screen to choose a new password.</div>
                      <table role="presentation" align="center" cellspacing="0" cellpadding="0" style="margin:0 auto; background:#f4f7fb; border:1px solid #dbe5f1; border-radius:18px;">
                        <tr>
                          <td style="padding:18px 14px;">
                            <table role="presentation" cellspacing="0" cellpadding="0" style="margin:0 auto; white-space:nowrap;">
                              <tr>
                                {code_cells}
                              </tr>
                            </table>
                          </td>
                        </tr>
                      </table>
                    </td>
                  </tr>
                  <tr>
                    <td style="padding:18px 34px 34px 34px; text-align:center; background:#ffffff;">
                      <div style="font-size:14px; line-height:1.8; color:#64748b;">This code will expire in 30 minutes.</div>
                      <div style="font-size:14px; line-height:1.8; color:#64748b; margin-top:4px;">If you did not request this, you can safely ignore this email.</div>
                      <div style="width:72px; height:1px; background:#e7edf5; margin:20px auto 18px auto;"></div>
                      <div style="font-size:13px; line-height:1.8; color:#7c8ba4;">Questions? Contact <a href="mailto:{support_email}" style="color:#ff8a57; text-decoration:none; font-weight:700;">{support_email}</a></div>
                    </td>
                  </tr>
                </table>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>
""".strip()


def send_password_reset_code_email(fullname: str, recipient_email: str, reset_code: str) -> tuple[bool, str]:
    sender_email = load_gmail_sender_email_permanently()
    app_password = load_gmail_app_password_permanently()
    if not sender_email or not app_password:
        return False, "Email delivery settings are not configured in Admin API Settings."

    logo_cid = make_msgid(domain="cognistudy.ai")[1:-1] if LOGO_FILE.exists() else None
    message = EmailMessage()
    message["Subject"] = "Your CogniStudy.ai password reset code"
    message["From"] = f"CyberNauts <{sender_email}>"
    message["To"] = recipient_email.strip().lower()
    message.set_content(
        f"""Hello {fullname},

Your CogniStudy.ai password reset code is {reset_code}.

Enter this code on the password reset screen to choose a new password.
This code expires in 30 minutes.

If you did not request this, you can ignore this email.

CyberNauts
CogniStudy.ai
""".strip()
    )
    message.add_alternative(
        build_password_reset_email_html(fullname, reset_code, logo_cid, sender_email),
        subtype="html",
    )

    html_part = message.get_body(preferencelist=("html",))
    if html_part and logo_cid and LOGO_FILE.exists():
        html_part.add_related(
            LOGO_FILE.read_bytes(),
            maintype="image",
            subtype=(LOGO_FILE.suffix.lower().lstrip(".") or "png"),
            cid=f"<{logo_cid}>",
        )

    try:
        with smtplib.SMTP(GMAIL_SMTP_HOST, GMAIL_SMTP_PORT, timeout=30) as server:
            server.starttls()
            server.login(sender_email, app_password)
            server.send_message(message)
        return True, "Password reset email sent successfully."
    except smtplib.SMTPAuthenticationError:
        return False, "SMTP authentication failed. Update the Gmail app password for the sender account."
    except Exception as error:
        return False, f"{type(error).__name__}: {error}"


def clear_password_reset_state() -> None:
    for state_key in (
        "password_reset_open",
        "password_reset_step",
        "password_reset_email",
        "password_reset_code_input",
        "password_reset_new_password",
        "password_reset_confirm_password",
    ):
        st.session_state.pop(state_key, None)


def load_user_by_email(email: str) -> dict | None:
    return fetch_one(
        """
        SELECT id, fullname, email, role, plan, account_status, created_at
        FROM users
        WHERE LOWER(email) = %s
        LIMIT 1
        """,
        (email.strip().lower(),),
    )


def invalidate_password_reset_codes(user_id: int) -> None:
    execute_query(
        """
        UPDATE password_reset_codes
        SET consumed_at = CURRENT_TIMESTAMP
        WHERE user_id = %s AND consumed_at IS NULL
        """,
        (user_id,),
    )


def generate_unique_password_reset_code() -> str:
    now = datetime.now()
    for _ in range(50):
        code = f"{secrets.randbelow(900000) + 100000:06d}"
        existing = fetch_one(
            """
            SELECT id
            FROM password_reset_codes
            WHERE reset_code = %s AND consumed_at IS NULL AND expires_at > %s
            LIMIT 1
            """,
            (code, now),
        )
        if not existing:
            return code
    raise RuntimeError("Could not generate a unique reset code. Please try again.")


def create_password_reset_request(email: str) -> tuple[bool, str]:
    normalized_email = email.strip().lower()
    if not normalized_email:
        return False, "Enter the email address you used when you created your account."
    if "@" not in normalized_email or "." not in normalized_email:
        return False, "Enter a valid email address."

    user = load_user_by_email(normalized_email)
    if not user:
        return False, "No account was found with that email address."
    if str(user.get("account_status", "active")).lower() != "active":
        return False, "This account is suspended. Please contact the admin."

    invalidate_password_reset_codes(int(user["id"]))
    reset_code = generate_unique_password_reset_code()
    expires_at = datetime.now() + timedelta(minutes=30)
    request_id = execute_query(
        """
        INSERT INTO password_reset_codes (user_id, email, reset_code, expires_at)
        VALUES (%s, %s, %s, %s)
        """,
        (int(user["id"]), normalized_email, reset_code, expires_at),
    )
    email_sent, email_status = send_password_reset_code_email(user["fullname"], normalized_email, reset_code)
    log_system_activity(
        actor_name=user["fullname"],
        actor_role=user["role"],
        actor_id=int(user["id"]),
        activity="Password reset requested",
        details=f"Password reset code requested for {normalized_email}.",
    )
    if not email_sent:
        execute_query(
            """
            UPDATE password_reset_codes
            SET consumed_at = CURRENT_TIMESTAMP
            WHERE id = %s
            """,
            (int(request_id),),
        )
        log_system_activity(
            actor_name=user["fullname"],
            actor_role=user["role"],
            actor_id=int(user["id"]),
            activity="Password reset email failed",
            details=email_status,
        )
        return False, email_status

    log_system_activity(
        actor_name=user["fullname"],
        actor_role=user["role"],
        actor_id=int(user["id"]),
        activity="Password reset email sent",
        details=f"6-digit reset code sent to {normalized_email}.",
    )
    return True, f"A 6-digit verification code was sent to {mask_email_address(normalized_email)}."


def reset_password_with_code(email: str, reset_code: str, new_password: str, confirm_password: str) -> tuple[bool, str]:
    normalized_email = email.strip().lower()
    sanitized_code = "".join(ch for ch in reset_code if ch.isdigit())[:6]

    if not normalized_email:
        return False, "Enter the account email address first."
    if len(sanitized_code) != 6:
        return False, "Enter the 6-digit verification code from your email."
    if not new_password or not confirm_password:
        return False, "Enter and confirm your new password."
    if new_password != confirm_password:
        return False, "Passwords do not match."
    is_valid_password, password_error = validate_password_strength(new_password)
    if not is_valid_password:
        return False, password_error

    reset_row = fetch_one(
        """
        SELECT pr.id, pr.user_id, pr.email, pr.reset_code, pr.expires_at, u.fullname, u.role
        FROM password_reset_codes pr
        JOIN users u ON u.id = pr.user_id
        WHERE LOWER(pr.email) = %s AND pr.reset_code = %s AND pr.consumed_at IS NULL
        ORDER BY pr.created_at DESC
        LIMIT 1
        """,
        (normalized_email, sanitized_code),
    )
    if not reset_row:
        return False, "That verification code is invalid. Check the code and try again."
    if reset_row["expires_at"] < datetime.now():
        execute_query(
            """
            UPDATE password_reset_codes
            SET consumed_at = CURRENT_TIMESTAMP
            WHERE id = %s
            """,
            (int(reset_row["id"]),),
        )
        return False, "That verification code has expired. Request a new one."

    execute_query(
        """
        UPDATE users
        SET password_hash = %s
        WHERE id = %s
        """,
        (hash_password(new_password), int(reset_row["user_id"])),
    )
    invalidate_password_reset_codes(int(reset_row["user_id"]))
    log_system_activity(
        actor_name=reset_row["fullname"],
        actor_role=reset_row["role"],
        actor_id=int(reset_row["user_id"]),
        activity="Password reset completed",
        details=f"Password updated through email verification for {normalized_email}.",
    )
    return True, "Password updated successfully. You can sign in now."


def update_user_password_hash(user_id: int, password_hash_value: str) -> None:
    execute_query(
        """
        UPDATE users
        SET password_hash = %s
        WHERE id = %s
        """,
        (password_hash_value, int(user_id)),
    )


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

    existing_user = fetch_one(
        """
        SELECT fullname, email
        FROM users
        WHERE LOWER(fullname) = %s OR LOWER(email) = %s
        LIMIT 1
        """,
        (fullname.lower(), email.lower()),
    )
    if existing_user:
        if existing_user["fullname"].lower() == fullname.lower():
            return False, "That fullname is already registered."
        return False, "That email is already registered."

    execute_query(
        """
        INSERT INTO users (fullname, email, password_hash, role, plan, account_status)
        VALUES (%s, %s, %s, 'user', 'Free', 'active')
        """,
        (fullname, email, hash_password(password)),
    )
    log_system_activity(
        actor_name=fullname,
        actor_role="user",
        activity="Registered account",
        details=f"New user account created for {email}.",
    )
    email_sent, email_status = send_signup_welcome_email(fullname, email)
    log_system_activity(
        actor_name=fullname,
        actor_role="user",
        activity="Welcome email sent" if email_sent else "Welcome email failed",
        details=email_status,
    )
    if email_sent:
        return True, "Account created. You can sign in now. A welcome email was sent to your email address."
    return True, (
        "Account created. You can sign in now. Welcome email could not be sent right now. "
        f"{email_status}"
    )


def authenticate_user(identifier: str, password: str) -> tuple[dict | None, str | None]:
    identifier = identifier.strip().lower()

    user = fetch_one(
        """
        SELECT id, fullname, email, password_hash, role, plan, account_status, created_at
        FROM users
        WHERE LOWER(fullname) = %s OR LOWER(email) = %s
        LIMIT 1
        """,
        (identifier, identifier),
    )
    if not user or not verify_password(password, str(user.get("password_hash", ""))):
        return None, None
    if str(user.get("account_status", "active")).lower() != "active":
        return None, "This account is suspended. Please contact the admin."
    if password_hash_needs_upgrade(str(user.get("password_hash", ""))):
        upgraded_hash = hash_password(password)
        update_user_password_hash(int(user["id"]), upgraded_hash)
        user["password_hash"] = upgraded_hash
    return user, None


def save_key_permanently(key: str) -> None:
    if not insecure_secret_storage_allowed():
        raise RuntimeError(build_secret_storage_error(API_KEY_ENV))
    normalized_key = key.strip()
    execute_query(
        """
        INSERT INTO app_settings (setting_key, setting_value)
        VALUES ('api_key', %s)
        ON DUPLICATE KEY UPDATE setting_value = VALUES(setting_value)
        """,
        (normalized_key,),
    )


def load_key_permanently() -> str:
    env_value = os.getenv(API_KEY_ENV, "").strip()
    if env_value:
        return env_value
    if not insecure_secret_storage_allowed():
        return ""

    setting_row = fetch_one(
        "SELECT setting_value FROM app_settings WHERE setting_key = 'api_key' LIMIT 1"
    )
    saved_value = (setting_row["setting_value"] if setting_row else "") or ""
    if saved_value.strip():
        return saved_value.strip()

    legacy_value = read_legacy_text(LEGACY_API_KEY_FILE)
    if legacy_value:
        save_key_permanently(legacy_value)
        return legacy_value
    return ""


def save_gmail_sender_email_permanently(sender_email: str) -> None:
    normalized_email = sender_email.strip().lower()
    execute_query(
        """
        INSERT INTO app_settings (setting_key, setting_value)
        VALUES ('gmail_sender_email', %s)
        ON DUPLICATE KEY UPDATE setting_value = VALUES(setting_value)
        """,
        (normalized_email,),
    )


def load_gmail_sender_email_permanently() -> str:
    env_value = os.getenv(GMAIL_SENDER_EMAIL_ENV, "").strip().lower()
    if env_value:
        return env_value

    setting_row = fetch_one(
        "SELECT setting_value FROM app_settings WHERE setting_key = 'gmail_sender_email' LIMIT 1"
    )
    saved_value = (setting_row["setting_value"] if setting_row else "") or ""
    return saved_value.strip().lower()


def save_gmail_app_password_permanently(app_password: str) -> None:
    if not insecure_secret_storage_allowed():
        raise RuntimeError(build_secret_storage_error(GMAIL_APP_PASSWORD_ENV))
    normalized_password = app_password.replace(" ", "").strip()
    execute_query(
        """
        INSERT INTO app_settings (setting_key, setting_value)
        VALUES ('gmail_app_password', %s)
        ON DUPLICATE KEY UPDATE setting_value = VALUES(setting_value)
        """,
        (normalized_password,),
    )


def load_gmail_app_password_permanently() -> str:
    env_value = os.getenv(GMAIL_APP_PASSWORD_ENV, "").replace(" ", "").strip()
    if env_value:
        return env_value
    if not insecure_secret_storage_allowed():
        return ""

    setting_row = fetch_one(
        "SELECT setting_value FROM app_settings WHERE setting_key = 'gmail_app_password' LIMIT 1"
    )
    saved_value = (setting_row["setting_value"] if setting_row else "") or ""
    return saved_value.replace(" ", "").strip()


def save_system_prompt_permanently(prompt: str) -> None:
    normalized_prompt = prompt.strip()
    execute_query(
        """
        INSERT INTO app_settings (setting_key, setting_value)
        VALUES ('system_prompt', %s)
        ON DUPLICATE KEY UPDATE setting_value = VALUES(setting_value)
        """,
        (normalized_prompt,),
    )


def load_system_prompt_permanently() -> str:
    env_value = os.getenv(SYSTEM_PROMPT_ENV, "").strip()
    if env_value:
        return env_value

    setting_row = fetch_one(
        "SELECT setting_value FROM app_settings WHERE setting_key = 'system_prompt' LIMIT 1"
    )
    saved_value = (setting_row["setting_value"] if setting_row else "") or ""
    normalized_saved = saved_value.strip()
    legacy_value = read_legacy_text(LEGACY_SYSTEM_PROMPT_FILE)

    if normalized_saved and normalized_saved != DEFAULT_SYSTEM_PROMPT:
        return normalized_saved

    if legacy_value and legacy_value != normalized_saved:
        save_system_prompt_permanently(legacy_value)
        return legacy_value

    if normalized_saved:
        return normalized_saved
    return DEFAULT_SYSTEM_PROMPT


def persist_system_prompt() -> None:
    current_prompt = st.session_state.system_prompt_field.strip() or DEFAULT_SYSTEM_PROMPT
    st.session_state.saved_system_prompt = current_prompt
    st.session_state.system_prompt_field = current_prompt
    save_system_prompt_permanently(current_prompt)
    current_user = st.session_state.get("current_user")
    if current_user and current_user.get("role") == "admin":
        log_system_activity(
            actor_name=current_user["fullname"],
            actor_role="admin",
            actor_id=int(current_user["id"]),
            activity="Updated master system prompt",
            details=f"Master prompt saved with {len(current_prompt)} characters.",
        )


def sync_system_prompt_state() -> str:
    active_prompt = load_system_prompt_permanently()
    st.session_state.saved_system_prompt = active_prompt
    st.session_state.system_prompt_field = active_prompt
    return active_prompt


def get_actual_usage() -> pd.DataFrame:
    usage_rows = fetch_all(
        """
        SELECT usage_date, total_tokens
        FROM (
            SELECT DATE(created_at) AS usage_date, SUM(tokens) AS total_tokens
            FROM usage_logs
            GROUP BY DATE(created_at)
            ORDER BY usage_date DESC
            LIMIT 14
        ) recent_usage
        ORDER BY usage_date ASC
        """
    )

    if not usage_rows:
        return pd.DataFrame(columns=["Date", "Tokens"])

    formatted_rows = []
    for row in usage_rows:
        usage_date = row.get("usage_date")
        if hasattr(usage_date, "strftime"):
            label = usage_date.strftime("%b %d, %Y")
        else:
            label = str(usage_date)
        formatted_rows.append({"Date": label, "Tokens": int(row.get("total_tokens") or 0)})

    return pd.DataFrame(formatted_rows)


def append_usage(tokens: int) -> None:
    day = datetime.now().strftime("%a")[:3]
    execute_query(
        "INSERT INTO usage_logs (day, tokens) VALUES (%s, %s)",
        (day, int(tokens)),
    )


def record_user_document(user_id: int, file_name: str, subject: str = "General") -> int:
    return execute_query(
        """
        INSERT INTO user_documents (user_id, file_name, subject)
        VALUES (%s, %s, %s)
        """,
        (user_id, file_name, subject),
    )


def load_user_documents(user_id: int) -> list[dict]:
    return fetch_all(
        """
        SELECT file_name, subject, uploaded_at
        FROM user_documents
        WHERE user_id = %s
        ORDER BY uploaded_at DESC, id DESC
        """,
        (user_id,),
    )


def get_total_document_count() -> int:
    document_row = fetch_one("SELECT COUNT(*) AS total_documents FROM user_documents")
    return int(document_row["total_documents"]) if document_row else 0


def infer_subject_from_filename(file_name: str) -> str:
    lowered = file_name.lower()
    keyword_map = {
        "Mathematics": ["math", "algebra", "geometry", "calculus", "statistics"],
        "Biology": ["bio", "biology", "cell", "genetics", "anatomy"],
        "Chemistry": ["chem", "chemistry", "atom", "molecule", "reaction"],
        "Physics": ["physics", "motion", "force", "energy", "wave"],
        "History": ["history", "civilization", "war", "empire", "revolution"],
        "English": ["english", "literature", "grammar", "reading", "writing"],
        "Computer Science": ["computer", "program", "python", "coding", "software"],
    }

    for subject, keywords in keyword_map.items():
        if any(keyword in lowered for keyword in keywords):
            return subject
    return "General"


def normalize_system_prompt(system_prompt: str | None) -> str:
    compact_prompt = " ".join((system_prompt or "").split())
    return compact_prompt or DEFAULT_SYSTEM_PROMPT


def clean_extracted_text(raw_text: str, limit: int = 12000) -> str:
    cleaned_text = raw_text.replace("\x00", " ")
    cleaned_text = re.sub(r"\r\n?", "\n", cleaned_text)
    cleaned_text = re.sub(r"[ \t]+", " ", cleaned_text)
    cleaned_text = re.sub(r"\n{3,}", "\n\n", cleaned_text).strip()
    return cleaned_text[:limit].strip()


def extract_xml_text_chunks(xml_bytes: bytes) -> list[str]:
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return []

    text_chunks: list[str] = []
    for node in root.iter():
        node_text = (node.text or "").strip()
        if not node_text:
            continue
        if not re.search(r"[A-Za-z0-9]", node_text):
            continue
        if len(node_text) > 400:
            node_text = node_text[:400].strip()
        text_chunks.append(node_text)
    return text_chunks


def extract_text_from_docx(file_bytes: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(file_bytes)) as archive:
        document_xml = archive.read("word/document.xml")
    root = ET.fromstring(document_xml)
    namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    text_chunks = [node.text for node in root.findall(".//w:t", namespace) if node.text]
    return clean_extracted_text("\n".join(text_chunks))


def extract_text_from_pptx(file_bytes: bytes) -> str:
    slides_text: list[str] = []
    with zipfile.ZipFile(io.BytesIO(file_bytes)) as archive:
        slide_files = sorted(
            file_name
            for file_name in archive.namelist()
            if file_name.startswith("ppt/slides/slide") and file_name.endswith(".xml")
        )
        for slide_index, slide_file in enumerate(slide_files, start=1):
            text_chunks = extract_xml_text_chunks(archive.read(slide_file))
            if text_chunks:
                slides_text.append(f"Slide {slide_index}: " + " ".join(text_chunks))
        if not slides_text:
            extra_xml_files = sorted(
                file_name
                for file_name in archive.namelist()
                if file_name.startswith("ppt/")
                and file_name.endswith(".xml")
                and "/_rels/" not in file_name
            )
            for xml_file in extra_xml_files:
                text_chunks = extract_xml_text_chunks(archive.read(xml_file))
                if text_chunks:
                    slides_text.append(" ".join(text_chunks))
    return clean_extracted_text("\n\n".join(slides_text))


def extract_text_from_pdf(file_bytes: bytes) -> str:
    try:
        from pypdf import PdfReader  # type: ignore
    except ImportError:
        try:
            from PyPDF2 import PdfReader  # type: ignore
        except ImportError:
            return ""

    reader = PdfReader(io.BytesIO(file_bytes))
    text_chunks = []
    for page in reader.pages:
        page_text = page.extract_text() or ""
        if page_text.strip():
            text_chunks.append(page_text)
    return clean_extracted_text("\n\n".join(text_chunks))


def extract_uploaded_file_text(uploaded_file) -> str:
    if not uploaded_file:
        return ""

    file_bytes = uploaded_file.getvalue()
    suffix = Path(getattr(uploaded_file, "name", "")).suffix.lower()

    try:
        if suffix in {".txt", ".md", ".csv", ".json", ".py"}:
            return clean_extracted_text(file_bytes.decode("utf-8", errors="ignore"))
        if suffix == ".docx":
            return extract_text_from_docx(file_bytes)
        if suffix == ".pptx":
            return extract_text_from_pptx(file_bytes)
        if suffix == ".pdf":
            return extract_text_from_pdf(file_bytes)
    except Exception:
        return ""

    return ""


def summarize_system_prompt(system_prompt: str | None, limit: int = 180) -> str:
    normalized_prompt = normalize_system_prompt(system_prompt)
    if len(normalized_prompt) <= limit:
        return normalized_prompt
    return normalized_prompt[: limit - 3].rstrip() + "..."


def normalize_summary_preference_label(summary_preference: str) -> str:
    normalized_preference = (summary_preference or "").strip().lower()
    if "detailed" in normalized_preference:
        return "Detailed Summary"
    return "Short Summary"


def get_quiz_configuration(quiz_preference: str) -> dict:
    normalized_preference = quiz_preference.lower()
    if "beginner" in normalized_preference or "easy" in normalized_preference:
        return {
            "difficulty": "easy",
            "item_count": 15,
            "allowed_types": ["multiple_choice"],
            "type_distribution": [("multiple_choice", 15)],
            "label": "Beginner Quiz",
            "display_name": "Beginner",
        }
    if "intermediate" in normalized_preference or "intermidiate" in normalized_preference or "medium" in normalized_preference:
        return {
            "difficulty": "medium",
            "item_count": 30,
            "allowed_types": ["true_false", "matching"],
            "type_distribution": [("true_false", 10), ("matching", 20)],
            "label": "Intermediate Quiz",
            "display_name": "Intermediate",
        }
    return {
        "difficulty": "hard",
        "item_count": 60,
        "allowed_types": ["modified_true_false", "identification", "enumeration"],
        "type_distribution": [("modified_true_false", 20), ("identification", 20), ("enumeration", 20)],
        "label": "Advanced Quiz",
        "display_name": "Advanced",
    }


def normalize_quiz_preference_label(quiz_preference: str) -> str:
    quiz_config = get_quiz_configuration(quiz_preference or "")
    return f"{quiz_config['display_name']} ({quiz_config['item_count']} items)"


def get_quiz_difficulty_option_labels() -> list[str]:
    return [
        "Beginner (15 items)",
        "Intermediate (30 items)",
        "Advanced (60 items)",
    ]


def get_quiz_question_description(question_type: str) -> str:
    descriptions = {
        "multiple_choice": "Multiple Choice: Choose your best answer from the four options below.",
        "true_false": "True or False: Decide if the statement is correct, then choose True or False.",
        "matching": "Matching Type: Pick one unique answer from the answer pool below.",
        "modified_true_false": "Modified True or False: Write TRUE if the statement is correct. If it is false, write the correct answer on the blank and highlight the word or phrase that makes it wrong.",
        "identification": "Identification: Write the correct term, concept, or answer on the blank.",
        "enumeration": "Enumeration: List all required answers clearly in the numbered blanks.",
    }
    return descriptions.get(question_type, "Answer the question carefully using the information from the reviewer.")


def apply_quiz_type_distribution(normalized_payload: list[dict], quiz_config: dict) -> list[dict]:
    distribution = quiz_config.get("type_distribution", [])
    if not distribution:
        return normalized_payload[: int(quiz_config["item_count"])]

    distributed_payload: list[dict] = []
    for question_type, question_count in distribution:
        matching_items = [item for item in normalized_payload if item.get("type") == question_type]
        if len(matching_items) < int(question_count):
            raise ValueError(f"Generated quiz did not include enough {question_type} items.")
        distributed_payload.extend(matching_items[: int(question_count)])
    return distributed_payload[: int(quiz_config["item_count"])]


def extract_focus_terms(module_text: str, subject: str, limit: int = 18) -> list[str]:
    stopwords = {
        "about",
        "after",
        "again",
        "answer",
        "answers",
        "around",
        "article",
        "articles",
        "become",
        "below",
        "between",
        "chapter",
        "chapters",
        "choose",
        "clue",
        "clues",
        "concept",
        "concepts",
        "could",
        "detail",
        "details",
        "each",
        "every",
        "first",
        "follow",
        "form",
        "forms",
        "found",
        "group",
        "important",
        "into",
        "item",
        "items",
        "lesson",
        "linked",
        "match",
        "matching",
        "mode",
        "module",
        "other",
        "page",
        "pages",
        "point",
        "points",
        "ppt",
        "pptx",
        "quiz",
        "reviewer",
        "reviewers",
        "section",
        "sections",
        "should",
        "slide",
        "slides",
        "some",
        "study",
        "subject",
        "summary",
        "their",
        "there",
        "these",
        "the",
        "those",
        "title",
        "titles",
        "topic",
        "topics",
        "through",
        "under",
        "using",
        "value",
        "values",
        "way",
        "ways",
        "which",
        "would",
        "review",
        "student",
        "students",
        "teacher",
        "because",
        "being",
        "while",
        "where",
        "when",
        "also",
        "have",
        "with",
        "from",
        "that",
        "this",
        "your",
    }
    words = re.findall(r"[A-Za-z][A-Za-z\-]{2,}", module_text or "")
    seen: set[str] = set()
    focus_terms: list[str] = []
    for word in words:
        normalized = word.lower()
        if normalized in stopwords or normalized == subject.lower():
            continue
        if normalized not in seen:
            seen.add(normalized)
            focus_terms.append(word.strip("-").title())
        if len(focus_terms) >= limit:
            break

    if not focus_terms:
        base_terms = [
            subject,
            "Concept",
            "Principle",
            "Technique",
            "Example",
            "Definition",
            "Application",
            "Process",
            "Analysis",
            "Comparison",
            "Interpretation",
            "Structure",
            "Detail",
            "Meaning",
            "Context",
            "Review",
            "Practice",
            "Recall",
        ]
        focus_terms = base_terms[:limit]

    while len(focus_terms) < limit:
        focus_terms.append(f"{subject} Topic {len(focus_terms) + 1}")

    return focus_terms[:limit]


def build_matching_clue_from_module(module_text: str, match_term: str, subject: str, clue_number: int) -> str:
    normalized_term = match_term.strip()
    if not normalized_term:
        return f"Choose the reviewer term that matches clue #{clue_number} for the {subject} lesson."

    sentence_candidates = [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?])\s+|\n+", module_text or "")
        if sentence.strip()
    ]
    search_pattern = re.compile(rf"\b{re.escape(normalized_term)}\b", re.IGNORECASE)

    for sentence in sentence_candidates:
        if len(sentence) < 24:
            continue
        if not search_pattern.search(sentence):
            continue
        clue_sentence = search_pattern.sub("__________", sentence, count=1).strip()
        clue_sentence = re.sub(r"\s{2,}", " ", clue_sentence)
        if len(clue_sentence) > 180:
            clue_sentence = clue_sentence[:177].rstrip(" ,;:-") + "..."
        return f"Choose the reviewer term that completes this clue: {clue_sentence}"

    word_count = len(normalized_term.split())
    return (
        f"Choose the reviewer term from the answer pool. Clue #{clue_number}: "
        f"it starts with '{normalized_term[0].upper()}' and has {word_count} word(s)."
    )


def get_module_sentence_candidates(module_text: str) -> list[str]:
    sentence_candidates: list[str] = []
    for raw_sentence in re.split(r"(?<=[.!?])\s+|\n+", module_text or ""):
        sentence = re.sub(r"\s+", " ", raw_sentence or "").strip(" -\t")
        if len(sentence) < 24:
            continue
        sentence_candidates.append(sentence)
    return sentence_candidates


def find_sentence_for_term(module_text: str, term: str) -> str | None:
    if not term.strip():
        return None

    search_pattern = re.compile(rf"\b{re.escape(term.strip())}\b", re.IGNORECASE)
    ranked_sentences: list[tuple[int, str]] = []
    for sentence in get_module_sentence_candidates(module_text):
        if not search_pattern.search(sentence):
            continue

        score = 0
        if 35 <= len(sentence) <= 180:
            score += 3
        if sentence.count(",") <= 2:
            score += 1
        if not sentence.endswith(":"):
            score += 1
        ranked_sentences.append((score, sentence))

    if not ranked_sentences:
        return None

    ranked_sentences.sort(key=lambda item: item[0], reverse=True)
    return ranked_sentences[0][1]


def replace_term_once(sentence: str, source_term: str, replacement_term: str) -> str:
    return re.sub(
        rf"\b{re.escape(source_term.strip())}\b",
        replacement_term.strip(),
        sentence,
        count=1,
        flags=re.IGNORECASE,
    )


def build_true_false_statement_from_module(
    module_text: str,
    subject: str,
    focus_term: str,
    alternate_term: str,
    is_true: bool,
) -> str:
    focus_sentence = find_sentence_for_term(module_text, focus_term)
    if focus_sentence:
        if is_true:
            return focus_sentence
        mutated_sentence = replace_term_once(focus_sentence, focus_term, alternate_term)
        if mutated_sentence != focus_sentence:
            return mutated_sentence

    if is_true:
        return f"In the {subject} lesson, {focus_term} is presented as a concept students should understand."
    return f"In the {subject} lesson, {alternate_term} is presented as the same idea as {focus_term}."


def build_identification_prompt_from_module(module_text: str, focus_term: str, subject: str) -> str:
    focus_sentence = find_sentence_for_term(module_text, focus_term)
    if focus_sentence:
        masked_sentence = replace_term_once(focus_sentence, focus_term, "__________")
        if masked_sentence != focus_sentence:
            return f"Identify the missing lesson term: {masked_sentence}"

    return f"Identify the lesson term connected to this {subject} idea: {focus_term[0].upper()}..."


def build_enumeration_prompt_and_answers(
    module_text: str,
    subject: str,
    focus_terms: list[str],
    start_index: int,
) -> tuple[str, list[str]]:
    sentence_candidates = get_module_sentence_candidates(module_text)
    lower_lookup = {term.lower(): term for term in focus_terms}

    for sentence in sentence_candidates:
        matched_terms: list[str] = []
        for term in focus_terms:
            if re.search(rf"\b{re.escape(term)}\b", sentence, re.IGNORECASE):
                canonical_term = lower_lookup.get(term.lower(), term)
                if canonical_term not in matched_terms:
                    matched_terms.append(canonical_term)
            if len(matched_terms) >= 3:
                break
        if matched_terms:
            for offset in range(len(focus_terms)):
                candidate = focus_terms[(start_index + offset) % len(focus_terms)]
                if candidate not in matched_terms:
                    matched_terms.append(candidate)
                if len(matched_terms) >= 3:
                    break

            snippet = sentence if len(sentence) <= 180 else sentence[:177].rstrip(" ,;:-") + "..."
            return (
                f"Based on this lesson context, list the three related terms or details: {snippet}",
                matched_terms[:3],
            )

    fallback_answers: list[str] = []
    for offset in range(3):
        candidate = focus_terms[(start_index + offset) % len(focus_terms)]
        if candidate not in fallback_answers:
            fallback_answers.append(candidate)

    return (
        f"List three important terms or details mentioned in the {subject} lesson.",
        fallback_answers[:3],
    )


def coerce_bool(value) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "t", "yes"}:
            return True
        if lowered in {"false", "f", "no"}:
            return False
    return None


def to_string_list(value) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [part.strip() for part in re.split(r",|\n", value) if part.strip()]
    return []


def build_fallback_quiz_payload(
    file_name: str,
    subject: str,
    quiz_preference: str,
    module_text: str,
) -> list[dict]:
    quiz_config = get_quiz_configuration(quiz_preference)
    item_count = int(quiz_config["item_count"])
    focus_terms = extract_focus_terms(module_text, subject, limit=max(18, item_count))
    difficulty = quiz_config["difficulty"]

    if difficulty == "easy":
        quiz_payload = []
        for index in range(item_count):
            correct_term = focus_terms[index % len(focus_terms)]
            options = [
                correct_term,
                focus_terms[(index + 1) % len(focus_terms)],
                focus_terms[(index + 2) % len(focus_terms)],
                focus_terms[(index + 3) % len(focus_terms)],
            ]
            quiz_payload.append(
                {
                    "type": "multiple_choice",
                    "prompt": f"Which term belongs to the {subject} reviewer focus for item {index + 1}?",
                    "options": options,
                    "answer_index": 0,
                    "hint": f"Review the concept related to {correct_term}.",
                }
            )
        return quiz_payload

    if difficulty == "medium":
        true_false_count = 10
        matching_count = item_count - true_false_count
        matching_answers = focus_terms[:matching_count]
        quiz_payload = []
        for index in range(true_false_count):
            statement_term = focus_terms[index % len(focus_terms)]
            alternate_term = focus_terms[(index + 5) % len(focus_terms)]
            is_true = index % 4 != 1
            statement = build_true_false_statement_from_module(
                module_text=module_text,
                subject=subject,
                focus_term=statement_term,
                alternate_term=alternate_term,
                is_true=is_true,
            )
            quiz_payload.append(
                {
                    "type": "true_false",
                    "statement": statement,
                    "answer_bool": is_true,
                    "hint": "Decide whether the statement matches the lesson content from the module.",
                }
            )
        for index in range(matching_count):
            match_term = matching_answers[index % len(matching_answers)]
            quiz_payload.append(
                {
                    "type": "matching",
                    "prompt": build_matching_clue_from_module(module_text, match_term, subject, index + 1),
                    "correct_answer": match_term,
                    "match_options": matching_answers,
                    "hint": "Each matching answer can only be used once.",
                }
            )
        return quiz_payload

    quiz_payload = []
    for question_type, question_count in quiz_config["type_distribution"]:
        for offset in range(question_count):
            index = len(quiz_payload)
            focus_term = focus_terms[index % len(focus_terms)]
            if question_type == "modified_true_false":
                is_true = offset % 2 == 0
                wrong_term = focus_terms[(index + 4) % len(focus_terms)]
                base_statement = build_true_false_statement_from_module(
                    module_text=module_text,
                    subject=subject,
                    focus_term=focus_term,
                    alternate_term=wrong_term,
                    is_true=True,
                )
                statement = base_statement if is_true else replace_term_once(base_statement, focus_term, wrong_term)
                quiz_payload.append(
                    {
                        "type": "modified_true_false",
                        "statement": statement,
                        "answer_bool": is_true,
                        "incorrect_phrase": "" if is_true else wrong_term,
                        "replacement_answer": "TRUE" if is_true else focus_term,
                        "hint": "Write TRUE if the statement is correct. If false, write the correct replacement and highlight the wrong phrase.",
                    }
                )
            elif question_type == "identification":
                quiz_payload.append(
                    {
                        "type": "identification",
                        "prompt": build_identification_prompt_from_module(module_text, focus_term, subject),
                        "accepted_answers": [focus_term],
                        "hint": f"The expected answer is the lesson term hidden or described in the prompt.",
                    }
                )
            else:
                enum_prompt, enum_answers = build_enumeration_prompt_and_answers(
                    module_text=module_text,
                    subject=subject,
                    focus_terms=focus_terms,
                    start_index=index,
                )
                quiz_payload.append(
                    {
                        "type": "enumeration",
                        "prompt": enum_prompt,
                        "accepted_answers": enum_answers,
                        "hint": "Use one blank per answer.",
                    }
                )
    return quiz_payload


def normalize_generated_quiz_payload(raw_payload: list[dict], quiz_preference: str) -> list[dict]:
    quiz_config = get_quiz_configuration(quiz_preference)
    allowed_types = set(quiz_config["allowed_types"])
    normalized_payload: list[dict] = []

    for raw_item in raw_payload:
        if not isinstance(raw_item, dict):
            continue

        question_type = str(raw_item.get("type") or "").strip().lower()
        if not question_type and isinstance(raw_item.get("options"), list):
            question_type = "multiple_choice"

        if question_type not in allowed_types:
            continue

        hint = str(raw_item.get("hint", "")).strip() or "Review the lesson and answer carefully."
        if question_type == "multiple_choice":
            options = [str(option).strip() for option in raw_item.get("options", []) if str(option).strip()]
            answer_index = raw_item.get("answer_index", 0)
            try:
                answer_index = int(answer_index)
            except (TypeError, ValueError):
                continue
            prompt = str(raw_item.get("prompt", "")).strip()
            if prompt and len(options) == 4 and 0 <= answer_index <= 3:
                normalized_payload.append(
                    {
                        "type": "multiple_choice",
                        "prompt": prompt,
                        "options": options,
                        "answer_index": answer_index,
                        "hint": hint,
                    }
                )
        elif question_type == "true_false":
            statement = str(raw_item.get("statement") or raw_item.get("prompt") or "").strip()
            answer_bool = coerce_bool(raw_item.get("answer_bool", raw_item.get("answer")))
            if statement and answer_bool is not None:
                normalized_payload.append(
                    {
                        "type": "true_false",
                        "statement": statement,
                        "answer_bool": answer_bool,
                        "hint": hint,
                    }
                )
        elif question_type == "matching":
            prompt = str(raw_item.get("prompt", "")).strip()
            correct_answer = str(raw_item.get("correct_answer") or raw_item.get("answer") or "").strip()
            match_options = [str(option).strip() for option in raw_item.get("match_options", raw_item.get("options", [])) if str(option).strip()]
            if prompt and correct_answer and len(match_options) >= 2:
                if correct_answer not in match_options:
                    match_options.append(correct_answer)
                normalized_payload.append(
                    {
                        "type": "matching",
                        "prompt": prompt,
                        "correct_answer": correct_answer,
                        "match_options": match_options,
                        "hint": hint,
                    }
                )
        elif question_type == "modified_true_false":
            statement = str(raw_item.get("statement") or raw_item.get("prompt") or "").strip()
            answer_bool = coerce_bool(raw_item.get("answer_bool", raw_item.get("answer")))
            incorrect_phrase = str(raw_item.get("incorrect_phrase") or raw_item.get("wrong_phrase") or "").strip()
            replacement_answer = str(raw_item.get("replacement_answer") or raw_item.get("correct_answer") or "").strip()
            if statement and answer_bool is not None and (answer_bool or (incorrect_phrase and replacement_answer)):
                normalized_payload.append(
                    {
                        "type": "modified_true_false",
                        "statement": statement,
                        "answer_bool": answer_bool,
                        "incorrect_phrase": incorrect_phrase,
                        "replacement_answer": replacement_answer or ("TRUE" if answer_bool else ""),
                        "hint": hint,
                    }
                )
        elif question_type == "identification":
            prompt = str(raw_item.get("prompt", "")).strip()
            accepted_answers = to_string_list(raw_item.get("accepted_answers", raw_item.get("answer")))
            if prompt and accepted_answers:
                normalized_payload.append(
                    {
                        "type": "identification",
                        "prompt": prompt,
                        "accepted_answers": accepted_answers,
                        "hint": hint,
                    }
                )
        elif question_type == "enumeration":
            prompt = str(raw_item.get("prompt", "")).strip()
            accepted_answers = to_string_list(raw_item.get("accepted_answers", raw_item.get("answer")))
            if prompt and len(accepted_answers) >= 2:
                normalized_payload.append(
                    {
                        "type": "enumeration",
                        "prompt": prompt,
                        "accepted_answers": accepted_answers,
                        "hint": hint,
                    }
                )

    if len(normalized_payload) < quiz_config["item_count"]:
        raise ValueError("Generated quiz payload did not include enough valid items.")

    normalized_payload = apply_quiz_type_distribution(normalized_payload, quiz_config)

    if quiz_config["difficulty"] == "medium":
        type_distribution = [item["type"] for item in normalized_payload]
        if type_distribution[:10] != ["true_false"] * 10 or type_distribution[10:] != ["matching"] * 20:
            raise ValueError("Intermediate quiz must contain 10 true/false items followed by 20 matching items.")
        matching_answers = [item["correct_answer"] for item in normalized_payload if item["type"] == "matching"]
        if len(set(matching_answers)) != len(matching_answers):
            raise ValueError("Matching answers must be unique.")
        shared_pool = list(dict.fromkeys(matching_answers))
        for item in normalized_payload:
            if item["type"] == "matching":
                item["match_options"] = shared_pool

    if quiz_config["difficulty"] == "hard":
        type_distribution = [item["type"] for item in normalized_payload]
        expected_distribution = (
            ["modified_true_false"] * 20
            + ["identification"] * 20
            + ["enumeration"] * 20
        )
        if type_distribution != expected_distribution:
            raise ValueError("Advanced quiz must contain 20 modified true or false, 20 identification, and 20 enumeration items.")

    return normalized_payload


def normalize_generated_quiz_batch(
    raw_payload: list[dict],
    question_type: str,
    expected_count: int,
) -> list[dict]:
    normalized_items: list[dict] = []
    for raw_item in raw_payload:
        if not isinstance(raw_item, dict):
            continue
        item_type = str(raw_item.get("type") or "").strip().lower()
        if not item_type and isinstance(raw_item.get("options"), list):
            item_type = "multiple_choice"
        if item_type != question_type:
            continue

        hint = str(raw_item.get("hint", "")).strip() or "Review the reviewer and answer carefully."
        if question_type == "multiple_choice":
            options = [str(option).strip() for option in raw_item.get("options", []) if str(option).strip()]
            prompt = str(raw_item.get("prompt", "")).strip()
            try:
                answer_index = int(raw_item.get("answer_index", 0))
            except (TypeError, ValueError):
                continue
            if prompt and len(options) == 4 and 0 <= answer_index <= 3:
                normalized_items.append(
                    {
                        "type": "multiple_choice",
                        "prompt": prompt,
                        "options": options,
                        "answer_index": answer_index,
                        "hint": hint,
                    }
                )
        elif question_type == "true_false":
            statement = str(raw_item.get("statement") or raw_item.get("prompt") or "").strip()
            answer_bool = coerce_bool(raw_item.get("answer_bool", raw_item.get("answer")))
            if statement and answer_bool is not None:
                normalized_items.append(
                    {
                        "type": "true_false",
                        "statement": statement,
                        "answer_bool": answer_bool,
                        "hint": hint,
                    }
                )
        elif question_type == "matching":
            prompt = str(raw_item.get("prompt", "")).strip()
            correct_answer = str(raw_item.get("correct_answer") or raw_item.get("answer") or "").strip()
            match_options = [str(option).strip() for option in raw_item.get("match_options", raw_item.get("options", [])) if str(option).strip()]
            if prompt and correct_answer and len(match_options) >= 2:
                if correct_answer not in match_options:
                    match_options.append(correct_answer)
                normalized_items.append(
                    {
                        "type": "matching",
                        "prompt": prompt,
                        "correct_answer": correct_answer,
                        "match_options": match_options,
                        "hint": hint,
                    }
                )
        elif question_type == "modified_true_false":
            statement = str(raw_item.get("statement") or raw_item.get("prompt") or "").strip()
            answer_bool = coerce_bool(raw_item.get("answer_bool", raw_item.get("answer")))
            incorrect_phrase = str(raw_item.get("incorrect_phrase") or raw_item.get("wrong_phrase") or "").strip()
            replacement_answer = str(raw_item.get("replacement_answer") or raw_item.get("correct_answer") or "").strip()
            if statement and answer_bool is not None and (answer_bool or (incorrect_phrase and replacement_answer)):
                normalized_items.append(
                    {
                        "type": "modified_true_false",
                        "statement": statement,
                        "answer_bool": answer_bool,
                        "incorrect_phrase": incorrect_phrase,
                        "replacement_answer": replacement_answer or ("TRUE" if answer_bool else ""),
                        "hint": hint,
                    }
                )
        elif question_type == "identification":
            prompt = str(raw_item.get("prompt", "")).strip()
            accepted_answers = to_string_list(raw_item.get("accepted_answers", raw_item.get("answer")))
            if prompt and accepted_answers:
                normalized_items.append(
                    {
                        "type": "identification",
                        "prompt": prompt,
                        "accepted_answers": accepted_answers,
                        "hint": hint,
                    }
                )
        elif question_type == "enumeration":
            prompt = str(raw_item.get("prompt", "")).strip()
            accepted_answers = to_string_list(raw_item.get("accepted_answers", raw_item.get("answer")))
            if prompt and len(accepted_answers) >= 2:
                normalized_items.append(
                    {
                        "type": "enumeration",
                        "prompt": prompt,
                        "accepted_answers": accepted_answers,
                        "hint": hint,
                    }
                )

    if question_type == "matching":
        unique_matching_items: list[dict] = []
        seen_answers: set[str] = set()
        for item in normalized_items:
            answer_key = item["correct_answer"].strip().lower()
            if answer_key in seen_answers:
                continue
            seen_answers.add(answer_key)
            unique_matching_items.append(item)
        normalized_items = unique_matching_items

    if len(normalized_items) < expected_count:
        raise ValueError(f"Generated {question_type} batch did not include enough valid items.")

    return normalized_items[:expected_count]


def normalize_loaded_quiz_payload(raw_payload: list[dict]) -> list[dict]:
    normalized_payload: list[dict] = []
    for raw_item in raw_payload:
        if not isinstance(raw_item, dict):
            continue
        question_type = str(raw_item.get("type") or "").strip().lower()
        if not question_type and isinstance(raw_item.get("options"), list):
            question_type = "multiple_choice"
        if question_type == "multiple_choice":
            options = [str(option).strip() for option in raw_item.get("options", []) if str(option).strip()]
            try:
                answer_index = int(raw_item.get("answer_index", 0))
            except (TypeError, ValueError):
                answer_index = 0
            normalized_payload.append(
                {
                    "type": "multiple_choice",
                    "prompt": str(raw_item.get("prompt", "")).strip(),
                    "options": options,
                    "answer_index": answer_index,
                    "hint": str(raw_item.get("hint", "")).strip(),
                }
            )
        elif question_type == "true_false":
            normalized_payload.append(
                {
                    "type": "true_false",
                    "statement": str(raw_item.get("statement") or raw_item.get("prompt") or "").strip(),
                    "answer_bool": bool(coerce_bool(raw_item.get("answer_bool", raw_item.get("answer")))),
                    "hint": str(raw_item.get("hint", "")).strip(),
                }
            )
        elif question_type == "matching":
            match_options = [str(option).strip() for option in raw_item.get("match_options", raw_item.get("options", [])) if str(option).strip()]
            correct_answer = str(raw_item.get("correct_answer") or raw_item.get("answer") or "").strip()
            if correct_answer and correct_answer not in match_options:
                match_options.append(correct_answer)
            normalized_payload.append(
                {
                    "type": "matching",
                    "prompt": str(raw_item.get("prompt", "")).strip(),
                    "correct_answer": correct_answer,
                    "match_options": match_options,
                    "hint": str(raw_item.get("hint", "")).strip(),
                }
            )
        elif question_type == "modified_true_false":
            normalized_payload.append(
                {
                    "type": "modified_true_false",
                    "statement": str(raw_item.get("statement") or raw_item.get("prompt") or "").strip(),
                    "answer_bool": bool(coerce_bool(raw_item.get("answer_bool", raw_item.get("answer")))),
                    "incorrect_phrase": str(raw_item.get("incorrect_phrase") or raw_item.get("wrong_phrase") or "").strip(),
                    "replacement_answer": str(raw_item.get("replacement_answer") or raw_item.get("correct_answer") or "").strip(),
                    "hint": str(raw_item.get("hint", "")).strip(),
                }
            )
        elif question_type == "identification":
            normalized_payload.append(
                {
                    "type": "identification",
                    "prompt": str(raw_item.get("prompt", "")).strip(),
                    "accepted_answers": to_string_list(raw_item.get("accepted_answers", raw_item.get("answer"))),
                    "hint": str(raw_item.get("hint", "")).strip(),
                }
            )
        elif question_type == "enumeration":
            normalized_payload.append(
                {
                    "type": "enumeration",
                    "prompt": str(raw_item.get("prompt", "")).strip(),
                    "accepted_answers": to_string_list(raw_item.get("accepted_answers", raw_item.get("answer"))),
                    "hint": str(raw_item.get("hint", "")).strip(),
                }
            )
    return [item for item in normalized_payload if any(str(value).strip() for value in item.values())]


def strip_json_fences(raw_text: str) -> str:
    trimmed_text = raw_text.strip()
    if trimmed_text.startswith("```"):
        trimmed_text = re.sub(r"^```(?:json)?\s*", "", trimmed_text)
        trimmed_text = re.sub(r"\s*```$", "", trimmed_text)
    return trimmed_text.strip()


def parse_generation_json(raw_text: str) -> dict:
    cleaned_text = strip_json_fences(raw_text)
    start_index = cleaned_text.find("{")
    end_index = cleaned_text.rfind("}")
    if start_index == -1 or end_index == -1:
        raise ValueError("Model output did not contain JSON.")
    return json.loads(cleaned_text[start_index : end_index + 1])


def build_fallback_reviewer_package(
    file_name: str,
    subject: str,
    summary_preference: str,
    quiz_preference: str,
    module_text: str,
    system_prompt: str,
) -> tuple[str, str, list[dict]]:
    prompt_summary = summarize_system_prompt(system_prompt)
    quiz_config = get_quiz_configuration(quiz_preference)
    quiz_mode_label = quiz_preference or "Not generated yet"
    reviewer_title = f"{subject} Reviewer: {file_name}"
    reviewer_body = f"""
## Lesson Snapshot
- Module file: **{file_name}**
- Subject: **{subject}**
- Summary mode: **{summary_preference}**
- Quiz mode: **{quiz_mode_label}**
- Quiz items: **{quiz_config['item_count']}**

## Quick Reviewer
- This reviewer was generated from the app fallback template because a live AI synthesis result was not available.
- Use the teacher's module together with the generated quiz to review the most important lesson points.
- Admin prompt applied during fallback generation: **{prompt_summary}**

## Review Focus
1. Identify the lesson goals and high-value terms.
2. Rewrite long explanations into short reviewer notes.
3. Review weak quiz areas before the next attempt.
"""

    quiz_payload = build_fallback_quiz_payload(
        file_name=file_name,
        subject=subject,
        quiz_preference=quiz_preference,
        module_text=module_text,
    )

    return reviewer_title, reviewer_body.strip(), quiz_payload


def split_reviewer_sentences(source_text: str, limit: int = 8) -> list[str]:
    normalized_text = re.sub(r"\s+", " ", source_text).strip()
    if not normalized_text:
        return []
    sentences = [
        sentence.strip(" -•\t")
        for sentence in re.split(r"(?<=[.!?])\s+", normalized_text)
        if len(sentence.strip()) >= 18
    ]
    return sentences[:limit]


def reviewer_text_blocks(reviewer_body: str) -> list[str]:
    cleaned_text = reviewer_body.replace("\r\n", "\n")
    cleaned_text = re.sub(r"```.*?```", " ", cleaned_text, flags=re.S)
    cleaned_text = re.sub(r"^#{1,6}\s*", "", cleaned_text, flags=re.M)
    cleaned_text = re.sub(r"^\s*[-*+]\s+", "", cleaned_text, flags=re.M)
    cleaned_text = re.sub(r"^\s*\d+\.\s+", "", cleaned_text, flags=re.M)
    cleaned_text = re.sub(r"\*\*(.*?)\*\*", r"\1", cleaned_text)
    cleaned_text = re.sub(r"__(.*?)__", r"\1", cleaned_text)
    cleaned_text = re.sub(r"`([^`]*)`", r"\1", cleaned_text)

    blocks: list[str] = []
    for raw_block in re.split(r"\n\s*\n+", cleaned_text):
        lines = [line.strip() for line in raw_block.splitlines() if line.strip()]
        if not lines:
            continue
        block_text = re.sub(r"\s+", " ", " ".join(lines)).strip(" -")
        if block_text.lower() in {"lesson snapshot", "quick reviewer", "review focus"}:
            continue
        if block_text:
            blocks.append(block_text)

    if blocks:
        return blocks
    return split_reviewer_sentences(cleaned_text, limit=8)


def reviewer_body_has_structured_sections(reviewer_body: str) -> bool:
    normalized_body = reviewer_body.strip()
    if not normalized_body:
        return False

    known_markers = [
        "## Lesson Snapshot",
        "## Quick Reviewer",
        "## Review Focus",
        "TITLE:",
        "OVERVIEW:",
        "KEY CONCEPTS:",
        "DEFINITIONS:",
        "FORMULAS / RULES",
        "EXAMPLES",
        "COMMON MISTAKES:",
        "SUMMARY:",
        "TOPIC OVERVIEW:",
        "KEY POINTS:",
        "IMPORTANT TERMS:",
        "RULES / FORMULAS:",
        "QUICK RECAP:",
    ]
    if any(marker in normalized_body for marker in known_markers):
        return True

    return bool(re.search(r"(^|\n)#{1,6}\s+\S+", normalized_body))


def emphasize_quoted_reviewer_phrases(reviewer_text: str) -> str:
    def replace_match(match: re.Match[str]) -> str:
        phrase = match.group(2).strip()
        if not phrase:
            return match.group(0)
        return f"**{phrase}**"

    return re.sub(r'(["“”])\s*([^"\n“”]{2,160}?)\s*(["“”])', replace_match, reviewer_text)


def ensure_preferred_reviewer_format(
    reviewer_body: str,
    file_name: str,
    subject: str,
    summary_preference: str,
    quiz_preference: str,
    quiz_payload: list[dict],
) -> str:
    normalized_body = reviewer_body.strip()
    if reviewer_body_has_structured_sections(normalized_body):
        return emphasize_quoted_reviewer_phrases(normalized_body)

    blocks = reviewer_text_blocks(normalized_body)
    summary_points = blocks[:4]
    focus_points = blocks[4:10]

    if not summary_points:
        summary_points = split_reviewer_sentences(normalized_body, limit=4)
    if not summary_points:
        summary_points = [f"This reviewer highlights the key ideas from the {subject} module."]

    if not focus_points:
        focus_points = split_reviewer_sentences(" ".join(blocks), limit=4)
    if not focus_points:
        focus_terms = extract_focus_terms(normalized_body or file_name, subject, limit=4)
        focus_points = [
            f"Review how {term} connects to the main lesson."
            for term in focus_terms[:4]
        ]
    if not focus_points:
        focus_points = [
            "Identify the lesson goals and high-value terms.",
            "Rewrite long explanations into short reviewer notes.",
            "Review weak quiz areas before the next attempt.",
        ]

    quick_reviewer_markdown = "\n".join(f"- {point}" for point in summary_points[:4])
    review_focus_markdown = "\n".join(
        f"{index}. {point}" for index, point in enumerate(focus_points[:6], start=1)
    )
    quiz_mode_label = quiz_preference or "Not generated yet"

    formatted_body = f"""
## Lesson Snapshot
- Module file: **{file_name}**
- Subject: **{subject}**
- Summary mode: **{summary_preference}**
- Quiz mode: **{quiz_mode_label}**
- Quiz items: **{len(quiz_payload)}**

## Quick Reviewer
{quick_reviewer_markdown}

## Review Focus
{review_focus_markdown}
""".strip()
    return emphasize_quoted_reviewer_phrases(formatted_body)


def salvage_reviewer_body(raw_response: str) -> str:
    cleaned_response = strip_json_fences(raw_response).strip()
    if not cleaned_response:
        return ""
    if cleaned_response.startswith("{") and cleaned_response.endswith("}"):
        return ""
    if len(cleaned_response) < 80:
        return ""
    return cleaned_response


def call_openai_generation(api_key: str, system_prompt: str, user_prompt: str) -> str:
    payload = {
        "model": "gpt-4o-mini",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.3,
        "response_format": {"type": "json_object"},
    }
    request = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        response_json = json.loads(response.read().decode("utf-8"))
    return response_json["choices"][0]["message"]["content"]


def call_gemini_generation(api_key: str, system_prompt: str, user_prompt: str) -> str:
    payload = {
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"parts": [{"text": user_prompt}]}],
        "generationConfig": {
            "temperature": 0.3,
            "responseMimeType": "application/json",
            "maxOutputTokens": 8192,
        },
    }
    last_error_message = "Unknown Gemini API error."
    for model_name in GEMINI_MODEL_CANDIDATES:
        request = urllib.request.Request(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                response_json = json.loads(response.read().decode("utf-8"))
            return response_json["candidates"][0]["content"]["parts"][0]["text"]
        except urllib.error.HTTPError as error:
            error_body = error.read().decode("utf-8", errors="ignore")
            last_error_message = f"{model_name}: HTTP {error.code} {error_body[:220]}"
            continue
        except Exception as error:
            last_error_message = f"{model_name}: {type(error).__name__}: {error}"
            continue

    raise RuntimeError(last_error_message)


def call_generation_model(api_key: str, system_prompt: str, user_prompt: str) -> str:
    if api_key.strip().startswith("AIza"):
        return call_gemini_generation(api_key.strip(), system_prompt, user_prompt)
    return call_openai_generation(api_key.strip(), system_prompt, user_prompt)


def build_generation_prompt(
    file_name: str,
    subject: str,
    summary_preference: str,
    module_text: str,
) -> str:
    return f"""
Generate only the reviewer from the uploaded learning module.

Requirements:
- Use the uploaded module text as the source of truth.
- The active system prompt already defines the reviewer structure and study design rules. Follow it exactly.
- Produce a real reviewer, not a system-status summary.
- Do not inject quiz content, fallback notes, admin prompt notes, system status text, or generation status into reviewer_body.
- Generate reviewer_body only for the selected summary preference: {summary_preference}.
- reviewer_title should be a clean human-readable lesson title.
- Return JSON only, with this shape:
  {{
    "reviewer_title": "string",
    "reviewer_body": "markdown string"
  }}

Context:
- File name: {file_name}
- Subject: {subject}
- Summary preference: {summary_preference}

Module text:
{module_text}
""".strip()


def build_generation_repair_prompt(
    file_name: str,
    subject: str,
    summary_preference: str,
    module_text: str,
    validation_error: str,
    previous_response: str,
) -> str:
    previous_excerpt = strip_json_fences(previous_response).strip()
    if len(previous_excerpt) > 3000:
        previous_excerpt = previous_excerpt[:3000].rstrip() + "\n...[truncated]"

    return f"""
The previous response could not be used by the application.

Validation or parsing issue:
{validation_error}

Return a corrected response as VALID JSON ONLY.
Do not include explanation, markdown fences, or any extra text.
Regenerate only the reviewer so it follows the required schema and rules exactly.

Required context:
- File name: {file_name}
- Subject: {subject}
- Summary preference: {summary_preference}

Previous invalid response:
{previous_excerpt or "[empty response]"}

Module text:
{module_text}
""".strip()


def build_quiz_generation_prompt(reviewer_text: str, quiz_preference: str) -> str:
    quiz_config = get_quiz_configuration(quiz_preference)
    difficulty_name = quiz_config["display_name"]
    item_count = int(quiz_config["item_count"])

    difficulty_rules = []
    if difficulty_name == "Beginner":
        difficulty_rules.extend(
            [
                "If QUIZ_DIFFICULTY = Beginner:",
                "- Generate exactly 15 items",
                "- Type: multiple_choice only",
                "- Each item must include 1 correct answer and 3 realistic distractors",
                '- Each item must include: "type", "prompt", "options", "answer_index", and "hint"',
            ]
        )
    elif difficulty_name in {"Intermediate", "Intermidiate"}:
        difficulty_rules.extend(
            [
                "If QUIZ_DIFFICULTY = Intermediate:",
                "- Generate exactly 30 items total",
                "- Distribution:",
                "  - 10 true_false items",
                "  - 20 matching items",
                "- true_false items must include: type, statement, answer_bool, hint",
                "- matching items must include: type, prompt, correct_answer, match_options, hint",
                "- matching prompts must be clear clue, definition, description, or sentence-based cues from the reviewer",
                "- correct_answer values must be unique across matching items",
                "- match_options must be the shared answer pool for the matching set",
            ]
        )
    else:
        difficulty_rules.extend(
            [
                "If QUIZ_DIFFICULTY = Advanced:",
                "- Generate exactly 60 items total",
                "- Distribution:",
                "  - 20 modified_true_false items",
                "  - 20 identification items",
                "  - 20 enumeration items",
                "- modified_true_false items must include: type, statement, answer_bool, incorrect_phrase, replacement_answer, hint",
                "- identification items must include: type, prompt, accepted_answers, hint",
                "- enumeration items must include: type, prompt, accepted_answers, hint",
                "- For false modified_true_false items, include only ONE incorrect concept and the exact incorrect phrase",
            ]
        )

    return f"""
You are an expert academic quiz generator.

Your task is to generate exactly ONE quiz set based strictly on the provided reviewer.

IMPORTANT:
- The reviewer is the ONLY source of truth.
- Do NOT use outside knowledge.
- Do NOT invent or assume information.
- Every question must be directly supported by the reviewer.
- Questions must be clear, valid, and answerable using ONLY the reviewer.
- Follow the application's required JSON structure exactly.
- Return JSON only. Do not return markdown, explanations, or extra text.

==================================================
1. INPUT
==================================================

REVIEWER:
\"\"\"
{reviewer_text}
\"\"\"

QUIZ_DIFFICULTY:
{difficulty_name}

NUMBER_OF_ITEMS:
{item_count}

==================================================
2. GLOBAL RULES
==================================================

- Generate only the selected difficulty.
- Each question is worth 1 point.
- Every question must come directly from the reviewer.
- Keep wording clear, student-friendly, and academically correct.
- Avoid vague, generic, or filler questions.
- Avoid statements like:
  - "X is one of the lesson ideas the student should review."
  - "Match the term linked to clue #5."
  - anything not tied to a real reviewer detail
- Every prompt must sound like it came from the actual reviewer content.

==================================================
3. DIFFICULTY RULES
==================================================

{chr(10).join(difficulty_rules)}

==================================================
4. VALIDATION RULE
==================================================

Before finalizing each item, check:
- Is the answer clearly supported by the reviewer?
- Is the wording specific to the reviewer?
- Does the question type match the selected difficulty?
- Does the item fit the required JSON schema?

If NO, revise or remove the item.

==================================================
5. REQUIRED OUTPUT FORMAT
==================================================

Return JSON only in this shape:

{{
  "quiz_payload": [
    {{
      "type": "multiple_choice | true_false | matching | modified_true_false | identification | enumeration",
      "prompt": "string",
      "statement": "string when needed",
      "options": ["a", "b", "c", "d"],
      "answer_index": 0,
      "answer_bool": true,
      "correct_answer": "string",
      "match_options": ["string"],
      "accepted_answers": ["string"],
      "incorrect_phrase": "string",
      "replacement_answer": "string",
      "hint": "string"
    }}
  ]
}}

==================================================
6. FINAL INSTRUCTION
==================================================

Generate exactly ONE quiz based only on the reviewer.
Use only the selected QUIZ_DIFFICULTY.
Use exactly NUMBER_OF_ITEMS items.
Return valid JSON only.
""".strip()


def build_quiz_generation_batch_prompt(
    reviewer_text: str,
    quiz_preference: str,
    question_type: str,
    question_count: int,
) -> str:
    difficulty_name = get_quiz_configuration(quiz_preference)["display_name"]
    batch_rules = {
        "multiple_choice": """
- Generate exactly {question_count} items
- Use type = "multiple_choice" only
- Each item must include: prompt, options, answer_index, hint
- options must contain exactly 4 items
- Include 1 correct answer and 3 realistic distractors
""",
        "true_false": """
- Generate exactly {question_count} items
- Use type = "true_false" only
- Each item must include: statement, answer_bool, hint
- Mix true and false statements
- False items must change only one key detail and still sound realistic
""",
        "matching": """
- Generate exactly {question_count} items
- Use type = "matching" only
- Each item must include: prompt, correct_answer, match_options, hint
- Each prompt must be a clear clue, definition, description, or sentence-based cue from the reviewer
- correct_answer values must be unique across all items in this batch
- match_options must contain the shared answer pool for the entire matching batch
""",
        "modified_true_false": """
- Generate exactly {question_count} items
- Use type = "modified_true_false" only
- Each item must include: statement, answer_bool, incorrect_phrase, replacement_answer, hint
- If answer_bool is true: incorrect_phrase must be "" and replacement_answer must be "TRUE"
- If answer_bool is false: include exactly one wrong phrase and the correct replacement
""",
        "identification": """
- Generate exactly {question_count} items
- Use type = "identification" only
- Each item must include: prompt, accepted_answers, hint
- accepted_answers must contain reviewer-supported short-answer terms only
""",
        "enumeration": """
- Generate exactly {question_count} items
- Use type = "enumeration" only
- Each item must include: prompt, accepted_answers, hint
- accepted_answers must contain reviewer-supported list answers only
- Use enumeration only when the reviewer clearly supports list-like answers
""",
    }

    return f"""
You are an expert academic quiz generator.

Your task is to generate exactly one quiz batch based strictly on the provided reviewer.

IMPORTANT:
- The reviewer is the ONLY source of truth.
- Do NOT use outside knowledge.
- Do NOT invent or assume information.
- Every question must be directly supported by the reviewer.
- Return JSON only.

REVIEWER:
\"\"\"
{reviewer_text}
\"\"\"

QUIZ_DIFFICULTY:
{difficulty_name}

QUIZ_BATCH_TYPE:
{question_type}

BATCH_ITEM_COUNT:
{question_count}

Rules:
- Generate only the requested QUIZ_BATCH_TYPE.
- Do not include any other question types in this response.
- Keep wording clear, specific, and reviewer-based.
- Avoid vague statements and generic filler phrasing.
{batch_rules[question_type].format(question_count=question_count).strip()}

Return JSON only in this shape:
{{
  "quiz_payload": [
    {{
      "type": "multiple_choice | true_false | matching | modified_true_false | identification | enumeration",
      "prompt": "string",
      "statement": "string when needed",
      "options": ["a", "b", "c", "d"],
      "answer_index": 0,
      "answer_bool": true,
      "correct_answer": "string",
      "match_options": ["string"],
      "accepted_answers": ["string"],
      "incorrect_phrase": "string",
      "replacement_answer": "string",
      "hint": "string"
    }}
  ]
}}
""".strip()


def build_quiz_generation_repair_prompt(
    reviewer_text: str,
    quiz_preference: str,
    validation_error: str,
    previous_response: str,
) -> str:
    previous_excerpt = strip_json_fences(previous_response).strip()
    if len(previous_excerpt) > 3000:
        previous_excerpt = previous_excerpt[:3000].rstrip() + "\n...[truncated]"

    return f"""
The previous quiz response could not be used by the application.

Validation or parsing issue:
{validation_error}

Return a corrected response as VALID JSON ONLY.
Do not include explanation, markdown fences, or extra text.
Regenerate only the quiz so it follows the required quiz schema and difficulty rules exactly.

QUIZ_DIFFICULTY:
{get_quiz_configuration(quiz_preference)["display_name"]}

Previous invalid response:
{previous_excerpt or "[empty response]"}

REVIEWER:
\"\"\"
{reviewer_text}
\"\"\"
""".strip()


def build_quiz_generation_batch_repair_prompt(
    reviewer_text: str,
    quiz_preference: str,
    question_type: str,
    question_count: int,
    validation_error: str,
    previous_response: str,
) -> str:
    previous_excerpt = strip_json_fences(previous_response).strip()
    if len(previous_excerpt) > 3000:
        previous_excerpt = previous_excerpt[:3000].rstrip() + "\n...[truncated]"

    return f"""
The previous quiz batch response could not be used by the application.

Validation or parsing issue:
{validation_error}

Return a corrected response as VALID JSON ONLY.
Do not include explanation, markdown fences, or extra text.
Regenerate only the requested quiz batch.

QUIZ_DIFFICULTY:
{get_quiz_configuration(quiz_preference)["display_name"]}

QUIZ_BATCH_TYPE:
{question_type}

BATCH_ITEM_COUNT:
{question_count}

Previous invalid response:
{previous_excerpt or "[empty response]"}

REVIEWER:
\"\"\"
{reviewer_text}
\"\"\"
""".strip()


def generate_reviewer_package(
    file_name: str,
    subject: str,
    summary_preference: str,
    system_prompt: str,
    api_key: str,
    module_text: str,
) -> tuple[str, str, str, str]:
    normalized_api_key = api_key.strip()
    if not normalized_api_key:
        raise RuntimeError("No API key is currently saved in Admin API Settings.")
    if not module_text:
        raise RuntimeError("The uploaded file did not provide extractable text for live AI synthesis.")

    reviewer_generation_prompt = build_generation_prompt(
        file_name=file_name,
        subject=subject,
        summary_preference=summary_preference,
        module_text=module_text,
    )

    reviewer_raw_response = ""
    reviewer_repair_used = False
    reviewer_title = f"{subject} Reviewer"
    reviewer_body = ""

    reviewer_prompts_to_try = [reviewer_generation_prompt]
    last_reviewer_error = "Reviewer generation failed."

    for attempt_index in range(2):
        current_prompt = reviewer_prompts_to_try[attempt_index]
        try:
            reviewer_raw_response = call_generation_model(normalized_api_key, system_prompt, current_prompt)
            reviewer_payload = parse_generation_json(reviewer_raw_response)
            reviewer_title = str(reviewer_payload.get("reviewer_title", "")).strip() or f"{subject} Reviewer"
            reviewer_body = str(reviewer_payload.get("reviewer_body", "")).strip()
            if not reviewer_body:
                raise ValueError("Generated reviewer payload was incomplete.")
            break
        except Exception as error:
            last_reviewer_error = str(error)
            if attempt_index == 0:
                reviewer_repair_used = True
                reviewer_prompts_to_try.append(
                    build_generation_repair_prompt(
                        file_name=file_name,
                        subject=subject,
                        summary_preference=summary_preference,
                        module_text=module_text,
                        validation_error=last_reviewer_error,
                        previous_response=reviewer_raw_response,
                    )
                )
                continue
            raise RuntimeError(
                f"Reviewer generation failed after one repair attempt: {last_reviewer_error}"
            ) from error

    reviewer_body = ensure_preferred_reviewer_format(
        reviewer_body=reviewer_body,
        file_name=file_name,
        subject=subject,
        summary_preference=summary_preference,
        quiz_preference="",
        quiz_payload=[],
    )

    repair_notes: list[str] = []
    if reviewer_repair_used:
        repair_notes.append("Reviewer output was repaired automatically after the first AI response failed validation.")

    return reviewer_title, reviewer_body, "ai", " ".join(repair_notes).strip()


def generate_quiz_payload_for_reviewer(
    reviewer_body: str,
    quiz_preference: str,
    api_key: str,
) -> tuple[list[dict], str]:
    normalized_api_key = api_key.strip()
    if not normalized_api_key:
        raise RuntimeError("No API key is currently saved in Admin API Settings.")
    if not reviewer_body.strip():
        raise RuntimeError("The reviewer does not contain enough content for quiz generation.")

    quiz_config = get_quiz_configuration(quiz_preference)
    combined_quiz_payload: list[dict] = []
    quiz_repair_used = False

    for question_type, question_count in quiz_config["type_distribution"]:
        quiz_raw_response = ""
        last_quiz_error = f"{question_type} batch generation failed."
        quiz_prompts_to_try = [
            build_quiz_generation_batch_prompt(
                reviewer_text=reviewer_body,
                quiz_preference=quiz_preference,
                question_type=question_type,
                question_count=int(question_count),
            )
        ]

        batch_payload: list[dict] = []
        for attempt_index in range(2):
            current_prompt = quiz_prompts_to_try[attempt_index]
            try:
                quiz_raw_response = call_generation_model(
                    normalized_api_key,
                    QUIZ_GENERATION_SYSTEM_PROMPT,
                    current_prompt,
                )
                quiz_payload = parse_generation_json(quiz_raw_response).get("quiz_payload", [])
                if not isinstance(quiz_payload, list):
                    raise ValueError("Generated quiz payload was incomplete.")
                batch_payload = normalize_generated_quiz_batch(
                    quiz_payload,
                    question_type=question_type,
                    expected_count=int(question_count),
                )
                break
            except Exception as error:
                last_quiz_error = str(error)
                if attempt_index == 0:
                    quiz_repair_used = True
                    quiz_prompts_to_try.append(
                        build_quiz_generation_batch_repair_prompt(
                            reviewer_text=reviewer_body,
                            quiz_preference=quiz_preference,
                            question_type=question_type,
                            question_count=int(question_count),
                            validation_error=last_quiz_error,
                            previous_response=quiz_raw_response,
                        )
                    )
                    continue
                raise RuntimeError(
                    f"Quiz generation failed for {question_type} after one repair attempt: {last_quiz_error}"
                ) from error

        combined_quiz_payload.extend(batch_payload)

    normalized_quiz = normalize_generated_quiz_payload(combined_quiz_payload, quiz_preference)
    generation_reason = (
        "Quiz output was repaired automatically after the first AI response failed validation."
        if quiz_repair_used
        else ""
    )
    return normalized_quiz, generation_reason


def create_generated_reviewer(
    user_id: int,
    document_id: int,
    file_name: str,
    subject: str,
    summary_preference: str,
    module_text: str,
) -> tuple[int, str, str]:
    summary_preference = normalize_summary_preference_label(summary_preference)
    active_system_prompt = load_system_prompt_permanently()
    saved_api_key = load_key_permanently()
    reviewer_title, reviewer_body, generation_mode, generation_reason = generate_reviewer_package(
        file_name=file_name,
        subject=subject,
        summary_preference=summary_preference,
        system_prompt=active_system_prompt,
        api_key=saved_api_key,
        module_text=module_text,
    )
    reviewer_id = execute_query(
        """
        INSERT INTO generated_reviewers (
            user_id, document_id, file_name, subject, summary_preference,
            quiz_preference, reviewer_title, reviewer_body, quiz_payload
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            user_id,
            document_id,
            file_name,
            subject,
            summary_preference,
            "",
            reviewer_title,
            reviewer_body,
            json.dumps([]),
        ),
    )
    current_user = st.session_state.get("current_user")
    if current_user:
        log_system_activity(
            actor_name=current_user["fullname"],
            actor_role=current_user["role"],
            actor_id=int(current_user["id"]),
            activity="Generated reviewer",
            details=f"{generation_mode.upper()} generation for {file_name} under {subject}. Reviewer only.",
        )
    return reviewer_id, generation_mode, generation_reason


def update_generated_reviewer_quiz(
    reviewer_id: int,
    quiz_preference: str,
    quiz_payload: list[dict],
) -> None:
    execute_query(
        """
        UPDATE generated_reviewers
        SET quiz_preference = %s, quiz_payload = %s
        WHERE id = %s
        """,
        (
            normalize_quiz_preference_label(quiz_preference),
            json.dumps(quiz_payload),
            reviewer_id,
        ),
    )


def generate_quiz_for_reviewer(
    reviewer_id: int,
    quiz_preference: str,
) -> tuple[dict, str, str]:
    reviewer = load_generated_reviewer_by_id(reviewer_id)
    if not reviewer:
        raise RuntimeError("The selected reviewer could not be found.")

    normalized_quiz_preference = normalize_quiz_preference_label(quiz_preference)
    saved_api_key = load_key_permanently()
    quiz_payload, generation_reason = generate_quiz_payload_for_reviewer(
        reviewer_body=reviewer["reviewer_body"],
        quiz_preference=normalized_quiz_preference,
        api_key=saved_api_key,
    )
    update_generated_reviewer_quiz(
        reviewer_id=reviewer_id,
        quiz_preference=normalized_quiz_preference,
        quiz_payload=quiz_payload,
    )

    refreshed_reviewer = load_generated_reviewer_by_id(reviewer_id)
    current_user = st.session_state.get("current_user")
    if current_user and refreshed_reviewer:
        log_system_activity(
            actor_name=current_user["fullname"],
            actor_role=current_user["role"],
            actor_id=int(current_user["id"]),
            activity="Generated quiz",
            details=(
                f"AI quiz generation for {refreshed_reviewer['file_name']} under "
                f"{refreshed_reviewer['subject']}. Quiz mode: {normalized_quiz_preference}."
            ),
        )
    if not refreshed_reviewer:
        raise RuntimeError("The reviewer was updated, but the refreshed quiz could not be loaded.")
    return refreshed_reviewer, "ai", generation_reason


def load_latest_generated_reviewer(user_id: int) -> dict | None:
    reviewer = fetch_one(
        """
        SELECT id, user_id, document_id, file_name, subject, summary_preference, quiz_preference,
               reviewer_title, reviewer_body, quiz_payload, created_at
        FROM generated_reviewers
        WHERE user_id = %s
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """,
        (user_id,),
    )
    if reviewer:
        reviewer["quiz_payload"] = normalize_loaded_quiz_payload(json.loads(reviewer["quiz_payload"]))
    return reviewer


def load_generated_reviewer_by_id(reviewer_id: int) -> dict | None:
    reviewer = fetch_one(
        """
        SELECT id, user_id, document_id, file_name, subject, summary_preference, quiz_preference,
               reviewer_title, reviewer_body, quiz_payload, created_at
        FROM generated_reviewers
        WHERE id = %s
        LIMIT 1
        """,
        (reviewer_id,),
    )
    if reviewer:
        reviewer["quiz_payload"] = normalize_loaded_quiz_payload(json.loads(reviewer["quiz_payload"]))
    return reviewer


def load_generated_reviewers_for_user(user_id: int) -> list[dict]:
    reviewers = fetch_all(
        """
        SELECT id, user_id, document_id, file_name, subject, summary_preference, quiz_preference,
               reviewer_title, reviewer_body, quiz_payload, created_at
        FROM generated_reviewers
        WHERE user_id = %s
        ORDER BY created_at DESC, id DESC
        """,
        (user_id,),
    )
    for reviewer in reviewers:
        reviewer["quiz_payload"] = normalize_loaded_quiz_payload(json.loads(reviewer["quiz_payload"]))
    return reviewers


def delete_generated_reviewer_for_user(user_id: int, reviewer_id: int) -> None:
    execute_query(
        """
        DELETE FROM generated_reviewers
        WHERE id = %s AND user_id = %s
        """,
        (reviewer_id, user_id),
    )


def build_reviewer_download_content(reviewer: dict) -> str:
    formatted_body = ensure_preferred_reviewer_format(
        reviewer_body=reviewer["reviewer_body"],
        file_name=reviewer["file_name"],
        subject=reviewer["subject"],
        summary_preference=reviewer["summary_preference"],
        quiz_preference=reviewer["quiz_preference"],
        quiz_payload=reviewer["quiz_payload"],
    )
    download_content = "\n".join(
        [
            f"# {reviewer['reviewer_title']}",
            "",
            f"- Module File: {reviewer['file_name']}",
            f"- Subject: {reviewer['subject']}",
            f"- Summary Mode: {reviewer['summary_preference']}",
            "",
            formatted_body,
        ]
    ).strip()

    definition_pattern = re.compile(r'^(\s*(?:[-*]\s+|\d+\.\s+)?)["“”]?([A-Za-z][^:\n]{0,160}?)["“”]?\s*:\s+(.+)$')
    formatted_lines: list[str] = []
    for line in download_content.splitlines():
        stripped_line = line.strip()
        if not stripped_line or stripped_line.startswith("#") or "**" in line:
            formatted_lines.append(line)
            continue
        match = definition_pattern.match(line)
        if match:
            prefix, term, remainder = match.groups()
            formatted_lines.append(f"{prefix}**{term.strip()}**: {remainder}")
        else:
            formatted_lines.append(line)
    return "\n".join(formatted_lines).strip()


def parse_markdown_bold_segments(text: str) -> list[tuple[str, bool]]:
    segments: list[tuple[str, bool]] = []
    cursor = 0
    for match in re.finditer(r"\*\*(.+?)\*\*", text):
        if match.start() > cursor:
            segments.append((text[cursor:match.start()], False))
        if match.group(1):
            segments.append((match.group(1), True))
        cursor = match.end()
    if cursor < len(text):
        segments.append((text[cursor:], False))
    return [(segment_text, is_bold) for segment_text, is_bold in segments if segment_text]


def estimate_pdf_text_width(text: str, font_size: int, is_bold: bool = False) -> float:
    width_factor = 0.56 if is_bold else 0.52
    return len(text) * font_size * width_factor


def trim_pdf_line_segments(segments: list[tuple[str, bool]]) -> list[tuple[str, bool]]:
    cleaned_segments = [(segment_text, is_bold) for segment_text, is_bold in segments if segment_text]
    if not cleaned_segments:
        return []

    first_text, first_bold = cleaned_segments[0]
    cleaned_segments[0] = (first_text.lstrip(), first_bold)
    if not cleaned_segments[0][0]:
        cleaned_segments = cleaned_segments[1:]
        if not cleaned_segments:
            return []

    last_text, last_bold = cleaned_segments[-1]
    cleaned_segments[-1] = (last_text.rstrip(), last_bold)
    if not cleaned_segments[-1][0]:
        cleaned_segments = cleaned_segments[:-1]

    return cleaned_segments


def wrap_pdf_styled_segments(segments: list[tuple[str, bool]], font_size: int, usable_width: int) -> list[list[tuple[str, bool]]]:
    tokens: list[tuple[str, bool]] = []
    for segment_text, is_bold in segments:
        for token in re.findall(r"\s+|\S+\s*", segment_text):
            if token:
                tokens.append((token, is_bold))

    if not tokens:
        return [[]]

    wrapped_lines: list[list[tuple[str, bool]]] = []
    current_line: list[tuple[str, bool]] = []
    current_width = 0.0

    for token_text, is_bold in tokens:
        token_width = estimate_pdf_text_width(token_text, font_size, is_bold)
        if current_line and current_width + token_width > usable_width and token_text.strip():
            trimmed_line = trim_pdf_line_segments(current_line)
            if trimmed_line:
                wrapped_lines.append(trimmed_line)
            token_text = token_text.lstrip()
            token_width = estimate_pdf_text_width(token_text, font_size, is_bold)
            current_line = []
            current_width = 0.0

        if current_line and current_line[-1][1] == is_bold:
            previous_text, _ = current_line[-1]
            current_line[-1] = (previous_text + token_text, is_bold)
        else:
            current_line.append((token_text, is_bold))
        current_width += token_width

    trimmed_line = trim_pdf_line_segments(current_line)
    if trimmed_line:
        wrapped_lines.append(trimmed_line)

    return wrapped_lines or [[]]


def escape_pdf_text(value: str) -> str:
    sanitized = (
        value.replace("•", "-")
        .replace("—", "-")
        .replace("–", "-")
        .replace("\t", "    ")
    )
    sanitized = sanitized.replace("**", "").replace("__", "")
    sanitized = sanitized.encode("latin-1", "replace").decode("latin-1")
    return sanitized.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def build_simple_text_pdf(styled_lines: list[tuple[str, int]]) -> bytes:
    page_width = 595
    page_height = 842
    left_margin = 52
    top_margin = 790
    bottom_margin = 52
    usable_width = page_width - (left_margin * 2)

    pages: list[list[str]] = []
    current_page: list[str] = []
    current_y = float(top_margin)

    def start_new_page() -> None:
        nonlocal current_page, current_y
        if current_page:
            pages.append(current_page)
        current_page = []
        current_y = float(top_margin)

    def add_blank_space(amount: float) -> None:
        nonlocal current_y
        current_y -= amount
        if current_y < bottom_margin:
            start_new_page()

    for raw_text, font_size in styled_lines:
        if not raw_text.strip():
            add_blank_space(10)
            continue

        parsed_segments = parse_markdown_bold_segments(raw_text)
        wrapped_lines = wrap_pdf_styled_segments(parsed_segments, font_size, usable_width)

        line_gap = font_size + (8 if font_size >= 20 else 6 if font_size >= 14 else 5)
        for line_segments in wrapped_lines:
            if current_y - line_gap < bottom_margin:
                start_new_page()
            current_x = float(left_margin)
            for segment_text, is_bold in line_segments:
                escaped_line = escape_pdf_text(segment_text)
                font_reference = "/F2" if is_bold else "/F1"
                current_page.append(
                    f"BT {font_reference} {font_size} Tf 1 0 0 1 {current_x:.2f} {current_y:.2f} Tm ({escaped_line}) Tj ET"
                )
                current_x += estimate_pdf_text_width(segment_text, font_size, is_bold)
            current_y -= line_gap

        current_y -= 2

    if current_page:
        pages.append(current_page)

    if not pages:
        pages = [["BT /F1 12 Tf 1 0 0 1 52 790 Tm (Reviewer content unavailable.) Tj ET"]]

    objects: list[bytes] = []
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(b"<< /Type /Pages /Kids [] /Count 0 >>")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>")

    page_object_ids: list[int] = []
    next_object_id = 5

    for page_commands in pages:
        page_object_id = next_object_id
        content_object_id = next_object_id + 1
        page_object_ids.append(page_object_id)
        next_object_id += 2

        content_stream = "\n".join(page_commands).encode("latin-1", "replace")
        page_object = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {page_width} {page_height}] "
            f"/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> /Contents {content_object_id} 0 R >>"
        ).encode("latin-1")
        content_object = (
            f"<< /Length {len(content_stream)} >>\nstream\n".encode("latin-1")
            + content_stream
            + b"\nendstream"
        )
        objects.append(page_object)
        objects.append(content_object)

    kids = " ".join(f"{page_id} 0 R" for page_id in page_object_ids)
    objects[1] = f"<< /Type /Pages /Kids [{kids}] /Count {len(page_object_ids)} >>".encode("latin-1")

    pdf_parts = [b"%PDF-1.4\n"]
    offsets = [0]
    current_offset = len(pdf_parts[0])
    for object_number, object_body in enumerate(objects, start=1):
        offsets.append(current_offset)
        obj_header = f"{object_number} 0 obj\n".encode("latin-1")
        obj_footer = b"\nendobj\n"
        pdf_parts.extend([obj_header, object_body, obj_footer])
        current_offset += len(obj_header) + len(object_body) + len(obj_footer)

    xref_offset = current_offset
    pdf_parts.append(f"xref\n0 {len(objects) + 1}\n".encode("latin-1"))
    pdf_parts.append(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        pdf_parts.append(f"{offset:010d} 00000 n \n".encode("latin-1"))

    trailer = (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF"
    ).encode("latin-1")
    pdf_parts.append(trailer)
    return b"".join(pdf_parts)


def build_reviewer_download_pdf(reviewer: dict) -> bytes:
    reviewer_content = build_reviewer_download_content(reviewer)
    styled_lines: list[tuple[str, int]] = []
    for line in reviewer_content.splitlines():
        stripped_line = line.strip()
        if not stripped_line:
            styled_lines.append(("", 12))
        elif stripped_line.startswith("# "):
            styled_lines.append((stripped_line[2:].strip(), 24))
        elif stripped_line.startswith("## "):
            styled_lines.append((stripped_line[3:].strip(), 17))
        elif stripped_line.startswith("- "):
            styled_lines.append((f"- {stripped_line[2:].strip()}", 11))
        else:
            styled_lines.append((stripped_line, 12))

    return build_simple_text_pdf(styled_lines)


def save_quiz_attempt(
    user_id: int,
    reviewer_id: int,
    file_name: str,
    subject: str,
    score: int,
    total_questions: int,
) -> None:
    percentage = round((score / total_questions) * 100, 2) if total_questions else 0
    execute_query(
        """
        INSERT INTO quiz_attempts (user_id, reviewer_id, file_name, subject, score, total_questions, percentage)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
        (user_id, reviewer_id, file_name, subject, score, total_questions, percentage),
    )


def load_quiz_attempts(user_id: int) -> list[dict]:
    return fetch_all(
        """
        SELECT qa.id, qa.reviewer_id, qa.file_name, qa.subject, qa.score, qa.total_questions, qa.percentage, qa.attempted_at,
               COALESCE(gr.quiz_preference, '') AS quiz_preference
        FROM quiz_attempts qa
        LEFT JOIN generated_reviewers gr ON gr.id = qa.reviewer_id
        WHERE qa.user_id = %s
        ORDER BY qa.attempted_at DESC, qa.id DESC
        """,
        (user_id,),
    )


def build_user_insight_cards(user_id: int, latest_reviewer: dict | None) -> list[dict]:
    attempts = load_quiz_attempts(user_id)
    if attempts:
        latest_attempt = attempts[0]
        lowest_attempt = min(attempts, key=lambda attempt: float(attempt["percentage"]))
        return [
            {
                "label": "INSIGHT",
                "color": "#2DD4BF",
                "message": f"Your latest quiz on {latest_attempt['file_name']} scored {float(latest_attempt['percentage']):.0f}%.",
            },
            {
                "label": "REMINDER",
                "color": "#ff6b35",
                "message": f"Review {lowest_attempt['file_name']} again. It has your lowest quiz score at {float(lowest_attempt['percentage']):.0f}%.",
            },
            {
                "label": "NEXT STEP",
                "color": "#94A3B8",
                "message": "Open the reviewer, revisit your weak areas, then retake the quiz to improve retention.",
            },
        ]

    if latest_reviewer:
        return [
            {
                "label": "INSIGHT",
                "color": "#2DD4BF",
                "message": f"{latest_reviewer['file_name']} is ready for review. Open the reviewer when you want to study it.",
            },
            {
                "label": "REMINDER",
                "color": "#ff6b35",
                "message": "You can generate a quiz later from inside the reviewer when you are ready to practice.",
            },
            {
                "label": "NEXT STEP",
                "color": "#94A3B8",
                "message": "Use View Reviewer >> to study the generated notes, then choose Generate Quiz when you want to practice.",
            },
        ]

    return [
        {
            "label": "INSIGHT",
            "color": "#2DD4BF",
            "message": "Upload a teacher module to generate your first reviewer.",
        },
        {
            "label": "REMINDER",
            "color": "#ff6b35",
            "message": "The system will use your future quiz scores to remind you which past module needs the most review.",
        },
        {
            "label": "NEXT STEP",
            "color": "#94A3B8",
            "message": "Choose your summary mode, run synthesis, then open the reviewer to generate a quiz later if you want one.",
        },
    ]


def get_selected_module_subject() -> str:
    selected_subject = st.session_state.get("module_subject", "Select Subject")
    if selected_subject == "Custom":
        return st.session_state.get("custom_module_subject", "").strip()
    if selected_subject == "Select Subject":
        return ""
    return selected_subject


def render_grade_analytics_charts(user_id: int) -> None:
    quiz_attempts = load_quiz_attempts(user_id)
    if not quiz_attempts:
        st.info("No graded quizzes yet. Finish a quiz to generate subject-based score charts.")
        return

    subject_attempt_map: dict[str, list[dict]] = {}
    for attempt in sorted(quiz_attempts, key=lambda row: (row["attempted_at"], row["id"])):
        subject_attempt_map.setdefault(attempt["subject"], []).append(attempt)

    for subject, attempts in subject_attempt_map.items():
        quiz_labels = []
        for index, attempt in enumerate(attempts, start=1):
            difficulty_text = str(attempt.get("quiz_preference") or "").strip()
            difficulty_text = difficulty_text.split("(")[0].strip() or "Unknown"
            quiz_labels.append(f"Quiz {index}<br>{difficulty_text}")
        total_items = [int(attempt["total_questions"]) for attempt in attempts]
        score_items = [int(attempt["score"]) for attempt in attempts]
        percentages = [float(attempt["percentage"]) for attempt in attempts]
        max_items = max(total_items) if total_items else 0
        chart_width = max(860, len(attempts) * 110)

        figure = go.Figure()
        figure.add_trace(
            go.Bar(
                x=quiz_labels,
                y=total_items,
                name="Quiz Items",
                marker_color="rgba(148,163,184,0.35)",
                hovertemplate="Items: %{y}<extra></extra>",
            )
        )
        figure.add_trace(
            go.Bar(
                x=quiz_labels,
                y=score_items,
                name="Your Score",
                marker_color="#ff6b35",
                customdata=list(zip(total_items, percentages)),
                hovertemplate="Score: %{y}<br>Total Items: %{customdata[0]}<br>Percent: %{customdata[1]:.0f}%<extra></extra>",
            )
        )
        figure.update_layout(
            barmode="overlay",
            width=chart_width,
            height=320,
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font=dict(color="white"),
            margin=dict(l=65, r=30, t=20, b=65),
            xaxis=dict(
                type="category",
                tickfont=dict(color="white"),
                categoryorder="array",
                categoryarray=quiz_labels,
            ),
            yaxis=dict(
                title=dict(text="Items", font=dict(color="white")),
                tickfont=dict(color="white"),
                gridcolor="rgba(148,163,184,0.15)",
                range=[0, max_items + 2],
            ),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
            bargap=0.45,
        )

        chart_html = pio.to_html(
            figure,
            include_plotlyjs=True,
            full_html=False,
            config={"displayModeBar": False, "responsive": False},
        )

        st.markdown(
            f"""
            <div class="bento-card" style="padding-bottom:16px;">
                <p style="color:#94A3B8; font-size:11px; font-weight:800; margin:0;">GRADE ANALYTICS</p>
                <h3 style="color:white; margin:10px 0 6px 0; font-size:26px; font-weight:800;">{subject}</h3>
            </div>
            """,
            unsafe_allow_html=True,
        )
        components.html(
            f"""
            <style>
                .grade-chart-scroll {{
                    width: 100%;
                    overflow-x: auto;
                    overflow-y: hidden;
                    padding-bottom: 6px;
                    scrollbar-width: thin;
                    scrollbar-color: rgba(255, 107, 53, 0.72) rgba(15, 23, 42, 0.92);
                }}
                .grade-chart-scroll::-webkit-scrollbar {{
                    height: 12px;
                }}
                .grade-chart-scroll::-webkit-scrollbar-track {{
                    background: rgba(15, 23, 42, 0.92);
                    border-radius: 999px;
                    border: 1px solid rgba(255, 255, 255, 0.08);
                }}
                .grade-chart-scroll::-webkit-scrollbar-thumb {{
                    background: linear-gradient(90deg, rgba(255, 107, 53, 0.82), rgba(249, 115, 22, 0.82));
                    border-radius: 999px;
                    border: 2px solid rgba(15, 23, 42, 0.92);
                }}
                .grade-chart-scroll::-webkit-scrollbar-thumb:hover {{
                    background: linear-gradient(90deg, rgba(255, 107, 53, 0.96), rgba(249, 115, 22, 0.96));
                }}
            </style>
            <div class="grade-chart-scroll">
                {chart_html}
            </div>
            """,
            height=360,
            scrolling=True,
        )
        st.write("")


def resolve_user_reviewer(user_id: int, latest_reviewer: dict | None = None) -> dict | None:
    active_reviewer_id = st.session_state.get("active_reviewer_id")
    reviewer = None

    if active_reviewer_id:
        reviewer = load_generated_reviewer_by_id(int(active_reviewer_id))
        if reviewer and int(reviewer["user_id"]) != int(user_id):
            reviewer = None
            st.session_state.active_reviewer_id = None

    if reviewer is None:
        reviewer = latest_reviewer or load_latest_generated_reviewer(int(user_id))

    if reviewer:
        st.session_state.active_reviewer_id = int(reviewer["id"])

    return reviewer


def initials_for(fullname: str) -> str:
    parts = [part for part in fullname.split() if part]
    if not parts:
        return "CS"
    return "".join(part[0] for part in parts[:2]).upper()


def is_blocked_upload(uploaded_file) -> bool:
    if not uploaded_file:
        return False

    file_name = getattr(uploaded_file, "name", "").lower()
    file_type = getattr(uploaded_file, "type", "").lower()
    return file_name.endswith(".mp4") or file_type == "video/mp4"


def init_session() -> None:
    defaults = {
        "route": "signin",
        "current_user": None,
        "user_page": "Overview",
        "admin_nav": "System Overview",
        "flash_message": None,
        "saved_api_key": load_key_permanently(),
        "saved_gmail_sender_email": load_gmail_sender_email_permanently(),
        "saved_system_prompt": load_system_prompt_permanently(),
        "gmail_sender_email_field": load_gmail_sender_email_permanently(),
        "gmail_app_password_field": "",
        "system_prompt_field": load_system_prompt_permanently(),
        "signin_identifier": "",
        "password_reset_open": False,
        "password_reset_step": "request",
        "password_reset_email": "",
        "password_reset_code_input": "",
        "password_reset_new_password": "",
        "password_reset_confirm_password": "",
        "module_subject": "Select Subject",
        "custom_module_subject": "",
        "summary_preference": "Short Summary",
        "quiz_preference": "Beginner (15 items)",
        "active_reviewer_id": None,
        "quiz_started": False,
        "quiz_finished": False,
        "quiz_index": 0,
        "quiz_score": 0,
        "quiz_question_started_at": None,
        "quiz_started_at": None,
        "quiz_total_seconds": 0,
        "quiz_answers": {},
        "quiz_result_saved": False,
        "quiz_last_result": None,
        "quiz_exit_target": None,
        "quiz_exit_label": "",
        "reviewer_quiz_confirm_reviewer_id": None,
        "reviewer_quiz_pending_difficulty": "",
        "admin_selected_user_activity_id": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value
    sync_system_prompt_state()


def set_flash(message_type: str, message: str) -> None:
    st.session_state.flash_message = {"type": message_type, "message": message}


def show_flash() -> None:
    flash_message = st.session_state.pop("flash_message", None)
    if not flash_message:
        return

    if flash_message["type"] == "success":
        st.success(flash_message["message"])
    elif flash_message["type"] == "warning":
        st.warning(flash_message["message"])
    else:
        st.error(flash_message["message"])


def go_to(route: str) -> None:
    valid_routes = {"signin", "signup", "reset_password", "user_dashboard", "admin_dashboard"}
    st.session_state.route = route if route in valid_routes else "signin"
    st.rerun()


def open_password_reset_page(prefill_email: str = "") -> None:
    st.session_state.password_reset_open = True
    st.session_state.password_reset_step = "request"
    normalized_email = prefill_email.strip().lower()
    if normalized_email and "@" in normalized_email and "." in normalized_email:
        st.session_state.password_reset_email = normalized_email
    st.session_state.route = "reset_password"
    st.rerun()


def logout_user() -> None:
    current_user = st.session_state.get("current_user")
    if current_user:
        log_system_activity(
            actor_name=current_user["fullname"],
            actor_role=current_user["role"],
            actor_id=int(current_user["id"]),
            activity="Signed out",
            details="User signed out of the current session.",
        )
    st.session_state.current_user = None
    st.session_state.user_page = "Overview"
    st.session_state.admin_nav = "System Overview"
    st.session_state.signin_identifier = ""
    clear_password_reset_state()
    st.session_state.active_reviewer_id = None
    st.session_state.quiz_started = False
    st.session_state.quiz_finished = False
    st.session_state.quiz_index = 0
    st.session_state.quiz_score = 0
    st.session_state.quiz_question_started_at = None
    st.session_state.quiz_started_at = None
    st.session_state.quiz_total_seconds = 0
    st.session_state.quiz_answers = {}
    st.session_state.quiz_result_saved = False
    st.session_state.quiz_last_result = None
    st.session_state.admin_selected_user_activity_id = None
    clear_reviewer_quiz_request()
    set_flash("success", "You have been signed out.")
    go_to("signin")


def open_reviewer_page(reviewer_id: int) -> None:
    clear_quiz_exit_request()
    st.session_state.active_reviewer_id = reviewer_id
    clear_reviewer_quiz_request()
    st.session_state.user_page = "Reviewer"
    st.rerun()


def open_quiz_page(reviewer_id: int) -> None:
    reviewer = load_generated_reviewer_by_id(int(reviewer_id))
    if not reviewer:
        set_flash("warning", "That reviewer could not be found anymore. Please open it again from your reviewer list.")
        st.session_state.user_page = "Overview"
        st.rerun()
    if not reviewer.get("quiz_payload"):
        set_flash("warning", "This reviewer does not have a quiz yet. Generate one first from the reviewer page.")
        open_reviewer_page(int(reviewer_id))
        return
    clear_quiz_exit_request()
    st.session_state.active_reviewer_id = reviewer_id
    clear_reviewer_quiz_request()
    st.session_state.user_page = "Quiz"
    reset_quiz_state()
    st.rerun()


def clear_quiz_exit_request() -> None:
    st.session_state.quiz_exit_target = None
    st.session_state.quiz_exit_label = ""


def clear_reviewer_quiz_request() -> None:
    st.session_state.reviewer_quiz_confirm_reviewer_id = None
    st.session_state.reviewer_quiz_pending_difficulty = ""


def request_quiz_exit(target_page: str, target_label: str) -> None:
    st.session_state.quiz_exit_target = target_page
    st.session_state.quiz_exit_label = target_label


def reset_quiz_state() -> None:
    st.session_state.quiz_started = False
    st.session_state.quiz_finished = False
    st.session_state.quiz_index = 0
    st.session_state.quiz_score = 0
    st.session_state.quiz_question_started_at = None
    st.session_state.quiz_started_at = None
    st.session_state.quiz_total_seconds = 0
    st.session_state.quiz_answers = {}
    st.session_state.quiz_result_saved = False
    st.session_state.quiz_last_result = None
    clear_quiz_exit_request()


def get_quiz_answer_key(question_index: int) -> str:
    return str(question_index)


def get_quiz_answer(question_index: int):
    return st.session_state.quiz_answers.get(get_quiz_answer_key(question_index))


def set_quiz_answer(question_index: int, answer) -> None:
    st.session_state.quiz_answers[get_quiz_answer_key(question_index)] = answer


def normalize_answer_text(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(text).lower()).strip()


def statement_word_tokens(statement: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9]+(?:[-'][A-Za-z0-9]+)?|[^\w\s]", statement)


def highlight_phrase_markup(statement: str, selected_phrase: str) -> str:
    phrase = str(selected_phrase or "").strip()
    if not phrase:
        return html.escape(statement)

    match = re.search(re.escape(phrase), statement, re.IGNORECASE)
    if not match:
        return html.escape(statement)

    before = html.escape(statement[: match.start()])
    highlighted = html.escape(statement[match.start() : match.end()])
    after = html.escape(statement[match.end() :])
    return f"{before}<mark class='quiz-highlight-token'>{highlighted}</mark>{after}"


def selected_modified_phrase(answer_state: dict, question: dict) -> str:
    direct_phrase = str(answer_state.get("selected_phrase", "")).strip()
    if direct_phrase:
        return direct_phrase
    selected_tokens = answer_state.get("selected_tokens", [])
    tokens = statement_word_tokens(question.get("statement", ""))
    chosen_tokens = [tokens[index] for index in selected_tokens if 0 <= index < len(tokens)]
    return " ".join(chosen_tokens).strip()


def get_modified_true_false_response(question_index: int) -> str:
    answer_state = get_quiz_answer(question_index)
    if not isinstance(answer_state, dict):
        return ""
    return str(answer_state.get("response", "")).strip()


def score_question(question_index: int, question: dict) -> int:
    answer_state = get_quiz_answer(question_index)
    question_type = question.get("type", "multiple_choice")

    if question_type == "multiple_choice":
        return int(answer_state == int(question.get("answer_index", -1)))

    if question_type == "true_false":
        return int(answer_state is not None and bool(answer_state) == bool(question.get("answer_bool")))

    if question_type == "matching":
        return int(answer_state is not None and str(answer_state).strip() == str(question.get("correct_answer", "")).strip())

    if question_type == "modified_true_false":
        if not isinstance(answer_state, dict):
            return 0
        verdict = normalize_answer_text(answer_state.get("response", ""))
        expected_truth = bool(question.get("answer_bool"))
        if expected_truth:
            return int(verdict == "true")
        if verdict == "true" or not verdict:
            return 0
        replacement_answer = normalize_answer_text(question.get("replacement_answer", ""))
        if replacement_answer and not (
            verdict == replacement_answer
            or verdict in replacement_answer
            or replacement_answer in verdict
        ):
            return 0
        incorrect_phrase = normalize_answer_text(question.get("incorrect_phrase", ""))
        selected_phrase = normalize_answer_text(selected_modified_phrase(answer_state, question))
        if not incorrect_phrase:
            return 1
        return int(bool(selected_phrase) and (incorrect_phrase in selected_phrase or selected_phrase in incorrect_phrase))

    if question_type == "identification":
        normalized_answer = normalize_answer_text(answer_state or "")
        accepted_answers = [normalize_answer_text(item) for item in question.get("accepted_answers", [])]
        return int(bool(normalized_answer) and any(normalized_answer == option or normalized_answer in option or option in normalized_answer for option in accepted_answers))

    if question_type == "enumeration":
        if isinstance(answer_state, list):
            normalized_entries = [normalize_answer_text(part) for part in answer_state if normalize_answer_text(part)]
        else:
            raw_answer = str(answer_state or "")
            normalized_entries = [normalize_answer_text(part) for part in re.split(r",|\n", raw_answer) if normalize_answer_text(part)]
        if not normalized_entries:
            return 0
        accepted_answers = [normalize_answer_text(item) for item in question.get("accepted_answers", [])]
        return int(
            all(
                any(entry == option or entry in option or option in entry for entry in normalized_entries)
                for option in accepted_answers
            )
        )

    return 0


def calculate_quiz_score(reviewer: dict) -> int:
    return sum(score_question(index, question) for index, question in enumerate(reviewer["quiz_payload"]))


def move_quiz_index(step: int, total_questions: int) -> None:
    st.session_state.quiz_index = max(0, min(total_questions - 1, st.session_state.quiz_index + step))


def get_matching_available_options(questions: list[dict], question_index: int) -> list[str]:
    current_question = questions[question_index]
    current_answer = get_quiz_answer(question_index)
    option_pool = list(current_question.get("match_options", []))
    used_answers = {
        str(answer).strip()
        for index, answer in ((idx, get_quiz_answer(idx)) for idx, item in enumerate(questions) if item.get("type") == "matching" and idx != question_index)
        if answer
    }
    available = [option for option in option_pool if option not in used_answers or option == current_answer]
    return available


def toggle_modified_token(question_index: int, token_index: int) -> None:
    answer_state = get_quiz_answer(question_index) or {"response": "", "selected_tokens": [], "highlight_mode": False}
    selected_tokens = list(answer_state.get("selected_tokens", []))
    if token_index in selected_tokens:
        selected_tokens.remove(token_index)
    else:
        selected_tokens.append(token_index)
        selected_tokens.sort()
    answer_state["selected_tokens"] = selected_tokens
    set_quiz_answer(question_index, answer_state)


def start_quiz_attempt(reviewer: dict) -> None:
    st.session_state.quiz_started = True
    st.session_state.quiz_finished = False
    st.session_state.quiz_index = 0
    st.session_state.quiz_score = 0
    st.session_state.quiz_question_started_at = None
    st.session_state.quiz_started_at = time.time()
    st.session_state.quiz_total_seconds = len(reviewer["quiz_payload"]) * 60
    st.session_state.quiz_answers = {}
    st.session_state.quiz_result_saved = False
    st.session_state.quiz_last_result = None


def finish_quiz_attempt(reviewer: dict) -> None:
    if st.session_state.quiz_result_saved:
        return

    total_questions = len(reviewer["quiz_payload"])
    final_score = calculate_quiz_score(reviewer)
    save_quiz_attempt(
        user_id=int(reviewer["user_id"]),
        reviewer_id=int(reviewer["id"]),
        file_name=reviewer["file_name"],
        subject=reviewer["subject"],
        score=int(final_score),
        total_questions=total_questions,
    )
    percentage = round((final_score / total_questions) * 100, 2) if total_questions else 0
    st.session_state.quiz_score = final_score
    st.session_state.quiz_last_result = {
        "score": final_score,
        "total_questions": total_questions,
        "percentage": percentage,
    }
    st.session_state.quiz_started = False
    st.session_state.quiz_finished = True
    st.session_state.quiz_result_saved = True
    st.session_state.quiz_question_started_at = None
    st.session_state.quiz_started_at = None
    current_user = st.session_state.get("current_user")
    if current_user:
        log_system_activity(
            actor_name=current_user["fullname"],
            actor_role=current_user["role"],
            actor_id=int(current_user["id"]),
            activity="Completed quiz",
            details=f"Scored {final_score}/{total_questions} in {reviewer['subject']} for {reviewer['file_name']}.",
        )


@st.fragment(run_every=1)
def render_quiz_timer_fragment(reviewer: dict) -> None:
    if not st.session_state.quiz_started or st.session_state.quiz_finished:
        return

    total_seconds = int(st.session_state.quiz_total_seconds or (len(reviewer["quiz_payload"]) * 60))
    elapsed = time.time() - float(st.session_state.quiz_started_at or time.time())
    remaining = max(0, total_seconds - int(elapsed))
    progress_width = max(0.0, min(100.0, (remaining / total_seconds) * 100 if total_seconds else 0))
    minutes, seconds = divmod(remaining, 60)
    st.markdown(
        f"""
        <div class="quiz-timer-line">
            <div class="quiz-timer-fill" style="width:{progress_width}%;"></div>
            <div class="quiz-timer-bubble" style="left:calc({progress_width}% - 28px);">
                {minutes:02d}:{seconds:02d}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if remaining <= 0:
        finish_quiz_attempt(reviewer)
        st.rerun()


def render_auth_shell(title: str, subtitle: str, allow_vertical_scroll: bool = False) -> None:
    logo_b64 = get_base64(LOGO_FILE)
    logo_markup = (
        f'<img src="data:image/png;base64,{logo_b64}" class="logo-img">'
        if logo_b64
        else '<div class="logo-fallback">CS</div>'
    )

    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@300;400;500;600;700;800&display=swap');
        :root {
            --primary-orange: #ff6b35;
            --glow-navy: #1e293b;
            --bg-obsidian: #020617;
            --input-bg: rgba(38, 50, 69, 0.6);
            --border-glass: rgba(255, 255, 255, 0.10);
            --auth-stage-lift: 34px;
        }
        * { font-family: 'Plus Jakarta Sans', sans-serif; }
        html, body, .stApp, [data-testid="stAppViewContainer"], [data-testid="stMain"], [data-testid="stMainBlockContainer"] {
            height: 100dvh !important;
            max-height: 100dvh !important;
            overflow: hidden !important;
            overscroll-behavior: none !important;
        }
        body { margin: 0 !important; }
        .stApp { background: radial-gradient(circle at 0% 100%, var(--glow-navy) 0%, var(--bg-obsidian) 100%); }
        header, footer, .stDeployButton, [data-testid="stSidebarCollapsedControl"] { display: none !important; }
        section[data-testid="stSidebar"] {
            display: none !important;
            width: 0 !important;
            min-width: 0 !important;
            max-width: 0 !important;
            flex: 0 0 0 !important;
            margin: 0 !important;
            padding: 0 !important;
        }
        [data-testid="stSidebarUserContent"] {
            display: none !important;
        }
        [data-testid="stAppViewContainer"] > section[data-testid="stMain"] {
            width: 100% !important;
            min-width: 100% !important;
            max-width: 100% !important;
        }
        section[data-testid="stMain"] {
            overflow: hidden !important;
        }
        [data-testid="block-container"] {
            padding: 0 !important;
            max-width: none !important;
            height: 100dvh !important;
            max-height: 100dvh !important;
            overflow: hidden !important;
        }
        html::-webkit-scrollbar, body::-webkit-scrollbar, [data-testid="stMain"]::-webkit-scrollbar { display: none !important; }
        .auth-header { width: 100%; text-align: center; padding-top: 6px; }
        .logo-img, .logo-fallback { width: 78px; height: 78px; margin: 0 auto 4px auto; }
        .logo-fallback {
            display: flex; align-items: center; justify-content: center;
            background: white; color: var(--primary-orange); border-radius: 18px;
            font-weight: 800; letter-spacing: 1px;
        }
        .brand-tag { font-size: 10px; color: white; letter-spacing: 4px; font-weight: 600; text-transform: uppercase; }
        .auth-stage-lift {
            margin-top: calc(var(--auth-stage-lift) * -1);
        }
        .orange-line-divider {
            width: 100vw;
            max-width: 100vw;
            height: 2px;
            background-color: var(--primary-orange);
            margin: 10px calc(50% - 50vw) 24px calc(50% - 50vw);
            position: relative;
        }
        .auth-heading {
            text-align: center;
            margin-bottom: 10px;
            margin-top: 0;
        }
        .auth-form-lift {
            margin-top: 0;
        }
        .title-main {
            font-size: 54px; font-weight: 800; color: white; text-align: center;
            margin: 0; letter-spacing: -2px; line-height: 1;
        }
        .title-sub {
            font-size: 32px; font-weight: 600; color: white; text-align: center;
            margin: 10px 0 0 0; line-height: 1.05;
        }
        .field-label {
            color: white; font-size: 13px; font-weight: 600;
            margin: 0 0 6px 0;
        }
        [data-testid="stTextInput"] > div [data-baseweb="input"] {
            background-color: var(--input-bg) !important;
            border: 1px solid rgba(255, 255, 255, 0.02) !important;
            border-radius: 10px !important;
            min-height: 40px;
            box-shadow: none !important;
        }
        .stTextInput input {
            color: white !important;
            font-size: 14px !important;
        }
        [data-testid="stTextInputPasswordVisibility"] {
            color: rgba(255, 255, 255, 0.9) !important;
            background: transparent !important;
        }
        div.stButton {
            margin: 0 !important;
        }
        div.stButton > button[kind="secondary"] {
            background: transparent !important;
            color: #8ea0c4 !important;
            border: none !important;
            padding: 0 !important;
            min-height: auto !important;
            height: auto !important;
            line-height: 1.2 !important;
            border-radius: 0 !important;
            box-shadow: none !important;
            font-weight: 500 !important;
            font-size: 13px !important;
            text-decoration: none !important;
            justify-content: flex-start !important;
            cursor: pointer !important;
            width: fit-content !important;
            min-width: 0 !important;
            max-width: none !important;
            white-space: nowrap !important;
            transition: color 0.18s ease, transform 0.18s ease, opacity 0.18s ease !important;
        }
        div.stButton > button[kind="secondary"] p,
        div.stButton > button[kind="secondary"] span,
        div.stButton > button[kind="secondary"] div {
            font-size: 13px !important;
            line-height: 1.2 !important;
            font-weight: 500 !important;
            color: inherit !important;
        }
        div.stButton > button[kind="secondary"]:hover {
            background: transparent !important;
            color: #ff6b35 !important;
            border: none !important;
            transform: translateY(-1px) !important;
        }
        div.stButton > button[kind="secondary"]:focus,
        div.stButton > button[kind="secondary"]:focus-visible {
            outline: none !important;
            box-shadow: none !important;
        }
        div.stButton > button[kind="primary"] {
            background: linear-gradient(90deg, #ff6b35, #f97316) !important;
            color: white !important;
            border: none !important;
            border-radius: 999px !important;
            box-shadow: 0 10px 25px rgba(255, 107, 53, 0.25) !important;
            font-size: 15px !important;
            font-weight: 700 !important;
            width: 148px !important;
            min-width: 148px !important;
            height: 44px !important;
            min-height: 44px !important;
            justify-content: center !important;
            margin-left: auto !important;
            padding: 0 18px !important;
            cursor: pointer !important;
            transition: transform 0.18s ease, box-shadow 0.18s ease, filter 0.18s ease !important;
        }
        div.stButton > button[kind="primary"]:hover {
            color: white !important;
            background: linear-gradient(90deg, #ff6b35, #f97316) !important;
            transform: translateY(-2px) !important;
            box-shadow: 0 14px 32px rgba(255, 107, 53, 0.32) !important;
            filter: brightness(1.03) !important;
        }
        .auth-hint {
            color: #7f90b1;
            font-size: 12px;
            margin: 6px 0 10px 0;
            line-height: 1.2;
        }
        .auth-static-link {
            color: #8ea0c4;
            font-size: 13px;
            line-height: 1.2;
            margin-top: 0;
            margin-bottom: 6px;
            user-select: none;
            transition: color 0.18s ease;
        }
        .auth-footer-gap {
            height: 2px;
        }
        .auth-reset-panel {
            margin-top: 16px;
            padding: 18px 18px 14px 18px;
            border-radius: 18px;
            background: rgba(12, 20, 34, 0.72);
            border: 1px solid rgba(255, 107, 53, 0.18);
            box-shadow: 0 16px 36px rgba(0, 0, 0, 0.18);
        }
        .auth-reset-title {
            color: white;
            font-size: 18px;
            font-weight: 700;
            margin: 0 0 6px 0;
        }
        .auth-reset-copy {
            color: #9db0d1;
            font-size: 13px;
            line-height: 1.6;
            margin: 0 0 14px 0;
        }
        .auth-reset-note {
            color: #ffb089;
            font-size: 12px;
            line-height: 1.6;
            margin: 0 0 14px 0;
            font-weight: 600;
        }
        .st-key-reset_request_actions div.stButton > button[kind="primary"] {
            width: 100% !important;
            min-width: 0 !important;
            margin-left: 0 !important;
        }
        .st-key-reset_verify_actions div.stButton > button[kind="primary"] {
            width: 100% !important;
            min-width: 0 !important;
            margin-left: 0 !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    if allow_vertical_scroll:
        st.markdown(
            """
            <style>
            html, body, .stApp, [data-testid="stAppViewContainer"], [data-testid="stMainBlockContainer"] {
                min-height: 100dvh !important;
                height: auto !important;
                max-height: none !important;
                overflow-x: hidden !important;
                overflow-y: auto !important;
            }
            section[data-testid="stMain"] {
                height: 100dvh !important;
                max-height: 100dvh !important;
                overflow-x: hidden !important;
                overflow-y: scroll !important;
                overscroll-behavior-y: contain !important;
            }
            [data-testid="block-container"] {
                min-height: calc(100dvh + 96px) !important;
                height: auto !important;
                max-height: none !important;
                overflow-y: visible !important;
                padding-bottom: 72px !important;
            }
            </style>
            """,
            unsafe_allow_html=True,
        )

    st.markdown(
        f"""
        <div class="auth-stage-lift">
            <div class="auth-header">
                {logo_markup}
                <div class="brand-tag">CyberNauts</div>
            </div>
            <div class="orange-line-divider"></div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    _, center_col, _ = st.columns([1.65, 0.95, 1.65])
    with center_col:
        st.markdown(
            f"""
            <div class="auth-heading">
                <h1 class="title-main">CogniStudy</h1>
                <h2 class="title-sub">{title}</h2>
            </div>
            """,
            unsafe_allow_html=True,
        )
        show_flash()


def render_signin() -> None:
    render_auth_shell("Sign in", "")

    _, center_col, _ = st.columns([1.65, 0.95, 1.65])
    with center_col:
        st.markdown('<div class="auth-form-lift">', unsafe_allow_html=True)
        st.markdown('<div class="field-label">Fullname or Email</div>', unsafe_allow_html=True)
        identifier = st.text_input(
            "Fullname or Email",
            value=st.session_state.get("signin_identifier", ""),
            label_visibility="collapsed",
            key="signin_identifier_input",
        )
        st.markdown('<div class="auth-footer-gap"></div>', unsafe_allow_html=True)
        st.markdown('<div class="field-label">Password</div>', unsafe_allow_html=True)
        password = st.text_input(
            "Password",
            type="password",
            label_visibility="collapsed",
            key="signin_password_input",
        )

        footer_top_left, footer_top_right = st.columns([1.7, 1])
        with footer_top_left:
            if st.button("Forgot password", key="forgot_password_toggle", type="secondary"):
                open_password_reset_page(identifier)
            if st.button("Don't have an account? Sign up", key="go_signup", type="secondary"):
                clear_password_reset_state()
                go_to("signup")
        with footer_top_right:
            if st.button("Sign in", key="signin_submit", type="primary"):
                st.session_state.signin_identifier = identifier
                user, auth_error = authenticate_user(identifier, password)
                if user:
                    clear_password_reset_state()
                    st.session_state.current_user = user
                    st.session_state.user_page = "Overview"
                    st.session_state.admin_nav = "System Overview"
                    log_system_activity(
                        actor_name=user["fullname"],
                        actor_role=user["role"],
                        actor_id=int(user["id"]),
                        activity="Signed in",
                        details=f"Signed in through the main authentication screen as {user['role']}.",
                    )
                    set_flash("success", f"Welcome back, {user['fullname']}.")
                    append_usage(250)
                    if user["role"] == "admin":
                        go_to("admin_dashboard")
                    else:
                        go_to("user_dashboard")
                else:
                    st.error(auth_error or "Invalid credentials. Check your full name or email and password.")
        st.markdown('</div>', unsafe_allow_html=True)


def render_signup() -> None:
    render_auth_shell("Sign up", "")

    _, center_col, _ = st.columns([1.65, 0.95, 1.65])
    with center_col:
        st.markdown('<div class="auth-form-lift">', unsafe_allow_html=True)
        st.markdown('<div class="field-label">Fullname</div>', unsafe_allow_html=True)
        fullname = st.text_input(
            "Fullname",
            label_visibility="collapsed",
            key="signup_fullname_input",
        )

        st.markdown('<div class="auth-footer-gap"></div>', unsafe_allow_html=True)
        st.markdown('<div class="field-label">Email</div>', unsafe_allow_html=True)
        email = st.text_input(
            "Email",
            label_visibility="collapsed",
            key="signup_email_input",
        )

        st.markdown('<div class="auth-footer-gap"></div>', unsafe_allow_html=True)
        st.markdown('<div class="field-label">Password</div>', unsafe_allow_html=True)
        password = st.text_input(
            "Password",
            type="password",
            label_visibility="collapsed",
            key="signup_password_input",
        )

        st.markdown('<div class="auth-footer-gap"></div>', unsafe_allow_html=True)
        st.markdown('<div class="field-label">Confirm Password</div>', unsafe_allow_html=True)
        confirm_password = st.text_input(
            "Confirm Password",
            type="password",
            label_visibility="collapsed",
            key="signup_confirm_password_input",
        )

        footer_left, footer_right = st.columns([1.55, 1])
        with footer_left:
            if st.button("Already have an account? Sign in", key="back_to_signin", type="secondary"):
                clear_password_reset_state()
                go_to("signin")
        with footer_right:
            if st.button("Sign up", key="signup_submit", type="primary"):
                if password != confirm_password:
                    st.error("Passwords do not match.")
                else:
                    success, message = register_user(fullname, email, password)
                    if success:
                        st.session_state.signin_identifier = fullname
                        clear_password_reset_state()
                        set_flash("success", message)
                        append_usage(100)
                        go_to("signin")
                    else:
                        st.error(message)
        st.markdown('</div>', unsafe_allow_html=True)


def render_reset_password() -> None:
    render_auth_shell("Reset password", "", allow_vertical_scroll=True)

    _, center_col, _ = st.columns([1.65, 0.95, 1.65])
    with center_col:
        st.markdown('<div class="auth-form-lift">', unsafe_allow_html=True)
        if st.session_state.password_reset_step == "request":
            st.markdown('<div class="auth-reset-title">Reset your password</div>', unsafe_allow_html=True)
            st.markdown(
                '<div class="auth-reset-copy">Enter the email address you used when you created your account. We will send a unique 6-digit verification code there.</div>',
                unsafe_allow_html=True,
            )
            st.markdown('<div class="field-label">Account Email</div>', unsafe_allow_html=True)
            st.text_input(
                "Account Email",
                key="password_reset_email",
                label_visibility="collapsed",
                placeholder="Enter your registered email",
            )

            with st.container(key="reset_request_actions"):
                request_left, request_right = st.columns([0.8, 1.2])
                with request_left:
                    if st.button("Cancel", key="cancel_reset_request_page", type="secondary", use_container_width=True):
                        clear_password_reset_state()
                        go_to("signin")
                with request_right:
                    if st.button("Send code", key="send_reset_code_page", type="primary", use_container_width=True):
                        success, message = create_password_reset_request(st.session_state.password_reset_email)
                        if success:
                            st.session_state.password_reset_step = "verify"
                            st.session_state.password_reset_code_input = ""
                            st.session_state.password_reset_new_password = ""
                            st.session_state.password_reset_confirm_password = ""
                            set_flash("success", message)
                            st.rerun()
                        st.error(message)
        else:
            st.markdown('<div class="auth-reset-title">Enter your verification code</div>', unsafe_allow_html=True)
            st.markdown(
                f'<div class="auth-reset-copy">We sent a reset code to <strong>{html.escape(mask_email_address(st.session_state.password_reset_email))}</strong>. Enter the code below and choose your new password.</div>',
                unsafe_allow_html=True,
            )
            st.markdown(
                '<div class="auth-reset-note">The code expires in 30 minutes. Request a new code if it expires before you finish.</div>',
                unsafe_allow_html=True,
            )
            st.markdown('<div class="field-label">Account Email</div>', unsafe_allow_html=True)
            st.text_input(
                "Reset Email",
                key="password_reset_email",
                label_visibility="collapsed",
                disabled=True,
            )
            st.markdown('<div class="auth-footer-gap"></div>', unsafe_allow_html=True)
            st.markdown('<div class="field-label">6-digit Code</div>', unsafe_allow_html=True)
            st.text_input(
                "6-digit Code",
                key="password_reset_code_input",
                label_visibility="collapsed",
                max_chars=6,
                placeholder="Enter the code from your email",
            )
            st.markdown('<div class="auth-footer-gap"></div>', unsafe_allow_html=True)
            st.markdown('<div class="field-label">New Password</div>', unsafe_allow_html=True)
            st.text_input(
                "New Password",
                type="password",
                key="password_reset_new_password",
                label_visibility="collapsed",
            )
            st.markdown('<div class="auth-footer-gap"></div>', unsafe_allow_html=True)
            st.markdown('<div class="field-label">Confirm New Password</div>', unsafe_allow_html=True)
            st.text_input(
                "Confirm New Password",
                type="password",
                key="password_reset_confirm_password",
                label_visibility="collapsed",
            )

            with st.container(key="reset_verify_actions"):
                verify_left, verify_right = st.columns([0.82, 1.18])
                with verify_left:
                    if st.button("Cancel", key="cancel_reset_verify_page", type="secondary", use_container_width=True):
                        clear_password_reset_state()
                        go_to("signin")
                    st.markdown('<div class="auth-footer-gap"></div>', unsafe_allow_html=True)
                    if st.button("Send new code", key="resend_reset_code_page", type="secondary", use_container_width=True):
                        success, message = create_password_reset_request(st.session_state.password_reset_email)
                        if success:
                            st.session_state.password_reset_code_input = ""
                            st.session_state.password_reset_new_password = ""
                            st.session_state.password_reset_confirm_password = ""
                            set_flash("success", message)
                            st.rerun()
                        st.error(message)
                with verify_right:
                    if st.button("Save", key="confirm_password_reset_page", type="primary", use_container_width=True):
                        success, message = reset_password_with_code(
                            st.session_state.password_reset_email,
                            st.session_state.password_reset_code_input,
                            st.session_state.password_reset_new_password,
                            st.session_state.password_reset_confirm_password,
                        )
                        if success:
                            st.session_state.signin_identifier = st.session_state.password_reset_email
                            clear_password_reset_state()
                            set_flash("success", message)
                            go_to("signin")
                        st.error(message)
        st.markdown('</div>', unsafe_allow_html=True)


def inject_user_dashboard_css() -> None:
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@300;400;500;600;700;800&display=swap');
        :root {
            --primary-orange: #ff6b35;
            --bg-obsidian: #020617;
            --sidebar-navy: #112240;
            --card-slate: rgba(30, 41, 59, 0.4);
            --text-white: #f8fafc;
            --border-glass: rgba(255, 255, 255, 0.08);
        }
        * { font-family: 'Plus Jakarta Sans', sans-serif; }
        .stApp { background: radial-gradient(circle at 0% 100%, #1e293b, #020617); color: var(--text-white); }
        header[data-testid="stHeader"],
        [data-testid="stToolbar"],
        [data-testid="stDecoration"],
        .stDeployButton,
        #MainMenu,
        footer {
            display: none !important;
            visibility: hidden !important;
        }
        [data-testid="block-container"] {
            padding-top: 0.85rem !important;
        }
        [data-testid="stAppViewContainer"],
        [data-testid="stMain"],
        [data-testid="block-container"],
        [data-testid="stVerticalBlock"] {
            caret-color: transparent !important;
        }
        input,
        textarea,
        [contenteditable="true"],
        [data-baseweb="input"] input {
            caret-color: auto !important;
        }
        [data-testid="stSidebarCollapsedControl"] {
            background-color: var(--sidebar-navy) !important;
            color: var(--primary-orange) !important;
            border: 1px solid var(--border-glass) !important;
            border-radius: 0 10px 10px 0 !important;
            top: 10px !important;
        }
        [data-testid="stSidebar"] {
            background-color: var(--sidebar-navy) !important;
            border-right: 1px solid var(--border-glass);
        }
        .user-identity {
            background: linear-gradient(135deg, #ff6b35 0%, #f97316 100%);
            padding: 20px; border-radius: 20px; margin-bottom: 0;
            box-shadow: 0 10px 20px rgba(255, 107, 53, 0.2);
            position: relative;
            transition: transform 0.2s ease, box-shadow 0.2s ease, filter 0.2s ease;
        }
        .user-identity.is-active {
            box-shadow: 0 0 0 1px rgba(255, 206, 180, 0.35), 0 14px 28px rgba(255, 107, 53, 0.24);
        }
        .st-key-user_profile_wrap:hover .user-identity {
            transform: translateY(-2px);
            box-shadow: 0 0 0 1px rgba(255, 206, 180, 0.28), 0 18px 34px rgba(255, 107, 53, 0.28);
            filter: brightness(1.02);
        }
        .bento-card {
            background: var(--card-slate);
            backdrop-filter: blur(15px);
            border: 1px solid var(--border-glass);
            border-radius: 24px;
            padding: 24px;
            transition: transform 0.18s ease, border-color 0.18s ease, box-shadow 0.18s ease, background 0.18s ease;
        }
        .bento-card:hover {
            transform: translateY(-2px) scale(1.005);
            border-color: rgba(255, 140, 92, 0.20);
            box-shadow: 0 16px 30px rgba(2, 6, 23, 0.18);
            background: rgba(30, 41, 59, 0.48);
        }
        [data-testid="stSidebar"] .st-key-user_profile_wrap {
            position: relative;
            margin-bottom: 25px;
        }
        [data-testid="stSidebar"] .st-key-user_profile_card {
            position: absolute;
            inset: 0;
            z-index: 4;
            margin: 0 !important;
        }
        [data-testid="stSidebar"] .st-key-user_profile_card div.stButton {
            height: 100% !important;
        }
        [data-testid="stSidebar"] .st-key-user_profile_card div.stButton > button {
            width: 100% !important;
            min-height: 100% !important;
            height: 100% !important;
            border-radius: 20px !important;
            background: transparent !important;
            border: none !important;
            box-shadow: none !important;
            color: transparent !important;
            padding: 0 !important;
            margin: 0 !important;
            font-size: 0 !important;
            cursor: pointer !important;
        }
        [data-testid="stSidebar"] .st-key-user_profile_card div.stButton > button:hover,
        [data-testid="stSidebar"] .st-key-user_profile_card div.stButton > button:focus,
        [data-testid="stSidebar"] .st-key-user_profile_card div.stButton > button:focus-visible {
            background: transparent !important;
            border: none !important;
            box-shadow: none !important;
            color: transparent !important;
            outline: none !important;
        }
        [data-testid="stSidebar"] .st-key-user_profile_card div.stButton > button p,
        [data-testid="stSidebar"] .st-key-user_profile_card div.stButton > button span,
        [data-testid="stSidebar"] .st-key-user_profile_card div.stButton > button div {
            font-size: 0 !important;
            line-height: 0 !important;
            color: transparent !important;
        }
        .meter-bar-bg {
            height: 8px; background: rgba(255, 255, 255, 0.05);
            border-radius: 10px; margin-top: 15px;
        }
        .meter-bar-fill {
            height: 100%; background: linear-gradient(90deg, #ff6b35, #f97316);
            border-radius: 10px; box-shadow: 0 0 15px rgba(255, 107, 53, 0.4);
        }
        div.stButton > button { border-radius: 12px !important; font-weight: 600 !important; }
        [data-testid="stSidebar"] div.stButton > button[kind="secondary"] {
            background: rgba(255, 255, 255, 0.08) !important;
            color: white !important;
            border: 1px solid rgba(255, 255, 255, 0.14) !important;
            min-height: 42px !important;
            transition: background 0.18s ease, border-color 0.18s ease, box-shadow 0.18s ease, transform 0.18s ease !important;
        }
        [data-testid="stSidebar"] div.stButton > button[kind="secondary"]:hover {
            background: rgba(255, 107, 53, 0.20) !important;
            color: white !important;
            border: 1px solid rgba(255, 140, 92, 0.34) !important;
            box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.06), 0 8px 20px rgba(255, 107, 53, 0.12) !important;
            transform: translateY(-1px) !important;
        }
        [data-testid="stSidebar"] div.stButton > button[kind="secondary"]:focus,
        [data-testid="stSidebar"] div.stButton > button[kind="secondary"]:focus-visible {
            background: rgba(255, 107, 53, 0.20) !important;
            color: white !important;
            border: 1px solid rgba(255, 140, 92, 0.34) !important;
            box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.06), 0 8px 20px rgba(255, 107, 53, 0.12) !important;
            outline: none !important;
        }
        [data-testid="stSidebar"] div.stButton > button[kind="primary"] {
            background: rgba(255, 107, 53, 0.20) !important;
            color: white !important;
            border: 1px solid rgba(255, 140, 92, 0.34) !important;
            min-height: 42px !important;
            box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.06), 0 8px 20px rgba(255, 107, 53, 0.12) !important;
            transition: background 0.18s ease, border-color 0.18s ease, box-shadow 0.18s ease, transform 0.18s ease !important;
        }
        [data-testid="stSidebar"] div.stButton > button[kind="primary"]:hover {
            background: rgba(255, 107, 53, 0.25) !important;
            color: white !important;
            border: 1px solid rgba(255, 140, 92, 0.4) !important;
            transform: translateY(-1px) !important;
            box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.07), 0 10px 24px rgba(255, 107, 53, 0.16) !important;
        }
        [data-testid="stSidebar"] .st-key-user_profile_card div.stButton > button[kind="secondary"] {
            opacity: 0 !important;
            background: transparent !important;
            border: none !important;
            box-shadow: none !important;
            color: transparent !important;
        }
        [data-testid="stSidebar"] .st-key-user_profile_card div.stButton > button[kind="secondary"]:hover,
        [data-testid="stSidebar"] .st-key-user_profile_card div.stButton > button[kind="secondary"]:focus,
        [data-testid="stSidebar"] .st-key-user_profile_card div.stButton > button[kind="secondary"]:focus-visible {
            opacity: 0 !important;
            background: transparent !important;
            border: none !important;
            box-shadow: none !important;
            color: transparent !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_user_dashboard() -> None:
    inject_user_dashboard_css()
    quiz_mode = st.session_state.user_page == "Quiz"
    if quiz_mode:
        st.markdown(
            """
            <style>
            [data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"] {
                display: none !important;
            }
            </style>
            """,
            unsafe_allow_html=True,
        )
    user = st.session_state.current_user
    greeting_name = user["fullname"].split()[0] if user else "Scholar"
    user_documents = load_user_documents(int(user["id"])) if user else []
    latest_reviewer = load_latest_generated_reviewer(int(user["id"])) if user else None
    current_reviewer = resolve_user_reviewer(int(user["id"]), latest_reviewer) if user else None
    insight_cards = build_user_insight_cards(int(user["id"]), current_reviewer or latest_reviewer) if user else []

    if not quiz_mode:
        with st.sidebar:
            render_sidebar_brand(
                "<h1 style='color:white; font-size:24px; letter-spacing:-1px;'>Cogni"
                "<span style='color:#ff6b35'>Study</span></h1>"
            )
            profile_card_class = " is-active" if st.session_state.user_page == "Profile" else ""
            with st.container(key="user_profile_wrap"):
                st.markdown(
                    f"""
                    <div class="user-identity{profile_card_class}">
                        <div style="display:flex; align-items:center; gap:12px;">
                            <div style="background:white; width:40px; height:40px; border-radius:12px; display:flex; align-items:center; justify-content:center; font-weight:800; color:#ff6b35;">
                                {initials_for(user['fullname'])}
                            </div>
                            <div>
                                <div style="color:white; font-size:14px; font-weight:700;">{user['fullname']}</div>
                                <div style="color:rgba(255,255,255,0.8); font-size:10px; font-weight:800; letter-spacing:1px;">{user['plan'].upper()} SCHOLAR</div>
                            </div>
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                if st.button("Open profile", use_container_width=True, key="user_profile_card", type="secondary"):
                    clear_reviewer_quiz_request()
                    st.session_state.user_page = "Profile"
                    st.rerun()

            if st.button(
                "System Overview",
                use_container_width=True,
                key="user_overview",
                type="primary" if st.session_state.user_page == "Overview" else "secondary",
            ):
                clear_reviewer_quiz_request()
                st.session_state.user_page = "Overview"
                st.rerun()
            if st.button(
                "Reviewer Library",
                use_container_width=True,
                key="user_library",
                type="primary" if st.session_state.user_page == "Library" else "secondary",
            ):
                clear_reviewer_quiz_request()
                st.session_state.user_page = "Library"
                st.rerun()
            if st.button(
                "Grade Analytics",
                use_container_width=True,
                key="user_analytics",
                type="primary" if st.session_state.user_page == "Analytics" else "secondary",
            ):
                clear_reviewer_quiz_request()
                st.session_state.user_page = "Analytics"
                st.rerun()

            st.write("###")
            st.markdown(
                "<p style='font-size:11px; color:#94A3B8; font-weight:700; margin-bottom:10px; letter-spacing:1px;'>SYSTEM</p>",
                unsafe_allow_html=True,
            )
            brightness = st.slider("Adjust Brightness", 10, 100, 100, key="brightness")
            eye_protection = st.toggle("Eye Protection Mode", key="eye_protection")

            brightness_opacity = (100 - brightness) / 100 * 0.8
            eye_display = "block" if eye_protection else "none"
            eye_opacity = 0.15 if eye_protection else 0

            st.markdown(
                f"""
                <div style="position:fixed; top:0; left:0; width:100vw; height:100vh; background:black; pointer-events:none; z-index:9999999; opacity:{brightness_opacity};"></div>
                <div style="position:fixed; top:0; left:0; width:100vw; height:100vh; background:#ff9100; pointer-events:none; z-index:9999998; display:{eye_display}; opacity:{eye_opacity};"></div>
                """,
                unsafe_allow_html=True,
            )

            st.write("###")
            if st.button("Log out", use_container_width=True, key="user_logout"):
                logout_user()

    show_flash()

    if st.session_state.user_page == "Overview":
        now = datetime.now()
        greeting = "Good Evening" if now.hour >= 18 else "Good Day"
        api_ready = bool(st.session_state.saved_api_key)

        head_col1, head_col2 = st.columns([3, 1])
        with head_col1:
            st.markdown(
                f"<h1 style='color:white; font-size:42px; font-weight:800; margin-bottom:0;'>{greeting}, {greeting_name}.</h1>",
                unsafe_allow_html=True,
            )
            st.markdown(
                "<p style='color:#94A3B8; font-size:18px;'>Build structured summaries and downloadable reviewer files from your teacher's module, then generate quizzes later from inside the reviewer.</p>",
                unsafe_allow_html=True,
            )
        with head_col2:
            st.write("##")
            st.markdown(
                "<div style='text-align:right;'><span style='color:#2DD4BF; border:1px solid rgba(45,212,191,0.3); background:rgba(45,212,191,0.1); padding:4px 12px; border-radius:50px; font-size:11px; font-weight:800;'>SYSTEM OPERATIONAL</span></div>",
                unsafe_allow_html=True,
            )

        st.write("##")
        col_engine, col_radar = st.columns([1.8, 1])
        with col_engine:
            selected_subject = get_selected_module_subject()
            summary_options = ["Short Summary", "Detailed Summary"]
            if st.session_state.summary_preference not in summary_options:
                st.session_state.summary_preference = "Short Summary"
            st.markdown("<div class='bento-card' style='height:100%;'>", unsafe_allow_html=True)
            st.markdown(
                "<p style='color:#94A3B8; font-size:11px; font-weight:800; margin:0 0 14px 0;'>MODULE INPUT</p>",
                unsafe_allow_html=True,
            )
            subject_left, subject_right = st.columns([1.2, 1])
            with subject_left:
                st.selectbox(
                    "Module Subject",
                    MODULE_SUBJECT_OPTIONS,
                    key="module_subject",
                )
            with subject_right:
                if st.session_state.module_subject == "Custom":
                    st.text_input(
                        "Custom Subject",
                        key="custom_module_subject",
                        placeholder="Enter subject name",
                    )
                else:
                    st.markdown(
                        f"<p style='color:#94A3B8; font-size:13px; font-weight:600; margin-top:34px;'>{'Subject ready for upload' if selected_subject else 'Choose a subject to unlock file browsing'}</p>",
                        unsafe_allow_html=True,
                    )
            uploaded_file = st.file_uploader(
                "Browse Module",
                key="user_upload",
                disabled=not bool(selected_subject),
            )
            if not selected_subject:
                st.caption("Select the module subject first. After that, you can browse and upload the file.")
            selected_summary_preference = st.selectbox(
                "Summary Preference",
                summary_options,
                key="summary_preference",
            )
            if uploaded_file:
                if is_blocked_upload(uploaded_file):
                    st.error("MP4 files are not allowed. Please upload any other file type.")
                else:
                    st.info(f"File ready: {uploaded_file.name}")
                    if st.button("Generate Module >>", key="synthesis", use_container_width=True):
                        extracted_module_text = extract_uploaded_file_text(uploaded_file)
                        detected_subject = selected_subject or infer_subject_from_filename(uploaded_file.name)
                        document_id = record_user_document(
                            int(user["id"]),
                            uploaded_file.name,
                            detected_subject,
                        )
                        try:
                            reviewer_id, generation_mode, generation_reason = create_generated_reviewer(
                                user_id=int(user["id"]),
                                document_id=document_id,
                                file_name=uploaded_file.name,
                                subject=detected_subject,
                                summary_preference=selected_summary_preference,
                                module_text=extracted_module_text,
                            )
                        except Exception as error:
                            log_system_activity(
                                actor_name=user["fullname"],
                                actor_role=user["role"],
                                actor_id=int(user["id"]),
                                activity="Generation failed",
                                details=f"Live AI generation failed for {uploaded_file.name} under {detected_subject}. Reason: {error}",
                            )
                            set_flash("error", f"Synthesis failed for {uploaded_file.name}. {error}")
                            st.rerun()

                        append_usage(1200)
                        st.session_state.active_reviewer_id = reviewer_id
                        set_flash(
                            "success",
                            (
                                f"Synthesis complete. AI reviewer is ready for {uploaded_file.name}."
                                if not generation_reason
                                else f"Synthesis complete for {uploaded_file.name}. {generation_reason}"
                            ),
                        )
                        st.rerun()
            if current_reviewer:
                st.markdown(
                    "<p style='color:#2DD4BF; font-size:12px; font-weight:700; margin:18px 0 10px 0;'>Latest reviewer is ready.</p>",
                    unsafe_allow_html=True,
                )
                if st.button("View Reviewer >>", key="view_reviewer_action", use_container_width=True):
                    open_reviewer_page(int(current_reviewer["id"]))
            st.markdown("</div>", unsafe_allow_html=True)

        with col_radar:
            if user_documents:
                upload_total = len(user_documents)
                meter_width = min(100, max(20, upload_total * 20))
                st.markdown(
                    f"""
                    <div class="bento-card">
                        <p style="color:#94A3B8; font-size:11px; font-weight:800; margin:0;">UPLOAD HISTORY</p>
                        <h1 style="margin:0; font-size:38px; font-weight:800; color:white;">{upload_total}</h1>
                        <div class="meter-bar-bg"><div class="meter-bar-fill" style="width:{meter_width}%;"></div></div>
                        <p style="color:#ff6b35; font-size:11px; font-weight:800; margin-top:5px;">MODULES PROCESSED IN YOUR ACCOUNT</p>
                    </div>
                    <div style="margin-top:20px;"></div>
                    """,
                    unsafe_allow_html=True,
                )
                st.markdown("<div class='bento-card'>", unsafe_allow_html=True)
                st.markdown(
                    "<p style='color:white; font-weight:800; font-size:13px; margin-top:0;'>SUBJECT ACTIVITY</p>",
                    unsafe_allow_html=True,
                )
                mastery_data = (
                    pd.DataFrame(user_documents)
                    .groupby("subject")
                    .size()
                    .reset_index(name="Uploads")
                    .rename(columns={"subject": "Subject"})
                )
                fig = px.line_polar(mastery_data, r="Uploads", theta="Subject", line_close=True)
                fig.update_traces(
                    fill="toself",
                    line_color="#ff6b35",
                    fillcolor="rgba(255, 107, 53, 0.4)",
                )
                fig.update_layout(
                    paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="rgba(0,0,0,0)",
                    font=dict(color="white", size=11),
                    polar=dict(bgcolor="rgba(0,0,0,0)", radialaxis=dict(visible=False)),
                    margin=dict(l=50, r=50, t=40, b=40),
                    height=280,
                )
                st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
                st.markdown("</div>", unsafe_allow_html=True)
            else:
                st.markdown(
                    """
                    <div class="bento-card">
                        <p style="color:#94A3B8; font-size:11px; font-weight:800; margin:0;">INPUT STATUS</p>
                        <h1 style="margin:0; font-size:38px; font-weight:800; color:white;">0</h1>
                        <p style="color:#cbd5e1; font-size:14px; margin-top:14px;">No study records yet. Upload a module file to create your first summary and quiz set.</p>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

        st.markdown("<h3 style='font-weight:800; color:white;'>Insights</h3>", unsafe_allow_html=True)
        insight_one, insight_two, insight_three = st.columns(3)
        for column, insight_card in zip(
            [insight_one, insight_two, insight_three],
            insight_cards,
        ):
            with column:
                st.markdown(
                    f"""
                    <div class="bento-card">
                        <small style="color:{insight_card['color']}; font-weight:800; letter-spacing:1px;">{insight_card['label']}</small>
                        <p style="margin-top:12px; font-size:14px; color:white;">{insight_card['message']}</p>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

    elif st.session_state.user_page == "Profile":
        created_at_value = user.get("created_at")
        if hasattr(created_at_value, "strftime"):
            created_at_display = created_at_value.strftime("%Y-%m-%d %H:%M")
        else:
            created_at_display = str(created_at_value or "Unknown")
        modules_uploaded = len(user_documents)
        reviewer_ready = current_reviewer["reviewer_title"] if current_reviewer else "No reviewer generated yet"
        brightness_value = int(st.session_state.get("brightness", 100))
        eye_protection_enabled = bool(st.session_state.get("eye_protection", False))

        st.markdown(
            "<h1 style='color:white; font-size:42px; font-weight:800;'>Profile & Settings</h1>",
            unsafe_allow_html=True,
        )
        st.markdown(
            "<p style='color:#94A3B8; font-size:18px;'>Review your account details and current app preferences in one place.</p>",
            unsafe_allow_html=True,
        )
        st.write("##")

        profile_left, profile_right = st.columns([1.2, 0.8])
        with profile_left:
            st.markdown("<div class='bento-card'>", unsafe_allow_html=True)
            st.markdown(
                "<p style='color:#2DD4BF; font-size:12px; font-weight:800; margin:0 0 16px 0; letter-spacing:1px;'>ACCOUNT DETAILS</p>",
                unsafe_allow_html=True,
            )
            details_rows = [
                ("Full Name", user["fullname"]),
                ("Email", user["email"]),
                ("Role", str(user.get("role", "user")).title()),
                ("Plan", str(user.get("plan", "Free")).title()),
                ("Status", str(user.get("account_status", "active")).title()),
                ("Member Since", created_at_display),
            ]
            for label, value in details_rows:
                st.markdown(
                    f"""
                    <div style="display:flex; justify-content:space-between; gap:18px; align-items:flex-start; padding:12px 0; border-bottom:1px solid rgba(255,255,255,0.06);">
                        <span style="color:#94A3B8; font-size:13px; font-weight:700;">{html.escape(label)}</span>
                        <span style="color:white; font-size:14px; font-weight:700; text-align:right;">{html.escape(str(value))}</span>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
            st.markdown("</div>", unsafe_allow_html=True)

        with profile_right:
            st.markdown("<div class='bento-card'>", unsafe_allow_html=True)
            st.markdown(
                "<p style='color:#FF8C5C; font-size:12px; font-weight:800; margin:0 0 16px 0; letter-spacing:1px;'>SETTINGS</p>",
                unsafe_allow_html=True,
            )
            settings_rows = [
                ("Brightness", f"{brightness_value}%"),
                ("Eye Protection", "Enabled" if eye_protection_enabled else "Disabled"),
                ("Quiz Generation", "From inside the reviewer"),
            ]
            for label, value in settings_rows:
                st.markdown(
                    f"""
                    <div style="padding:12px 0; border-bottom:1px solid rgba(255,255,255,0.06);">
                        <div style="color:#94A3B8; font-size:12px; font-weight:800; margin-bottom:6px;">{html.escape(label)}</div>
                        <div style="color:white; font-size:15px; font-weight:700;">{html.escape(value)}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
            st.markdown(
                "<p style='color:#94A3B8; font-size:12px; margin:16px 0 0 0;'>Tip: you can still adjust live display controls from the sidebar.</p>",
                unsafe_allow_html=True,
            )
            st.markdown("</div>", unsafe_allow_html=True)

        st.write("##")
        snapshot_one, snapshot_two = st.columns(2)
        with snapshot_one:
            st.markdown(
                f"""
                <div class="bento-card">
                    <p style="color:#94A3B8; font-size:11px; font-weight:800; margin:0;">STUDY SNAPSHOT</p>
                    <h2 style="color:white; font-size:28px; font-weight:800; margin:12px 0 6px 0;">{modules_uploaded}</h2>
                    <p style="color:#cbd5e1; font-size:14px; margin:0;">Modules uploaded in your account.</p>
                </div>
                """,
                unsafe_allow_html=True,
            )
        with snapshot_two:
            st.markdown(
                f"""
                <div class="bento-card">
                    <p style="color:#94A3B8; font-size:11px; font-weight:800; margin:0;">CURRENT REVIEWER</p>
                    <h2 style="color:white; font-size:24px; font-weight:800; margin:12px 0 6px 0;">{html.escape(str(reviewer_ready))}</h2>
                    <p style="color:#cbd5e1; font-size:14px; margin:0;">Open the reviewer any time to generate a quiz when you're ready.</p>
                </div>
                """,
                unsafe_allow_html=True,
            )

    elif st.session_state.user_page == "Reviewer":
        render_reviewer_page(user, latest_reviewer)

    elif st.session_state.user_page == "Quiz":
        render_quiz_page(user, latest_reviewer)

    elif st.session_state.user_page == "Library":
        st.markdown(
            "<h1 style='color:white; font-size:42px; font-weight:800;'>Reviewer Library</h1>",
            unsafe_allow_html=True,
        )
        st.markdown(
            "<p style='color:#94A3B8; font-size:18px;'>Access and manage your generated reviewers.</p>",
            unsafe_allow_html=True,
        )
        st.write("##")
        generated_reviewers = load_generated_reviewers_for_user(int(user["id"]))
        st.markdown('<div class="bento-card">', unsafe_allow_html=True)
        if generated_reviewers:
            st.markdown(
                "<p style='color:#94A3B8; font-size:12px; font-weight:800; margin:0 0 16px 0; letter-spacing:1px;'>GENERATED REVIEWERS</p>",
                unsafe_allow_html=True,
            )
            for reviewer in generated_reviewers:
                download_name = f"{Path(reviewer['file_name']).stem}_reviewer.pdf"
                reviewer_download = build_reviewer_download_pdf(reviewer)
                st.markdown(
                    f"""
                    <div style="border:1px solid rgba(255,255,255,0.08); border-radius:18px; padding:18px 20px; background:rgba(15,23,42,0.28); margin-bottom:14px;">
                        <div style="display:flex; justify-content:space-between; gap:16px; align-items:flex-start;">
                            <div>
                                <p style="color:#2DD4BF; font-size:11px; font-weight:800; margin:0; letter-spacing:1px;">REVIEWER</p>
                                <h3 style="color:white; margin:8px 0 4px 0; font-size:22px; font-weight:800;">{html.escape(reviewer['reviewer_title'])}</h3>
                                <p style="color:#94A3B8; margin:0; font-size:14px;">{html.escape(reviewer['file_name'])} • {html.escape(reviewer['subject'])}</p>
                                <p style="color:#64748B; margin:8px 0 0 0; font-size:12px;">Summary: {html.escape(reviewer['summary_preference'])} • Quiz: {html.escape(reviewer['quiz_preference'])} • Generated: {reviewer['created_at']}</p>
                            </div>
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                action_view, action_download, action_delete = st.columns([1, 1, 1])
                with action_view:
                    if st.button("Open Reviewer", key=f"library_open_{reviewer['id']}", use_container_width=True):
                        open_reviewer_page(int(reviewer["id"]))
                with action_download:
                    st.download_button(
                        "Download Reviewer",
                        data=reviewer_download,
                        file_name=download_name,
                        mime="application/pdf",
                        key=f"library_download_{reviewer['id']}",
                        use_container_width=True,
                    )
                with action_delete:
                    if st.button("Delete Reviewer", key=f"library_delete_{reviewer['id']}", use_container_width=True):
                        delete_generated_reviewer_for_user(int(user["id"]), int(reviewer["id"]))
                        if int(st.session_state.get("active_reviewer_id") or 0) == int(reviewer["id"]):
                            st.session_state.active_reviewer_id = None
                            reset_quiz_state()
                        log_system_activity(
                            actor_name=user["fullname"],
                            actor_role=user["role"],
                            actor_id=int(user["id"]),
                            activity="Deleted reviewer",
                            details=f"Deleted reviewer {reviewer['reviewer_title']} for {reviewer['file_name']}.",
                        )
                        set_flash("success", f"Deleted {reviewer['reviewer_title']}.")
                        st.rerun()
        else:
            st.info("No generated reviewers yet. Generate a module from System Overview to build your first reviewer.")
        st.markdown("</div>", unsafe_allow_html=True)

    elif st.session_state.user_page == "Analytics":
        st.markdown(
            "<h1 style='color:white; font-size:42px; font-weight:800;'>Grade Analytics</h1>",
            unsafe_allow_html=True,
        )
        st.markdown(
            "<p style='color:#94A3B8; font-size:18px;'>Track graded quizzes by subject, items, and score progression across every attempt.</p>",
            unsafe_allow_html=True,
        )
        st.write("##")
        render_grade_analytics_charts(int(user["id"]))


def render_reviewer_page(user: dict, latest_reviewer: dict | None) -> None:
    reviewer = resolve_user_reviewer(int(user["id"]), latest_reviewer)

    if not reviewer:
        st.markdown(
            "<h1 style='color:white; font-size:42px; font-weight:800;'>Reviewer</h1>",
            unsafe_allow_html=True,
        )
        st.info("No reviewer is available yet. Generate one first from System Overview.")
        if st.button("Back to Overview", key="reviewer_back_empty", use_container_width=True):
            st.session_state.user_page = "Overview"
            st.rerun()
        return

    st.markdown(
        f"<h1 style='color:white; font-size:42px; font-weight:800; margin-bottom:0;'>Reviewer: {reviewer['subject']}</h1>",
        unsafe_allow_html=True,
    )
    st.markdown(
        "<p style='color:#94A3B8; font-size:18px;'>Study your generated reviewer first, then generate a quiz only if you want to practice.</p>",
        unsafe_allow_html=True,
    )
    st.write("##")

    quiz_options = get_quiz_difficulty_option_labels()
    raw_quiz_label = str(reviewer.get("quiz_preference") or "").strip()
    current_quiz_label = normalize_quiz_preference_label(raw_quiz_label) if raw_quiz_label else ""
    current_reviewer_id = int(reviewer["id"])
    reviewer_quiz_widget_key = f"reviewer_quiz_preference_{current_reviewer_id}"
    default_quiz_label = current_quiz_label if current_quiz_label in quiz_options else "Beginner (15 items)"
    if reviewer_quiz_widget_key not in st.session_state:
        st.session_state[reviewer_quiz_widget_key] = default_quiz_label
    elif st.session_state[reviewer_quiz_widget_key] not in quiz_options:
        st.session_state[reviewer_quiz_widget_key] = default_quiz_label

    stat_one, stat_two, stat_three = st.columns(3)
    with stat_one:
        st.markdown(
            f"""
            <div class="bento-card">
                <p style="color:#94A3B8; font-size:11px; font-weight:800; margin:0;">MODULE</p>
                <p style="color:white; font-size:18px; font-weight:700; margin:12px 0 0 0;">{reviewer['file_name']}</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with stat_two:
        st.markdown(
            f"""
            <div class="bento-card">
                <p style="color:#94A3B8; font-size:11px; font-weight:800; margin:0;">SUMMARY MODE</p>
                <p style="color:white; font-size:18px; font-weight:700; margin:12px 0 0 0;">{reviewer['summary_preference']}</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with stat_three:
        quiz_status = (
            normalize_quiz_preference_label(str(reviewer.get("quiz_preference") or ""))
            if reviewer["quiz_payload"]
            else "Not generated yet"
        )
        st.markdown(
            f"""
            <div class="bento-card">
                <p style="color:#94A3B8; font-size:11px; font-weight:800; margin:0;">QUIZ STATUS</p>
                <p style="color:white; font-size:18px; font-weight:700; margin:12px 0 0 0;">{quiz_status}</p>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.write("##")
    st.markdown(
        f"""
        <div class="bento-card">
            <p style="color:#2DD4BF; font-size:11px; font-weight:800; letter-spacing:1px; margin:0;">GENERATED REVIEWER</p>
            <h3 style="color:white; margin:14px 0 6px 0; font-size:28px; font-weight:800;">{reviewer['reviewer_title']}</h3>
            <p style="color:#94A3B8; margin:0;">Created for {reviewer['file_name']} under {reviewer['subject']}.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.write("")
    formatted_reviewer_body = ensure_preferred_reviewer_format(
        reviewer_body=reviewer["reviewer_body"],
        file_name=reviewer["file_name"],
        subject=reviewer["subject"],
        summary_preference=reviewer["summary_preference"],
        quiz_preference=reviewer["quiz_preference"],
        quiz_payload=reviewer["quiz_payload"],
    )
    st.markdown(formatted_reviewer_body)

    st.write("")
    st.markdown(
        "<p style='color:#94A3B8; font-size:11px; font-weight:800; margin:0 0 8px 0; letter-spacing:1px;'>QUIZ GENERATION</p>",
        unsafe_allow_html=True,
    )
    selected_quiz_preference = st.selectbox(
        "Quiz Difficulty",
        quiz_options,
        key=reviewer_quiz_widget_key,
    )
    if reviewer["quiz_payload"]:
        st.caption(
            f"Current quiz: {normalize_quiz_preference_label(str(reviewer.get('quiz_preference') or ''))}. Generating again will replace the existing quiz for this reviewer."
        )
    else:
        st.caption("No quiz has been generated for this reviewer yet.")

    if st.button("Generate Quiz >>", key="reviewer_generate_quiz", type="primary", use_container_width=True):
        st.session_state.reviewer_quiz_confirm_reviewer_id = int(reviewer["id"])
        st.session_state.reviewer_quiz_pending_difficulty = selected_quiz_preference
        st.rerun()

    if int(st.session_state.get("reviewer_quiz_confirm_reviewer_id") or 0) == int(reviewer["id"]):
        pending_quiz_difficulty = st.session_state.get("reviewer_quiz_pending_difficulty") or selected_quiz_preference
        st.warning(
            f"Generate {pending_quiz_difficulty} for this reviewer now? The quiz will open automatically after generation."
        )
        confirm_generate_col, cancel_generate_col = st.columns(2)
        with confirm_generate_col:
            if st.button("Yes, generate quiz", key="reviewer_generate_quiz_confirm", use_container_width=True):
                try:
                    refreshed_reviewer, _generation_mode, generation_reason = generate_quiz_for_reviewer(
                        reviewer_id=int(reviewer["id"]),
                        quiz_preference=pending_quiz_difficulty,
                    )
                except Exception as error:
                    st.session_state.reviewer_quiz_confirm_reviewer_id = None
                    st.session_state.reviewer_quiz_pending_difficulty = ""
                    set_flash("error", f"Quiz generation failed for {reviewer['file_name']}. {error}")
                    st.rerun()
                st.session_state.reviewer_quiz_confirm_reviewer_id = None
                st.session_state.reviewer_quiz_pending_difficulty = ""
                st.session_state.active_reviewer_id = int(refreshed_reviewer["id"])
                set_flash(
                    "success",
                    (
                        f"Quiz generated for {reviewer['file_name']}."
                        if not generation_reason
                        else f"Quiz generated for {reviewer['file_name']}. {generation_reason}"
                    ),
                )
                open_quiz_page(int(refreshed_reviewer["id"]))
        with cancel_generate_col:
            if st.button("No, keep reading", key="reviewer_generate_quiz_cancel", use_container_width=True):
                st.session_state.reviewer_quiz_confirm_reviewer_id = None
                st.session_state.reviewer_quiz_pending_difficulty = ""
                st.rerun()

    review_left, review_center, review_right = st.columns([1, 1.1, 1])
    with review_left:
        if st.button("Back to Overview", key="reviewer_back", use_container_width=True):
            clear_reviewer_quiz_request()
            st.session_state.user_page = "Overview"
            st.rerun()
    with review_center:
        st.markdown(
            "<div style='color:#64748B; font-size:13px; font-weight:700; text-align:center; padding-top:12px;'>Generate a quiz above when you are ready to practice.</div>",
            unsafe_allow_html=True,
        )
    with review_right:
        if st.button("Reviewer Library", key="reviewer_library", use_container_width=True):
            clear_reviewer_quiz_request()
            st.session_state.user_page = "Library"
            st.rerun()


def build_highlighted_statement_markup(question_index: int, question: dict) -> str:
    answer_state = get_quiz_answer(question_index) or {}
    if isinstance(answer_state, dict):
        selected_phrase = selected_modified_phrase(answer_state, question)
        if selected_phrase:
            return highlight_phrase_markup(question.get("statement", ""), selected_phrase)

    selected_tokens = set(answer_state.get("selected_tokens", [])) if isinstance(answer_state, dict) else set()
    rendered_tokens: list[str] = []
    for token_index, token in enumerate(statement_word_tokens(question.get("statement", ""))):
        safe_token = html.escape(token)
        if token_index in selected_tokens and re.search(r"[A-Za-z0-9]", token):
            rendered_tokens.append(f"<mark class='quiz-highlight-token'>{safe_token}</mark>")
        else:
            rendered_tokens.append(safe_token)
    return (
        " ".join(rendered_tokens)
        .replace(" ,", ",")
        .replace(" .", ".")
        .replace(" !", "!")
        .replace(" ?", "?")
        .replace(" ;", ";")
        .replace(" :", ":")
    )


def build_quiz_question_markup(question_index: int, question: dict) -> str:
    question_number = question_index + 1
    question_type = question.get("type", "multiple_choice")
    prompt_text = str(question.get("prompt") or question.get("statement") or "").strip()
    safe_prompt = html.escape(prompt_text)

    if question_type == "multiple_choice":
        return f"<div class='quiz-question-line'><span class='quiz-question-number'>{question_number}.</span> {safe_prompt}</div>"

    if question_type == "modified_true_false":
        return (
            "<div class='quiz-question-line'>"
            f"<span class='quiz-question-number'>{question_number}.</span> "
            f"{build_highlighted_statement_markup(question_index, question)}"
            "</div>"
        )

    if question_type == "enumeration":
        accepted_answers = question.get("accepted_answers", [])
        blank_count = max(2, len(accepted_answers) if isinstance(accepted_answers, list) else 0)
        return (
            "<div class='quiz-question-line'>"
            f"<span class='quiz-question-number'>1-{blank_count}:</span> "
            f"{safe_prompt}"
            "</div>"
        )

    if question_type in {"true_false", "identification", "matching"}:
        return (
            "<div class='quiz-question-line'>"
            f"<span class='quiz-question-number'>{question_number}.</span> "
            f"{safe_prompt}"
            "</div>"
        )

    return f"<div class='quiz-question-line'><span class='quiz-question-number'>{question_number}.</span> {safe_prompt}</div>"


def render_modified_true_false_selector(question_index: int, question: dict) -> None:
    answer_state = get_quiz_answer(question_index)
    if not isinstance(answer_state, dict):
        answer_state = {"response": "", "selected_tokens": [], "selected_phrase": "", "highlight_mode": False}
    answer_state.setdefault("response", "")
    answer_state.setdefault("selected_tokens", [])
    answer_state.setdefault("selected_phrase", "")
    answer_state.setdefault("highlight_mode", False)

    error_key = f"quiz_mtf_error_{question_index}"
    error_message = st.session_state.pop(error_key, None)
    response_value = st.text_input(
        "Modified True or False Answer",
        value=str(answer_state.get("response", "")),
        key=f"quiz_mtf_response_{question_index}",
        placeholder="Write TRUE or the correct replacement answer",
        label_visibility="collapsed",
    )
    answer_state["response"] = response_value.strip()
    if normalize_answer_text(response_value) == "true":
        answer_state["selected_tokens"] = []
        answer_state["selected_phrase"] = ""
        answer_state["highlight_mode"] = False
    set_quiz_answer(question_index, answer_state)

    if st.button("🖍", key=f"quiz_mtf_pen_{question_index}", use_container_width=False):
        if normalize_answer_text(response_value) == "true":
            st.session_state[error_key] = "Remove your answer before you use highlight."
        else:
            answer_state["highlight_mode"] = not bool(answer_state.get("highlight_mode"))
            set_quiz_answer(question_index, answer_state)
        st.rerun()

    if error_message:
        st.error(error_message)

    st.markdown(
        "<div class='quiz-mtf-note'>Note: click the highlighter pen icon, then drag across the wrong word or phrase in the statement below.</div>",
        unsafe_allow_html=True,
    )

    if answer_state.get("highlight_mode"):
        selected_phrase = render_drag_text_highlighter(
            statement=question.get("statement", ""),
            selected_phrase=str(answer_state.get("selected_phrase", "")).strip(),
            key=f"quiz_mtf_drag_{question_index}",
        )
        if selected_phrase != str(answer_state.get("selected_phrase", "")).strip():
            answer_state["selected_phrase"] = selected_phrase
            answer_state["selected_tokens"] = []
            set_quiz_answer(question_index, answer_state)


def render_quiz_question_input(question_index: int, question: dict, questions: list[dict]) -> None:
    question_type = question.get("type", "multiple_choice")
    current_answer = get_quiz_answer(question_index)

    if question_type == "multiple_choice":
        option_columns = st.columns(len(question["options"]))
        for option_index, (column, option_label) in enumerate(zip(option_columns, question["options"])):
            with column:
                if st.button(
                    option_label,
                    key=f"quiz_mcq_option_{question_index}_{option_index}",
                    type="primary" if current_answer == option_index else "secondary",
                    use_container_width=True,
                ):
                    set_quiz_answer(question_index, option_index)
                    st.rerun()
        return

    if question_type == "true_false":
        true_col, false_col = st.columns(2)
        with true_col:
            if st.button(
                "True",
                key=f"quiz_tf_true_{question_index}",
                type="primary" if current_answer is True else "secondary",
                use_container_width=True,
            ):
                set_quiz_answer(question_index, True)
                st.rerun()
        with false_col:
            if st.button(
                "False",
                key=f"quiz_tf_false_{question_index}",
                type="primary" if current_answer is False else "secondary",
                use_container_width=True,
            ):
                set_quiz_answer(question_index, False)
                st.rerun()
        return

    if question_type == "matching":
        available_options = get_matching_available_options(questions, question_index)
        selected_option = st.selectbox(
            "Pick the matching answer",
            ["Select answer"] + available_options,
            index=0 if not current_answer else (available_options.index(current_answer) + 1 if current_answer in available_options else 0),
            key=f"quiz_match_{question_index}",
            label_visibility="collapsed",
        )
        set_quiz_answer(question_index, None if selected_option == "Select answer" else selected_option)
        return

    if question_type == "modified_true_false":
        render_modified_true_false_selector(question_index, question)
        return

    if question_type == "identification":
        response = st.text_input(
            "Type your answer",
            value=str(current_answer or ""),
            key=f"quiz_identification_{question_index}",
            placeholder="Write your answer here",
            label_visibility="collapsed",
        )
        set_quiz_answer(question_index, response)
        return

    if question_type == "enumeration":
        accepted_answers = question.get("accepted_answers", [])
        blank_count = max(2, len(accepted_answers) if isinstance(accepted_answers, list) else 0)
        existing_answers = current_answer if isinstance(current_answer, list) else []
        entries: list[str] = []
        for blank_index in range(blank_count):
            entry_value = existing_answers[blank_index] if blank_index < len(existing_answers) else ""
            number_col, input_col = st.columns([0.08, 0.92])
            with number_col:
                st.markdown(
                    f"<div class='quiz-enum-answer-label'>{blank_index + 1}.</div>",
                    unsafe_allow_html=True,
                )
            with input_col:
                entry = st.text_input(
                    f"Enumeration {blank_index + 1}",
                    value=str(entry_value),
                    key=f"quiz_enumeration_{question_index}_{blank_index}",
                    placeholder="Write answer",
                    label_visibility="collapsed",
                )
            entries.append(entry)
        set_quiz_answer(question_index, entries)


def render_quiz_page(user: dict, latest_reviewer: dict | None) -> None:
    reviewer = resolve_user_reviewer(int(user["id"]), latest_reviewer)

    if not reviewer:
        st.markdown(
            "<h1 style='color:white; font-size:42px; font-weight:800;'>Quiz</h1>",
            unsafe_allow_html=True,
        )
        st.info("No quiz is available yet. Generate a reviewer first from System Overview.")
        if st.button("Back to Overview", key="quiz_back_empty", use_container_width=True):
            st.session_state.user_page = "Overview"
            st.rerun()
        return

    questions = reviewer["quiz_payload"]
    if not questions:
        st.warning("This reviewer does not contain quiz items yet. Open the reviewer page and generate a quiz first.")
        if st.button("Back to Reviewer", key="quiz_back_to_reviewer_empty_payload", use_container_width=True):
            open_reviewer_page(int(reviewer["id"]))
        return

    total_questions = len(questions)
    current_index = min(st.session_state.quiz_index, max(total_questions - 1, 0))
    current_question = questions[current_index]
    progress_text = f"{current_index + 1} / {total_questions}" if total_questions else "0 / 0"
    total_minutes = total_questions
    current_question_type = current_question.get("type", "multiple_choice")
    question_direction = get_quiz_question_description(current_question_type)
    question_markup = build_quiz_question_markup(current_index, current_question)
    active_quiz_config = get_quiz_configuration(reviewer["quiz_preference"])
    difficulty_label = active_quiz_config["display_name"]
    quiz_page_title = f"{difficulty_label} Quiz"

    st.markdown(
        """
        <style>
        div.stButton > button[kind="primary"] {
            background: linear-gradient(90deg, #ff6b35, #f97316) !important;
            color: white !important;
            border: none !important;
            box-shadow: 0 10px 25px rgba(255, 107, 53, 0.25) !important;
            transition: transform 0.18s ease, box-shadow 0.18s ease, filter 0.18s ease !important;
        }
        div.stButton > button[kind="primary"]:hover {
            transform: translateY(-2px) !important;
            box-shadow: 0 14px 32px rgba(255, 107, 53, 0.32) !important;
            filter: brightness(1.03) !important;
        }
        .quiz-shell {
            position: relative;
            background: linear-gradient(180deg, rgba(255,255,255,0.98) 0%, rgba(245,247,250,0.96) 100%);
            border-radius: 28px;
            border: 1px solid rgba(255, 255, 255, 0.18);
            min-height: 520px;
            padding: 30px 34px 168px 34px;
            box-shadow: 0 20px 60px rgba(2, 6, 23, 0.28);
            animation: quizCardFade 220ms ease;
        }
        .quiz-shell.quiz-shell-active {
            min-height: 410px;
            padding-bottom: 72px;
            margin-bottom: 18px;
        }
        .quiz-shell.quiz-shell-active.quiz-shell-enumeration {
            min-height: 640px;
            padding-bottom: 228px;
        }
        .quiz-meta {
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 12px;
            margin-bottom: 18px;
        }
        .quiz-meta-left {
            color: #64748B;
            font-size: 13px;
            font-weight: 800;
            letter-spacing: 0.2px;
        }
        .quiz-meta-pill {
            color: #475569;
            font-size: 13px;
            font-weight: 800;
            letter-spacing: 0.5px;
        }
        .quiz-direction {
            color: #64748B;
            font-size: 14px;
            font-weight: 700;
            line-height: 1.45;
            margin: 0 0 10px 0;
            max-width: 720px;
        }
        .quiz-item-label {
            color: #64748B;
            font-size: 13px;
            font-weight: 800;
            letter-spacing: 0.8px;
            text-transform: uppercase;
            margin-bottom: 22px;
        }
        .quiz-question {
            color: #334155;
            font-size: 25px;
            line-height: 1.5;
            font-weight: 500;
            text-align: left;
            margin: 40px auto 26px auto;
            max-width: 880px;
        }
        .quiz-question-line {
            font-size: 24px;
            line-height: 1.7;
            color: #334155;
            font-weight: 500;
        }
        .quiz-question-number {
            font-weight: 800;
            margin-right: 8px;
        }
        .quiz-blank-prefix {
            display: inline-block;
            min-width: 138px;
            font-weight: 800;
            color: #0f172a;
        }
        .quiz-enum-answer-label {
            color: #334155;
            font-size: 20px;
            font-weight: 700;
            line-height: 52px;
            text-align: right;
            padding-right: 4px;
        }
        .quiz-highlight-token {
            background: rgba(255, 107, 53, 0.22);
            color: #0f172a;
            padding: 2px 6px;
            border-radius: 8px;
        }
        .quiz-result-score {
            font-size: 62px;
            font-weight: 800;
            color: white;
            margin: 0;
        }
        .quiz-timer-line {
            position: relative;
            width: 100%;
            height: 10px;
            background: rgba(15, 23, 42, 0.92);
            border-radius: 999px;
            overflow: visible;
            margin: 10px 0 20px 0;
        }
        .quiz-timer-fill {
            position: absolute;
            left: 0;
            top: 0;
            height: 10px;
            background: linear-gradient(90deg, #ff6b35, #f97316);
            border-radius: 999px;
            transition: width 0.6s linear;
        }
        .quiz-timer-bubble {
            position: absolute;
            top: -34px;
            transform: translateX(-50%);
            min-width: 58px;
            text-align: center;
            background: rgba(15, 23, 42, 0.96);
            color: white;
            font-size: 11px;
            font-weight: 800;
            border-radius: 12px;
            padding: 6px 10px;
            border: 1px solid rgba(255,255,255,0.08);
            white-space: nowrap;
        }
        .quiz-timer-bubble::after {
            content: "";
            position: absolute;
            left: 50%;
            bottom: -7px;
            transform: translateX(-50%);
            width: 0;
            height: 0;
            border-left: 7px solid transparent;
            border-right: 7px solid transparent;
            border-top: 7px solid rgba(15, 23, 42, 0.96);
        }
        .quiz-answer-slot {
            max-width: 980px;
            min-height: 34px;
            margin: 0 auto;
            border: none;
            border-radius: 18px;
            background: transparent;
        }
        [data-testid="stVerticalBlock"] > div:has(.quiz-answer-anchor) {
            height: 0 !important;
            margin: 0 !important;
        }
        [data-testid="stVerticalBlock"] > div:has(.quiz-answer-anchor-enumeration) {
            height: 0 !important;
            margin: 0 !important;
        }
        [data-testid="stVerticalBlock"] > div:has(.quiz-answer-anchor) + div {
            max-width: 980px;
            margin: -188px auto 28px auto !important;
            position: relative;
            z-index: 6;
        }
        [data-testid="stVerticalBlock"] > div:has(.quiz-answer-anchor-enumeration) + div {
            max-width: 980px;
            margin: -238px auto 28px auto !important;
            position: relative;
            z-index: 6;
        }
        [data-testid="stVerticalBlock"] > div:has(.quiz-answer-anchor) + div > div {
            background: transparent;
            border: none;
            border-radius: 0;
            padding: 0 8px;
        }
        [data-testid="stVerticalBlock"] > div:has(.quiz-answer-anchor-enumeration) + div > div {
            background: transparent;
            border: none;
            border-radius: 0;
            padding: 0 8px;
        }
        [data-testid="stVerticalBlock"] > div:has(.quiz-answer-anchor) + div [data-testid="stVerticalBlock"] {
            gap: 0.65rem;
        }
        [data-testid="stVerticalBlock"] > div:has(.quiz-answer-anchor-enumeration) + div [data-testid="stVerticalBlock"] {
            gap: 0.45rem;
        }
        [data-testid="stVerticalBlock"] > div:has(.quiz-answer-anchor) + div label,
        [data-testid="stVerticalBlock"] > div:has(.quiz-answer-anchor) + div p,
        [data-testid="stVerticalBlock"] > div:has(.quiz-answer-anchor) + div span,
        [data-testid="stVerticalBlock"] > div:has(.quiz-answer-anchor) + div div {
            color: #334155 !important;
        }
        [data-testid="stVerticalBlock"] > div:has(.quiz-answer-anchor-enumeration) + div label,
        [data-testid="stVerticalBlock"] > div:has(.quiz-answer-anchor-enumeration) + div p,
        [data-testid="stVerticalBlock"] > div:has(.quiz-answer-anchor-enumeration) + div span,
        [data-testid="stVerticalBlock"] > div:has(.quiz-answer-anchor-enumeration) + div div {
            color: #334155 !important;
        }
        [data-testid="stVerticalBlock"] > div:has(.quiz-answer-anchor) + div input,
        [data-testid="stVerticalBlock"] > div:has(.quiz-answer-anchor) + div textarea {
            background: rgba(255,255,255,0.92) !important;
            color: #0f172a !important;
        }
        [data-testid="stVerticalBlock"] > div:has(.quiz-answer-anchor-enumeration) + div input,
        [data-testid="stVerticalBlock"] > div:has(.quiz-answer-anchor-enumeration) + div textarea {
            background: rgba(255,255,255,0.92) !important;
            color: #0f172a !important;
        }
        [data-testid="stVerticalBlock"] > div:has(.quiz-answer-anchor) + div [data-baseweb="input"],
        [data-testid="stVerticalBlock"] > div:has(.quiz-answer-anchor) + div [data-baseweb="select"] > div {
            background: rgba(255,255,255,0.92) !important;
            border-radius: 14px !important;
        }
        [data-testid="stVerticalBlock"] > div:has(.quiz-answer-anchor-enumeration) + div [data-baseweb="input"],
        [data-testid="stVerticalBlock"] > div:has(.quiz-answer-anchor-enumeration) + div [data-baseweb="select"] > div {
            background: rgba(255,255,255,0.92) !important;
            border-radius: 14px !important;
        }
        [data-testid="stVerticalBlock"] > div:has(.quiz-answer-anchor) + div div.stButton > button {
            width: 100% !important;
            min-height: 56px !important;
            height: 56px !important;
            border-radius: 14px !important;
            justify-content: flex-start !important;
            padding: 0 16px !important;
            white-space: normal !important;
            text-align: left !important;
            box-shadow: none !important;
            font-size: 15px !important;
            font-weight: 600 !important;
            transition: transform 0.16s ease, border-color 0.16s ease, box-shadow 0.16s ease, background 0.16s ease, color 0.16s ease !important;
        }
        [data-testid="stVerticalBlock"] > div:has(.quiz-answer-anchor) + div div.stButton > button[kind="secondary"] {
            background: transparent !important;
            color: #334155 !important;
            border: 1px solid rgba(148,163,184,0.28) !important;
        }
        [data-testid="stVerticalBlock"] > div:has(.quiz-answer-anchor) + div div.stButton > button[kind="primary"] {
            background: transparent !important;
            color: #c2410c !important;
            border: 1px solid rgba(255,107,53,0.55) !important;
        }
        [data-testid="stVerticalBlock"] > div:has(.quiz-answer-anchor) + div div.stButton > button:hover {
            transform: translateY(-1px) !important;
            box-shadow: 0 10px 20px rgba(15, 23, 42, 0.08) !important;
        }
        [data-testid="stVerticalBlock"] > div:has(.quiz-answer-anchor) + div div.stButton > button[kind="secondary"]:hover {
            background: rgba(255,255,255,0.58) !important;
            border: 1px solid rgba(148,163,184,0.38) !important;
        }
        [data-testid="stVerticalBlock"] > div:has(.quiz-answer-anchor) + div div.stButton > button[kind="primary"]:hover {
            background: rgba(255,107,53,0.10) !important;
            border: 1px solid rgba(255,107,53,0.62) !important;
            color: #9a3412 !important;
        }
        .quiz-mtf-note {
            color: #64748B;
            font-size: 12px;
            font-weight: 700;
            margin: 8px 0 12px 0;
        }
        .quiz-nav-spacer {
            height: 1px;
        }
        .quiz-nav-gap {
            height: 12px;
        }
        .quiz-answer-follow-gap {
            height: 72px;
        }
        .quiz-control-gap {
            height: 18px;
        }
        @keyframes quizCardFade {
            from {
                opacity: 0;
                transform: translateY(10px);
            }
            to {
                opacity: 1;
                transform: translateY(0);
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    quiz_top_left, quiz_top_right = st.columns([4.9, 1.15])
    with quiz_top_left:
        st.markdown(
            f"<h1 style='color:white; font-size:42px; font-weight:800; margin-bottom:0;'>{quiz_page_title}</h1>",
            unsafe_allow_html=True,
        )
        st.markdown(
            f"<p style='color:#94A3B8; font-size:18px;'>Timed quiz for <b>{reviewer['file_name']}</b>. Total time is based on item count: <b>{total_minutes} minute(s)</b> for <b>{total_questions}</b> item(s).</p>",
            unsafe_allow_html=True,
        )
    with quiz_top_right:
        st.markdown(
            f"""
            <div class="bento-card" style="text-align:center; margin-top:0;">
                <p style="color:#94A3B8; font-size:11px; font-weight:800; margin:0;">PROGRESS</p>
                <p style="color:white; font-size:24px; font-weight:800; margin:12px 0 0 0;">{progress_text}</p>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.write("##")

    if st.session_state.quiz_started and st.session_state.quiz_exit_target:
        st.markdown(
            f"""
            <div class="bento-card" style="border-color:rgba(255,107,53,0.32);">
                <p style="color:#ff6b35; font-size:11px; font-weight:800; margin:0;">SUBMIT QUIZ?</p>
                <p style="color:white; font-size:16px; margin:12px 0 0 0;">You are still taking this quiz. Submit and grade your current answers before opening {st.session_state.quiz_exit_label}?</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        prompt_left, prompt_right = st.columns(2)
        with prompt_left:
            if st.button("Yes, submit quiz", key="quiz_exit_submit", type="primary", use_container_width=True):
                finish_quiz_attempt(reviewer)
                exit_target = st.session_state.quiz_exit_target
                clear_quiz_exit_request()
                set_flash("success", "Quiz submitted and graded.")
                reset_quiz_state()
                st.session_state.user_page = exit_target
                st.rerun()
        with prompt_right:
            if st.button("No, continue quiz", key="quiz_exit_cancel", use_container_width=True):
                clear_quiz_exit_request()
                st.rerun()
        st.write("")

    if st.session_state.quiz_finished and st.session_state.quiz_last_result:
        last_result = st.session_state.quiz_last_result
        recommendation = (
            f"Review {reviewer['file_name']} again before retaking the quiz."
            if float(last_result["percentage"]) < 80
            else "Strong work. Open the reviewer one more time, then try another module."
        )
        st.markdown(
            f"""
            <div class="bento-card">
                <p style="color:#2DD4BF; font-size:11px; font-weight:800; margin:0;">QUIZ COMPLETE</p>
                <p class="quiz-result-score">{int(last_result['score'])}/{int(last_result['total_questions'])}</p>
                <p style="color:#cbd5e1; font-size:17px; margin:0 0 16px 0;">Final score: {float(last_result['percentage']):.0f}%</p>
                <p style="color:#94A3B8; font-size:14px; margin:0;">{recommendation}</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.write("")
        result_left, result_center, result_right = st.columns([1, 1.15, 1])
        with result_left:
            if st.button("View Reviewer >>", key="quiz_result_reviewer", use_container_width=True):
                open_reviewer_page(int(reviewer["id"]))
        with result_center:
            if st.button("Retake Quiz", key="quiz_restart", type="primary", use_container_width=True):
                reset_quiz_state()
                start_quiz_attempt(reviewer)
                st.rerun()
        with result_right:
            if st.button("Back to Overview", key="quiz_result_overview", use_container_width=True):
                st.session_state.user_page = "Overview"
                st.rerun()
        return

    st.markdown(
        f"""
        <div style="padding-left:8px; color:#94A3B8; font-size:14px; font-weight:600;">
            {reviewer['file_name']}
        </div>
        """,
        unsafe_allow_html=True,
    )
    if st.session_state.quiz_started:
        render_quiz_timer_fragment(reviewer)
    else:
        st.markdown(
            """
            <div class="quiz-timer-line">
                <div class="quiz-timer-fill" style="width:100%;"></div>
                <div class="quiz-timer-bubble" style="left:calc(100% - 28px);">READY</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    quiz_shell_classes = ["quiz-shell"]
    if st.session_state.quiz_started:
        quiz_shell_classes.append("quiz-shell-active")
        if current_question.get("type") == "enumeration":
            quiz_shell_classes.append("quiz-shell-enumeration")
    quiz_shell_class = " ".join(quiz_shell_classes)

    st.markdown(
        f"""
        <div class="{quiz_shell_class}">
            <div class="quiz-meta">
                <div class="quiz-meta-left">
                    <div class="quiz-direction">{question_direction}</div>
                    <div class="quiz-item-label">Item {current_index + 1}</div>
                </div>
                <div class="quiz-meta-pill">Difficulty: {difficulty_label}</div>
            </div>
            <div class="quiz-question">{question_markup}</div>
            <div class="quiz-answer-slot"></div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.write("")

    if st.session_state.quiz_started:
        answer_anchor_class = "quiz-answer-anchor-enumeration" if current_question.get("type") == "enumeration" else "quiz-answer-anchor"
        st.markdown(f"<div class='{answer_anchor_class}'></div>", unsafe_allow_html=True)
        render_quiz_question_input(current_index, current_question, questions)
        if current_question.get("type") not in {"modified_true_false", "enumeration"}:
            st.markdown("<div class='quiz-answer-follow-gap'></div>", unsafe_allow_html=True)
        st.markdown("<div class='quiz-nav-gap'></div>", unsafe_allow_html=True)
        nav_left, nav_gap_left, nav_center, nav_gap_right, nav_right = st.columns([1, 0.12, 4, 0.12, 1])
        with nav_left:
            if current_index > 0 and st.button("Prev", key="quiz_prev", type="primary", use_container_width=True):
                move_quiz_index(-1, total_questions)
                st.rerun()
        with nav_gap_left:
            st.markdown("<div class='quiz-nav-spacer'></div>", unsafe_allow_html=True)
        with nav_center:
            st.markdown("<div class='quiz-nav-spacer'></div>", unsafe_allow_html=True)
        with nav_gap_right:
            st.markdown("<div class='quiz-nav-spacer'></div>", unsafe_allow_html=True)
        with nav_right:
            if current_index < total_questions - 1 and st.button("Next", key="quiz_next", type="primary", use_container_width=True):
                move_quiz_index(1, total_questions)
                st.rerun()

    st.markdown("<div class='quiz-control-gap'></div>", unsafe_allow_html=True)
    control_left, control_gap_left, control_center, control_gap_right, control_right = st.columns([1, 0.08, 1.15, 0.08, 1])
    with control_left:
        if st.button("View Reviewer >>", key="quiz_view_reviewer", use_container_width=True):
            if st.session_state.quiz_started:
                request_quiz_exit("Reviewer", "the reviewer")
                st.rerun()
            else:
                open_reviewer_page(int(reviewer["id"]))
    with control_gap_left:
        st.markdown("<div class='quiz-nav-spacer'></div>", unsafe_allow_html=True)
    with control_center:
        if not st.session_state.quiz_started:
            if st.button("Start", key="quiz_start", type="primary", use_container_width=True):
                start_quiz_attempt(reviewer)
                st.rerun()
        else:
            if st.button("Finish", key="quiz_finish", type="primary", use_container_width=True):
                finish_quiz_attempt(reviewer)
                st.rerun()
    with control_gap_right:
        st.markdown("<div class='quiz-nav-spacer'></div>", unsafe_allow_html=True)
    with control_right:
        if st.button("Back to Overview", key="quiz_back_overview", use_container_width=True):
            if st.session_state.quiz_started:
                request_quiz_exit("Overview", "System Overview")
                st.rerun()
            else:
                st.session_state.user_page = "Overview"
                reset_quiz_state()
                st.rerun()


def inject_admin_dashboard_css() -> None:
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@300;400;500;600;700;800&display=swap');
        :root {
            --primary-orange: #ff6b35;
            --bg-obsidian: #020617;
            --sidebar-navy: #112240;
            --card-slate: rgba(30, 41, 59, 0.4);
            --text-white: #f8fafc;
            --border-glass: rgba(255, 255, 255, 0.08);
        }
        * { font-family: 'Plus Jakarta Sans', sans-serif; }
        .stApp { background: radial-gradient(circle at 0% 100%, #1e293b, #020617); color: var(--text-white); }
        header[data-testid="stHeader"],
        [data-testid="stToolbar"],
        [data-testid="stDecoration"],
        .stDeployButton,
        #MainMenu,
        footer {
            display: none !important;
            visibility: hidden !important;
        }
        [data-testid="block-container"] {
            padding-top: 0.85rem !important;
        }
        [data-testid="stAppViewContainer"],
        [data-testid="stMain"],
        [data-testid="block-container"],
        [data-testid="stVerticalBlock"] {
            caret-color: transparent !important;
        }
        input,
        textarea,
        [contenteditable="true"],
        [data-baseweb="input"] input {
            caret-color: auto !important;
        }
        [data-testid="stSidebarCollapsedControl"] {
            background-color: var(--sidebar-navy) !important;
            color: var(--primary-orange) !important;
            border: 1px solid var(--border-glass) !important;
            border-radius: 0 10px 10px 0 !important;
            top: 10px !important;
        }
        [data-testid="stSidebar"] {
            background-color: var(--sidebar-navy) !important;
            border-right: 1px solid var(--border-glass);
        }
        .admin-identity {
            background: linear-gradient(135deg, #ff6b35 0%, #f97316 100%);
            padding: 20px; border-radius: 20px; margin-bottom: 25px;
            box-shadow: 0 10px 20px rgba(255, 107, 53, 0.2);
        }
        .admin-card {
            background: var(--card-slate);
            backdrop-filter: blur(15px);
            border: 1px solid var(--border-glass);
            border-radius: 24px;
            padding: 24px;
            transition: transform 0.18s ease, border-color 0.18s ease, box-shadow 0.18s ease, background 0.18s ease;
        }
        .admin-card:hover {
            transform: translateY(-2px) scale(1.005);
            border-color: rgba(255, 140, 92, 0.20);
            box-shadow: 0 16px 30px rgba(2, 6, 23, 0.18);
            background: rgba(30, 41, 59, 0.48);
        }
        .status-badge {
            color: #2DD4BF; font-weight: 800; font-size: 11px;
            border: 1px solid rgba(45, 212, 191, 0.3); background: rgba(45, 212, 191, 0.1);
            padding: 4px 12px; border-radius: 50px;
        }
        div.stButton > button { border-radius: 12px !important; font-weight: 600 !important; }
        [data-testid="stSidebar"] div.stButton > button[kind="secondary"] {
            background: rgba(255, 255, 255, 0.08) !important;
            color: white !important;
            border: 1px solid rgba(255, 255, 255, 0.14) !important;
            min-height: 42px !important;
            transition: background 0.18s ease, border-color 0.18s ease, box-shadow 0.18s ease, transform 0.18s ease !important;
        }
        [data-testid="stSidebar"] div.stButton > button[kind="secondary"]:hover {
            background: rgba(255, 107, 53, 0.20) !important;
            color: white !important;
            border: 1px solid rgba(255, 140, 92, 0.34) !important;
            box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.06), 0 8px 20px rgba(255, 107, 53, 0.12) !important;
            transform: translateY(-1px) !important;
        }
        [data-testid="stSidebar"] div.stButton > button[kind="secondary"]:focus,
        [data-testid="stSidebar"] div.stButton > button[kind="secondary"]:focus-visible {
            background: rgba(255, 107, 53, 0.20) !important;
            color: white !important;
            border: 1px solid rgba(255, 140, 92, 0.34) !important;
            box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.06), 0 8px 20px rgba(255, 107, 53, 0.12) !important;
            outline: none !important;
        }
        [data-testid="stSidebar"] div.stButton > button[kind="primary"] {
            background: rgba(255, 107, 53, 0.20) !important;
            color: white !important;
            border: 1px solid rgba(255, 140, 92, 0.34) !important;
            min-height: 42px !important;
            box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.06), 0 8px 20px rgba(255, 107, 53, 0.12) !important;
            transition: background 0.18s ease, border-color 0.18s ease, box-shadow 0.18s ease, transform 0.18s ease !important;
        }
        [data-testid="stSidebar"] div.stButton > button[kind="primary"]:hover {
            background: rgba(255, 107, 53, 0.25) !important;
            color: white !important;
            border: 1px solid rgba(255, 140, 92, 0.4) !important;
            transform: translateY(-1px) !important;
            box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.07), 0 10px 24px rgba(255, 107, 53, 0.16) !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_admin_dashboard() -> None:
    inject_admin_dashboard_css()
    user = st.session_state.current_user
    scholar_users = load_users(include_admin=False)
    all_users = load_users(include_admin=True)
    scholar_count = len(scholar_users)

    with st.sidebar:
        render_sidebar_brand(
            "<h1 style='color:white; font-size:24px; letter-spacing:-1px;'>Cogni"
            "<span style='color:#ff6b35'>Admin</span></h1>"
        )
        st.markdown(
            f"""
            <div class="admin-identity">
                <div style="display:flex; align-items:center; gap:12px;">
                    <div style="background:white; width:40px; height:40px; border-radius:12px; display:flex; align-items:center; justify-content:center; font-weight:800; color:#ff6b35;">
                        {initials_for(user['fullname'])}
                    </div>
                    <div>
                        <div style="color:white; font-size:14px; font-weight:700;">{user['fullname']}</div>
                        <div style="color:rgba(255,255,255,0.8); font-size:10px; font-weight:800; letter-spacing:1px;">ROOT ACCESS</div>
                    </div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        if st.button(
            "System Overview",
            use_container_width=True,
            key="admin_overview",
            type="primary" if st.session_state.admin_nav == "System Overview" else "secondary",
        ):
            st.session_state.admin_nav = "System Overview"
            st.rerun()
        if st.button(
            "User Database",
            use_container_width=True,
            key="admin_users",
            type="primary" if st.session_state.admin_nav == "User Database" else "secondary",
        ):
            st.session_state.admin_nav = "User Database"
            st.rerun()
        if st.button(
            "API Settings",
            use_container_width=True,
            key="admin_api",
            type="primary" if st.session_state.admin_nav == "API Settings" else "secondary",
        ):
            st.session_state.admin_nav = "API Settings"
            st.rerun()
        if st.button(
            "Audit Logs",
            use_container_width=True,
            key="admin_logs",
            type="primary" if st.session_state.admin_nav == "Audit Logs" else "secondary",
        ):
            st.session_state.admin_nav = "Audit Logs"
            st.rerun()

        st.write("###")
        if st.button("Exit to user app", use_container_width=True, key="admin_exit"):
            logout_user()

    show_flash()

    head_col1, head_col2 = st.columns([3, 1])
    with head_col1:
        st.markdown(
            f"<h1 style='color:white; font-size:42px; font-weight:800; margin-bottom:0;'>{st.session_state.admin_nav}</h1>",
            unsafe_allow_html=True,
        )
        st.markdown(
            "<p style='color:#94A3B8; font-size:18px;'>Orchestrating the CogniStudy neural core.</p>",
            unsafe_allow_html=True,
        )
    with head_col2:
        st.write("##")
        api_ready = bool(st.session_state.saved_api_key)
        status_text = "SYSTEM OPERATIONAL" if api_ready else "ACTION REQUIRED"
        status_color = "#2DD4BF" if api_ready else "#ff6b35"
        st.markdown(
            f"<div style='text-align:right;'><span class='status-badge' style='color:{status_color}; border-color:{status_color};'>{status_text}</span></div>",
            unsafe_allow_html=True,
        )

    st.write("##")

    if st.session_state.admin_nav == "System Overview":
        usage_data = get_actual_usage()
        total_tokens = int(usage_data["Tokens"].sum())
        total_documents = get_total_document_count()
        estimated_cost = (total_tokens / 1_000_000) * 0.075

        metric_one, metric_two, metric_three, metric_four = st.columns(4)
        with metric_one:
            st.markdown(
                f'<div class="admin-card"><small style="color:#94A3B8;">ACTIVE USERS</small><h2 style="color:white; margin:0;">{scholar_count}</h2></div>',
                unsafe_allow_html=True,
            )
        with metric_two:
            st.markdown(
                f'<div class="admin-card"><small style="color:#94A3B8;">FILES PROCESSED</small><h2 style="color:white; margin:0;">{total_documents}</h2></div>',
                unsafe_allow_html=True,
            )
        with metric_three:
            st.markdown(
                f'<div class="admin-card"><small style="color:#94A3B8;">API COST (MTD)</small><h2 style="color:#ff6b35; margin:0;">${estimated_cost:.5f}</h2></div>',
                unsafe_allow_html=True,
            )
        with metric_four:
            st.markdown(
                '<div class="admin-card"><small style="color:#94A3B8;">TOKEN LIMIT</small><h2 style="color:white; margin:0;">1.2M</h2></div>',
                unsafe_allow_html=True,
            )

        st.write("##")
        st.markdown('<div class="admin-card">', unsafe_allow_html=True)
        st.subheader("API Token Consumption")
        usage_fig = px.bar(usage_data, x="Date", y="Tokens")
        usage_fig.update_traces(
            marker_color="#ff6b35",
            marker_line_color="#ff6b35",
            marker_line_width=1.5,
            opacity=0.8,
        )
        usage_fig.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font_color="white",
            margin=dict(l=0, r=0, t=20, b=0),
            height=300,
        )
        st.plotly_chart(usage_fig, use_container_width=True, config={"displayModeBar": False})
        st.markdown("</div>", unsafe_allow_html=True)

    elif st.session_state.admin_nav == "User Database":
        st.markdown('<div class="admin-card">', unsafe_allow_html=True)
        st.subheader("Registered Accounts")
        if all_users:
            registry_df = pd.DataFrame(all_users)
            registry_df["role"] = registry_df["role"].str.title()
            registry_df["account_status"] = registry_df["account_status"].str.title()
            registry_df = registry_df[["fullname", "email", "role", "account_status", "created_at"]]
            registry_df.columns = ["Name", "Email", "Role", "Status", "Created"]
            st.dataframe(registry_df, use_container_width=True)
            st.write("")
            st.markdown("#### Account Controls")
            for account in all_users:
                row_left, row_status, row_history, row_action, row_delete = st.columns([2.1, 1, 1.15, 1, 1])
                with row_left:
                    st.markdown(
                        f"**{account['fullname']}**  \n<small style='color:#94A3B8;'>{account['email']}</small>",
                        unsafe_allow_html=True,
                    )
                with row_status:
                    st.markdown(
                        f"Role: **{str(account['role']).title()}**  \nStatus: **{str(account.get('account_status', 'active')).title()}**"
                    )
                if account["role"] == "admin":
                    with row_history:
                        if st.button("View Activity", key=f"admin_user_activity_{account['id']}", use_container_width=True):
                            st.session_state.admin_selected_user_activity_id = int(account["id"])
                            st.rerun()
                    with row_action:
                        st.caption("Protected")
                    with row_delete:
                        st.caption("Protected")
                else:
                    is_active = str(account.get("account_status", "active")).lower() == "active"
                    with row_history:
                        if st.button("View Activity", key=f"admin_user_activity_{account['id']}", use_container_width=True):
                            st.session_state.admin_selected_user_activity_id = int(account["id"])
                            st.rerun()
                    with row_action:
                        action_label = "Suspend" if is_active else "Activate"
                        if st.button(action_label, key=f"admin_user_status_{account['id']}", use_container_width=True):
                            new_status = "suspended" if is_active else "active"
                            update_user_account_status(int(account["id"]), new_status)
                            log_system_activity(
                                actor_name=user["fullname"],
                                actor_role="admin",
                                actor_id=int(user["id"]),
                                activity=f"{action_label} user",
                                details=f"{action_label}d {account['fullname']} ({account['email']}).",
                            )
                            set_flash("success", f"{account['fullname']} is now {new_status}.")
                            st.rerun()
                    with row_delete:
                        if st.button("Delete", key=f"admin_user_delete_{account['id']}", use_container_width=True):
                            delete_user_account(int(account["id"]))
                            log_system_activity(
                                actor_name=user["fullname"],
                                actor_role="admin",
                                actor_id=int(user["id"]),
                                activity="Deleted user",
                                details=f"Deleted {account['fullname']} ({account['email']}).",
                            )
                            set_flash("success", f"{account['fullname']} was deleted.")
                            st.rerun()
                selected_activity_user_id = int(st.session_state.get("admin_selected_user_activity_id") or 0)
                if selected_activity_user_id == int(account["id"]):
                    activity_rows = load_system_activities_for_user(int(account["id"]), limit=25)
                    st.markdown(
                        f"""
                        <div style="margin:10px 0 16px 0; padding:16px 18px; border-radius:16px; border:1px solid rgba(255,255,255,0.08); background:rgba(15,23,42,0.28);">
                            <p style="color:#2DD4BF; font-size:11px; font-weight:800; letter-spacing:1px; margin:0 0 8px 0;">USER ACTIVITY</p>
                            <h4 style="color:white; margin:0 0 6px 0;">{html.escape(account['fullname'])}</h4>
                            <p style="color:#94A3B8; margin:0; font-size:13px;">Recent system actions and history for this account.</p>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
                    close_history_col, _ = st.columns([1, 4])
                    with close_history_col:
                        if st.button("Hide Activity", key=f"admin_user_activity_close_{account['id']}", use_container_width=True):
                            st.session_state.admin_selected_user_activity_id = None
                            st.rerun()
                    if activity_rows:
                        activity_df = pd.DataFrame(activity_rows)
                        activity_df = activity_df[["created_at", "activity", "details"]]
                        activity_df.columns = ["When", "Activity", "Details"]
                        st.dataframe(activity_df, use_container_width=True)
                    else:
                        st.info("No activity history has been logged for this account yet.")
        else:
            st.info("No user records yet. New sign-ups will appear here automatically.")
        st.markdown("</div>", unsafe_allow_html=True)

    elif st.session_state.admin_nav == "API Settings":
        active_prompt = sync_system_prompt_state()
        current_saved_email = load_gmail_sender_email_permanently()
        current_saved_app_password = load_gmail_app_password_permanently()
        api_key_managed_by_env = bool(os.getenv(API_KEY_ENV, "").strip())
        gmail_password_managed_by_env = bool(os.getenv(GMAIL_APP_PASSWORD_ENV, "").replace(" ", "").strip())
        plaintext_secret_storage_enabled = insecure_secret_storage_allowed()
        st.session_state.saved_gmail_sender_email = current_saved_email
        if not st.session_state.get("gmail_sender_email_field"):
            st.session_state.gmail_sender_email_field = current_saved_email
        brain_col, prompt_col = st.columns([1, 1.2])
        with brain_col:
            st.markdown('<div class="admin-card" style="height:100%;">', unsafe_allow_html=True)
            st.subheader("Neural Engine Config")
            api_input = st.text_input(
                "Enter API Key",
                value=st.session_state.saved_api_key,
                type="password",
                key="api_key_field",
            )
            if api_key_managed_by_env:
                st.caption(f"The active API key is currently managed by {API_KEY_ENV}.")
            elif not plaintext_secret_storage_enabled:
                st.caption(build_secret_storage_error(API_KEY_ENV))
            if st.button("Save Config", key="save_api", use_container_width=True):
                if api_input.strip():
                    try:
                        save_key_permanently(api_input)
                    except RuntimeError as error:
                        st.error(str(error))
                    else:
                        st.session_state.saved_api_key = api_input.strip()
                        log_system_activity(
                            actor_name=user["fullname"],
                            actor_role="admin",
                            actor_id=int(user["id"]),
                            activity="Updated API key",
                            details="Saved a new API key in API Settings.",
                        )
                        st.success("API key secured.")
                else:
                    st.warning("Please enter an API key before saving.")
            st.write("")
            st.subheader("Welcome Email Config")
            gmail_sender_input = st.text_input(
                "Sender Gmail Address",
                key="gmail_sender_email_field",
            )
            gmail_password_input = st.text_input(
                "Gmail App Password",
                key="gmail_app_password_field",
                type="password",
                placeholder="Leave blank to keep the current saved password",
            )
            password_status = "Configured" if current_saved_app_password else "Not configured"
            st.caption(
                f"Current sender: {current_saved_email or 'Not configured'}"
            )
            if gmail_password_managed_by_env:
                st.caption(
                    f"Gmail app password: {password_status}. The active password is currently managed by {GMAIL_APP_PASSWORD_ENV}."
                )
            elif plaintext_secret_storage_enabled:
                st.caption(
                    "Gmail app password: "
                    f"{password_status}. Environment variables override values saved here."
                )
            else:
                st.caption(build_secret_storage_error(GMAIL_APP_PASSWORD_ENV))
            if st.button("Save Email Delivery", key="save_email_delivery", use_container_width=True):
                normalized_sender = gmail_sender_input.strip().lower()
                normalized_password = gmail_password_input.replace(" ", "").strip()
                password_to_store = normalized_password or current_saved_app_password
                if not normalized_sender:
                    st.warning("Please enter the sender Gmail address before saving.")
                elif "@" not in normalized_sender or "." not in normalized_sender:
                    st.warning("Please enter a valid sender Gmail address.")
                elif not password_to_store:
                    st.warning("Please enter the Gmail app password before saving.")
                else:
                    try:
                        if normalized_password:
                            save_gmail_app_password_permanently(normalized_password)
                    except RuntimeError as error:
                        st.error(str(error))
                    else:
                        save_gmail_sender_email_permanently(normalized_sender)
                        st.session_state.saved_gmail_sender_email = normalized_sender
                        st.session_state.gmail_sender_email_field = normalized_sender
                        st.session_state.gmail_app_password_field = ""
                        log_system_activity(
                            actor_name=user["fullname"],
                            actor_role="admin",
                            actor_id=int(user["id"]),
                            activity="Updated welcome email config",
                            details=f"Saved sender email {normalized_sender} and refreshed email delivery settings.",
                        )
                        st.success("Email delivery settings saved.")
            st.markdown("</div>", unsafe_allow_html=True)
        with prompt_col:
            st.markdown('<div class="admin-card" style="height:100%;">', unsafe_allow_html=True)
            st.subheader("Master System Prompt")
            st.text_area(
                "Instructions",
                height=210,
                key="system_prompt_field",
                on_change=persist_system_prompt,
            )
            st.caption("This exact prompt is the one used for new reviewer and quiz generations. If the admin edits it here, the system adopts the new prompt automatically.")
            st.caption(f"Active prompt length: {len(active_prompt)} characters")
            st.markdown("</div>", unsafe_allow_html=True)

    elif st.session_state.admin_nav == "Audit Logs":
        st.markdown('<div class="admin-card">', unsafe_allow_html=True)
        st.subheader("System Audit Trail")
        usage_data = get_actual_usage()
        admin_activity = pd.DataFrame(load_system_activities("admin", limit=50))
        user_activity = pd.DataFrame(load_system_activities("user", limit=50))
        st.write("Recent token activity by date:")
        st.dataframe(usage_data, use_container_width=True)
        st.write("")
        st.markdown("#### Admin System Activity")
        if not admin_activity.empty:
            st.dataframe(admin_activity, use_container_width=True)
        else:
            st.info("No admin activity has been logged yet.")
        st.write("")
        st.markdown("#### User System Activity")
        if not user_activity.empty:
            st.dataframe(user_activity, use_container_width=True)
        else:
            st.info("No user activity has been logged yet.")
        st.markdown("</div>", unsafe_allow_html=True)


def main() -> None:
    try:
        initialize_database()
    except RuntimeError as error:
        st.error(f"Startup configuration failed: {error}")
        st.stop()
    except mysql.connector.Error as error:
        st.error(f"Database connection failed: {error}")
        st.stop()

    init_session()

    route = st.session_state.route
    current_user = st.session_state.current_user

    if current_user:
        refreshed_user = load_user_by_id(int(current_user["id"]))
        if refreshed_user:
            st.session_state.current_user = refreshed_user
            current_user = refreshed_user
            if current_user["role"] != "admin" and str(current_user.get("account_status", "active")).lower() != "active":
                st.session_state.current_user = None
                set_flash("error", "This account has been suspended. Please contact the admin.")
                go_to("signin")
        else:
            st.session_state.current_user = None
            set_flash("warning", "Your account could not be found. Please sign in again.")
            go_to("signin")

    if route == "user_dashboard" and not current_user:
        set_flash("warning", "Please sign in first.")
        go_to("signin")

    if route == "admin_dashboard":
        if not current_user:
            set_flash("warning", "Please sign in first.")
            go_to("signin")
        if current_user["role"] != "admin":
            set_flash("error", "Admin access is required for that page.")
            go_to("user_dashboard")

    if route == "signin":
        render_signin()
    elif route == "signup":
        render_signup()
    elif route == "reset_password":
        render_reset_password()
    elif route == "user_dashboard":
        render_user_dashboard()
    elif route == "admin_dashboard":
        render_admin_dashboard()


if __name__ == "__main__":
    main()
