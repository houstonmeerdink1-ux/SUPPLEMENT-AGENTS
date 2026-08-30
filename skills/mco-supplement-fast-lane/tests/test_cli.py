import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
CLI_PATH = SKILL_ROOT / "scripts" / "fast_lane.py"
FIXTURE_ROOT = Path(__file__).with_name("fixtures") / "mirror"


class FastLaneCliTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.mirror = Path(self.temp_dir.name) / "mirror"
        shutil.copytree(FIXTURE_ROOT, self.mirror)

    def tearDown(self):
        self.temp_dir.cleanup()

    def run_cli(self, *arguments):
        return subprocess.run(
            [sys.executable, str(CLI_PATH), *map(str, arguments)],
            text=True,
            capture_output=True,
            check=False,
        )

    def beta_folder(self):
        return self.mirror / "Beta Homeowner - 300 Main Street"

    def source_snapshot(self):
        source = self.beta_folder() / "01 JOBNIMBUS SOURCE"
        return {
            str(path.relative_to(source)): path.read_bytes()
            for path in sorted(source.rglob("*"))
            if path.is_file()
        }

    def write_fake_jobnimbus(self, attachment_count=1):
        live = {
            "jnid": "job-beta",
            "number": "9003",
            "name": "Beta Homeowner",
            "address_line1": "300 Main Street",
            "address_line2": "",
            "city": "Sample City",
            "state_text": "KS",
            "zip": "66103",
            "date_updated": 1788100003,
            "attachment_count": attachment_count,
            "status_name": "Scope Received",
            "Claim #": "SYN-BETA",
        }
        script = Path(self.temp_dir.name) / f"jobnimbus-{attachment_count}.py"
        script.write_text(
            "import json, sys\n"
            "assert sys.argv[1:3] == ['find', 'jobs']\n"
            f"print(json.dumps([{json.dumps(live)}]))\n",
            encoding="utf-8",
        )
        return script

    def write_scope_gap(self):
        scope = {
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
                    "description": "Synthetic supported continuous ceiling work",
                    "quantity": {
                        "value": 120.0,
                        "unit": "SF",
                        "source": "synthetic-measurement#page-1",
                    },
                    "evidence": [
                        {
                            "source_id": "synthetic-photo-1",
                            "source_path": "01 JOBNIMBUS SOURCE/Attachments/Photos/synthetic-photo-1.jpg",
                            "supports": "synthetic ceiling opening",
                        }
                    ],
                    "carrier_credit": {
                        "status": "EXISTING_ALLOWANCE",
                        "line_reference": "carrier-line-12",
                    },
                    "unresolved_questions": [],
                }
            ],
        }
        path = Path(self.temp_dir.name) / "scope-gap.json"
        path.write_text(json.dumps(scope), encoding="utf-8")
        return path

    def test_index_command_writes_generated_root_index(self):
        result = self.run_cli("index", "--mirror-root", self.mirror, "--write")

        self.assertEqual(0, result.returncode, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(3, payload["job_count"])
        self.assertTrue((self.mirror / "_MIRROR CONTROL" / "fast-job-index.json").is_file())

    def test_resolve_command_returns_exact_locked_identity(self):
        result = self.run_cli("resolve", "Beta Homeowner", "--mirror-root", self.mirror)

        self.assertEqual(0, result.returncode, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual("job-beta", payload["job_id"])
        self.assertEqual("300 Main Street, Sample City, KS 66103", payload["exact_address"])

    def test_prepare_command_returns_locked_identity_and_cache_state(self):
        before = self.source_snapshot()

        result = self.run_cli("prepare", "Beta Homeowner", "--mirror-root", self.mirror)

        self.assertEqual(0, result.returncode, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual("job-beta", payload["job_id"])
        self.assertEqual("LOCAL_READY", payload["state"])
        self.assertFalse(payload["cache_hit"])
        self.assertEqual(before, self.source_snapshot())

    def test_ambiguous_cli_result_is_nonzero_and_lists_candidates(self):
        result = self.run_cli("resolve", "Alpha Homeowner", "--mirror-root", self.mirror)

        self.assertEqual(3, result.returncode)
        payload = json.loads(result.stdout)
        self.assertEqual("AMBIGUOUS_IDENTITY", payload["state"])
        self.assertEqual(2, len(payload["candidates"]))

    def test_status_reports_not_prepared_then_current_state(self):
        initial = self.run_cli("status", "Beta Homeowner", "--mirror-root", self.mirror)
        self.assertEqual("NOT_PREPARED", json.loads(initial.stdout)["state"])

        self.run_cli("prepare", "Beta Homeowner", "--mirror-root", self.mirror)
        current = self.run_cli("status", "Beta Homeowner", "--mirror-root", self.mirror)

        self.assertEqual(0, current.returncode, current.stderr)
        self.assertEqual("LOCAL_READY", json.loads(current.stdout)["state"])

    def test_changed_live_metadata_is_a_visible_pause(self):
        script = self.write_fake_jobnimbus(attachment_count=9)

        result = self.run_cli(
            "live-check",
            "Beta Homeowner",
            "--mirror-root",
            self.mirror,
            "--jobnimbus-script",
            script,
        )

        self.assertEqual(4, result.returncode)
        payload = json.loads(result.stdout)
        self.assertEqual("SOURCE_CHANGED", payload["state"])
        self.assertEqual(["attachment_count"], payload["changed_fields"])

    def test_scope_audit_and_approval_commands_reach_pricing_ready_in_order(self):
        script = self.write_fake_jobnimbus()
        scope_gap = self.write_scope_gap()
        live = self.run_cli(
            "live-check",
            "Beta Homeowner",
            "--mirror-root",
            self.mirror,
            "--jobnimbus-script",
            script,
        )
        self.assertEqual(0, live.returncode, live.stderr)

        audited = self.run_cli(
            "mark-audited",
            "Beta Homeowner",
            "--mirror-root",
            self.mirror,
            "--scope-gap",
            scope_gap,
        )
        self.assertEqual(0, audited.returncode, audited.stderr)
        self.assertEqual("SCOPE_AUDITED", json.loads(audited.stdout)["state"])

        approved = self.run_cli(
            "approve-scope",
            "Beta Homeowner",
            "--mirror-root",
            self.mirror,
            "--scope-gap",
            scope_gap,
            "--approved-by",
            "Houston",
            "--approved-at",
            "2026-08-30T12:30:00-05:00",
            "--baseline-code",
            "SYNKC1_JAN26",
            "--baseline-month",
            "2026-01",
            "--target-code",
            "SYNKC1_AUG26",
            "--target-month",
            "2026-08",
        )

        self.assertEqual(0, approved.returncode, approved.stderr)
        self.assertEqual("PRICING_READY", json.loads(approved.stdout)["state"])
        manifest = (
            self.beta_folder()
            / "02 LOCAL WORKING FILES"
            / "00 FAST LANE"
            / "xactimate-entry-manifest.json"
        )
        self.assertTrue(manifest.is_file())


if __name__ == "__main__":
    unittest.main()
