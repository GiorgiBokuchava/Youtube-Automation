import concurrent.futures
import os

import praw


def create_reddit_client():
    return praw.Reddit(
        client_id=os.getenv("REDDIT_CLIENT_ID"),
        client_secret=os.getenv("REDDIT_CLIENT_SECRET"),
        user_agent=os.getenv("REDDIT_USER_AGENT"),
        requestor_kwargs={"timeout": 30},
    )


def _with_timeout(fn, timeout=30, retries=2, backoff=2.0):
    attempt = 0
    while attempt <= retries:
        attempt += 1
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                return ex.submit(fn).result(timeout=timeout)
        except Exception:
            import time

            time.sleep(min(8.0, backoff ** (attempt - 1)))
    return []


def fetch_feed(subreddit, mode: str, limit: int) -> list:
    """Fetch a subreddit listing (used by long-form video sourcing)."""
    if mode == "new":
        return _with_timeout(lambda: list(subreddit.new(limit=limit)))
    if mode == "hot":
        return _with_timeout(lambda: list(subreddit.hot(limit=limit)))
    if mode == "rising":
        return _with_timeout(lambda: list(subreddit.rising(limit=limit)))
    if mode == "top_day":
        return _with_timeout(
            lambda: list(subreddit.top(time_filter="day", limit=limit))
        )
    if mode == "top_week":
        return _with_timeout(
            lambda: list(subreddit.top(time_filter="week", limit=limit))
        )
    if mode == "top_month":
        return _with_timeout(
            lambda: list(subreddit.top(time_filter="month", limit=limit))
        )
    if mode == "top_year":
        return _with_timeout(
            lambda: list(subreddit.top(time_filter="year", limit=limit))
        )
    if mode == "top_all":
        return _with_timeout(
            lambda: list(subreddit.top(time_filter="all", limit=limit))
        )
    return []


def search_subreddit(
    subreddit,
    query: str,
    *,
    sort: str = "top",
    time_filter: str = "month",
    limit: int = 40,
) -> list:
    """
    Search posts within a single subreddit (restrict_sr is implicit when called on Subreddit).
    """
    return _with_timeout(
        lambda: list(
            subreddit.search(
                query,
                sort=sort,
                time_filter=time_filter,
                limit=limit,
            )
        )
    )
