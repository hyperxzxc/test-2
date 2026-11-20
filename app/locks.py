from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import delete, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.errors import AppError
from app.models import ResourceLock, now


@contextmanager
def resource_lock(sessions: sessionmaker, resource: str) -> Iterator[None]:
    owner = str(uuid4())
    with sessions() as db:
        claimed = db.execute(
            update(ResourceLock)
            .where(
                ResourceLock.resource == resource,
                ResourceLock.expires_at < now(),
            )
            .values(owner=owner, expires_at=now() + timedelta(minutes=10))
        ).rowcount
        if not claimed:
            db.add(
                ResourceLock(
                    resource=resource, owner=owner, expires_at=now() + timedelta(minutes=10)
                )
            )
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise AppError("busy", "Ресурс занят другой операцией. Повторите позже", 409) from None
    try:
        yield
    finally:
        with sessions() as db:
            db.execute(
                delete(ResourceLock).where(
                    ResourceLock.resource == resource, ResourceLock.owner == owner
                )
            )
            db.commit()
