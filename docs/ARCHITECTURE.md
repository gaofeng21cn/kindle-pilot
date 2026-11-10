# Architecture

## Owners

- manifests/compatibility.json owns route and asset declarations.
- kindle_companion.compat owns version comparison and route decisions.
- kindle_companion.state owns the workflow receipt; caches and terminal output do not replace it.
- kindle_companion.mtp owns single-session MTP command construction and transfer error interpretation.
- kindle_companion.wireless and kindle_companion.pairing own the host-side session/pairing protocol, while KOReader `KindlePilot.koplugin` owns the on-device code display and starts the independent pairing daemon. The daemon owns temporary authorization and cleanup outside the KOReader UI event loop. KOReader's SSH/Dropbear remains the SSH server owner; wireless transport does not grant collection-edit capability.
- kindle_companion.collection_additions owns additive membership payloads, visibility-aware count checks, exact task-created collection retirement and whole-plan readback. The native Kindle service owns database mutations.
- capabilities/kindle-pilot.json owns the exported KindlePilot capability-module catalog; `kindle_companion.capabilities` is its read-only discovery surface. Package exports and plugin presentation must match this catalog.
- kindle_companion.collections owns the pinned KC headless adapter, indexed series inventory and cross-checking receipts against later snapshots. KC owns native mutation, backup, identity and pending-result checks; it accesses cc.db read-only and submits changes through the Kindle-local /change service.
- The route's native_collections record owns the separately qualified native-collection support state. Jailbreak compatibility does not imply collection-edit compatibility.
- The user owns Kindle-screen actions and account authentication.
- `opl-package.json` owns the software's stable Package identity, display metadata and native carrier declaration. The Codex plugin manager owns marketplace discovery, installation, updates, enabled state and removal; Framework projects that state for the unified application manager.
- `kindle_companion.software` reads software metadata without device discovery, task receipts or credentials. Software installation and version checks are separate from all device evidence layers below. The current Git marketplace is a development source, not a Stable artifact publication.

Plugin removal preserves books, backups and task state. Knowledge and credential integration uses the shared OPL source/provider owners when those resources are needed; the software catalog does not store device credentials or a second personal library.

## Evidence layers

The workflow distinguishes:

1. USB visibility;
2. route compatibility;
3. local asset digest;
4. MTP command result and remote readback;
5. application launch;
6. account login and book-opening behavior.

An exit code alone cannot prove a transfer. A file on the device cannot prove that KOReader loaded the plugin. A visible QR code cannot prove that the account session was accepted.

## Extension rule

Adding a route requires an official upstream URL, exact firmware and model mapping, every required asset's digest, the manual handoff points, and a fixture-backed compatibility test. If any of those are missing, the route remains informational and cannot be selected for an automated write.
