from threading import RLock


_lock = RLock()
_merge_gateway_api_key: str | None = None
_github_api_token: str | None = None
_github_account: str | None = None
_github_verified_repo: str | None = None


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


def get_github_api_token() -> str | None:
    """Return the process-local GitHub credential, if one was supplied."""
    with _lock:
        return _github_api_token


def get_github_connection() -> tuple[str | None, str | None]:
    """Return the account and repository most recently verified by GitHub."""
    with _lock:
        return _github_account, _github_verified_repo


def set_github_api_token(api_token: str, *, account: str, repo: str) -> None:
    """Keep a verified GitHub credential in memory for this process lifetime."""
    normalized = api_token.strip()
    if not normalized:
        raise ValueError("Enter a GitHub access token.")
    with _lock:
        global _github_api_token, _github_account, _github_verified_repo
        _github_api_token = normalized
        _github_account = account
        _github_verified_repo = repo


def record_github_verification(*, account: str, repo: str) -> None:
    """Record validation metadata for a server-configured GitHub credential."""
    with _lock:
        global _github_account, _github_verified_repo
        _github_account = account
        _github_verified_repo = repo


def clear_runtime_credentials() -> None:
    """Clear process-local credentials. Primarily useful for test isolation."""
    with _lock:
        global _merge_gateway_api_key, _github_api_token
        global _github_account, _github_verified_repo
        _merge_gateway_api_key = None
        _github_api_token = None
        _github_account = None
        _github_verified_repo = None
