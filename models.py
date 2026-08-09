"""
Database models for NUIST Power Query plugin.
Uses SQLModel + async SQLAlchemy with aiosqlite.
"""
import base64
import json
import time
from datetime import datetime, timezone
from typing import Optional, List

from sqlmodel import SQLModel, Field
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker


class PowerAccount(SQLModel, table=True):
    __tablename__ = "power_accounts"
    __table_args__ = {"extend_existing": True}

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: str = Field(max_length=128, nullable=False, index=True)
    student_id: str = Field(max_length=32, nullable=False)
    password_b64: str = Field(max_length=256, nullable=False)
    room_label: str = Field(max_length=32, default="default")
    xiaoqu_id: str = Field(max_length=64, default="3&沁园")
    loudong_id: str = Field(max_length=64, default="15&沁园22栋")
    room_id: str = Field(max_length=64, nullable=False)
    token: Optional[str] = Field(default=None, max_length=2048)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    def set_password(self, password: str):
        self.password_b64 = base64.b64encode(password.encode("utf-8")).decode("utf-8")

    def get_password(self) -> str:
        return base64.b64decode(self.password_b64.encode("utf-8")).decode("utf-8")

    def token_is_valid(self) -> bool:
        if not self.token:
            return False
        try:
            payload = self.token.split(".")[1]
            payload += "=" * (4 - len(payload) % 4)
            data = json.loads(base64.urlsafe_b64decode(payload))
            exp = data.get("exp", 0)
            return time.time() < exp
        except Exception:
            return False


class PowerSubscription(SQLModel, table=True):
    __tablename__ = "power_subscriptions"
    __table_args__ = {"extend_existing": True}

    id: Optional[int] = Field(default=None, primary_key=True)
    account_id: int = Field(foreign_key="power_accounts.id", nullable=False, index=True)
    session_id: str = Field(max_length=256, nullable=False, index=True)
    interval_minutes: int = Field(default=60)
    threshold: float = Field(default=10.0)
    critical_threshold: float = Field(default=5.0)
    enabled: bool = Field(default=True)
    last_check_at: Optional[datetime] = Field(default=None)
    last_balance: Optional[float] = Field(default=None)


