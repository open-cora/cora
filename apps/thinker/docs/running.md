# Running one

This page is for whoever installs a thinker and invokes it.

## What it needs

Network access to the record, and whatever does the thinking. Nothing else: no
database, no queue, no inbound port. It dials out, and nothing ever dials in.

It is not a server. It is started with one question, reads once, answers once,
prints the answer and exits.

## Starting one

```sh
python -m thinker --config thinker.toml --inquiry <id>
python -m thinker --config thinker.toml --execution <id> --objective "..."
```

Two ways to name the question, and one thinking either way.

**The first answers a question already on the record.** It claims it before
reading anything, and exits 3 if another thinker already holds it. This is how a
question put by something else reaches a thinker.

**The second opens a question and then answers it.** This is what somebody at a
terminal with a run in hand does.

There is no third way that leaves no record, and the absence is deliberate: an
answer nobody can find afterwards is the state this was built to end.

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

**There is no beamline setting.** A conductor is told which beamline it is at
because it asks for work before it has any, and the question would otherwise be
circular. A thinker is handed a run, and the record says where that ran.

**There is no objective setting.** It changes with every invocation, which is
what makes it an argument. A thinker configured with a standing objective would
apply yesterday's question to today's run without anybody having said so.

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
