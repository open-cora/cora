-- An operation's listing row says whether a run of it drives devices.
--
-- A run composed for a proposal claimed the station's devices whatever it
-- ran, so a transfer to another facility held a detector and a stage for
-- the hours it took. The facility now declares, once per operation, whether
-- a run of it drives devices where it runs, and that declaration is a new
-- event on the operation's stream. The listing carries it because the
-- caller that most needs it, whatever keeps operations in step with a
-- register, looks each one up by name and has to tell an operation nobody
-- declared from one declared either way.
--
-- Nullable, and the null is an answer: nobody has declared it. That is a
-- third state rather than a quiet false, because an undeclared operation is
-- composed as it always was and a plan of several runs citing one is
-- refused.
--
-- ## Altered rather than rebuilt
--
-- Additive, and every row that exists is correctly null: the declaration is
-- a new event type, so no stream in any log carries one yet. Nothing has to
-- be replayed, which is the shape the proposal summary's `adopted_at` took
-- for the same reason. `OperationDefined` and `OperationRetired` are
-- unchanged, so every row already in the log folds as it did.
--
-- No index. The listing filters on name and status and reads this column
-- off the rows it already returns.

ALTER TABLE proj_execution_operation_summary
    ADD COLUMN drives_devices boolean;
