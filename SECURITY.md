# Security policy

This repository is an offline portfolio prototype and is not a production service.

## Reporting a vulnerability

Please use GitHub's private vulnerability reporting for this repository. Do not post secrets, private data, or a full exploit in a public issue.

## Current security boundaries

- The local server binds to `127.0.0.1` by default. Do not expose it to an untrusted network without authentication, authorization, and a deployment review.
- The XES parser uses `defusedxml` and bounded input sizes. Treat all local event logs as untrusted.
- The downloaded research file is checked against its published MD5 to detect accidental corruption; MD5 is not a modern authenticity guarantee.
- `joblib` artifacts use pickle-based serialization. Only load a model produced by this project or another trusted source.
- Do not commit the source event log, generated databases, models, predictions, access tokens, or other sensitive data.
