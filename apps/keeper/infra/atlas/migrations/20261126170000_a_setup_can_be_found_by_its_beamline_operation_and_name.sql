-- A setup can be listed, and found by the key a step names it by.
--
-- A setup is the values a beamline's conductor applies when it runs an
-- operation, under a name a step's config parameter carries. Its streams
-- answer what a setup holds once its id is known. They cannot answer which
-- setup a beamline holds under a name for an operation, which is the
-- question defining one asks before it writes and the question a step comes
-- down to, so this table answers it.
--
-- One row per setup. The genesis inserts it at revision 1, and each
-- revision moves it to the number the revision carries and the moment it
-- was made. Every column is derived from the log, so the table can be
-- dropped and rebuilt from the bookmark.
--
-- ## Why the key index is not unique
--
-- The defining handler refuses a second setup under a key already held, and
-- that refusal is a check made before the append rather than a lock, so a
-- race can still land two. A unique index would make the projection drop
-- the second, hiding a setup that exists in the log from every listing.
-- Showing both is the better failure, because a person can see it.

CREATE TABLE proj_execution_setup_summary (
    setup_id     uuid        PRIMARY KEY,
    beamline     text        NOT NULL,
    operation_id uuid        NOT NULL,
    name         text        NOT NULL,
    revision     integer     NOT NULL,
    created_at   timestamptz NOT NULL,
    revised_at   timestamptz NOT NULL
);

-- The key lookup, and the listing filters, which are its three parts.
CREATE INDEX proj_execution_setup_summary_key_idx
    ON proj_execution_setup_summary (beamline, operation_id, name);

-- The keyset-pagination sort key, with the id in it for the same
-- tie-breaking reason its siblings carry one.
CREATE INDEX proj_execution_setup_summary_keyset_idx
    ON proj_execution_setup_summary (created_at DESC, setup_id DESC);

GRANT SELECT, INSERT, UPDATE, DELETE ON proj_execution_setup_summary TO keeper_app;

INSERT INTO projection_bookmarks (name)
VALUES ('proj_execution_setup_summary')
ON CONFLICT DO NOTHING;
