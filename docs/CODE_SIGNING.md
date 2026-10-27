# Code signing policy

*Last updated: 2026-10-24*

## Current status

Shoji's Windows releases are **not code-signed yet**, so Windows SmartScreen may warn when you run `Shoji.exe`.
We plan to apply for free code signing for open source projects from the
[SignPath Foundation](https://signpath.org/). This page will be updated if that happens.

Until then, you can check that a download is genuine:

- Every release is built by the public [release workflow](../.github/workflows/release.yml) on GitHub Actions from
  the tagged source in this repository, and the build log is public.
- Each release has a `.sha256` file. Compare it with `Get-FileHash .\Shoji-<version>-windows-x64.zip -Algorithm SHA256`
  in PowerShell.
- You can also run Shoji from source (see the [README](../README.md#install)).

## How releases are made

- Binaries are built only by GitHub Actions from this repository. Nothing is built or uploaded by hand.
- Third-party packages are installed from pinned versions with hashes (`requirements-lock.txt`), so a build uses
  exactly the reviewed versions.
- Releases are published manually by the maintainer after reviewing the changes.
- Third-party components are listed in [NOTICE](../NOTICE) and [docs/LICENSING.md](LICENSING.md) and are
  included in `THIRD_PARTY_LICENSES.txt` in every release.

## Team and roles

| Role | Members |
|---|---|
| Committers and reviewers | [ebipepe](https://github.com/ebipepe) |
| Approvers (release signing) | [ebipepe](https://github.com/ebipepe) |

All team members use multi-factor authentication for GitHub.

## Privacy

Shoji does not send any data to the Shoji project. See the [privacy policy](PRIVACY.md) for what it stores on your
PC and which servers it connects to.
