import uuid
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.daily_checkpoint import DailyCheckpoint
from app.repositories.daily_checkpoint import DailyCheckpointRepository
from app.schemas.daily_checkpoint import DailyCheckpointCreate, DailyCheckpointResponse


class DailyCheckpointService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = DailyCheckpointRepository(session)

    async def create(self, data: DailyCheckpointCreate) -> DailyCheckpointResponse:
        # Check for existing checkpoint (unique constraint will also enforce this,
        # but we give a better error message)
        existing = await self.repo.find_existing(
            data.user_id, data.checkpoint_type, data.checkpoint_date
        )
        if existing:
            raise ValueError(
                f"A {data.checkpoint_type} checkpoint already exists for "
                f"{data.checkpoint_date}. Only one per type per day is allowed."
            )

        checkpoint = DailyCheckpoint(
            user_id=data.user_id,
            checkpoint_type=data.checkpoint_type,
            checkpoint_date=data.checkpoint_date,
            checkpoint_at=data.checkpoint_at,
            mood=data.mood,
            energy=data.energy,
            sleep_quality=data.sleep_quality,
            body_state_score=data.body_state_score,
            notes=data.notes,
            recorded_at=data.recorded_at,
            context=data.context,
        )
        await self.repo.create(checkpoint)
        await self.session.commit()
        return DailyCheckpointResponse.model_validate(checkpoint)

    async def list(
        self,
        user_id: uuid.UUID,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[DailyCheckpointResponse], int]:
        items = await self.repo.list_by_user(
            user_id, start_date=start_date, end_date=end_date, offset=offset, limit=limit
        )
        total = await self.repo.count_by_user(user_id, start_date=start_date, end_date=end_date)
        return [DailyCheckpointResponse.model_validate(c) for c in items], total
