# Third-party notices

This repository contains integration metadata and host-side workflow code. It does not redistribute the jailbreak books or third-party plugin archives.

| Component | Source | Role | Repository policy |
|---|---|---|---|
| Véra | [KindleModding](https://kindlemodding.org/jailbreaking/Vera/) | jailbreak route and device-specific books | URL and SHA-256 only; download from upstream |
| KOReader | [koreader/koreader](https://github.com/koreader/koreader) | reader runtime | release URL and SHA-256 only |
| Moon / 月读 | [AnkioTomas/moon](https://github.com/AnkioTomas/moon) | unified library and account sources | release URL and SHA-256 only |
| kindle.koplugin | [kaikozlov/kindle.koplugin](https://github.com/kaikozlov/kindle.koplugin) | Kindle Library and KFX conversion | release URL and SHA-256 only |
| KC / kc-ivy | [uiu8/kc-ivy](https://github.com/uiu8/kc-ivy) | native collection read-only export, guarded trial, headless protocol/planner | MIT; pinned release downloaded locally; no third-party archive or binary committed |
| SQLite amalgamation | [sqlite.org](https://sqlite.org/) | compile the upstream KC read-only backup checker for modern generated-column syntax | public domain; source URL and SHA-256 only |

The manifests intentionally use upstream-unverified where the upstream repository does not expose a license value that this project can independently confirm. Users and downstream packagers must follow each upstream project's current license and release terms.
