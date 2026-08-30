import csv
import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = SKILL_ROOT / "scripts" / "fast_lane_core.py"
FIXTURE_ROOT = Path(__file__).with_name("fixtures") / "mirror"


def load_core():
    spec = importlib.util.spec_from_file_location("fast_lane_core", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class IdentityResolverTests(unittest.TestCase):
    def setUp(self):
        self.core = load_core()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.mirror = Path(self.temp_dir.name) / "mirror"
        shutil.copytree(FIXTURE_ROOT, self.mirror)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_unique_full_name_resolves_to_exact_locked_identity(self):
        index = self.core.build_index(self.mirror)

        job = self.core.resolve_job(index, "Beta Homeowner")

        self.assertEqual("job-beta", job["job_id"])
        self.assertEqual("contact-beta", job["contact_id"])
        self.assertEqual("9003", job["job_number"])
        self.assertEqual("300 Main Street, Sample City, KS 66103", job["exact_address"])
        self.assertEqual("66103", job["zip"])
        self.assertTrue(job["pricing_identity_ready"])

    def test_duplicate_name_refuses_to_guess_and_returns_both_candidates(self):
        index = self.core.build_index(self.mirror)

        with self.assertRaises(self.core.AmbiguousIdentityError) as caught:
            self.core.resolve_job(index, "Alpha Homeowner")

        self.assertEqual(
            {"job-alpha-100", "job-alpha-200"},
            {candidate["job_id"] for candidate in caught.exception.candidates},
        )

    def test_short_unique_name_can_resolve_only_when_one_candidate_survives(self):
        index = self.core.build_index(self.mirror)

        job = self.core.resolve_job(index, "Beta")

        self.assertEqual("job-beta", job["job_id"])

    def test_roster_and_source_job_number_conflict_fails_closed(self):
        job_path = (
            self.mirror
            / "Beta Homeowner - 300 Main Street"
            / "01 JOBNIMBUS SOURCE"
            / "Record"
            / "jobnimbus-job.json"
        )
        payload = json.loads(job_path.read_text(encoding="utf-8"))
        payload["number"] = "9903"
        job_path.write_text(json.dumps(payload), encoding="utf-8")

        with self.assertRaisesRegex(self.core.IdentityConflictError, "9003"):
            self.core.build_index(self.mirror)

    def test_missing_mirror_root_fails_before_search(self):
        missing = Path(self.temp_dir.name) / "not-mounted"

        with self.assertRaises(self.core.DriveUnavailableError):
            self.core.build_index(missing)

    def test_excluded_roster_row_is_not_indexed(self):
        index = self.core.build_index(self.mirror)

        self.assertNotIn("9999", {job["job_number"] for job in index["jobs"]})

    def test_write_index_writes_only_generated_root_control_files(self):
        index = self.core.build_index(self.mirror)

        output = self.core.write_index(index, self.mirror)

        self.assertEqual(
            self.mirror / "_MIRROR CONTROL" / "fast-job-index.json",
            output,
        )
        self.assertEqual(index, json.loads(output.read_text(encoding="utf-8")))
        state_path = output.with_name("fast-job-index-state.json")
        self.assertTrue(state_path.is_file())
        self.assertFalse(any((self.mirror / "Beta Homeowner - 300 Main Street" / "01 JOBNIMBUS SOURCE").glob("fast-*")))

    def test_missing_zip_keeps_identity_but_blocks_pricing_readiness(self):
        job_path = (
            self.mirror
            / "Beta Homeowner - 300 Main Street"
            / "01 JOBNIMBUS SOURCE"
            / "Record"
            / "jobnimbus-job.json"
        )
        contact_path = job_path.with_name("jobnimbus-contact.json")
        for path in (job_path, contact_path):
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["zip"] = ""
            path.write_text(json.dumps(payload), encoding="utf-8")
        roster_path = self.mirror / "_MIRROR CONTROL" / "approved-jobs.csv"
        rows = list(csv.DictReader(roster_path.read_text(encoding="utf-8").splitlines()))
        for row in rows:
            if row["job_number"] == "9003":
                row["exact_address"] = "300 Main Street, Sample City, KS"
        with roster_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)

        index = self.core.build_index(self.mirror)
        job = self.core.resolve_job(index, "Beta Homeowner")

        self.assertFalse(job["pricing_identity_ready"])
        self.assertEqual("", job["zip"])

    def test_five_digit_street_number_is_not_mistaken_for_roster_zip(self):
        roster_path = self.mirror / "_MIRROR CONTROL" / "approved-jobs.csv"
        rows = list(csv.DictReader(roster_path.read_text(encoding="utf-8").splitlines()))
        for row in rows:
            if row["job_number"] == "9003":
                row["exact_address"] = "12345 Main Street, Sample City, KS 66103"
        with roster_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)

        job_path = (
            self.mirror
            / "Beta Homeowner - 300 Main Street"
            / "01 JOBNIMBUS SOURCE"
            / "Record"
            / "jobnimbus-job.json"
        )
        contact_path = job_path.with_name("jobnimbus-contact.json")
        for path in (job_path, contact_path):
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["address_line1"] = "12345 Main Street"
            path.write_text(json.dumps(payload), encoding="utf-8")

        index = self.core.build_index(self.mirror)
        job = self.core.resolve_job(index, "Beta Homeowner")

        self.assertEqual("66103", job["zip"])
        self.assertEqual("12345 Main Street, Sample City, KS 66103", job["exact_address"])


if __name__ == "__main__":
    unittest.main()
