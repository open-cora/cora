# Spikes

Throwaway programs that answer a question by running, so a decision is
made against a measurement rather than against a guess. Nothing in
`apps/` imports anything here, and nothing here is maintained once its
question is answered.

`FINDINGS.md` is the deliverable in every one of them. The scripts are
only how the findings were obtained, and they are kept so a reader can
check the work or rerun it against a newer version of whatever was
driven.

## Two kinds, and how to tell which you are writing

**`<system>_adapter`** asks what one outside system's wire actually looks
like, and what talking to it would cost. One directory per system, named
for the system rather than for the role it plays here:
`tiled_adapter` is titled "Store adapter spike" for that reason. The
suffix is a family marker, not a claim that an adapter exists or that one
should. A spike concluding that the adapter should not be built is a
finding, and the directory keeps the system's name anyway.

These open with a bold line saying they are not production code, because
the scripts look like something a reader might import.

**Named for a thing** asks whether a design of ours survives contact with
something. `conductor` asks whether an app holding a control seam and an
acquisition seam can keep two steps off one device. No outside system is
the subject, so no system's name would fit, and there is no adapter to
mistake the scripts for.

When a spike drives a real system while asking a design question, the
question is which of those is the subject. `conductor` drove a real
RunEngine over real Channel Access and is not named for either, because
neither one was what was under examination.

## What is here

| Spike | Question |
| --- | --- |
| [bluesky_adapter](bluesky_adapter/FINDINGS.md) | What a RunEngine publishes, and what a run's natural key should be |
| [dm_adapter](dm_adapter/FINDINGS.md) | What a second store calls a body of data, and whether its client library has to come along |
| [ophyd_adapter](ophyd_adapter/FINDINGS.md) | What a device is, and what a state record may claim about one |
| [queueserver_adapter](queueserver_adapter/FINDINGS.md) | What a conducted run looks like when the engine runs behind a shared queue |
| [tiled_adapter](tiled_adapter/FINDINGS.md) | What identifies a body of data in the store, and whether the store announces an ending |
| [tomoscan_adapter](tomoscan_adapter/FINDINGS.md) | A second engine, and which of the run verbs it can actually report |
| [conductor](conductor/FINDINGS.md) | Whether two steps of one procedure can be kept off one device, and what a walk leaves behind |
