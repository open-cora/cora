"""FastAPI application factory and its MCP surface.

`create_app()` builds a fresh app with its own FastMCP server. Production
calls it once at import; tests call it per `TestClient` context so each gets
an isolated app, registry, and kernel.

## What a bounded context adds here

Nothing else in the tree may import every BC, so each one plugs in at four
points, all of them in `create_app`:

  1. `register_<bc>_tools(mcp, get_handlers=...)`, before `mcp.streamable_http_app()`.
  2. `wire_<bc>(deps)` inside the lifespan, assigned to `app.state.<bc>`.
  3. `register_<bc>_projections(registry, deps)` inside the lifespan.
  4. `register_<bc>_routes(fastapi_app)`, after the app is constructed.

The `get_handlers` callbacks close over `fastapi_app` rather than over the
handler bundle, because the lifespan has not run when tools are registered.
That indirection is why tool registration can precede wiring.

There are no bounded contexts yet, so the app currently serves `/health`,
`/readyz`, `/metrics`, the RFC 9728 metadata document, and an MCP endpoint
with an empty tool list.
"""

import contextlib
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response, status
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from prometheus_client import CollectorRegistry
from prometheus_fastapi_instrumentator import Instrumentator

from aroc import __version__
from aroc.api._readiness import probe_database, readiness_body
from aroc.api.middleware import BodySizeLimitMiddleware
from aroc.api.protected_resource_metadata import register_protected_resource_metadata_route
from aroc.infrastructure.auth.bearer_auth_middleware import BearerAuthMiddleware
from aroc.infrastructure.auth.exception_handlers import register_auth_exception_handlers
from aroc.infrastructure.config import Settings
from aroc.infrastructure.deps import build_kernel
from aroc.infrastructure.idempotency_pruner import idempotency_pruner_lifespan
from aroc.infrastructure.observability import configure_tracing, instrument_app
from aroc.infrastructure.projection.lifespan import projection_worker_lifespan
from aroc.infrastructure.projection.registry import ProjectionRegistry


def _settings_for_app() -> Settings:
    """Load settings from the environment.

    Wrapped so tests can inject a `Settings` instance into `create_app`
    without monkeypatching the environment for the whole process.
    """
    return Settings()  # pyright: ignore[reportCallIssue]  # Pydantic loads from env


