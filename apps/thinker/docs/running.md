# Running one

This page is for whoever installs a thinker and runs it.

## What it needs

Network access to the record, and whatever does the thinking. Nothing else: no
database, no queue, no inbound port. It dials out, and nothing ever dials in.

That last sentence survives the fact that a thinker now waits. It waits by
holding open a request it made, so being told that a question exists arrives as
the answer to an outbound call, and nothing listens at this end.

## Starting one

```sh
python -m thinker --config thinker.toml --serve
python -m thinker --config thinker.toml --inquiry <id>
python -m thinker --config thinker.toml --execution <id> --objective "..."
```

Three ways to arrive at a question, and one thinking whichever way.

**The first finds its own.** It asks the keeper for a question nobody has taken
up, claims it, answers it, and asks again, forever. This is the one to install as
a service, and it is what makes a question put by an agent get answered with
nobody watching.

**The second answers a question already on the record and stops.** It claims it
before reading anything, and exits 3 if another thinker already holds it.

**The third opens a question and then answers it.** This is what somebody at a
terminal with a run in hand does.

There is no way that leaves no record, and the absence is deliberate: an answer
nobody can find afterwards is the state this was built to end. It matters most
in the first mode, where nobody is reading the output and the record is the only
copy of the answer.

## Running one as a service

```sh
python -m thinker --config thinker.toml --serve --wait 30
```

`--wait` is how long one request for a question may be held open before the
keeper answers it empty and the thinker opens another. It is a bound on the
socket rather than on anybody's patience: connections held open indefinitely die
in proxies and NAT tables without telling either end, and nothing is lost at the
ceiling, because a question sits there until something takes it. The keeper
refuses an ask above its own ceiling of sixty seconds.

A `SIGTERM` stops it the way Ctrl-C does, after the thinking in progress
finishes rather than in the middle of one. A thinker killed mid-thought leaves
its question claimed with nothing on it, which is the shape this system reads as
an abandoned thinker, and nothing expires that claim.

Two thinkers running at once is allowed and costs nothing much. Both may reach
for one question, one of them loses the claim, and the loser goes back for
another. What it costs is a wasted ask, not a wasted inference.

## Configuring one

```toml
[keeper]
base_url = "https://keeper.example"
token = "a-thinker-token"

[inference]
profile = "beamline_2bm.thinking:inference"
```

Three settings, and the third is required.

**The inference profile** names something importable that hands back whatever
does the thinking. It is a dotted path rather than a block of settings because
a client with its own credentials and state is an object a text file cannot
hold. A model name, a temperature and a retry policy are arguments to whatever
that builds, and none of them appear here.

**There is no beamline setting**, although a thinker now asks for work before it
has any, which is the reason a conductor needs one. The difference is what the
work is attached to: an execution is dispatched to a beamline, and an inquiry
names an execution and carries no beamline of its own. So a thinker takes any
open question and the record tells it where that execution ran.

**There is no objective setting.** It changes with every question, which is what
makes it the asker's to give. A thinker configured with a standing objective
would apply yesterday's question to today's run without anybody having said so,
and a thinker that finds its own work reads the objective off the question it
found.

## What the exit status means

```
   0    it ran. any of the four answers.
   1    the record could not be reached, or the thinking failed.
   2    the configuration will not load.
   3    another thinker already holds this question.
```

**The status says whether the thinker ran, never what it concluded.** All four
answers are a success, because deciding that there is nothing to run next is a
real answer and not a failure.

**A failure is never turned into an answer.** Nothing is swallowed. A record
that cannot be reached and a provider that crashed both stop the thinking, and
neither becomes an abstention. Returning one would read as a thinker that looked
and found nothing, when it is a thinker that did not look.

**Exit 3 is not a fault.** Another thinker holding the question is an ordinary
race, not an outage, and treating it as one would send somebody looking for a
broken record.

**Serving reaches only 0 and 2.** A configuration still refuses to start, and
after that there is nothing left for a status to say: the process ends when it
is told to. Everything that would have been a 1 is said out loud, waited out and
tried again, and everything that would have been a 3 is the next turn of the
loop. What is caught changes who tries again, never what is written down: a
thinking that did not happen still reaches the record as nothing at all.

## Running the tests

```sh
uv sync --all-extras
uv run pytest -q
uv run ruff check src tests && uv run ruff format --check src tests
uv run pyright src tests
```

The suite needs no record and no provider. Both seams are exercised through
stand-ins, and the HTTP adapter is checked through a transport that inspects the
request rather than sending it.
