-- The execution summary can tell a parked execution from a ready one.
--
-- A driver whose step outlasts its bound now parks the execution rather than
-- ending it, and the execution becomes ready once whatever watches the far
-- side reports the handed-off step's work stopped. Ready is derived, not
-- reported: the fold reads that engine report against the step the execution
-- parked at, which is the last step reported.
--
-- This table has to derive the same thing, because the work intake reads it,
-- and it could not. A step report names its step by index and an engine
-- report names it by id, and only the genesis holds the pairing, so nothing
-- here could say whether an engine report was about the step an execution is
-- waiting on. Without that, a late report for a run that finished inside its
-- bound would read a parked execution as ready while the step it waits on was
-- still running, and a driver would walk on past work that had not finished.
--
-- So two columns, both arrays and both written idempotently:
--
--   step_ids        the genesis step ids in their order, written once. The
--                   step an execution parked at is
--                   step_ids[max(reported_indices) + 1], arrays being
--                   one-based.
--   settled_steps   every step id an engine report has ended, as a set. A
--                   union is harmless on replay where a flag per step
--                   would need a column per step.
--
-- The second is a set and not a single value because the order is not fixed.
-- The driver reports the handed-off step and then parks, in two requests, and
-- an engine report for that step can land between them. Parking then has to
-- find the ending already recorded, or the execution would wait for a report
-- that has already arrived.
--
-- No trigger fires on a row becoming ready, and that is not an oversight. A
-- conductor asks for ready work without holding the request, before it holds
-- one for dispatches, so nothing waits on that change. A held request woken
-- by it would query for dispatched work and find none.
--
-- Dropped and rebuilt rather than altered, for the reason every rebuild of
-- this table gives: it is derived, no existing row could supply the new
-- columns, and the bookmark below starts at zero so the worker recomputes
-- every row from the log.

DROP TABLE IF EXISTS proj_execution_execution_summary;  -- atlas:safety:allow=projection table, rebuilt from the event log

CREATE TABLE proj_execution_execution_summary (
    execution_id     uuid        PRIMARY KEY,
    procedure_id     uuid        NOT NULL,
    procedure_name   text        NOT NULL,
    beamline         text        NOT NULL,
    step_count       integer     NOT NULL,
    reported_indices integer[]   NOT NULL DEFAULT '{}',
    routines         text[]      NOT NULL DEFAULT '{}',
    step_ids         uuid[]      NOT NULL DEFAULT '{}',
    settled_steps    uuid[]      NOT NULL DEFAULT '{}',
    status           text        NOT NULL,
    created_at       timestamptz NOT NULL,
    updated_at       timestamptz NOT NULL
);

-- The lookup a caller makes when it holds a procedure and wants to know how its
-- executions went. NOT unique: a routine composed once is run every time it
-- runs, and every one of those rows is wanted.
CREATE INDEX proj_execution_execution_summary_procedure_idx
    ON proj_execution_execution_summary (procedure_id);

-- The work intake's query, and the reason `beamline` is on this table. It now
-- asks for two statuses, ready and then dispatched, and each ask fixes the
-- beamline and one status, which is the order of these two columns.
CREATE INDEX proj_execution_execution_summary_intake_idx
    ON proj_execution_execution_summary (beamline, status);

-- The keyset-pagination sort key, with the id in it for the same tie-breaking
-- reason its siblings carry one.
CREATE INDEX proj_execution_execution_summary_keyset_idx
    ON proj_execution_execution_summary (created_at DESC, execution_id DESC);

GRANT SELECT, INSERT, UPDATE, DELETE ON proj_execution_execution_summary TO keeper_app;

-- Put back, because dropping the table dropped it. The function survives a
-- DROP TABLE and the trigger does not; the rebuild before this one says what
-- forgetting it costs, and it is still true.
CREATE TRIGGER execution_summary_notify_trigger
    AFTER INSERT ON proj_execution_execution_summary
    FOR EACH ROW
    EXECUTE FUNCTION execution_summary_notify();

-- Recreated, so the bookmark goes too and starts at zero.
DELETE FROM projection_bookmarks WHERE name = 'proj_execution_execution_summary';

INSERT INTO projection_bookmarks (name)
VALUES ('proj_execution_execution_summary')
ON CONFLICT DO NOTHING;