def create_app(*, settings: Settings | None = None) -> FastAPI:
    """Build a fresh FastAPI app with its own FastMCP server instance.

    `settings` is an injection point for tests that need to override
    env-loaded config, such as a contract test that needs a specific
    `identity_providers` list. Production callers pass nothing.
    """
    settings = settings if settings is not None else _settings_for_app()

    # configure_tracing is a no-op when otel_exporter is "none", the default
    # in tests, so calling it per create_app() is safe. In production it runs
    # once and installs the global TracerProvider.
    tracing_teardown = configure_tracing(settings)

    # streamable_http_path="/" makes the inner MCP route the mount root, so
    # the full path under app.mount("/mcp", ...) is just "/mcp" rather than
    # "/mcp/mcp".
    #
    # transport_security: FastMCP's DNS-rebinding protection rejects unknown
    # Host headers. This server is embedded in FastAPI behind whatever host
    # security the deployment proxy enforces, so MCP's own check is relaxed
    # here rather than duplicated.
    mcp = FastMCP(
        "aroc",
        streamable_http_path="/",
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=False,
        ),
    )

    fastapi_app: FastAPI

    # Each BC registers its tools here, before the app below is built. The
    # get_handlers callback closes over `fastapi_app` because the lifespan
    # that populates app.state has not run yet.
    mcp_app = mcp.streamable_http_app()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        # MCP session manager first (per python-sdk#1367), then the shared
        # kernel inside it, so both surfaces share one wiring.
        async with mcp_app.router.lifespan_context(app):
            deps, teardown = await build_kernel(settings=settings)
            app.state.deps = deps

            # Each BC's wire_<bc>(deps) result lands on app.state here, and
            # each register_<bc>_projections(registry, deps) call goes below.
            registry = ProjectionRegistry()
            app.state.projections = registry

            try:
                async with (
                    projection_worker_lifespan(deps, registry, settings),
                    idempotency_pruner_lifespan(deps),
                ):
                    yield
            finally:
                # Workers must stop before the pool closes, otherwise the next
                # worker iteration after cancellation races `pool.close()` and
                # surfaces an asyncpg "pool is closing" InterfaceError. Putting
                # the teardown AFTER the workers' async-with block guarantees
                # the cancel-and-await dance has fully unwound first.
                #
                # Independent try/finally so a failure closing the pool cannot
                # skip the tracing flush; without it, spans buffered by the
                # BatchSpanProcessor would be lost.
                try:
                    with contextlib.suppress(Exception):
                        await teardown()
                finally:
                    tracing_teardown()

    fastapi_app = FastAPI(
        title="AROC",
        version=__version__,
        description="A parallel domain-modeling effort on an event-sourced chassis",
        lifespan=lifespan,
    )
    fastapi_app.add_middleware(
        BodySizeLimitMiddleware,
        max_bytes=settings.max_request_body_size_bytes,
    )
    # Bearer-token verification at the HTTP edge. Reads `Authorization:
    # Bearer <token>` and verifies via `kernel.token_verifier`, which is None
    # when no IdPs are configured, in which case the middleware no-ops and the
    # X-Principal-Id header path stays in effect. Added AFTER BodySizeLimit so
    # the size cap rejects cheaply before any token verification work.
    fastapi_app.add_middleware(BearerAuthMiddleware)

    # Prometheus instrumentation:
    #   - a per-app CollectorRegistry, so multiple create_app() calls in one
    #     test process do not double-register collectors against the global
    #     REGISTRY, which would crash the second TestClient.
    #   - excluded_handlers keeps monitoring traffic out of the counters:
    #     /metrics would otherwise pollute its own series on each scrape, and
    #     /readyz is probed on a fixed period, so its latency would swamp the
    #     request histograms with traffic reflecting the probe interval rather
    #     than real demand. /health stays counted: it is the sample request
    #     that proves instrumentation is live.
    #   - include_in_schema=False hides /metrics from OpenAPI; it is an
    #     operational endpoint, not part of the user-facing API.
    metrics_registry = CollectorRegistry()
    Instrumentator(
        registry=metrics_registry,
        excluded_handlers=["/metrics", "/readyz"],
    ).instrument(fastapi_app).expose(fastapi_app, include_in_schema=False)

    # OTel FastAPI instrumentation runs after app construction so the
    # instrumentor sees every route registered above and below. No-op when
    # tracing is off.
    instrument_app(fastapi_app, settings)

    # Each BC's register_<bc>_routes(fastapi_app) call goes here.

    # RFC 9728 Protected Resource Metadata, discoverable at
    # /.well-known/oauth-protected-resource. Clients dereference it after a
    # 401 with a WWW-Authenticate challenge to learn which IdPs issue tokens.
    register_protected_resource_metadata_route(fastapi_app)
    # Convert the typed errors raised by BearerAuthMiddleware and the
    # TokenVerifier into RFC 6750 401s (with a challenge) and 503s (with
    # Retry-After).
    register_auth_exception_handlers(fastapi_app)
    fastapi_app.mount("/mcp", mcp_app)

    @fastapi_app.get("/health")
    async def health() -> dict[str, str]:  # pyright: ignore[reportUnusedFunction]
        """Liveness probe.

        Checks nothing, and must keep checking nothing. Every dependency it
        could check is one a restart cannot fix: a database-checking liveness
        probe restarts the process into a database outage the restart cannot
        mend, turning one outage into a crash loop. Readiness is the probe
        that reports dependencies; see `/readyz`.
        """
        return {"status": "ok", "version": __version__}

    @fastapi_app.get("/readyz", include_in_schema=False)
    async def readyz(  # pyright: ignore[reportUnusedFunction]
        request: Request, response: Response
    ) -> dict[str, str]:
        """Readiness probe: can this process serve a correct request.

        Reports Postgres, the one dependency that can change after a
        successful boot. See `aroc.api._readiness` for why that is the whole
        check, and why liveness must not make it.

        The pool is read off `app.state` rather than closed over: the lifespan
        builds the kernel, so it does not exist when this route is registered.
        """
        request_deps = getattr(request.app.state, "deps", None)
        database = await probe_database(request_deps.pool if request_deps else None)
        body = readiness_body(
            database,
            settings,
            request_deps.schema_posture if request_deps else "matched",
        )
        if body["status"] != "ready":
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
            # Kubernetes ignores Retry-After on probes; it is here for humans
            # and curl, and for consistency with the auth handlers.
            response.headers["Retry-After"] = "5"
        return body

    return fastapi_app


app = create_app()
