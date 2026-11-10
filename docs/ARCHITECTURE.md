# Architecture

## Owners

- manifests/compatibility.json owns route and asset declarations.
- kindle_companion.compat owns version comparison and route decisions.
- kindle_companion.state owns the workflow receipt; caches and terminal output do not replace it.
- kindle_companion.mtp owns single-session MTP command construction and transfer error interpretation.
- kindle_companion.collections owns the pinned KC headless adapter, indexed series inventory and cross-checking receipts against later snapshots. KC owns native mutation, backup, identity and pending-result checks; it accesses cc.db read-only and submits changes through the Kindle-local /change service.
- The route's native_collections record owns the separately qualified native-collection support state. Jailbreak compatibility does not imply collection-edit compatibility.
- The user owns Kindle-screen actions and account authentication.

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
