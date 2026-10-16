-- An execution carries the routines it needs an engine for.
--
-- Copied off the operations its run steps cite, at dispatch, and this column
-- is the reason the copy exists. The work intake asks for every dispatched
-- execution at one beamline and then claims whatever came back, with nothing
-- checking that the conductor can run it. A claim is a write with nothing to
-- undo it, so every mismatch is a burned execution: the step is refused, the
-- execution is reported failed, and whatever could have driven it never sees
-- it.
--
-- The filter is a subset test, `routines <@ $n`, so a row is returned when
-- every routine it needs is one the caller runs. Both empty cases come out
-- right without a special case. A procedure of sets needs nothing and is
-- offered to everyone; a conductor with no engine passes the empty set and is
-- offered only those.
--
-- Same kind of column as `beamline` two migrations before this one, and
-- copied for the same reason stated there: it is a routing key on a page of
-- rows, not one consumer's one question about one row, which is what the
-- reference on a dispatched step answers and why that one is a reference.
--
-- No index. The intake index narrows to one beamline's dispatched rows first,
-- which is a handful, so the array test is a recheck over those rather than a
-- scan. An index here would be paid for on every write to earn nothing.
--
-- Dropped and rebuilt rather than altered, for the reason the beamline column
-- gives: the table is derived, no existing row could supply a value, and the
-- bookmark below starts at zero so the worker recomputes every row from the
-- log. Rows rebuilt from an event written before the genesis carried this
-- come back with the empty array, which is what every conductor already
-- assumed about them.

DROP TABLE IF EXISTS proj_execution_execution_summary;  -- atlas:safety:allow=projection table, rebuilt from the event log

CREATE TABLE proj_execution_execution_summary (
    execution_id     uuid        PRIMARY KEY,
    procedure_id     uuid        NOT NULL,
    procedure_name   text        NOT NULL,
    beamline         text        NOT NULL,
    step_count       integer     NOT NULL,
    reported_indices integer[]   NOT NULL DEFAULT '{}',
    routines         text[]      NOT NULL DEFAULT '{}',
    status           text        NOT NULL,
    created_at       timestamptz NOT NULL,
    updated_at       timestamptz NOT NULL
);

-- The lookup a caller makes when it holds a procedure and wants to know how its
-- executions went. NOT unique: a routine composed once is run every time it
-- runs, and every one of those rows is wanted.
CREATE INDEX proj_execution_execution_summary_procedure_idx
    ON proj_execution_execution_summary (procedure_id);

-- The work intake's query, and the reason `beamline` is on this table.
--
-- Both columns together, in that order, because every intake request fixes the
-- beamline and then asks for one status. A conductor at 2-BM polling for
-- dispatched work must not scan the executions of three other beamlines to
-- find out it has nothing to do, and that is the one query in this system
-- expected to run continuously.
CREATE INDEX proj_execution_execution_summary_intake_idx
    ON proj_execution_execution_summary (beamline, status);

-- The keyset-pagination sort key, with the id in it for the same tie-breaking
-- reason its siblings carry one.
CREATE INDEX proj_execution_execution_summary_keyset_idx
    ON proj_execution_execution_summary (created_at DESC, execution_id DESC);

GRANT SELECT, INSERT, UPDATE, DELETE ON proj_execution_execution_summary TO keeper_app;

-- Put back, because dropping the table dropped it.
--
-- This is the first rebuild of this table since the intake's wake-up trigger
-- was added to it, so it is the first one that could lose it, and nothing in
-- the two rebuilds above says so. The function survives a DROP TABLE and the
-- trigger does not, so a rebuild that copies the earlier ones verbatim leaves
-- a schema that looks complete and a long poll that never wakes: every intake
-- request would sleep to its ceiling and work would be picked up at the next
-- look instead of in milliseconds.
--
-- Nothing in the schema would have caught that. The integration check that
-- waits on the real channel did, and anyone rebuilding this table again
-- should read this block before copying the one above it.
CREATE TRIGGER execution_summary_notify_trigger
    AFTER INSERT ON proj_execution_execution_summary
    FOR EACH ROW
    EXECUTE FUNCTION execution_summary_notify();

-- Recreated, so the bookmark goes too and starts at zero.
DELETE FROM projection_bookmarks WHERE name = 'proj_execution_execution_summary';

INSERT INTO projection_bookmarks (name)
VALUES ('proj_execution_execution_summary')
ON CONFLICT DO NOTHING;
