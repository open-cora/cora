-- An operation and a procedure say whether they have been retired.
--
-- Both could only be defined, so a routine nothing answered to any longer
-- stayed listed beside the ones that worked, and a dispatch of it was
-- recorded and then waited forever. Retiring one is now an event, and the
-- listings read it from here: each row carries a status, Active or Retired,
-- and a listing leaves the retired rows out unless it is asked for them.
--
-- The status is derived, by the projection from which events a stream
-- carries, exactly as the fold derives it. A column a writer could set would
-- be a column a writer could set wrong.
--
-- ## Dropped and rebuilt rather than altered
--
-- `status` is NOT NULL, and while every existing row would take the same
-- value, that is true only because nothing has been retired yet, which is a
-- fact about today rather than one an ALTER should bake into a default. These
-- tables are derived, the events behind them are all still in the log, and
-- the bookmarks below start at zero, so the worker recomputes every row from
-- the log on its next pass. That is the pattern every projection change in
-- this tree uses.
--
-- The event payloads need nothing. `OperationDefined` and `ProcedureDefined`
-- are unchanged, and the two retirement events are new types rather than new
-- keys on old ones, so every row already in the log folds as it did.
--
-- No index on `status`. The default listing keeps the active rows of a table
-- holding tens of them, so the filter is a recheck over rows the keyset index
-- already returns in order, and an index would be paid for on every write to
-- earn nothing.

DROP TABLE IF EXISTS proj_execution_operation_summary;  -- atlas:safety:allow=projection table, rebuilt from the event log

CREATE TABLE proj_execution_operation_summary (
    operation_id uuid        PRIMARY KEY,
    name         text        NOT NULL,
    status       text        NOT NULL,
    created_at   timestamptz NOT NULL
);

-- The lookup an adapter makes: it holds the name an engine calls a routine
-- and needs the operation that name was written down as. NOT unique, because
-- two operations may share a name on purpose, and a unique index would make
-- the second invisible to every listing while it sat in the log.
CREATE INDEX proj_execution_operation_summary_name_idx
    ON proj_execution_operation_summary (name);

-- The keyset-pagination sort key, with the id in it for the same tie-breaking
-- reason its siblings carry one.
CREATE INDEX proj_execution_operation_summary_keyset_idx
    ON proj_execution_operation_summary (created_at DESC, operation_id DESC);

GRANT SELECT, INSERT, UPDATE, DELETE ON proj_execution_operation_summary TO keeper_app;

DROP TABLE IF EXISTS proj_execution_procedure_summary;  -- atlas:safety:allow=projection table, rebuilt from the event log

CREATE TABLE proj_execution_procedure_summary (
    procedure_id uuid        PRIMARY KEY,
    name         text        NOT NULL,
    beamline     text        NOT NULL,
    step_count   integer     NOT NULL,
    status       text        NOT NULL,
    created_at   timestamptz NOT NULL
);

-- The lookup a caller makes when it holds a name and needs the routine. NOT
-- unique, for the reason the operation's is not.
CREATE INDEX proj_execution_procedure_summary_name_idx
    ON proj_execution_procedure_summary (name);

CREATE INDEX proj_execution_procedure_summary_keyset_idx
    ON proj_execution_procedure_summary (created_at DESC, procedure_id DESC);

GRANT SELECT, INSERT, UPDATE, DELETE ON proj_execution_procedure_summary TO keeper_app;

-- Recreated, so the bookmarks go too and start at zero. The worker raises on
-- a registered projection with no bookmark, and replaying from the start is
-- what refills each table.
DELETE FROM projection_bookmarks
WHERE name IN ('proj_execution_operation_summary', 'proj_execution_procedure_summary');

INSERT INTO projection_bookmarks (name)
VALUES ('proj_execution_operation_summary'), ('proj_execution_procedure_summary')
ON CONFLICT DO NOTHING;
