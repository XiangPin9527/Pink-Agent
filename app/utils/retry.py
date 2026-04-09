import asyncio
from functools import wraps
from typing import Callable, TypeVar

from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

T = TypeVar("T")


def async_retry(
    max_attempts: int = 3,
    wait_min: float = 1.0,
    wait_max: float = 10.0,
    exceptions: tuple = (Exception,),
):
    """
    异步重试装饰器
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @retry(
            stop=stop_after_attempt(max_attempts),
            wait=wait_exponential(multiplier=1, min=wait_min, max=wait_max),
            retry=retry_if_exception_type(exceptions),
        )
        @wraps(func)
        async def wrapper(*args, **kwargs):
            return await func(*args, **kwargs)

        return wrapper

    return decorator


__all__ = ["async_retry"]
