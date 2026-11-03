# Maintaining this public skill

This checkout is the public export. The installed personal skill is a separate
source and can contain private preferences and experimental references.

- Use scripts/maintain.py sync for incremental updates. It uses a private source
  baseline under .git/skill-publisher and merges only changed source text.
- Do not copy the installed folder wholesale or publish its Git history.
- Resolve overlap conflicts in the public checkout, validate and commit the
  reviewed result, then record-baseline for that reviewed commit. Recording a
  baseline means every pending source change was actually reviewed.
- Run python scripts/maintain.py check before pushing. It checks privacy patterns,
  syntax, links, versions and the offline test suite.
- Use scripts/maintain.py release with a new X.Y.Z version and concrete notes.
  Tag push triggers release.yml, which requires all three Python checks first.
- Never replace an existing release/tag, force-push, or store source snapshots,
  credentials, experimental workbooks or private Origin projects in tracked files.
- Offline maintenance checks do not establish complete Origin acceptance.
