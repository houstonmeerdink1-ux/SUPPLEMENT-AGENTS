import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
CORE_PATH = SKILL_ROOT / "scripts" / "fast_lane_core.py"
FIXTURE_ROOT = Path(__file__).with_name("fixtures") / "mirror"


def load_core():
    spec = importlib.util.spec_from_file_location("fast_lane_core", CORE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ScopeGateTests(unittest.TestCase):
    def setUp(self):
        self.core = load_core()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.mirror = Path(self.temp_dir.name) / "mirror"
        shutil.copytree(FIXTURE_ROOT, self.mirror)
        self.job = self.core.resolve_job(
            self.core.build_index(self.mirror),
            "Beta Homeowner",
        )
        self.baseline = {"code": "SYNKC1_JAN26", "month": "2026-01"}
        self.target = {"code": "SYNKC1_AUG26", "month": "2026-08"}
        self.now = "2026-08-30T12:30:00-05:00"
        self.approved = {
            "schema_version": "1.0",
            "job_identity": {
                "job_id": "job-beta",
                "job_number": "9003",
                "exact_address": "300 Main Street, Sample City, KS 66103",
                "zip": "66103",
            },
            "approval_state": "HOUSTON_APPROVED",
            "approved_item_ids": ["ceiling-hall"],
            "items": [
                {
                    "item_id": "ceiling-hall",
                    "status": "REQUESTED",
                    "description": "Remove continuous ceiling finish and replace supported affected plane",
                    "quantity": {"value": 120.0, "unit": "SF", "source": "synthetic-measurement#page-1"},
                    "evidence": [
                        {
                            "source_id": "synthetic-photo-1",
                            "source_path": "01 JOBNIMBUS SOURCE/Attachments/Photos/synthetic-photo-1.jpg",
                            "supports": "open ceiling and continuous finish",
                        }
                    ],
                    "carrier_credit": {
                        "status": "EXISTING_ALLOWANCE",
                        "line_reference": "carrier-line-12",
                        "quantity": 10.0,
                        "unit": "SF",
                    },
                    "unresolved_questions": [],
                },
                {
                    "item_id": "ceiling-bedroom",
                    "status": "ACTION_NEEDED",
                    "description": "Bedroom ceiling work pending exact dimensions",
                    "quantity": None,
                    "evidence": [],
                    "carrier_credit": {"status": "UNKNOWN"},
                    "unresolved_questions": ["Confirm exact affected ceiling area."],
                },
                {
                    "item_id": "carrier-paid-paint",
                    "status": "PAID",
                    "description": "Existing carrier paint allowance retained as credit",
                    "quantity": {"value": 120.0, "unit": "SF", "source": "carrier-line-13"},
                    "evidence": [{"source_id": "carrier-line-13", "source_path": "carrier-scope.pdf#page-4"}],
                    "carrier_credit": {"status": "PAID", "line_reference": "carrier-line-13"},
                    "unresolved_questions": [],
                },
            ],
        }

    def tearDown(self):
        self.temp_dir.cleanup()

    def approve(self, payload=None):
        return self.core.approve_scope(
            payload or self.approved,
            self.job,
            approved_by="Houston",
            approved_at=self.now,
            baseline=self.baseline,
            target=self.target,
        )

    def test_unapproved_scope_cannot_create_pricing_manifest(self):
        payload = json.loads(json.dumps(self.approved))
        payload["approval_state"] = "DRAFT"

        with self.assertRaises(self.core.ScopeApprovalError):
            self.approve(payload)

    def test_requested_item_requires_quantity_and_evidence_pointer(self):
        payload = json.loads(json.dumps(self.approved))
        payload["items"][0]["evidence"] = []

        with self.assertRaises(self.core.ScopeValidationError):
            self.approve(payload)

    def test_blocked_item_cannot_be_approved_for_pricing(self):
        payload = json.loads(json.dumps(self.approved))
        payload["approved_item_ids"] = ["ceiling-bedroom"]

        with self.assertRaises(self.core.ScopeApprovalError):
            self.approve(payload)

    def test_scope_gap_may_not_supply_xactimate_price(self):
        payload = json.loads(json.dumps(self.approved))
        payload["items"][0]["unit_price"] = 14.25

        with self.assertRaisesRegex(self.core.ScopeValidationError, "price"):
            self.approve(payload)

    def test_scope_identity_must_match_locked_job(self):
        payload = json.loads(json.dumps(self.approved))
        payload["job_identity"]["exact_address"] = "301 Main Street, Sample City, KS 66103"

        with self.assertRaises(self.core.IdentityConflictError):
            self.approve(payload)

    def test_manifest_preserves_baseline_and_target_separately(self):
        result = self.approve()

        self.assertEqual(self.baseline, result["carrier_baseline_price_list"])
        self.assertEqual(self.target, result["authorized_target_price_list"])
        self.assertEqual("PRICING_READY", result["state"])
        self.assertEqual(
            ["ceiling-hall"],
            [item["item_id"] for item in result["requested_items"]],
        )
        self.assertNotIn("unit_price", result["requested_items"][0])

    def test_price_list_requires_exact_code_and_month(self):
        with self.assertRaises(self.core.ScopeValidationError):
            self.core.approve_scope(
                self.approved,
                self.job,
                approved_by="Houston",
                approved_at=self.now,
                baseline={"code": "SYNKC1_JAN26", "month": "January"},
                target=self.target,
            )

    def test_pricing_manifest_persists_only_after_scope_audited_state(self):
        self.core.prepare_job(self.job, now="2026-08-30T12:00:00-05:00")
        manifest = self.approve()
        working = Path(self.job["folder_path"]) / "02 LOCAL WORKING FILES" / "00 FAST LANE"

        with self.assertRaises(self.core.StateTransitionError):
            self.core.persist_pricing_manifest(self.job, manifest, now=self.now)
        self.assertFalse((working / "xactimate-entry-manifest.json").exists())

        state_path = working / "run-state.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["state"] = "SCOPE_AUDITED"
        state_path.write_text(json.dumps(state), encoding="utf-8")

        persisted = self.core.persist_pricing_manifest(self.job, manifest, now=self.now)

        self.assertEqual("PRICING_READY", persisted["state"])
        written = json.loads(
            (working / "xactimate-entry-manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual("job-beta", written["job_identity"]["job_id"])


if __name__ == "__main__":
    unittest.main()
