"""Composition root: the FastAPI application and its MCP surface.

This is the only layer permitted to depend on every bounded context. It builds
the app, wires each BC's handlers onto `app.state`, registers routes and MCP
tools, and owns the lifespan that builds and tears down the kernel.
"""
