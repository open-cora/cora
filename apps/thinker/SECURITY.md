# Security Policy

## Supported versions

The thinker is pre-1.0 and under active development. Only the `main` branch
receives security fixes. There are no LTS lines.

## Reporting a vulnerability

Please **do not** open a public issue for security vulnerabilities.

Use **GitHub's private vulnerability reporting** for this repository:

1. Go to the [Security tab](https://github.com/open-cora/thinker/security) of the repo.
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

A thinker reads records and writes one kind of record. It moves no hardware
and speaks to no engine. The write is a proposal, which is a suggestion that
something be run, and a facility that automatically runs what it is handed
has made a suggestion into an instruction somewhere outside this repository.

Three properties are load-bearing and each has a test:

- **The core names no seam.** Everything above `thinker.adapters` forms a
  conclusion without knowing that any provider or any transport exists, so a
  case cannot reach the network by accident.
- **A conclusion is a class and not a field.** Four distinct classes, and only
  one of them has a write behind it. A verdict string could be set to the
  wrong word by anything that touched it; a class cannot.
- **A failure is never reported as a conclusion.** A keeper that could not be
  reached and a provider that raised both stop the run. Neither becomes an
  `Abstain`, because a finding that nothing found is the worst thing this
  software could put into a permanent record.

## Scope

In scope:

- The thinker itself: the core, the keeper adapter, the configuration loader
  and the entrypoint.
- CI, build, and tooling in `.github/workflows/` and the `Makefile`.

Out of scope:

- Vulnerabilities in upstream dependencies; report those upstream.
- The keeper's API surface, including what a given token is allowed to do.
  Report those against
  [the keeper](https://github.com/open-cora/keeper/security).
- Whatever a deployment's inference profile builds. It is code the deployment
  writes and this repository ships none of it. What this software promises is
  that the thing behind the seam is handed a case and asked for a conclusion,
  not that it is trustworthy.
- A facility that acts on a proposal without a person reading it. A proposal
  is a record that something was advised. Turning one into a dispatched
  execution is a decision made elsewhere.

## Hardening notes

- **The configuration holds a bearer token.** It is a file an operator writes
  and this repository must never ship one. Give it the narrowest grant that
  lets a thinker read executions and make proposals. A token that can also
  dispatch is a thinker that can run what it advised, which is the property
  the split between advising and driving exists to prevent.
- **A proposal is written under whoever the token names.** The keeper reads
  the proposer off the authenticated principal, so a thinker sharing a
  person's credential produces advice that reads as that person's. Give it
  its own.
- **Every call goes out and none comes in.** A thinker needs no inbound port
  and no listening socket. A deployment that adds one has added an attack
  surface this design does not have.
- **A case is sent to whatever the profile builds.** If that is a hosted
  provider, then an execution's procedure, its parameters and its outcomes
  leave the facility. What a case contains is worth reading before choosing
  a profile, and it is exactly what `case.py` says it is.
