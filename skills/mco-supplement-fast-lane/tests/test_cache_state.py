import hashlib
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


def tree_snapshot(root: Path):
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


class CacheAndStateTests(unittest.TestCase):
    def setUp(self):
        self.core = load_core()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.mirror = Path(self.temp_dir.name) / "mirror"
        shutil.copytree(FIXTURE_ROOT, self.mirror)
        self.index = self.core.build_index(self.mirror)
        self.beta = self.core.resolve_job(self.index, "Beta Homeowner")

    def tearDown(self):
        self.temp_dir.cleanup()

    def fast_lane_dir(self, job):
        return Path(job["folder_path"]) / "02 LOCAL WORKING FILES" / "00 FAST LANE"

    def test_prepare_never_changes_source_tree(self):
        source_root = Path(self.beta["folder_path"]) / "01 JOBNIMBUS SOURCE"
        before = tree_snapshot(source_root)

        result = self.core.prepare_job(self.beta, now="2026-08-30T12:00:00-05:00")

        self.assertEqual(before, tree_snapshot(source_root))
        self.assertEqual("LOCAL_READY", result["state"])
        self.assertFalse(result["cache_hit"])
        generated = self.fast_lane_dir(self.beta)
        self.assertTrue((generated / "job-context.json").is_file())
        self.assertTrue((generated / "source-fingerprint.json").is_file())
        self.assertTrue((generated / "run-state.json").is_file())

    def test_api_only_verification_stops_as_source_incomplete(self):
        alpha_200 = next(
            job for job in self.index["jobs"] if job["job_id"] == "job-alpha-200"
        )

        result = self.core.prepare_job(alpha_200, now="2026-08-30T12:00:00-05:00")

        self.assertEqual("SOURCE_INCOMPLETE", result["state"])
        self.assertIn("mirror verification is incomplete", result["blockers"])

    def test_unchanged_fingerprint_is_cache_hit_and_preserves_analysis(self):
        self.core.prepare_job(self.beta, now="2026-08-30T12:00:00-05:00")
        scope_gap = self.fast_lane_dir(self.beta) / "scope-gap.json"
        scope_gap.write_text('{"marker":"keep-me"}\n', encoding="utf-8")

        second = self.core.prepare_job(self.beta, now="2026-08-30T12:01:00-05:00")

        self.assertTrue(second["cache_hit"])
        self.assertEqual("LOCAL_READY", second["state"])
        self.assertEqual(
            "keep-me",
            json.loads(scope_gap.read_text(encoding="utf-8"))["marker"],
        )

    def test_changed_manifest_invalidates_state_without_deleting_analysis(self):
        self.core.prepare_job(self.beta, now="2026-08-30T12:00:00-05:00")
        scope_gap = self.fast_lane_dir(self.beta) / "scope-gap.json"
        scope_gap.write_text('{"marker":"stale-but-preserved"}\n', encoding="utf-8")
        manifest = Path(self.beta["source_manifest_path"])
        with manifest.open("a", encoding="utf-8") as handle:
            handle.write(
                'document,Synthetic JobNimbus,new-doc,New document,"01 JOBNIMBUS SOURCE/Attachments/new.pdf",2026-08-30T12:00:30-0500,10,7777777777777777777777777777777777777777777777777777777777777777,PDF,VERIFIED,synthetic change\n'
            )

        result = self.core.prepare_job(self.beta, now="2026-08-30T12:01:00-05:00")

        self.assertEqual("SOURCE_CHANGED", result["state"])
        self.assertFalse(result["cache_hit"])
        self.assertTrue(scope_gap.is_file())
        self.assertIn("scope-gap.json", result["stale_artifacts"])

    def test_fingerprint_names_each_authoritative_input(self):
        fingerprint = self.core.fingerprint_job(self.beta)

        self.assertEqual(
            {"job_source", "contact_source", "source_manifest", "verification"},
            set(fingerprint["inputs"]),
        )
        self.assertRegex(fingerprint["source_fingerprint"], r"^[0-9a-f]{64}$")

    def test_invalid_state_transition_fails_closed(self):
        state = {"state": "LOCAL_READY", "history": []}

        with self.assertRaises(self.core.StateTransitionError):
            self.core.transition_state(
                state,
                "PRICING_READY",
                reason="skip audit and approval",
                now="2026-08-30T12:00:00-05:00",
            )

    def test_valid_state_transition_records_reason_and_history(self):
        state = {"state": "LOCAL_READY", "history": []}

        moved = self.core.transition_state(
            state,
            "DELTA_CHECKED",
            reason="exact live metadata matched",
            now="2026-08-30T12:00:00-05:00",
        )

        self.assertEqual("DELTA_CHECKED", moved["state"])
        self.assertEqual("exact live metadata matched", moved["history"][-1]["reason"])
        self.assertEqual("LOCAL_READY", moved["history"][-1]["from"])


if __name__ == "__main__":
    unittest.main()
