<p align="center"><img src="assets/branding/kindle-pilot-logo.png" alt="Kindle Pilot logo" width="132" /></p>

<p align="center"><strong>English</strong> | <a href="./README.md">中文</a></p>

<h1 align="center">Kindle Pilot</h1>

<p align="center"><strong>Let your Agent set up and maintain your Kindle.</strong></p>

Kindle Pilot supplies the Skill, workflows, and CLI for Kindle setup and maintenance. Your Agent checks compatibility, verifies downloads, transfers files, and resumes from saved progress. You perform the requested touchscreen steps, account confirmation, and QR scans.

## Start with one request

Connect and unlock the Kindle over USB; fully exit KOReader if it is running. Give a network- and USB-capable Agent this request:

```text
Follow https://github.com/gaofeng21cn/kindle-pilot and its Agent guide to configure my connected Kindle. Preserve the native library, set up KOReader, YueDu, supported reading services, and wireless maintenance. Tell me when touchscreen or QR steps are needed, then continue.
```

The Agent reads the [Skill](skills/kindle-pilot/SKILL.md), checks the host and compatibility manifest, and asks for the complete firmware version from Device Info. If the Skill is already installed, start with `$kindle-pilot` and describe the task.

## Capabilities

- Initial setup with a verified jailbreak route, KOReader, YueDu, and the library plugin.
- Local books and comics, with representative content opened for verification.
- WeChat Reading and Fanqie login where supported by YueDu's current sources; account and chapter access are checked separately.
- Preservation of the native library and delivery path, including native reading of existing KFX comics.
- Native collection management that reuses meaningful topic/source groups.
- Wireless maintenance integrated into initial USB setup, then temporary Wi-Fi sessions for inspection, backup, and organization.
- Recovery from saved progress and diagnosis of USB, transfer, and plugin problems.

## Compatibility

The current host path supports macOS, Python 3.10+, and OpenMTP. The [compatibility manifest](manifests/compatibility.json) currently records Colorsoft Signature Edition firmware `5.20.1.0.2` with the Véra route. It owns model, firmware, upstream URLs, digests, and redistribution policy. Other combinations require a verified route before installation.

USB visibility, transfer readback, application loading, and actual account/book behavior are separate checks. Device books, account cookies, pairing records, backups, and downloaded upstream packages remain local.

## Wireless use

After the initial setup is verified, keep the Kindle and host on the same LAN. In KOReader, open **KindlePilot 无线维护 → 配对此电脑并开始维护** and tell the Agent the six-digit code, preserving leading zeros. Codes last 120 seconds; maintenance closes after 30 minutes by default and the Agent closes it when finished. See [wireless maintenance](docs/WIRELESS_MAINTENANCE.md).

## Install and develop

OPL application management uses the native Codex plugin carrier, with Package/CLI ID `kindle-pilot` and selector `kindle-pilot@kindle-pilot`. Official artifacts own published versions; a source checkout is an explicit development path. Updating or uninstalling the host plugin does not remove Kindle books, device plugins, backups, or task files.

```sh
PYTHONPATH=src python3 -m kindle_companion --json software-info
PYTHONPATH=src python3 -m kindle_companion --json capabilities
PYTHONPATH=src python3 -m unittest discover -s tests -v
python3 scripts/check-package.py
```

The first two commands read software metadata only and report `device_status=not_checked`. Host tests do not connect to the device. See [capabilities](docs/CAPABILITIES.md), [workflow](docs/WORKFLOW.md), [native collections](docs/NATIVE_COLLECTIONS.md), and [architecture](docs/ARCHITECTURE.md).

Own code is [MIT-licensed](LICENSE); upstream licenses and sources are listed in [third-party notices](THIRD_PARTY_NOTICES.md).
