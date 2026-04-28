from __future__ import annotations

import base64
import hashlib
import hmac
import secrets


PBKDF2_PREFIX = "pbkdf2_sha256"
PBKDF2_ITERATIONS = 600_000
PASSWORD_MIN_LENGTH = 12


def _urlsafe_b64encode(raw_bytes: bytes) -> str:
    return base64.urlsafe_b64encode(raw_bytes).decode("ascii").rstrip("=")


def _urlsafe_b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(f"{value}{padding}")


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    derived_key = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PBKDF2_ITERATIONS,
    )
    return (
        f"{PBKDF2_PREFIX}${PBKDF2_ITERATIONS}"
        f"${_urlsafe_b64encode(salt)}${_urlsafe_b64encode(derived_key)}"
    )


def is_legacy_sha256_hash(password_hash: str) -> bool:
    normalized = password_hash.strip().lower()
    return len(normalized) == 64 and all(character in "0123456789abcdef" for character in normalized)


def verify_password(password: str, stored_hash: str) -> bool:
    normalized_hash = (stored_hash or "").strip()
    if not normalized_hash:
        return False

    if normalized_hash.startswith(f"{PBKDF2_PREFIX}$"):
        try:
            _, iteration_value, salt_value, hash_value = normalized_hash.split("$", 3)
            iterations = int(iteration_value)
            salt = _urlsafe_b64decode(salt_value)
            expected_hash = _urlsafe_b64decode(hash_value)
        except (TypeError, ValueError):
            return False

        actual_hash = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            iterations,
        )
        return hmac.compare_digest(actual_hash, expected_hash)

    if is_legacy_sha256_hash(normalized_hash):
        legacy_hash = hashlib.sha256(password.encode("utf-8")).hexdigest()
        return hmac.compare_digest(legacy_hash, normalized_hash)

    return False


def password_hash_needs_upgrade(stored_hash: str) -> bool:
    return not (stored_hash or "").strip().startswith(f"{PBKDF2_PREFIX}$")


def validate_password_strength(password: str) -> tuple[bool, str]:
    if len(password) < PASSWORD_MIN_LENGTH:
        return False, f"Password must be at least {PASSWORD_MIN_LENGTH} characters long."
    if not any(character.islower() for character in password):
        return False, "Password must include at least one lowercase letter."
    if not any(character.isupper() for character in password):
        return False, "Password must include at least one uppercase letter."
    if not any(character.isdigit() for character in password):
        return False, "Password must include at least one number."
    return True, ""
