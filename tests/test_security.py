from __future__ import annotations

import unittest

from memory_fabric.security import _looks_like_secret, _shannon_entropy, redact_secrets


class SecurityTests(unittest.TestCase):
    def test_redact_github_token(self) -> None:
        text = "My github token is ghp_12345678901234567890"
        redacted, count = redact_secrets(text)
        self.assertEqual(count, 1)
        self.assertIn("[REDACTED_SECRET]", redacted)
        self.assertNotIn("ghp_12345678901234567890", redacted)

    def test_redact_aws_key(self) -> None:
        text = "AWS key: AKIA1234567890ABCDEF"
        redacted, count = redact_secrets(text)
        self.assertEqual(count, 1)
        self.assertIn("[REDACTED_SECRET]", redacted)
        self.assertNotIn("AKIA1234567890ABCDEF", redacted)

    def test_redact_openai_key(self) -> None:
        text = "sk-A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6"
        redacted, count = redact_secrets(text)
        self.assertEqual(count, 1)
        self.assertEqual(redacted, "[REDACTED_SECRET]")

    def test_redact_key_value_assignment(self) -> None:
        text = 'super_secret_token = "some_random_value_longer_than_12"'
        redacted, count = redact_secrets(text)
        self.assertEqual(count, 1)
        self.assertEqual(redacted, 'super_secret_token = "[REDACTED_SECRET]"')

    def test_shannon_entropy_calculation(self) -> None:
        # A repeating string has low entropy
        low_entropy = _shannon_entropy("aaaaabbbbb")
        # 2 symbols with equal probability -> H = -2 * (0.5 * log2(0.5)) = 1.0
        self.assertAlmostEqual(low_entropy, 1.0)

        # A string with many unique characters has higher entropy
        high_entropy = _shannon_entropy("abcdefghij")
        self.assertGreater(high_entropy, 3.0)

    def test_looks_like_secret_checks(self) -> None:
        # Too short
        self.assertFalse(_looks_like_secret("short"))
        # Long but only lowercase
        self.assertFalse(_looks_like_secret("abcdefghijklmnopqrstuvwxyzabcdefghijklmn"))
        # High entropy, mix of cases, digits, symbols -> likely secret
        self.assertTrue(_looks_like_secret("aB3$eF8*kL2!nO9#qR5^uU1(xX7_zZ0-pP4%yY6Q"))

    def test_no_redaction_for_ordinary_text(self) -> None:
        ordinary = "This is a normal sentence about memory fabric architecture, path resolving and unit testing."
        redacted, count = redact_secrets(ordinary)
        self.assertEqual(count, 0)
        self.assertEqual(redacted, ordinary)


if __name__ == "__main__":
    unittest.main()
