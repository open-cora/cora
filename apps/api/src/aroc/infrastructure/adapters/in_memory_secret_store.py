"""In-memory `SecretStore` adapter for unit tests and the `test` app environment.

Mirrors the production adapter contract: same `store` / `load` / `revoke`
operations, same opaque-ref convention, same `SecretNotFoundError` on
missing ref and idempotent-revoke semantics. A `threading.Lock` guards
the dict so concurrent tasks see consistent state.

Not durable across process restarts and not safe for production
(filesystem keyring, HashiCorp Vault, AWS Secrets Manager, or cloud
KMS adapters are the production options per
`project_federation_port_design.md` Memo 2; deferred until first real
consumer).
"""

from threading import Lock

from aroc.infrastructure.ports.secret_store import SecretNotFoundError


class InMemorySecretStore:
    """Thread-safe in-memory implementation of the `SecretStore` port."""

    def __init__(self) -> None:
        self._records: dict[str, bytes] = {}
        self._lock = Lock()

    async def store(self, ref: str, secret: bytes) -> None:
        with self._lock:
            self._records[ref] = secret

    async def load(self, ref: str) -> bytes:
        with self._lock:
            try:
                return self._records[ref]
            except KeyError as exc:
                raise SecretNotFoundError(ref) from exc

    async def revoke(self, ref: str) -> None:
        with self._lock:
            self._records.pop(ref, None)


__all__ = ["InMemorySecretStore"]
