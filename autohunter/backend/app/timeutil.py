from datetime import datetime, timezone


def utcnow() -> datetime:
    """Naive UTC — единый формат времени во всей БД (SQLite/PostgreSQL)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def to_naive_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt
