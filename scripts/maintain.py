"""Maintain the public skill: review local changes, sync, tag and build releases.

Private source snapshots stay under .git/skill-publisher; they are never archived.
Python 3.7 compatible. Every subprocess receives argument arrays, never shell text.
"""
import argparse
import ast
import base64
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NAME = "battery-origin-plotting"
REPOSITORY = "shengf314/" + NAME
SOURCE_DIRS = ("plotting_core", "references", "templates", "scripts", "examples")
SOURCE_ROOT_FILES = ("SKILL.md", "requirements.txt")
LOCAL_ONLY = {"scripts/publish_public.ps1", "references/publication-workflow.md"}
TEXT_SUFFIXES = {".py", ".md", ".yaml", ".yml", ".json", ".cjs", ".ps1", ".txt"}
VERSION = re.compile(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)")
PRIVATE_PATH = re.compile(
    r"(?i)(?:\b[A-Z]:[\\/]+Users[\\/]+[^\s\\/\"<>]+|"
    r"\b[A-Z]:[\\/]+(?:AA[^\s\"<>]*|[^\s\"<>]*(?:博士|毕设)[^\s\"<>]*)|"
    r"/(?:home|Users)/[A-Za-z0-9_.-]+/)")
SECRETS = re.compile(
    r"(?:gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,}|"
    r"sk-(?:proj-)?[A-Za-z0-9_-]{24,}|"
    r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)")


class PublishingError(RuntimeError):
    pass


