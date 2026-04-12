from __future__ import annotations

import concurrent.futures
import logging
import os
import time
from typing import Callable, List, TypeVar

import praw

logger = logging.getLogger(__name__)

T = TypeVar("T")


def create_reddit_client():
    return praw.Reddit(
        client_id=os.getenv("REDDIT_CLIENT_ID"),
        client_secret=os.getenv("REDDIT_CLIENT_SECRET"),
        user_agent=os.getenv("REDDIT_USER_AGENT"),
        requestor_kwargs={"timeout": 30},
    )


def with_timeout(
    fn: Callable[[], T],
    name: str = "",
    what: str = "",
    timeout: int = 20,
    retries: int = 2,
    backoff: float = 2.0,
) -> T | list:
    attempt = 0
    while attempt <= retries:
        attempt += 1
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                fut = ex.submit(fn)
                return fut.result(timeout=timeout)
        except Exception:
            time.sleep(min(8.0, backoff ** (attempt - 1)))
    return []


def fetch_feed(subreddit, mode: str, limit: int) -> List:
    name = subreddit.display_name
    if mode == "new":
        return with_timeout(lambda: list(subreddit.new(limit=limit)), name, "new")
    if mode == "hot":
        return with_timeout(lambda: list(subreddit.hot(limit=limit)), name, "hot")
    if mode == "rising":
        return with_timeout(lambda: list(subreddit.rising(limit=limit)), name, "rising")
    if mode == "top_day":
        return with_timeout(
            lambda: list(subreddit.top(time_filter="day", limit=limit)), name, "top_day"
        )
    return []
