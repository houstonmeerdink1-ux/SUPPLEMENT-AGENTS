import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
CORE_PATH = SKILL_ROOT / "scripts" / "fast_lane_core.py"
CLI_PATH = SKILL_ROOT / "scripts" / "fast_lane.py"
FIXTURE_ROOT = Path(__file__).with_name("fixtures") / "mirror"


def load_core():
    spec = importlib.util.spec_from_file_location("fast_lane_core", CORE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class LiveDeltaTests(unittest.TestCase):
    def setUp(self):
        self.core = load_core()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.mirror = Path(self.temp_dir.name) / "mirror"
        shutil.copytree(FIXTURE_ROOT, self.mirror)
        index = self.core.build_index(self.mirror)
        self.local = self.core.resolve_job(index, "Beta Homeowner")
        self.live_same = {
            "jnid": "job-beta",
            "number": "9003",
            "name": "Beta Homeowner",
            "address_line1": "300 Main Street",
            "address_line2": "",
            "city": "Sample City",
            "state_text": "KS",
            "zip": "66103",
            "date_updated": 1788100003,
            "attachment_count": 1,
            "status_name": "Scope Received",
            "Claim #": "SYN-BETA",
        }

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_exact_live_record_with_same_metadata_is_delta_checked(self):
        result = self.core.compare_live_job(self.local, [self.live_same])

        self.assertEqual("DELTA_CHECKED", result["state"])
        self.assertEqual([], result["changed_fields"])
        self.assertTrue(result["snapshot_reusable"])
        self.assertFalse(result["attachment_completeness_proven"])

    def test_attachment_aggregate_change_stops_for_reconciliation(self):
        live = dict(self.live_same, attachment_count=107)

        result = self.core.compare_live_job(self.local, [live])

        self.assertEqual("SOURCE_CHANGED", result["state"])
        self.assertIn("attachment_count", result["changed_fields"])
        self.assertFalse(result["snapshot_reusable"])
        self.assertFalse(result["attachment_completeness_proven"])

    def test_date_update_change_invalidates_even_when_aggregate_is_same(self):
        live = dict(self.live_same, date_updated=1788109999)

        result = self.core.compare_live_job(self.local, [live])

        self.assertEqual("SOURCE_CHANGED", result["state"])
        self.assertEqual(["date_updated"], result["changed_fields"])

    def test_same_name_wrong_job_id_is_identity_conflict(self):
        live = dict(self.live_same, jnid="other-job")

        with self.assertRaises(self.core.IdentityConflictError):
            self.core.compare_live_job(self.local, [live])

    def test_exact_job_id_with_different_address_is_identity_conflict(self):
        live = dict(self.live_same, address_line1="301 Main Street")

        with self.assertRaisesRegex(self.core.IdentityConflictError, "address"):
            self.core.compare_live_job(self.local, [live])

    def test_exact_job_is_selected_from_unrelated_name_matches(self):
        unrelated = dict(self.live_same, jnid="other-job", number="9998")

        result = self.core.compare_live_job(self.local, [unrelated, self.live_same])

        self.assertEqual("job-beta", result["job_id"])

    def test_live_delta_is_persisted_without_touching_source(self):
        self.core.prepare_job(self.local, now="2026-08-30T12:00:00-05:00")
        source_job = Path(self.local["job_source_path"])
        before = source_job.read_bytes()
        delta = self.core.compare_live_job(self.local, [self.live_same])

        state = self.core.record_live_delta(
            self.local,
            delta,
            now="2026-08-30T12:00:30-05:00",
        )

        self.assertEqual("DELTA_CHECKED", state["state"])
        self.assertEqual(before, source_job.read_bytes())
        self.assertEqual("job-beta", state["last_live_delta"]["job_id"])

    def test_live_check_cli_uses_read_only_job_lookup_and_persists_result(self):
        fake_script = Path(self.temp_dir.name) / "fake_jobnimbus.py"
        fake_script.write_text(
            "import json, sys\n"
            "assert sys.argv[1:3] == ['find', 'jobs']\n"
            f"print(json.dumps([{json.dumps(self.live_same)}]))\n",
            encoding="utf-8",
        )

        result = subprocess.run(
            [
                sys.executable,
                str(CLI_PATH),
                "live-check",
                "Beta Homeowner",
                "--mirror-root",
                str(self.mirror),
                "--jobnimbus-script",
                str(fake_script),
            ],
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual("DELTA_CHECKED", payload["state"])
        state_path = (
            Path(self.local["folder_path"])
            / "02 LOCAL WORKING FILES"
            / "00 FAST LANE"
            / "run-state.json"
        )
        self.assertEqual(
            "DELTA_CHECKED",
            json.loads(state_path.read_text(encoding="utf-8"))["state"],
        )


if __name__ == "__main__":
    unittest.main()
