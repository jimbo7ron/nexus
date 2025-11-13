"""Simple async rate limiter using asyncio primitives."""
import asyncio
import time


class RateLimiter:
    """Rate limiter that allows a maximum number of operations per time period."""

    def __init__(self, rate: int, period: float = 1.0):
        """
        Initialize rate limiter.

        Args:
            rate: Maximum number of operations allowed per period
            period: Time period in seconds (default 1.0)
        """
        self.rate = rate
        self.period = period
        self._semaphore = None  # Lazy initialization in event loop
        self.tokens: list[float] = []

    def _get_semaphore(self):
        """Get or create semaphore in current event loop."""
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self.rate)
        return self._semaphore

    async def acquire(self):
        """Acquire permission to proceed, waiting if necessary to respect rate limit."""
        async with self._get_semaphore():
            now = time.monotonic()

            # Remove tokens older than the period
            self.tokens = [t for t in self.tokens if now - t < self.period]

            # If we're at the rate limit, wait until the oldest token expires
            if len(self.tokens) >= self.rate:
                sleep_time = self.period - (now - self.tokens[0])
                if sleep_time > 0:
                    await asyncio.sleep(sleep_time)
                    # Recompute now and clean up tokens again
                    now = time.monotonic()
                    self.tokens = [t for t in self.tokens if now - t < self.period]

            # Add the current token
            self.tokens.append(now)
