import os
from contextlib import contextmanager
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool


def pool():
    return ConnectionPool(
        os.environ["DATABASE_URL"],
        min_size=1,
        max_size=20,
        timeout=5,
        kwargs={"row_factory": dict_row, "connect_timeout": 3},
        open=True,
    )


@contextmanager
def operation_lock(conn, booking_id, blocking=True):
    query = (
        "SELECT pg_advisory_lock(hashtextextended(%s,0))"
        if blocking
        else "SELECT pg_try_advisory_lock(hashtextextended(%s,0)) AS acquired"
    )
    row = conn.execute(query, (str(booking_id),)).fetchone()
    conn.commit()
    acquired = blocking or row["acquired"]
    try:
        yield acquired
    finally:
        conn.rollback()
        if acquired:
            conn.execute(
                "SELECT pg_advisory_unlock(hashtextextended(%s,0))", (str(booking_id),)
            )
            conn.commit()
