# Conductor

Walks a procedure across a beamline, one step at a time, and refuses a step
whose hardware another walk is already holding.

A client of the keeper, not a part of it. It asks what has been dispatched to
its beamline, claims one execution, drives it through the seams a deployment
installs, and reports each step as the step ends. Nothing here imports the
keeper and nothing in the keeper imports this.

The package's own `README.md` is the design document: what a claim is, why it
names records rather than devices, what the control adapter does beyond a put,
and what this deliberately will not promise. These pages are the parts that
outlive any one reading of the code.

| Page | Subject |
| --- | --- |
| [Conducting](conducting.md) | What a conducted walk promises, what a restart does, and what survives when the process does not |
| [Client contract](client-contract.md) | The agreement with the keeper and with the reporter: two names for one acquisition, and the two metadata keys that join them |
| [Conventions](conventions.md) | How this project is written: naming, docstrings, comments, commits, test names |
| [Glossary](glossary.md) | The words shared with the keeper, and what each is pinned to |

Every design decision in this package came from a spike that drove real
hardware, and the tests name the finding each one answers. The spikes
themselves are gone; what they measured is quoted where it is relied on.
