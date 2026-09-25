# Security Policy

## Supported versions

The conductor is pre-1.0 and under active development. Only the `main` branch
receives security fixes. There are no LTS lines.

## Reporting a vulnerability

Please **do not** open a public issue for security vulnerabilities.

Use **GitHub's private vulnerability reporting** for this repository:

1. Go to the [Security tab](https://github.com/open-cora/conductor/security) of the repo.
2. Click **Report a vulnerability**.
3. Fill in the form with as much detail as you can:
   - the affected component (core, adapter, config, entrypoint)
   - the impact
   - reproduction steps or a proof-of-concept
   - the commit hash you tested against

You will receive an acknowledgement within **5 business days**. We aim to
issue a fix or a public advisory within **30 days** of acknowledgement,
depending on severity and complexity.

## What this software does, which is the thing to read first

A conductor moves hardware. It takes a step from the keeper, claims the
records that step names, and writes to them over a control protocol. A defect
that makes it drive the wrong record, or drive one it did not claim, is a
safety question before it is a security one.

Two properties are load-bearing and each has a test:

- **A claim is taken before a write and released after it.** Two walks cannot
  hold overlapping scopes. The ledger is in-process and deliberately not
  durable, so it says what this conductor is doing now and promises nothing
  about the moment after it dies.
- **The core names no seam.** Everything above `conductor.adapters` composes a
  procedure without knowing a control protocol exists, so the vocabulary a
  beamline routine is written in cannot reach hardware by accident.

## Scope

In scope:

- The conductor itself: the core, the adapters, the intake loop, the
  configuration loader and the entrypoint.
- CI, build, and tooling in `.github/workflows/` and the `Makefile`.

Out of scope:

- Vulnerabilities in upstream dependencies; report those upstream.
- The keeper's API surface. Report those against
  [the keeper](https://github.com/open-cora/keeper/security).
- A control system with no access control in front of it. Channel Access and
  its peers authenticate nobody by default, and a conductor is one client
  among however many the facility permits. Placing a beamline's control
  network behind the facility's own controls is a deployment question, not an
  application vulnerability. What this software promises is that IT does not
  write outside a claim, not that nothing else does.

## Hardening notes

- **The configuration holds a bearer token.** It is a file an operator writes
  and this repository must never ship one. Give it the narrowest grant that
  lets the conductor take work at its own beamline: a token good for a second
  beamline is one wrong grant away from driving hardware at the other end of
  the building.
- **Every call goes out and none comes in.** A conductor needs no inbound
  port and no listening socket. A deployment that adds one has added an
  attack surface this design does not have.
