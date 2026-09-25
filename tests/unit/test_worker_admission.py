"""Unit tests for worker admission token issuance and verification.

Reference: NODE_AGENT_IMPLEMENTATION_PLAN.md Section 8.1
"""

from __future__ import annotations

import base64
import json
import time
import unittest

from pbl4.common.worker_admission import (
    WorkerAdmissionClaims,
    WorkerAdmissionError,
    issue_worker_join_token,
    verify_worker_join_token,
)


class TestWorkerAdmission(unittest.TestCase):
    def setUp(self) -> None:
        self.secret = "top-secret-admission-key-12345"
        self.attempt_id = "attempt-001"
        self.allocation_id = "alloc-001"
        self.node_id = "node-alpha"
        self.fixed_now = 1700000000.0

    def test_issue_and_verify_success(self) -> None:
        token = issue_worker_join_token(
            self.secret,
            self.attempt_id,
            self.allocation_id,
            self.node_id,
            ttl_seconds=600,
            now=self.fixed_now,
        )
        self.assertIsInstance(token, str)
        self.assertIn(".", token)

        claims = verify_worker_join_token(
            self.secret,
            token,
            self.attempt_id,
            self.allocation_id,
            self.node_id,
            now=self.fixed_now + 100,
        )
        self.assertIsInstance(claims, WorkerAdmissionClaims)
        self.assertEqual(claims.v, 1)
        self.assertEqual(claims.attempt_id, self.attempt_id)
        self.assertEqual(claims.allocation_id, self.allocation_id)
        self.assertEqual(claims.node_id, self.node_id)
        self.assertEqual(claims.exp, int(self.fixed_now + 600))
        self.assertTrue(len(claims.nonce) >= 16)

    def test_nonce_is_randomized(self) -> None:
        t1 = issue_worker_join_token(
            self.secret, self.attempt_id, self.allocation_id, self.node_id, now=self.fixed_now
        )
        t2 = issue_worker_join_token(
            self.secret, self.attempt_id, self.allocation_id, self.node_id, now=self.fixed_now
        )
        self.assertNotEqual(t1, t2)
        c1 = verify_worker_join_token(
            self.secret, t1, self.attempt_id, self.allocation_id, self.node_id, now=self.fixed_now
        )
        c2 = verify_worker_join_token(
            self.secret, t2, self.attempt_id, self.allocation_id, self.node_id, now=self.fixed_now
        )
        self.assertNotEqual(c1.nonce, c2.nonce)

    def test_altered_payload_rejected(self) -> None:
        token = issue_worker_join_token(
            self.secret, self.attempt_id, self.allocation_id, self.node_id, now=self.fixed_now
        )
        payload_b64, sig_b64 = token.split(".")

        # Decode payload, tamper with attempt_id, re-encode without updating signature
        pad = (-len(payload_b64)) % 4
        payload_dict = json.loads(base64.urlsafe_b64decode(payload_b64 + "=" * pad).decode("utf-8"))
        payload_dict["attempt_id"] = "tampered-attempt"
        tampered_bytes = json.dumps(payload_dict, sort_keys=True, separators=(",", ":")).encode("utf-8")
        tampered_b64 = base64.urlsafe_b64encode(tampered_bytes).decode("ascii").rstrip("=")

        tampered_token = f"{tampered_b64}.{sig_b64}"
        with self.assertRaises(WorkerAdmissionError) as ctx:
            verify_worker_join_token(
                self.secret,
                tampered_token,
                self.attempt_id,
                self.allocation_id,
                self.node_id,
                now=self.fixed_now,
            )
        self.assertIn("signature", str(ctx.exception).lower())

    def test_altered_signature_rejected(self) -> None:
        token = issue_worker_join_token(
            self.secret, self.attempt_id, self.allocation_id, self.node_id, now=self.fixed_now
        )
        payload_b64, sig_b64 = token.split(".")
        # Corrupt the first character of the signature
        corrupted_sig = ("B" if sig_b64[0] == "A" else "A") + sig_b64[1:]
        corrupted_token = f"{payload_b64}.{corrupted_sig}"

        with self.assertRaises(WorkerAdmissionError) as ctx:
            verify_worker_join_token(
                self.secret,
                corrupted_token,
                self.attempt_id,
                self.allocation_id,
                self.node_id,
                now=self.fixed_now,
            )
        self.assertIn("signature", str(ctx.exception).lower())

    def test_expired_token_rejected(self) -> None:
        token = issue_worker_join_token(
            self.secret,
            self.attempt_id,
            self.allocation_id,
            self.node_id,
            ttl_seconds=300,
            now=self.fixed_now,
        )
        # Verify right at expiration / after expiration
        with self.assertRaises(WorkerAdmissionError) as ctx:
            verify_worker_join_token(
                self.secret,
                token,
                self.attempt_id,
                self.allocation_id,
                self.node_id,
                now=self.fixed_now + 301,
            )
        self.assertIn("expired", str(ctx.exception).lower())

    def test_scope_mismatch_rejected(self) -> None:
        token = issue_worker_join_token(
            self.secret, self.attempt_id, self.allocation_id, self.node_id, now=self.fixed_now
        )

        # Wrong attempt_id
        with self.assertRaises(WorkerAdmissionError) as ctx:
            verify_worker_join_token(
                self.secret,
                token,
                "wrong-attempt",
                self.allocation_id,
                self.node_id,
                now=self.fixed_now,
            )
        self.assertIn("attempt_id", str(ctx.exception))

        # Wrong allocation_id
        with self.assertRaises(WorkerAdmissionError) as ctx:
            verify_worker_join_token(
                self.secret,
                token,
                self.attempt_id,
                "wrong-allocation",
                self.node_id,
                now=self.fixed_now,
            )
        self.assertIn("allocation_id", str(ctx.exception))

        # Wrong node_id
        with self.assertRaises(WorkerAdmissionError) as ctx:
            verify_worker_join_token(
                self.secret,
                token,
                self.attempt_id,
                self.allocation_id,
                "wrong-node",
                now=self.fixed_now,
            )
        self.assertIn("node_id", str(ctx.exception))

    def test_malformed_token_structure(self) -> None:
        malformed_cases = [
            "",
            "not-a-token",
            "part1.part2.part3",
            ".signature",
            "payload.",
            "...",
        ]
        for case in malformed_cases:
            with self.subTest(case=case):
                with self.assertRaises(WorkerAdmissionError):
                    verify_worker_join_token(
                        self.secret,
                        case,
                        self.attempt_id,
                        self.allocation_id,
                        self.node_id,
                        now=self.fixed_now,
                    )

    def test_malformed_base64_or_json(self) -> None:
        # Invalid base64 characters
        with self.assertRaises(WorkerAdmissionError):
            verify_worker_join_token(
                self.secret,
                "???invalid_b64???.valid_sig",
                self.attempt_id,
                self.allocation_id,
                self.node_id,
                now=self.fixed_now,
            )

        # Base64 that decodes to non-JSON bytes
        non_json_b64 = base64.urlsafe_b64encode(b"not json content").decode("ascii").rstrip("=")
        # Sign it with secret so signature passes
        sig = base64.urlsafe_b64encode(
            b"arbitrary-sig-that-matches"
        ).decode("ascii").rstrip("=")
        with self.assertRaises(WorkerAdmissionError):
            verify_worker_join_token(
                self.secret,
                f"{non_json_b64}.{sig}",
                self.attempt_id,
                self.allocation_id,
                self.node_id,
                now=self.fixed_now,
            )

    def test_unsupported_version_rejected(self) -> None:
        payload = {
            "v": 2,
            "attempt_id": self.attempt_id,
            "allocation_id": self.allocation_id,
            "node_id": self.node_id,
            "exp": int(self.fixed_now + 600),
            "nonce": "1234567890abcdef",
        }
        payload_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        payload_b64 = base64.urlsafe_b64encode(payload_bytes).decode("ascii").rstrip("=")
        import hashlib
        import hmac
        sig = hmac.new(self.secret.encode("utf-8"), payload_bytes, hashlib.sha256).digest()
        sig_b64 = base64.urlsafe_b64encode(sig).decode("ascii").rstrip("=")

        token = f"{payload_b64}.{sig_b64}"
        with self.assertRaises(WorkerAdmissionError) as ctx:
            verify_worker_join_token(
                self.secret,
                token,
                self.attempt_id,
                self.allocation_id,
                self.node_id,
                now=self.fixed_now,
            )
        self.assertIn("version", str(ctx.exception).lower())

    def test_missing_claims_rejected(self) -> None:
        for missing_field in ["attempt_id", "allocation_id", "node_id", "exp", "nonce", "v"]:
            payload = {
                "v": 1,
                "attempt_id": self.attempt_id,
                "allocation_id": self.allocation_id,
                "node_id": self.node_id,
                "exp": int(self.fixed_now + 600),
                "nonce": "1234567890abcdef",
            }
            del payload[missing_field]
            payload_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
            payload_b64 = base64.urlsafe_b64encode(payload_bytes).decode("ascii").rstrip("=")
            import hashlib
            import hmac
            sig = hmac.new(self.secret.encode("utf-8"), payload_bytes, hashlib.sha256).digest()
            sig_b64 = base64.urlsafe_b64encode(sig).decode("ascii").rstrip("=")

            token = f"{payload_b64}.{sig_b64}"
            with self.subTest(missing_field=missing_field):
                with self.assertRaises(WorkerAdmissionError) as ctx:
                    verify_worker_join_token(
                        self.secret,
                        token,
                        self.attempt_id,
                        self.allocation_id,
                        self.node_id,
                        now=self.fixed_now,
                    )
                self.assertIn(missing_field, str(ctx.exception))

    def test_secret_is_not_leaked_in_exceptions(self) -> None:
        secret = "ultra-secret-phrase-xyz-789"
        try:
            verify_worker_join_token(
                secret,
                "invalid.token",
                self.attempt_id,
                self.allocation_id,
                self.node_id,
                now=self.fixed_now,
            )
        except WorkerAdmissionError as exc:
            self.assertNotIn(secret, str(exc))

    def test_invalid_issue_arguments(self) -> None:
        with self.assertRaises(WorkerAdmissionError):
            issue_worker_join_token("", self.attempt_id, self.allocation_id, self.node_id)
        with self.assertRaises(WorkerAdmissionError):
            issue_worker_join_token(self.secret, "", self.allocation_id, self.node_id)
        with self.assertRaises(WorkerAdmissionError):
            issue_worker_join_token(self.secret, self.attempt_id, "", self.node_id)
        with self.assertRaises(WorkerAdmissionError):
            issue_worker_join_token(self.secret, self.attempt_id, self.allocation_id, "")
        with self.assertRaises(WorkerAdmissionError):
            issue_worker_join_token(self.secret, self.attempt_id, self.allocation_id, self.node_id, ttl_seconds=-10)


if __name__ == "__main__":
    unittest.main()
