-- An operation's listing row says which of a run's parameters name a place.
--
-- A pursuit authorizes the places its work may read, write and move data
-- between, and the compute places it may process at, and it refuses a round
-- whose runs name any other. It can only read a run's places if something
-- says which of the run's values are places, and nothing in an operation's
-- schema does. The facility now declares it, once per operation, as a new
-- event on the operation's stream. The listing carries it for the caller
-- that carries device use, whatever keeps operations in step with a
-- register, which has to tell an operation nobody declared from one
-- declared.
--
-- Two nullable lists of parameter names, null together while nobody has
-- declared them. Either may be empty once declared, which is an answer: the
-- operation's runs name no place of that kind. The check holds the two
-- together, because the projection writes both in one statement and a row
-- with one list and not the other would be a declaration half read.
--
-- ## Altered rather than rebuilt
--
-- Additive, and every row that exists is correctly null: the declaration is
-- a new event type, so no stream in any log carries one yet. Nothing has to
-- be replayed, which is the shape the device use column took for the same
-- reason, and no bookmark is reset.
--
-- No index. Nothing filters on these, and the listing reads them off the
-- rows it already returns.

ALTER TABLE proj_execution_operation_summary
    ADD COLUMN place_parameters text[],
    ADD COLUMN compute_place_parameters text[],
    ADD CONSTRAINT proj_execution_operation_summary_place_use_whole
        CHECK ((place_parameters IS NULL) = (compute_place_parameters IS NULL));
