# Repository instructions

Use Chinese for user-facing reports unless the user requests another language.

The compatibility manifest is the source of truth for model, firmware, upstream
URL, asset digest, and redistribution policy. Do not add a route from a blog
or a nearby firmware guess.

Keep jailbreak books, device dumps, account cookies, QR payloads, and plugin
archives out of Git. Store them in ignored local directories and verify their
SHA-256 before transfer.

Separate the following states in every report:

- USB visible;
- route supported;
- asset hash verified;
- MTP write succeeded and was read back;
- application loaded;
- account or book behavior was verified.

Do not delete the device root, the whole documents directory, koreader,
libkh, unknown update files, or unknown user books. Build an explicit batch
and show its targets before destructive operations.