def run(args, cwd=ROOT, check=True):
    completed = subprocess.run([str(arg) for arg in args], cwd=str(cwd),
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if check and completed.returncode:
        raise PublishingError("%s failed:\n%s" % (
            args[0], completed.stderr.decode("utf-8", "replace").strip()))
    return completed


def git(repo, *args, **kwargs):
    return run(["git"] + list(args), cwd=repo, **kwargs)


def canonical(data):
    return data.decode("utf-8-sig").replace("\r\n", "\n").encode("utf-8")


def source_default():
    codex_root = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
    return codex_root / "skills" / NAME


def source_snapshot(source):
    source = Path(source).expanduser().resolve()
    if not (source / "SKILL.md").is_file():
        raise PublishingError("Source must be the installed skill folder")
    paths = [source / name for name in SOURCE_ROOT_FILES]
    for directory in SOURCE_DIRS:
        paths.extend((source / directory).rglob("*"))
    files = {}
    for path in paths:
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(source).as_posix()
        if relative in LOCAL_ONLY or any(
                part in {"__pycache__", ".tmp", "node_modules", ".git", ".venv", "origin reference"}
                for part in path.relative_to(source).parts):
            continue
        if path.suffix not in TEXT_SUFFIXES:
            continue  # Binary workbooks/projects and experimental data are public-managed.
        files[relative] = canonical(path.read_bytes())
    return source, files


def tracked_files(repo):
    names = git(repo, "ls-files", "-z").stdout.decode("utf-8").split("\0")
    files = {}
    for name in filter(None, names):
        target = Path(repo) / name
        if target.is_symlink():
            raise PublishingError("Public package cannot include symlinks: " + name)
        if not target.is_file():
            raise PublishingError("Tracked file is missing: " + name)
        files[name] = target.read_bytes()
    return files


def scan_files(files):
    issues = []
    for name, data in files.items():
        parts = Path(name).parts
        if (any(part in {".git", "node_modules", "__pycache__", ".venv", "origin reference"} for part in parts)
                or name.endswith((".opju", ".db", ".sqlite", ".pyc"))
                or Path(name).name.startswith(".env")
                or (name.endswith(".xlsx") and name != "examples/rate_input_example.xlsx")):
            issues.append(name + ": private/generated/binary file is outside the public package")
        if Path(name).suffix not in TEXT_SUFFIXES and Path(name).name not in {
                "LICENSE", ".gitignore", ".gitattributes"}:
            continue
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            issues.append(name + ": expected UTF-8 text")
            continue
        for index, line in enumerate(text.splitlines(), 1):
            if PRIVATE_PATH.search(line):
                issues.append("%s:%d: personal absolute path" % (name, index))
            if SECRETS.search(line):
                issues.append("%s:%d: credential/private-key pattern" % (name, index))
            if re.match(r"^(<<<<<<< |=======\s*$|>>>>>>> )", line):
                issues.append("%s:%d: unresolved merge marker" % (name, index))
        if name.endswith(".py"):
            try:
                ast.parse(text, filename=name)
            except SyntaxError as error:
                issues.append("%s:%s: Python syntax error" % (name, error.lineno))
        if name.endswith(".md"):
            for target in re.findall(r"\]\(([^)]+)\)", text):
                if "://" in target or target.startswith("#"):
                    continue
                target = target.split("#", 1)[0]
                resolved = (Path(name).parent / target).as_posix()
                # Normalize ../ without depending on the current working directory.
                normalized = os.path.normpath(resolved).replace("\\", "/")
                if normalized not in files and not any(
                        entry.startswith(normalized.rstrip("/") + "/") for entry in files):
                    issues.append(name + ": missing local link: " + target)
    return issues


def validate_files(files, tests=True):
    import yaml
    issues = scan_files(files)
    try:
        text = files["SKILL.md"].decode("utf-8-sig")
        metadata = yaml.safe_load(text.split("---", 2)[1]) if text.startswith("---") else {}
        if metadata.get("name") != NAME or not metadata.get("description"):
            issues.append("SKILL.md: name/description missing or incorrect")
        version = json.loads(files["package.json"].decode("utf-8"))["version"]
        lock = json.loads(files["package-lock.json"].decode("utf-8"))
        if not VERSION.fullmatch(version) or lock["version"] != version or lock["packages"][""]["version"] != version:
            issues.append("Package and lock versions must agree on an X.Y.Z version")
    except (KeyError, ValueError, IndexError, AttributeError) as error:
        issues.append("Invalid skill/package metadata: " + str(error))
    if issues:
        raise PublishingError("\n".join(issues))
    if tests:
        with tempfile.TemporaryDirectory(prefix="battery-public-check-") as temporary:
            checkout = Path(temporary) / NAME
            checkout.mkdir()
            for name, data in files.items():
                destination = checkout / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(data)
            result = run([sys.executable, "-X", "utf8", "-m", "unittest",
                          "discover", "-s", "tests", "-v"], cwd=checkout, check=False)
            if result.returncode:
                raise PublishingError("Prospective package tests failed:\n" +
                                      result.stderr.decode("utf-8", "replace"))
            print(result.stderr.decode("utf-8", "replace").strip())


def assert_clean(repo):
    if git(repo, "status", "--porcelain").stdout:
        raise PublishingError("Public checkout has uncommitted files; review and commit them first")
    if git(repo, "branch", "--show-current").stdout.decode().strip() != "main":
        raise PublishingError("Maintenance commands must run on main")


def assert_remote(repo):
    remote = git(repo, "remote", "get-url", "origin").stdout.decode().strip()
    accepted = {"https://github.com/" + REPOSITORY + ".git",
                "https://github.com/" + REPOSITORY,
                "git@github.com:" + REPOSITORY + ".git"}
    if remote not in accepted:
        raise PublishingError("origin must point to the configured public repository")


def refresh(repo):
    assert_remote(repo)
    git(repo, "fetch", "origin", "main", "--tags")
    git(repo, "merge", "--ff-only", "origin/main")


def state_file(repo):
    value = git(repo, "rev-parse", "--git-path", "skill-publisher/baseline.json").stdout.decode().strip()
    path = Path(value)
    return path if path.is_absolute() else Path(repo) / path


def record_baseline(repo, source, reviewed_commit):
    assert_clean(repo)
    current = git(repo, "rev-parse", "HEAD").stdout.decode().strip()
    if git(repo, "rev-parse", reviewed_commit).stdout.decode().strip() != current:
        raise PublishingError("Reviewed commit must be the current HEAD")
    validate_files(tracked_files(repo))
    source, files = source_snapshot(source)
    save_baseline(repo, source, files, current)
    print("Recorded private source baseline for reviewed commit " + current[:12])


def save_baseline(repo, source, files, commit):
    state = state_file(repo)
    state.parent.mkdir(parents=True, exist_ok=True)
    document = {"schema_version": 1, "source": str(source), "reviewed_commit": commit,
                "files": {name: base64.b64encode(data).decode("ascii") for name, data in files.items()}}
    temporary = state.with_suffix(".tmp")
    temporary.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(str(temporary), str(state))


def merge_text(name, public, previous, incoming):
    with tempfile.TemporaryDirectory(prefix="battery-public-merge-") as temporary:
        paths = [Path(temporary) / value for value in ("public", "previous-local", "new-local")]
        for path, content in zip(paths, (public, previous, incoming)):
            path.write_bytes(content)
        result = run(["git", "merge-file", "-p", "-L", "public", "-L", "previous-local",
                      "-L", "new-local"] + paths, check=False)
        if result.returncode:
            raise PublishingError(name + ": local/public changes overlap; port this change manually")
        return result.stdout


def plan_sync(public, previous, incoming):
    updated = dict(public)
    conflicts = []
    for name in sorted(set(previous) | set(incoming)):
        before, after = previous.get(name), incoming.get(name)
        if before == after:
            continue
        existing = public.get(name)
        if after is None:
            # Public edits must not be silently deleted with a local source file.
            if existing is not None and canonical(existing) != before:
                conflicts.append(name + ": local deletion conflicts with public edits")
            else:
                updated.pop(name, None)
        elif before is None:
            if existing is not None and canonical(existing) != after:
                conflicts.append(name + ": new local file collides with a public-managed file")
            else:
                updated[name] = after
        elif existing is None:
            conflicts.append(name + ": locally modified file was removed from the public package")
        else:
            try:
                updated[name] = merge_text(name, canonical(existing), before, after)
            except PublishingError as error:
                conflicts.append(str(error))
    if conflicts:
        raise PublishingError("\n".join(conflicts))
    return updated


def write_changes(repo, before, after):
    changed = []
    for name in sorted(set(before) | set(after)):
        if before.get(name) == after.get(name):
            continue
        target = Path(repo) / name
        target.resolve().relative_to(Path(repo).resolve())
        if name not in after:
            target.unlink()
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(after[name])
        changed.append(name)
    if changed:
        git(repo, "add", "--", *changed)
        git(repo, "diff", "--cached", "--check")
    return changed


def sync(repo, source, dry_run=False, push=False, message=None):
    assert_clean(repo)
    if push and not dry_run:
        refresh(repo)
    state = state_file(repo)
    if not state.is_file():
        raise PublishingError("No source baseline. Read references/maintenance.md before initializing")
    document = json.loads(state.read_text(encoding="utf-8"))
    source, incoming = source_snapshot(source)
    if Path(document["source"]).resolve() != source:
        raise PublishingError("Source differs from the private baseline; do not reuse another source snapshot")
    previous = {name: base64.b64decode(value) for name, value in document["files"].items()}
    before = tracked_files(repo)
    after = plan_sync(before, previous, incoming)
    changed = [name for name in sorted(set(before) | set(after)) if before.get(name) != after.get(name)]
    print(json.dumps({"mode": "preview" if dry_run else "sync", "changed_files": changed}, ensure_ascii=False))
    validate_files(after)
    if dry_run:
        return changed
    if changed:
        write_changes(repo, before, after)
        git(repo, "commit", "-m", message or "Sync reviewed local skill changes")
    commit = git(repo, "rev-parse", "HEAD").stdout.decode().strip()
    save_baseline(repo, source, incoming, commit)
    if push:
        assert_remote(repo)
        git(repo, "push", "origin", "HEAD:refs/heads/main")
    return changed


def version_tuple(value):
    if not VERSION.fullmatch(value):
        raise PublishingError("Version must be X.Y.Z without a leading v or prerelease suffix")
    return tuple(int(part) for part in value.split("."))


def version_files(files, version, notes):
    old = json.loads(files["package.json"].decode("utf-8"))["version"]
    if version_tuple(version) <= version_tuple(old):
        raise PublishingError("New version must be greater than " + old)
    if len(notes.strip()) < 20:
        raise PublishingError("Provide a concrete release note of at least 20 characters")
    updated = dict(files)
    for name in ("package.json", "package-lock.json"):
        value = json.loads(files[name].decode("utf-8"))
        value["version"] = version
        if name == "package-lock.json":
            value["packages"][""]["version"] = version
        updated[name] = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    name = "references/capability-status.md"
    text = files[name].decode("utf-8").replace("v" + old, "v" + version)
    updated[name] = text.encode("utf-8")
    updated["releases/v" + version + ".md"] = (notes.strip() + "\n").encode("utf-8")
    return updated


def release(repo, source, version, notes_file):
    # Validate notes/version before syncing or making any remote changes.
    notes = Path(notes_file).read_text(encoding="utf-8-sig")
    validate_files(version_files(tracked_files(repo), version, notes), tests=False)
    sync(repo, source, push=True)
    tag = "v" + version
    if git(repo, "show-ref", "--verify", "refs/tags/" + tag, check=False).returncode == 0:
        raise PublishingError("Local tag already exists; inspect/retry its push without replacing it")
    if git(repo, "ls-remote", "--tags", "origin", "refs/tags/" + tag).stdout:
        raise PublishingError("Remote tag already exists; choose a new version")
    before = tracked_files(repo)
    after = version_files(before, version, notes)
    validate_files(after)
    write_changes(repo, before, after)
    git(repo, "commit", "-m", "Release " + tag)
    git(repo, "push", "origin", "HEAD:refs/heads/main")
    git(repo, "tag", "-a", tag, "-m", "Release " + tag)
    git(repo, "push", "origin", "refs/tags/" + tag)
    print("Tag pushed. GitHub tests and publishes: https://github.com/" +
          REPOSITORY + "/actions/workflows/release.yml")


def build(repo, version, output):
    version_tuple(version)
    assert_clean_for_build = git(repo, "status", "--porcelain").stdout
    if assert_clean_for_build:
        raise PublishingError("Build requires a clean checkout")
    files = tracked_files(repo)
    validate_files(files, tests=False)  # CI's required reusable workflow runs tests first.
    if json.loads(files["package.json"].decode())["version"] != version:
        raise PublishingError("Tag and package version do not agree")
    notes = "releases/v" + version + ".md"
    if notes not in files:
        raise PublishingError("Release notes are missing: " + notes)
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    archive = output / (NAME + "-v" + version + ".zip")
    git(repo, "archive", "--format=zip", "--prefix=" + NAME + "/",
        "--output=" + str(archive), "HEAD")
    checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
    (output / "SHA256SUMS.txt").write_bytes((checksum + "  " + archive.name + "\n").encode("ascii"))
    print(json.dumps({"archive": archive.name, "sha256": checksum}))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check", help="scan the public tracked package and run offline tests")
    baseline = sub.add_parser("record-baseline", help="record an already-reviewed local/public correspondence")
    baseline.add_argument("--source", type=Path, default=source_default())
    baseline.add_argument("--reviewed-commit", required=True)
    sync_parser = sub.add_parser("sync", help="three-way merge changed local files into the public package")
    sync_parser.add_argument("--source", type=Path, default=source_default())
    sync_parser.add_argument("--dry-run", action="store_true")
    sync_parser.add_argument("--push", action="store_true")
    sync_parser.add_argument("--message")
    release_parser = sub.add_parser("release", help="sync, bump versions, commit and push a new release tag")
    release_parser.add_argument("--source", type=Path, default=source_default())
    release_parser.add_argument("--version", required=True)
    release_parser.add_argument("--notes-file", type=Path, required=True)
    build_parser = sub.add_parser("build", help="build a clean, checked, versioned release archive")
    build_parser.add_argument("--version", required=True)
    build_parser.add_argument("--output-dir", type=Path, default=ROOT / "dist")
    args = parser.parse_args(argv)
    try:
        if args.command == "check":
            validate_files(tracked_files(ROOT))
        elif args.command == "record-baseline":
            record_baseline(ROOT, args.source, args.reviewed_commit)
        elif args.command == "sync":
            sync(ROOT, args.source, args.dry_run, args.push, args.message)
        elif args.command == "release":
            release(ROOT, args.source, args.version, args.notes_file)
        elif args.command == "build":
            build(ROOT, args.version, args.output_dir)
        return 0
    except (PublishingError, OSError, ValueError) as error:
        print("Publishing stopped: " + str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
