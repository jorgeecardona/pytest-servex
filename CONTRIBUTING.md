# Contributing to pytest-servex

Developer and maintainer notes: toolchain, the dev loop, CI, and the release process. (Package
*users* need none of this. See the [README](README.md) for what pytest-servex does and how
to use it.)

## Contributing with an AI agent

Most changes here will be written with a coding agent. That is expected and welcome. To get a
good result from yours:

- Point it at [`AGENTS.md`](AGENTS.md) first. It has the build and test commands, the typed-API
  and style rules, and the gotchas of this repo. Agents read it automatically when started from
  the repo root.
- Ship a green `make check` (lint + format-check + typecheck + test). Have the agent run it and
  fix what it finds before opening the MR.
- Do not let it bypass the hooks. The patch version auto-bumps on `src/` changes and CI's
  version-guard checks it. A `--no-verify` commit fails the pipeline.
- Keep the diff small and typed (pyright runs strict), add a `CHANGELOG.md` entry, and do not
  reformat unrelated files.

## Development & CI

The toolchain is pinned with [proto](https://moonrepo.dev/proto) (`.prototools`: `moon` + `uv`)
and every CI-graded task is a [moon](https://moonrepo.dev) target running through `uv run`. After
cloning:

```bash
proto install          # installs the pinned moon + uv
uv sync                # install dependencies into .venv
make install-hooks     # pre-commit auto-bump + pre-push checks (one-time)
```

The dev loop (thin `make` aliases over the moon tasks, so `make` runs exactly what CI runs):

```bash
make format            # auto-format + autofix lint (ruff, line length 100)
make check             # the full test stage: lint + format-check + typecheck + test
make docs              # build the docs site strictly (as CI / the pages job do)
```

CI has two GitLab jobs. `ci` runs `proto install` for the toolchain, then one `moon run :ci`
for the whole graph (lint, format-check, typecheck, test, test-floor, build, docs, version-guard,
version-ahead). `pages` runs on `main` only and publishes the site that `ci` built.

There are no per-language jobs or hand-wired stages. moon orders the tasks, so run them through
`make` or `moon run`.

## Versioning

The version is `__version__` in `src/pytest_servex/__init__.py`. `pyproject.toml` reads it via
`[tool.hatch.version]` (its `version` is `dynamic`), so there is no second copy.

Do not edit it by hand. The pre-commit hook bumps the patch version when a `.py` file under
`src/` changes. CI's `version-guard` fails when a `src/` change has no bump, which catches
`--no-verify` commits and clones without hooks. `version-ahead` fails unless the version is
greater than the one on `origin/main`.

For a minor or major release, bump by hand: `make bump TYPE=minor`.

## Releasing

Releases are automated. There is no manual tag or publish step:

1. `pre-commit` bumps the patch version on any `src/` change (`make install-hooks` once after
   cloning). Commits that change only docs, tests, examples or config do not bump.
2. `version-guard` (part of `:ci`) checks the same rule in CI.
3. `:release` runs on a green `main` pipeline, after the full `:ci` graph. If the package version
   is not on PyPI yet, it publishes via OIDC Trusted Publishing. A version bump merged to `main`
   is released by that same pipeline, with no tag.

### One-time setup

PyPI uses OIDC Trusted Publishing: no API token is stored anywhere. In the PyPI account, open
Publishing and add a *pending* GitLab publisher (or add it to the project after the first manual
upload):

| Field | Value |
|-------|-------|
| PyPI Project Name | `pytest-servex` |
| Namespace | `cardona-oss` |
| Project name (repo) | `pytest-servex` |
| Top-level pipeline file | `.gitlab-ci.yml` |
| Environment name | `pypi` |

Pushes and MRs run the `:ci` graph only. Publishing happens only from a green `main`.

## License

By contributing, you agree that your contributions are licensed under the MIT License, the same
terms as the project (see [LICENSE](LICENSE)).
