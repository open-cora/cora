# Security Policy

CORA is a development tree holding several projects that ship apart. Each is
published as a repository of its own and each carries its own policy, so the
first question is which one a report belongs to.

## Reporting a vulnerability

Please **do not** open a public issue for security vulnerabilities.

Use **GitHub's private vulnerability reporting**, against the project the
defect is in:

| If the defect is in | Report against | Its policy |
| --- | --- | --- |
| The API, the event store, migrations, authentication or authorization | [open-cora/keeper](https://github.com/open-cora/keeper/security) | [apps/keeper/SECURITY.md](apps/keeper/SECURITY.md) |
| Walking a procedure, claiming hardware, driving a control protocol | [open-cora/conductor](https://github.com/open-cora/conductor/security) | [apps/conductor/SECURITY.md](apps/conductor/SECURITY.md) |
| Relaying an acquisition engine's documents | [open-cora/reporter](https://github.com/open-cora/reporter/security) | [apps/reporter/SECURITY.md](apps/reporter/SECURITY.md) |
| This tree itself: CI, tooling, the facility descriptors | [open-cora/cora](https://github.com/open-cora/cora/security) | this file |

If you are not sure which, report it here and it will be routed. A report in
the wrong place is far better than one not made.

You will receive an acknowledgement within **5 business days**. We aim to issue
a fix or a public advisory within **30 days** of acknowledgement, depending on
severity and complexity.

## Supported versions

Every project here is pre-1.0 and under active development. Only the `main`
branch receives security fixes, and there are no LTS lines. A mirror's `main`
is republished from this tree's `main`, so a fix reaches both at once.

## Scope of this repository's own policy

In scope:

- CI, build and tooling that belongs to the tree rather than to one project:
  the root `Makefile` and `.github/workflows/`, the pre-commit configuration,
  and the publishing path that produces the mirrors.
- The facility descriptors under `beamlines/`, which name real device
  addresses. They describe hardware and grant no access to it, but a wrong
  address in one is a defect worth reporting.

Out of scope:

- Anything inside a project, which the table above routes.
- Vulnerabilities in upstream dependencies; report those upstream.

## One thing that is not a vulnerability and is worth saying

A client's configuration holds a bearer token for the keeper. Those files are
written by an operator and this tree ships none of them, which is deliberate
rather than accidental: a committed token is the failure this arrangement
exists to avoid. Finding one committed here is a report worth making
immediately.
