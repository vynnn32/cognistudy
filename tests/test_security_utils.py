from __future__ import annotations

import unittest

from security_utils import (
    hash_password,
    password_hash_needs_upgrade,
    validate_password_strength,
    verify_password,
)


class SecurityUtilsTests(unittest.TestCase):
    def test_hash_and_verify_password_round_trip(self) -> None:
        password_hash = hash_password("StrongPassword123")
        self.assertTrue(password_hash.startswith("pbkdf2_sha256$"))
        self.assertTrue(verify_password("StrongPassword123", password_hash))
        self.assertFalse(verify_password("WrongPassword123", password_hash))

    def test_legacy_sha256_hash_still_verifies_and_needs_upgrade(self) -> None:
        legacy_hash = "e86f78a8a3caf0b60d8e74e5942aa6d86dc150cd3c03338aef25b7d2d7e3acc7"
        self.assertTrue(verify_password("Admin@123", legacy_hash))
        self.assertTrue(password_hash_needs_upgrade(legacy_hash))

    def test_modern_hash_does_not_need_upgrade(self) -> None:
        password_hash = hash_password("AnotherStrong123")
        self.assertFalse(password_hash_needs_upgrade(password_hash))

    def test_password_strength_validation(self) -> None:
        self.assertEqual(
            validate_password_strength("StrongPassword123"),
            (True, ""),
        )
        self.assertEqual(
            validate_password_strength("short"),
            (False, "Password must be at least 12 characters long."),
        )
        self.assertEqual(
            validate_password_strength("alllowercase123"),
            (False, "Password must include at least one uppercase letter."),
        )
        self.assertEqual(
            validate_password_strength("ALLUPPERCASE123"),
            (False, "Password must include at least one lowercase letter."),
        )
        self.assertEqual(
            validate_password_strength("NoNumbersHere"),
            (False, "Password must include at least one number."),
        )


if __name__ == "__main__":
    unittest.main()
