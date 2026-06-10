"""Shared async HTTP session management for connection pooling."""

from curl_cffi.requests import AsyncSession

from src.config import HTTP_TIMEOUT


class HTTPSessionManager:
    """Manages a shared curl_cffi async session with configurable proxy.

    Configure proxy once at startup, then all REST requests go through it.
    """

    def __init__(self, impersonate: str = "chrome") -> None:
        self._impersonate = impersonate
        self._proxy: str | None = None
        self._async: AsyncSession | None = None

    def configure(self, proxy: str | None) -> None:
        """Set proxy. Recreates session on next access if proxy changed."""
        if proxy != self._proxy:
            self._proxy = proxy
            if self._async is not None:
                self._async.close()
                self._async = None

    def get_async(self) -> AsyncSession:
        """Get or create the shared async session."""
        if self._async is None:
            kwargs = {"impersonate": self._impersonate, "timeout": HTTP_TIMEOUT}
            if self._proxy:
                kwargs["proxy"] = self._proxy
            self._async = AsyncSession(**kwargs)
        return self._async

    async def close_async(self) -> None:
        if self._async is not None:
            await self._async.close()
            self._async = None


# Global singleton — all modules share one manager to reuse connections
default_manager = HTTPSessionManager()