class PowerRecord(SQLModel, table=True):
    __tablename__ = "power_records"
    __table_args__ = {"extend_existing": True}

    id: Optional[int] = Field(default=None, primary_key=True)
    account_id: int = Field(foreign_key="power_accounts.id", nullable=False, index=True)
    balance: float = Field(nullable=False)
    recorded_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class DBManager:
    def __init__(self, db_url: str):
        self.engine = create_async_engine(db_url, echo=False)
        self.async_session = sessionmaker(
            self.engine, class_=AsyncSession, expire_on_commit=False
        )

    async def init(self):
        async with self.engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)

    # ---- Account CRUD ----

    async def get_account(self, user_id: str, room_label: str = "default") -> Optional[PowerAccount]:
        async with self.async_session() as session:
            stmt = select(PowerAccount).where(
                PowerAccount.user_id == user_id,
                PowerAccount.room_label == room_label,
            )
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    async def get_accounts_by_user(self, user_id: str) -> List[PowerAccount]:
        async with self.async_session() as session:
            stmt = select(PowerAccount).where(PowerAccount.user_id == user_id)
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def get_all_accounts(self) -> List[PowerAccount]:
        async with self.async_session() as session:
            stmt = select(PowerAccount)
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def get_account_by_id(self, account_id: int) -> Optional[PowerAccount]:
        async with self.async_session() as session:
            stmt = select(PowerAccount).where(PowerAccount.id == account_id)
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    async def upsert_account(self, user_id: str, student_id: str, password: str,
                             room_id: str, room_label: str = "default",
                             xiaoqu_id: str = "3&沁园",
                             loudong_id: str = "15&沁园22栋") -> PowerAccount:
        async with self.async_session() as session:
            stmt = select(PowerAccount).where(
                PowerAccount.user_id == user_id,
                PowerAccount.room_label == room_label,
            )
            result = await session.execute(stmt)
            account = result.scalar_one_or_none()
            if account:
                account.student_id = student_id
                account.password_b64 = base64.b64encode(
                    password.encode("utf-8")).decode("utf-8")
                account.room_id = room_id
                account.xiaoqu_id = xiaoqu_id
                account.loudong_id = loudong_id
            else:
                account = PowerAccount(
                    user_id=user_id, student_id=student_id,
                    password_b64=base64.b64encode(
                        password.encode("utf-8")).decode("utf-8"),
                    room_id=room_id, room_label=room_label,
                    xiaoqu_id=xiaoqu_id, loudong_id=loudong_id,
                )
                session.add(account)
            await session.commit()
            await session.refresh(account)
            return account

    async def delete_account(self, user_id: str, room_label: str = "default") -> bool:
        async with self.async_session() as session:
            stmt = select(PowerAccount).where(
                PowerAccount.user_id == user_id,
                PowerAccount.room_label == room_label,
            )
            result = await session.execute(stmt)
            account = result.scalar_one_or_none()
            if not account:
                return False
            sub_stmt = select(PowerSubscription).where(
                PowerSubscription.account_id == account.id
            )
            sub_result = await session.execute(sub_stmt)
            for sub in sub_result.scalars().all():
                await session.delete(sub)
            rec_stmt = select(PowerRecord).where(
                PowerRecord.account_id == account.id
            )
            rec_result = await session.execute(rec_stmt)
            for rec in rec_result.scalars().all():
                await session.delete(rec)
            await session.delete(account)
            await session.commit()
            return True

    async def update_token(self, user_id: str, room_label: str, token: str):
        async with self.async_session() as session:
            stmt = select(PowerAccount).where(
                PowerAccount.user_id == user_id,
                PowerAccount.room_label == room_label,
            )
            result = await session.execute(stmt)
            account = result.scalar_one_or_none()
            if account:
                account.token = token
                await session.commit()

    # ---- Subscription CRUD ----

    async def get_subscription(self, session_id: str) -> Optional[PowerSubscription]:
        async with self.async_session() as session:
            stmt = select(PowerSubscription).where(
                PowerSubscription.session_id == session_id,
                PowerSubscription.enabled == True,  # noqa: E712
            )
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    async def get_subscription_by_account(self, account_id: int) -> Optional[PowerSubscription]:
        async with self.async_session() as session:
            stmt = select(PowerSubscription).where(
                PowerSubscription.account_id == account_id,
                PowerSubscription.enabled == True,  # noqa: E712
            )
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    async def get_all_enabled_subscriptions(self) -> list:
        async with self.async_session() as session:
            stmt = select(PowerSubscription).where(
                PowerSubscription.enabled == True  # noqa: E712
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def get_all_subscriptions(self) -> list:
        async with self.async_session() as session:
            stmt = select(PowerSubscription)
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def upsert_subscription(self, session_id: str, account_id: int,
                                  interval_minutes: int = 60,
                                  threshold: float = 10.0,
                                  critical_threshold: float = 5.0) -> PowerSubscription:
        async with self.async_session() as session:
            stmt = select(PowerSubscription).where(
                PowerSubscription.session_id == session_id,
                PowerSubscription.account_id == account_id,
            )
            result = await session.execute(stmt)
            sub = result.scalar_one_or_none()
            if sub:
                sub.interval_minutes = interval_minutes
                sub.threshold = threshold
                sub.critical_threshold = critical_threshold
                sub.enabled = True
            else:
                sub = PowerSubscription(
                    session_id=session_id, account_id=account_id,
                    interval_minutes=interval_minutes,
                    threshold=threshold,
                    critical_threshold=critical_threshold,
                )
                session.add(sub)
            await session.commit()
            await session.refresh(sub)
            return sub

    async def disable_subscription(self, session_id: str, account_id: int = None) -> bool:
        async with self.async_session() as session:
            if account_id:
                stmt = select(PowerSubscription).where(
                    PowerSubscription.session_id == session_id,
                    PowerSubscription.account_id == account_id,
                    PowerSubscription.enabled == True,  # noqa: E712
                )
            else:
                stmt = select(PowerSubscription).where(
                    PowerSubscription.session_id == session_id,
                    PowerSubscription.enabled == True,  # noqa: E712
                )
            result = await session.execute(stmt)
            sub = result.scalar_one_or_none()
            if not sub:
                return False
            sub.enabled = False
            await session.commit()
            return True

    async def update_subscription_check(self, subscription_id: int,
                                        balance: float):
        async with self.async_session() as session:
            stmt = select(PowerSubscription).where(
                PowerSubscription.id == subscription_id
            )
            result = await session.execute(stmt)
            sub = result.scalar_one_or_none()
            if sub:
                sub.last_check_at = datetime.now(timezone.utc)
                sub.last_balance = balance
                await session.commit()

    # ---- History ----

    async def add_record(self, account_id: int, balance: float):
        async with self.async_session() as session:
            rec = PowerRecord(account_id=account_id, balance=balance)
            session.add(rec)
            await session.commit()

    async def get_records(self, account_id: int, limit: int = 10) -> List[PowerRecord]:
        async with self.async_session() as session:
            stmt = (select(PowerRecord)
                    .where(PowerRecord.account_id == account_id)
                    .order_by(desc(PowerRecord.recorded_at))
                    .limit(limit))
            result = await session.execute(stmt)
            return list(result.scalars().all())
