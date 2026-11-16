---
title: Registry credentials for private image pulls
status: open
area: core
owner: null
filed: 2026-11-16
fixed_in: null
scope: M
verify: test
---

Pulls send no `X-Registry-Auth` header, so a private image fails with `ImageNotFound` unless
it was pulled before. testcontainers-python had the same gap (issue 562 there).

Read `$DOCKER_CONFIG/config.json` (default `~/.docker/config.json`):

1. `auths.<registry>.auth`: base64 `user:password`, send as the auth header.
2. `credHelpers.<registry>` / `credsStore`: run `docker-credential-<name> get` with the
   registry on stdin.

No credentials in logs or exception messages.
