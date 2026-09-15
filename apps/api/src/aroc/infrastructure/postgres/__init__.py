"""Postgres tech primitives (connection pool).

Per docs/reference/glossary.md, Postgres adapters that implement
infrastructure ports live at `aroc.infrastructure.adapters.postgres_*`.
This package keeps tech primitives that are NOT adapters (resources
shared by those adapters) such as the asyncpg connection pool.
"""
