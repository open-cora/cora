-- The executions a conductor would take on its first ask: dispatched, and
-- neither claimed nor ended. One row each, oldest first, so whoever reads a
-- hold sees the beamline, what would run there, how long it has waited and
-- which execution to end if it should not.
--
-- Read from the event log rather than from the execution summary the intake
-- answers from. nothing-is-queued.sh says why: the summary can trail the log
-- after a hard stop, and the rows it would be missing are the newest.
SELECT d.payload ->> 'beamline'       AS beamline,
       d.payload ->> 'procedure_name' AS procedure_name,
       to_char(d.occurred_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS dispatched_at,
       d.stream_id                    AS execution_id
FROM events AS d
WHERE d.stream_type = 'Execution'
  AND d.event_type = 'ExecutionDispatched'
  AND NOT EXISTS (
        SELECT 1
        FROM events AS e
        WHERE e.stream_type = d.stream_type
          AND e.stream_id = d.stream_id
          AND e.event_type IN ('ExecutionClaimed', 'ExecutionEnded'))
ORDER BY d.occurred_at, d.stream_id;
