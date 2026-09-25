---
template: home.html
---

# Conducts a procedure across a beamline, one step at a time.

Asks the keeper what has been dispatched to its beamline, claims one execution,
drives it through the seams a deployment installs, and reports each outcome as
its step ends, so a walk that dies leaves behind the steps that finished rather
than nothing at all.

It refuses a step whose hardware another walk is already holding. Refusing beats
queueing here: a caller told which walk holds the device can decide something else.

A client of the keeper, not a part of it. Nothing here imports the keeper and
nothing in the keeper imports this.

## What is here

The code, and the pages that outlive any one reading of it. The package's own
`README.md` is the design document: what a claim is, why it names records rather
than devices, what the control adapter does beyond a put, and what this
deliberately will not promise.

| Page | Subject |
| --- | --- |
| [Conducting](conducting.md) | What a conducted walk promises, what a restart does, and what survives when the process does not |
| [Client contract](client-contract.md) | The agreement with the keeper and with the reporter: two names for one acquisition, and the two metadata keys that join them |
| [Conventions](conventions.md) | How this project is written: naming, docstrings, comments, commits, test names |
| [Glossary](glossary.md) | The words shared with the keeper, and what each is pinned to |

Every design decision in this package came from a spike that drove real
hardware, and the tests name the finding each one answers. The spikes
themselves are gone; what they measured is quoted where it is relied on.
