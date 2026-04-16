import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.schemas.common import BaseSchema, PaginatedResponse, TZDatetime

# --- Definitions ---


class MedicationDefinitionCreate(BaseModel):
    name: str = Field(max_length=255)
    active_ingredient: str | None = None
    dosage_form: str | None = Field(
        None, description="tablet, capsule, liquid, injection, topical, inhaler"
    )
    description: str | None = None


class MedicationDefinitionResponse(BaseSchema):
    id: int
    name: str
    active_ingredient: str | None
    dosage_form: str | None
    description: str | None
    created_at: datetime


# --- Regimens ---


class MedicationRegimenCreate(BaseModel):
    user_id: uuid.UUID
    medication_id: int
    dosage_amount: Decimal = Field(max_digits=7, decimal_places=2)
    dosage_unit: str = Field(max_length=31)
    frequency: str = Field(description="daily, twice_daily, three_times_daily, weekly, as_needed")
    instructions: str | None = None
    prescribed_by: str | None = None
    started_at: date
    ended_at: date | None = None


class MedicationRegimenResponse(BaseSchema):
    id: uuid.UUID
    user_id: uuid.UUID
    medication_id: int
    medication_name: str | None = None
    dosage_amount: Decimal
    dosage_unit: str
    frequency: str
    instructions: str | None
    prescribed_by: str | None
    started_at: date
    ended_at: date | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class MedicationRegimenList(PaginatedResponse):
    items: list[MedicationRegimenResponse]


# --- Logs ---


class MedicationLogCreate(BaseModel):
    user_id: uuid.UUID
    regimen_id: uuid.UUID
    status: str = Field(description="taken, skipped, delayed")
    scheduled_at: TZDatetime
    taken_at: TZDatetime | None = None
    dosage_amount: Decimal | None = None
    dosage_unit: str | None = None
    notes: str | None = None
    recorded_at: TZDatetime


class MedicationLogResponse(BaseSchema):
    id: uuid.UUID
    user_id: uuid.UUID
    regimen_id: uuid.UUID
    status: str
    scheduled_at: datetime
    taken_at: datetime | None
    dosage_amount: Decimal | None
    dosage_unit: str | None
    notes: str | None
    recorded_at: datetime
    ingested_at: datetime


class MedicationLogList(PaginatedResponse):
    items: list[MedicationLogResponse]
