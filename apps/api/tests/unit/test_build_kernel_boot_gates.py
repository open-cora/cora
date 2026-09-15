"""The production boot gates refuse rather than fall back.

Both defaults in `build_kernel` are permissive, and both are correct for
tests: `AllowAllAuthorize` lets a unit test exercise a handler without
standing up a policy, and an absent `require_authenticated_principal` lets a
developer curl the API.

Permissive defaults are also exactly how an authorization gate ends up off in
production with nothing recording that it was skipped. The reconciliation is
these refusals, so this file exercises the WRONG configuration and asserts the
process will not start.
"""

import pytest

from aroc.infrastructure.config import Settings
from aroc.infrastructure.deps import build_kernel

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("env", ["prod", "production", "staging"])
async def test_production_tier_refuses_to_boot_without_an_authorize_factory(env: str) -> None:
    settings = Settings(app_env=env, require_authenticated_principal=True)
    with pytest.raises(ValueError, match="requires authorize_factory"):
        await build_kernel(settings=settings)


@pytest.mark.parametrize("env", ["prod", "production", "staging"])
async def test_production_tier_refuses_to_boot_without_authenticated_principals(env: str) -> None:
    """Without the header check, any caller can claim any principal."""
    settings = Settings(app_env=env, require_authenticated_principal=False)
    with pytest.raises(ValueError, match="REQUIRE_AUTHENTICATED_PRINCIPAL"):
        await build_kernel(
            settings=settings,
            authorize_factory=lambda *_args, **_kwargs: None,  # pyright: ignore[reportArgumentType]
        )


async def test_test_env_builds_an_in_memory_kernel_with_no_pool() -> None:
    """The permissive path, asserted so the refusals above are not vacuous.

    If test mode also refused, the two tests above would pass for the wrong
    reason and this file would prove nothing about production specifically.
    """
    kernel, teardown = await build_kernel(settings=Settings(app_env="test"))
    try:
        assert kernel.pool is None
        assert kernel.authz is not None
        assert kernel.schema_posture == "matched"
    finally:
        await teardown()
