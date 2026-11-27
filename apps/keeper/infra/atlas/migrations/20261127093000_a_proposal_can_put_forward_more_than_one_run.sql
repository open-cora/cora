-- A proposal's summary row can stand for a plan of several runs.
--
-- A proposal used to be one run of one operation, so its row named that
-- operation and nothing about how many runs there were. A plan puts forward
-- up to sixteen runs in order, through a new genesis event on the same
-- stream, and proposes no one operation. Its row says how many runs it
-- holds and leaves the operation null, rather than naming the first run's
-- and reading as the whole of the advice to a caller that has not learned
-- what a plan is.
--
--     operation_id   null for a plan of several; the run's own otherwise
--     run_count      how many runs the proposal puts forward
--
-- ## Altered rather than rebuilt
--
-- Every row that exists was written from a `ProposalMade`, which can only
-- ever hold one run, so one is the true count for every one of them by what
-- that event is rather than by what happens to be in the log today. That is
-- what lets the default fill them in place and the bookmark stay where it
-- is. The default is dropped straight after, because every row written from
-- now on states its own count and a default would let an arm that forgot to
-- write one look correct.
--
-- `operation_id` loses NOT NULL and keeps every value it holds. A plan of
-- one still names its run's operation, so the only rows with a null are
-- plans of several, which no row written before this could be.
--
-- No index. Nothing asks for proposals by how many runs they hold, and the
-- open lookup is still the null test on `execution_id` the existing partial
-- index serves.

ALTER TABLE proj_counsel_proposal_summary
    ALTER COLUMN operation_id DROP NOT NULL;

ALTER TABLE proj_counsel_proposal_summary
    ADD COLUMN run_count integer NOT NULL DEFAULT 1;

ALTER TABLE proj_counsel_proposal_summary
    ALTER COLUMN run_count DROP DEFAULT;
