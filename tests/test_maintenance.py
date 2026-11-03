"""Behavioral tests for local/public merges and release packaging."""
import copy
import json
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

from scripts import maintain as publisher


class PublisherTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="battery-publisher-test-")
        self.directory = Path(self.temporary.name)

    def tearDown(self):
        # Git object files are read-only on Windows; Python 3.7's
        # TemporaryDirectory does not retry them automatically.
        owned = self.directory.resolve()
        if owned.parent != Path(tempfile.gettempdir()).resolve() or not owned.name.startswith("battery-publisher-test-"):
            raise RuntimeError("Unexpected test cleanup target")
        for path in owned.rglob("*"):
            path.resolve().relative_to(owned)
            if path.is_file() and not path.is_symlink():
                path.chmod(stat.S_IREAD | stat.S_IWRITE)
        self.temporary.cleanup()

    def minimal_files(self):
        return {
            "SKILL.md": b"---\nname: battery-origin-plotting\ndescription: Native Origin battery plots.\n---\n\nDraw supplied values.\n",
            "package.json": b'{"version":"1.0.1"}\n',
            "package-lock.json": b'{"version":"1.0.1","packages":{"":{"version":"1.0.1"}}}\n',
            "references/capability-status.md": b"Public version v1.0.1.\n",
            "plotting_core/example.py": b"value = 1\n",
            ".gitignore": b"dist/\n",
        }

    def create_repo(self, files=None):
        repo = self.directory / "public"
        repo.mkdir()
        publisher.git(repo, "init", "-b", "main")
        publisher.git(repo, "config", "user.name", "Fixture Maintainer")
        publisher.git(repo, "config", "user.email", "fixture@example.invalid")
        publisher.git(repo, "config", "core.autocrlf", "false")
        for name, data in (files or self.minimal_files()).items():
            path = repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        publisher.git(repo, "add", "--all")
        publisher.git(repo, "commit", "-m", "Fixture")
        return repo

    def test_merge_preserves_public_redaction_and_separate_code_change(self):
        base = ("private reference\n" + "".join("line %d\n" % index for index in range(20)) + "old behavior\n").encode()
        public = base.replace(b"private reference", b"public instructions")
        incoming = base.replace(b"old behavior", b"new behavior")
        merged = publisher.plan_sync({"code.py": public}, {"code.py": base}, {"code.py": incoming})
        self.assertIn(b"public instructions", merged["code.py"])
        self.assertIn(b"new behavior", merged["code.py"])
        self.assertNotIn(b"private reference", merged["code.py"])

    def test_overlapping_changes_stop_without_mutating_inputs(self):
        public = {"code.py": b"value = 2\n"}
        with self.assertRaises(publisher.PublishingError):
            publisher.plan_sync(public, {"code.py": b"value = 1\n"}, {"code.py": b"value = 3\n"})
        self.assertEqual(public["code.py"], b"value = 2\n")

    def test_local_deletion_does_not_remove_a_public_edit(self):
        with self.assertRaises(publisher.PublishingError):
            publisher.plan_sync({"code.py": b"public = True\n"}, {"code.py": b"local = True\n"}, {})

    def test_new_local_file_cannot_overwrite_public_helper(self):
        with self.assertRaises(publisher.PublishingError):
            publisher.plan_sync({"helper.py": b"public = True\n"}, {}, {"helper.py": b"local = True\n"})

    def test_unchanged_local_file_preserves_later_public_fixes(self):
        result = publisher.plan_sync({"code.py": b"public fix\n"}, {"code.py": b"old local\n"}, {"code.py": b"old local\n"})
        self.assertEqual(result["code.py"], b"public fix\n")

    def test_private_paths_are_reported_without_echoing_the_value(self):
        private = "C:" + chr(92) + "Users" + chr(92) + "FixtureUser" + chr(92) + "data"
        issues = publisher.scan_files({"notes.md": private.encode()})
        self.assertTrue(any("personal absolute path" in issue for issue in issues))
        self.assertTrue(all("FixtureUser" not in issue for issue in issues))

    def test_credentials_and_private_projects_are_rejected(self):
        credential = "gh" + "p_" + "a" * 36
        issues = publisher.scan_files({"notes.md": credential.encode(), "reference.opju": b"private"})
        self.assertTrue(any("credential" in issue for issue in issues))
        self.assertTrue(any("binary" in issue for issue in issues))

    def test_source_snapshot_excludes_experiment_and_local_helpers(self):
        source = self.directory / "source"
        (source / "references" / "origin reference").mkdir(parents=True)
        (source / "examples").mkdir()
        (source / "scripts").mkdir()
        (source / "SKILL.md").write_text("skill", encoding="utf-8")
        (source / "references" / "origin reference" / "source.opju").write_bytes(b"private")
        (source / "examples" / "real.xlsx").write_bytes(b"private")
        (source / "scripts" / "publish_public.ps1").write_text("local wrapper", encoding="utf-8")
        (source / "scripts" / "useful.py").write_text("value = 1\n", encoding="utf-8")
        _, files = publisher.source_snapshot(source)
        self.assertEqual(set(files), {"SKILL.md", "scripts/useful.py"})

    def test_version_update_keeps_manifest_lock_and_notes_consistent(self):
        files = publisher.version_files(self.minimal_files(), "1.1.0", "Add repeatable local synchronization and checked release packaging.")
        self.assertEqual(json.loads(files["package.json"])["version"], "1.1.0")
        self.assertEqual(json.loads(files["package-lock.json"])["packages"][""]["version"], "1.1.0")
        self.assertIn(b"v1.1.0", files["references/capability-status.md"])
        self.assertIn("releases/v1.1.0.md", files)

    def test_same_lower_and_malformed_versions_are_rejected(self):
        for version in ("1.0.1", "1.0.0", "01.1.0", "v1.1.0", "1.1.0;echo", "1.1.0-rc1"):
            with self.subTest(version=version), self.assertRaises(publisher.PublishingError):
                publisher.version_files(self.minimal_files(), version, "These notes describe a reviewed change.")

    def test_dry_run_is_read_only_and_real_sync_advances_baseline(self):
        repo = self.create_repo()
        source = self.directory / "source"
        (source / "plotting_core").mkdir(parents=True)
        (source / "SKILL.md").write_bytes(self.minimal_files()["SKILL.md"])
        example = source / "plotting_core" / "example.py"
        example.write_bytes(b"value = 1\n")
        source, files = publisher.source_snapshot(source)
        initial_commit = publisher.git(repo, "rev-parse", "HEAD").stdout.decode().strip()
        publisher.save_baseline(repo, source, files, initial_commit)
        state_before = publisher.state_file(repo).read_bytes()
        example.write_bytes(b"value = 3\n")
        original_validator = publisher.validate_files
        with patch.object(publisher, "validate_files", side_effect=lambda candidate: original_validator(candidate, tests=False)):
            changed = publisher.sync(repo, source, dry_run=True)
            self.assertEqual(changed, ["plotting_core/example.py"])
            self.assertEqual(publisher.state_file(repo).read_bytes(), state_before)
            self.assertEqual((repo / "plotting_core" / "example.py").read_bytes(), b"value = 1\n")
            publisher.sync(repo, source)
            self.assertEqual((repo / "plotting_core" / "example.py").read_bytes(), b"value = 3\n")
            self.assertFalse(publisher.git(repo, "status", "--porcelain").stdout)
            self.assertEqual(publisher.sync(repo, source, dry_run=True), [])

    def test_build_excludes_private_baseline_and_checks_tag_version(self):
        files = publisher.version_files(self.minimal_files(), "1.1.0", "Add repeatable local synchronization and checked release packaging.")
        repo = self.create_repo(files)
        publisher.save_baseline(repo, self.directory / "personal-source", {"SKILL.md": b"private source"}, "fixture")
        destination = repo / "dist"
        with self.assertRaises(publisher.PublishingError):
            publisher.build(repo, "1.0.1", destination)
        publisher.build(repo, "1.1.0", destination)
        with ZipFile(str(destination / "battery-origin-plotting-v1.1.0.zip")) as archive:
            self.assertFalse(any("/.git/" in name or "baseline.json" in name for name in archive.namelist()))
            self.assertEqual(archive.read("battery-origin-plotting/package.json"), files["package.json"])
        self.assertTrue((destination / "SHA256SUMS.txt").is_file())

    def test_release_preview_has_no_network_commits_tags_or_baseline_changes(self):
        repo = self.create_repo()
        source = self.directory / "source"
        (source / "plotting_core").mkdir(parents=True)
        (source / "SKILL.md").write_bytes(self.minimal_files()["SKILL.md"])
        example = source / "plotting_core" / "example.py"
        example.write_bytes(b"value = 1\n")
        source, files = publisher.source_snapshot(source)
        commit = publisher.git(repo, "rev-parse", "HEAD").stdout
        publisher.save_baseline(repo, source, files, commit.decode().strip())
        baseline = publisher.state_file(repo).read_bytes()
        example.write_bytes(b"value = 3\n")
        notes = self.directory / "notes.md"
        notes.write_text("Add reviewed local updates and an offline release preview.", encoding="utf-8")
        original_validator, original_runner = publisher.validate_files, publisher.run

        def local_only(args, *values, **options):
            if args[0] == "gh" or (args[0] == "git" and args[1] in {"push", "fetch", "ls-remote"}):
                raise AssertionError("Preview attempted network access")
            return original_runner(args, *values, **options)

        with patch.object(publisher, "validate_files", side_effect=lambda candidate: original_validator(candidate, tests=False)), patch.object(publisher, "run", side_effect=local_only):
            report = publisher.preview_release(repo, source, "1.1.0", notes)
        self.assertFalse(report["pushed"])
        self.assertEqual(publisher.git(repo, "rev-parse", "HEAD").stdout, commit)
        self.assertFalse(publisher.git(repo, "tag", "-l").stdout)
        self.assertFalse(publisher.git(repo, "status", "--porcelain").stdout)
        self.assertEqual(publisher.state_file(repo).read_bytes(), baseline)
        self.assertEqual((repo / "plotting_core" / "example.py").read_bytes(), b"value = 1\n")
        with ZipFile(report["archive"]) as bundle:
            self.assertEqual(bundle.read("battery-origin-plotting/plotting_core/example.py"), b"value = 3\n")
            self.assertEqual(json.loads(bundle.read("battery-origin-plotting/package.json"))["version"], "1.1.0")


if __name__ == "__main__":
    unittest.main()
