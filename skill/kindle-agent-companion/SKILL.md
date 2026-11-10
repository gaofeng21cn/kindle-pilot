---
name: kindle-agent-companion
description: "Manage a USB-connected jailbroken or jailbreakable Kindle from an Agent: identify the model and firmware, select a verified route, stage and hash-check upstream assets, run safe single-session OpenMTP transfers, install KOReader/Moon plugins, record workflow evidence, and guide the user through required on-device and QR-login steps."
---

# Kindle Agent Companion

Use this skill for a Kindle that the user has placed in scope and connected by USB. Read the repository's manifests/compatibility.json before making a route decision.

The workflow is evidence-bound:

- USB discovery proves visibility, not that the Kindle is unlocked or writable.
- A route decision requires an exact model code and firmware build. Do not substitute a nearby firmware unless the upstream route explicitly says so and the user accepts the uncertainty.
- A local SHA-256 match proves only that the downloaded asset matches the manifest.
- An MTP process exit code does not prove a transfer. Treat StoreFull, SendObjectInfo, invalid response codes, and any top-level error: as failure.
- A copied plugin does not prove that KOReader loaded it. Restart KOReader and verify the visible version or feature.
- A displayed QR code does not prove that WeRead or Fanqie accepted the session.

Use PYTHONPATH=src python3 -m kindle_companion for host-side checks. Use scripts/kindle-mtp.py or the kindle_companion.mtp.MtpClient for OpenMTP; keep one MTP client and one transfer batch active at a time.

The following steps must remain user-owned:

1. Opening the official jailbreak page and downloading the device-specific books when the route requires it.
2. Font Calibration settings and saving the theme.
3. Opening the exploit book and observing RESTARTING GUI.
4. Confirming the JAILBROKEN marker and KPM availability.
5. WeRead and Fanqie QR scans and any phone-side confirmation.

Before any destructive or broad write, show the exact target paths and preserve a recovery route. Never delete the entire documents directory, /koreader, /libkh, or an unknown .bin. Remove only explicitly identified filler files or stale update files after the user has observed jailbreak completion.

For a new model or firmware, stop at route selection and report the missing manifest evidence. Do not invent an asset URL or reuse a different model's jailbreak book.
