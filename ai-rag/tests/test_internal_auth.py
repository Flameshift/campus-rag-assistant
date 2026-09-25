"""内部服务签名测试。"""

import hashlib
import hmac
import unittest
from unittest.mock import patch

from app.internal_auth import InternalAuthMiddleware


class InternalAuthTests(unittest.TestCase):
    def test_valid_signature_is_accepted(self):
        with patch("app.internal_auth.config.INTERNAL_AUTH_SECRET", "test-secret"):
            signature = hmac.new(
                b"test-secret",
                b"1700000000\nPOST\n/api/chat",
                hashlib.sha256,
            ).hexdigest()

            self.assertTrue(
                InternalAuthMiddleware._valid_signature(
                    "1700000000",
                    "POST",
                    "/api/chat",
                    signature,
                )
            )

    def test_invalid_signature_is_rejected(self):
        with patch("app.internal_auth.config.INTERNAL_AUTH_SECRET", "test-secret"):
            self.assertFalse(
                InternalAuthMiddleware._valid_signature(
                    "1700000000",
                    "POST",
                    "/api/chat",
                    "invalid",
                )
            )


if __name__ == "__main__":
    unittest.main()
