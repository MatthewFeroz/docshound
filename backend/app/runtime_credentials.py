from threading import RLock


_lock = RLock()
_merge_gateway_api_key: str | None = None


def get_merge_gateway_api_key() -> str | None:
    """Return the process-local Gateway credential, if one was supplied."""
    with _lock:
        return _merge_gateway_api_key


def set_merge_gateway_api_key(api_key: str) -> None:
    """Keep a Gateway credential in memory for the lifetime of this process."""
    normalized = api_key.strip()
    if not normalized:
        raise ValueError("Enter a Merge Gateway API key.")
    with _lock:
        global _merge_gateway_api_key
        _merge_gateway_api_key = normalized


def clear_runtime_credentials() -> None:
    """Clear process-local credentials. Primarily useful for test isolation."""
    with _lock:
        global _merge_gateway_api_key
        _merge_gateway_api_key = None
