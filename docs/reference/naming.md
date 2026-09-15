# Naming

*Aggregates, events, commands, slices, ports, error classes.*

Seven rules, applied to any new field, event class, command, slice, aggregate, or agent name. R1 and R2 are guidelines that catch awkward names early. R3 through R7 are structural rules that produce naturally consistent families.

Run them at design time, not at review time. A rename costs one commit at two call sites and a day at twenty.

## R1: Read-aloud test

Say the name out loud. If it does not read like natural English, it is a smell, even when it parses correctly as code.

- "default parameters" reads naturally.
- "parameter defaults" stalls. It works as an adjectival construction, but not as a domain noun.

The trap is that code identifiers compose without grammar checks. `parameter_defaults: dict` typechecks fine. The compiler does not notice that English speakers will say "the default parameters". Identifiers that fight English become identifiers people misremember, mistype, and have to look up.

**Also count the term's domain overloads.** A term that reads naturally in isolation can have hidden collisions. At lock time, list the distinct meanings the word already carries in this domain. If there are more than three, look harder.

## R2: Symmetry across the family

When a related family of names exists (defaults / overrides / effective; declared / derived / cached), every member must share the same word-order skeleton.

Ask: if I list every member of this family, do they all share a skeleton? If not, fix it before locking.

**A family has a MEANING, not just a size.** Before adopting a family on a member-count argument, read two or three of its members and check that the family holds a meaning the new member shares. `to_X` returning something that is not an `X` joins the big family while breaking its semantics, which is worse than the outlier it replaced. Every cited fact can be true and the conclusion still wrong.

## R3: Family-noun primacy, with the role as an adjective prefix

**The family noun goes LAST. The role goes first, as an adjective.**

```
<role>_<family-noun-plural>

default_parameters     override_parameters     effective_parameters
default_settings       override_settings       effective_settings
```

This matches how English assembles compound nouns. The family noun carries the primary meaning; the adjective specializes it.

The counter-example to avoid is `<family>_<role>`, which puts the abstract family noun first and a role noun second, pretending to be a suffix. It is grammatical but awkward in use.

**This rule is read backwards more often than any other in this document.** R3 says noun-LAST. Before proposing a rename on R3 grounds, re-read this section.

The schema is the exception: a schema describes the family rather than specializing within it, so `parameters_schema` is family-noun plus descriptor. There is no role, because a schema is not a role within the family. It IS the family contract.

**Collective nouns are not plurals.** "Wiring" and "plumbing" read naturally in speech but break the field-name pattern. Use the plural for a collection field and reserve the collective for a higher-level concept label.

## R4: Lock-time read-aloud process

Before locking a design, run the R1 and R2 checks once more over every name in it. This is mechanical, takes about five minutes, and catches what mid-design momentum hides.

1. List every new name introduced: fields, events, commands, slices, error classes.
2. For each, say it aloud. Awkward? Flag it.
3. Group into families by shared role-words. Do the skeletons match? If not, flag.
4. Fix anything flagged and re-list.
5. Then lock.

## R5: Agent names are `<Domain><Doer>`

An agent identity (an entity that subscribes to events, runs inference, and registers a result) follows a doer pattern: a domain noun followed by the natural English agent-form of the verb the agent performs.

| Domain verb | English doer | Agent name |
| --- | --- | --- |
| draft | drafter | `<Domain>Drafter` |
| plan | planner | `<Domain>Planner` |
| verify | verifier | `<Domain>Verifier` |
| audit | auditor | `<Domain>Auditor` |
| detect | detector | `<Domain>Detector` |

Pick the natural doer suffix (`-er`, `-or`, `-ist`, `-ant`, or no change), not a mechanical `+er`. When the natural doer is awkward, use a synonym whose doer form reads cleanly.

**Why doer, not work-product.** An agent is a principal with a role, in PROV-O, in OpenTelemetry's `gen_ai.agent.*`, and in A2A's AgentCard. A cross-corpus audit of six agent frameworks found all six use doer or role naming and none name agents after work products. A team member is a doer, not the report they wrote.

This is a deliberate carve-out from the single-word preference: agents are tightly BC-scoped, and a bare doer noun would collide across BCs, so the domain qualifier earns its second word.

It does NOT apply to slice, command, or handler names, which stay verbs. It does NOT apply to the work product itself, which stays a work-product noun.

## R6: Cannot-transition errors are per-verb, not collapsed

When an aggregate exposes multiple verbs that all reject from the same source-state set, each verb gets its own error class: `<Aggregate>Cannot<Verb>Error`. Do not collapse them into a single `<Aggregate>CannotTransitionError` keyed on a `requested_transition: str` field.

1. The verb name in the class IS the diagnostic.
2. Handler-side mapping to HTTP 409 keys off `isinstance`, not a string field.
3. The transition-name string is duplicate information: the call site already knows which verb it called.

Carve-out: with only one such verb and no foreseeable second, a bare `<Aggregate>CannotTransitionError` is fine. Promote to per-verb the moment a second transition slice lands.

Collapsing the verb into a payload string is the same mistake R3 warns about: it hides the diagnostic where the reader cannot see it.

## R7: Logbook entry classes are single-word abstract nouns

An entry class written to `entries_<aggregate>_<noun_plural>` names itself as a bare single-word abstract noun. The BC and aggregate namespace differentiates it, so the class does not repeat the aggregate:

```
aroc.<bc>.aggregates.<aggregate>.entries.Observation
```

An entry class is a passive row reached only through its full module path, so it takes the bare noun. Its command is not a row, and takes the aggregate qualifier: `Append<Aggregate>Observations`.

This is the opposite direction from R5, and deliberately so. Agents are principals that collide across BCs; entry classes have no such collision concern.

## Where these rules do not apply

- **Single-instance fields** with no family. R2 has nothing to check. R1 still applies.
- **Industry-standard names** that follow a different convention. `created_at` and `occurred_at` are standard; do not rename them for symmetry with anything.
- **Names that landed before a rule existed.** Apply the rules to new work and let old work pass through normal evolution, unless a rename is independently motivated.

## Enforcement status

Two of these rules are checked today. The rest cannot be: they range over
bounded contexts, and there are none, so writing them now would produce tests
that pass by examining nothing. That is the failure mode `test_fitness_scope.py`
exists to prevent, and adding eight instances of it to look thorough would be
the wrong trade.

**Pending means unenforced.** A rule in the left column with "pending" beside
it is a convention you are expected to follow and nothing will catch you
breaking. Land the test with the bounded context that first makes it
non-vacuous.

| Rule | Check | Status |
| --- | --- | --- |
| Port naming (`<Thing>Lookup`, no `Port` suffix) | `test_port_naming_conventions.py` | enforced |
| Test names carry an outcome | `test_test_names_carry_outcome.py` | enforced |
| Event class shape `<Aggregate><PastParticiple>` | | pending, needs an aggregate |
| Command name derives the event name | | pending, needs a slice |
| Slice verb names carry the subject | | pending, needs a slice |
| REST URL kebab-case | | pending, needs a route |
| UUID collection fields carry `_ids` | | pending, needs an aggregate |
| Self-referential parent is `parent_id` | | pending, needs an aggregate |
| State error naming taxonomy | | pending, needs a state module |
