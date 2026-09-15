# Runtime

*Production hardening, logging, HTTP errors.*

Default-secure or refuse to boot. The app declines to start in production unless authentication is required and the database role is the read-write app role, not the migration owner. Everything else (limits, tracing, log shape) is wired so a missing piece is visible, not silent.

## Production hardening

Wired in `aroc/api/main.py:create_app()`.

- **Body size limit.** `BodySizeLimitMiddleware` returns 413 over `Settings.max_request_body_size_bytes`, default 1 MiB. Production also enforces at the reverse proxy.
- **Prometheus `/metrics`.** A per-app `CollectorRegistry`, because the global one crashes on a second `TestClient(create_app())`. Hidden from its own counters and from OpenAPI.
- **OpenTelemetry tracing.** `Settings.otel_exporter` is `none`, `console`, or `otlp`. OTLP honours the `OTEL_EXPORTER_OTLP_*` environment variables. Trace context is the source of truth for correlation: `current_correlation_id()` returns `UUID(int=trace_id)`. Handler spans come from `with_tracing` in `wire.py`, named `<bc>.<command|query>.<command_name>`.
- **Auth.** Three modes, picked in order:
    1. A **bearer-verified principal** on `request.state.principal`, set by `BearerAuthMiddleware` when `Settings.identity_providers` is configured.
    2. A **bearer-mode 401** with an RFC 6750 `WWW-Authenticate` header, when bearer is required but missing or invalid.
    3. The **`X-Principal-Id` header** when no identity providers are configured. Production MUST front this with a verifying proxy that strips any client-supplied header and sets the verified UUID.

    On the header path with no principal present, `Settings.require_authenticated_principal` controls the fallback: False yields `SYSTEM_PRINCIPAL_ID`, True yields 401. Token-introspection unavailability surfaces as 503 with `Retry-After: 5`.
- **Production startup gate.** Refuses to boot if `app_env` is production-tier AND `require_authenticated_principal` is False. Opt in with `APP_ENV=prod`, `REQUIRE_AUTHENTICATED_PRINCIPAL=true`, and a `DATABASE_URL` that connects as `aroc_app`.
- **Schema agreement gate.** Refuses to boot when the applied migration version is not the one the build expects. `ALLOW_SCHEMA_VERSION_MISMATCH=true` boots anyway with every append refused and reads still working, so a restored database can be inspected without risking an append-only history that cannot be corrected afterwards. Scope it honestly: this protects the event log, not every write.
- **Database role separation.** `aroc_app` has SELECT and INSERT on `events`; UPDATE, DELETE, and TRUNCATE are revoked. Migrations run as the database owner. Projection tables get full DML.

## Logging

Two patterns:

- **Handlers**: `<verb>.<event>` (`register_thing.start`, `register_thing.denied`, `register_thing.success`). Every handler emits `start` plus either `denied` or `success`. Decider failures propagate as exceptions.
- **Cross-cutting**: `<concern>.<event>` (`idempotency.hit_success`, `body_size_limit.rejected`).

**Field names:**

- `correlation_id`: request correlation, a str-cast UUID.
- `causation_id`: command handlers only; the upstream event id, `null` for an HTTP or MCP root. Always emitted.
- `principal_id`: the calling principal, a str-cast UUID.
- `command_name` / `query_name`: the dataclass name.
- `<aggregate>_id`: the aggregate id when in scope. One key per concept.

## HTTP errors

- **In routes**: `raise HTTPException(...)`. The FastAPI idiom.
- **In exception handlers**: `return JSONResponse(...)`. Raising `HTTPException` inside a handler creates nested-exception pitfalls.

Routes raise, handlers return. Same JSON shape over the wire.
