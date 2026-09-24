"""The intent: define a procedure."""

from dataclasses import dataclass

from aroc.execution.aggregates.procedure import ProcedureStep


@dataclass(frozen=True)
class DefineProcedure:
    """Compose a routine out of moves and acquisitions, in this order.

    Both fields are the caller's and the id is not: the new procedure id,
    the timestamp and the correlation id all come from the handler's
    ports, so the decision this command produces is reproducible on
    replay.

    `name` is a plain string here rather than the value object the state
    holds. The decider is where it becomes one, so that the refusal of a
    bad name is listed with the slice's other refusals instead of being
    raised somewhere up at the edge by whoever built the command.

    `steps` arrives as the step union rather than as raw dictionaries,
    because the two surfaces above already have to parse the caller's
    JSON into something and a command holding dictionaries would make
    every reader of the decider parse them again.
    """

    name: str
    steps: tuple[ProcedureStep, ...]


__all__ = ["DefineProcedure"]
