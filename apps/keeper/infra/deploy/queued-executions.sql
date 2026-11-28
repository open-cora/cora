-- The executions a conductor would take on its first ask, or as soon as the
-- work they wait on stops: dispatched and neither claimed nor ended, or
-- parked since they were last claimed and not ended. One row each, oldest
-- first, so whoever reads a hold sees the beamline, what would run there,
-- how long it has waited, which execution to end if it should not, and
-- whether it is new work or a walk that parked.
--
-- A parked execution counts although no conductor takes it yet. Whatever
-- watches its handed-off work makes it ready the moment that work stops,
-- which can be minutes after the API is back, and a conductor then
-- continues the walk with nobody having decided that it should. Ready is
-- not looked for apart from parked, because a parked execution becomes
-- ready with no event this query could see.
--
-- "Since they were last claimed" is the stream's own order: a claim at a
-- higher version than the parking is the claim that took the walk back.
--
-- Read from the event log rather than from the execution summary the intake
-- answers from. nothing-is-queued.sh says why: the summary can trail the log
-- after a hard stop, and the rows it would be missing are the newest.
SELECT d.payload ->> 'beamline'       AS beamline,
       d.payload ->> 'procedure_name' AS procedure_name,
       to_char(d.occurred_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS dispatched_at,
       d.stream_id                    AS execution_id,
       CASE WHEN EXISTS (
                SELECT 1
                FROM events AS p
                WHERE p.stream_type = d.stream_type
                  AND p.stream_id = d.stream_id
                  AND p.event_type = 'ExecutionParked')
            THEN 'parked' ELSE 'dispatched' END AS waiting
FROM events AS d
WHERE d.stream_type = 'Execution'
  AND d.event_type = 'ExecutionDispatched'
  AND NOT EXISTS (
        SELECT 1
        FROM events AS e
        WHERE e.stream_type = d.stream_type
          AND e.stream_id = d.stream_id
          AND e.event_type = 'ExecutionEnded')
  AND (
        NOT EXISTS (
          SELECT 1
          FROM events AS c
          WHERE c.stream_type = d.stream_type
            AND c.stream_id = d.stream_id
            AND c.event_type = 'ExecutionClaimed')
        OR EXISTS (
          SELECT 1
          FROM events AS p
          WHERE p.stream_type = d.stream_type
            AND p.stream_id = d.stream_id
            AND p.event_type = 'ExecutionParked'
            AND NOT EXISTS (
                  SELECT 1
                  FROM events AS c
                  WHERE c.stream_type = d.stream_type
                    AND c.stream_id = d.stream_id
                    AND c.event_type = 'ExecutionClaimed'
                    AND c.version > p.version)))
ORDER BY d.occurred_at, d.stream_id;
