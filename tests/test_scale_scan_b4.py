"""B4 — HC900 operational runs: scan endpoint lifecycle, reprocess tracking.

Covers:
  A. Scan run lifecycle — run created before subprocess, closed on exit
  B. Scan idempotency — X-Idempotency-Key dedup semantics
  C. Scan anti-overlap — concurrent ble_scan rejected with 409
  D. Scan provenance — subprocess receives --ingestion-run-id, device/agent ids
  E. Reprocess tracking — per-payload IngestionRun, idempotency, counters
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import app.api.v1.integrations as integrations_mod
from app.models.agent_instance import AgentInstance
from app.models.data_source import DataSource
from app.models.ingestion_run import IngestionRun
from app.models.ingestion_run_payload import IngestionRunPayload
from app.models.measurement import Measurement
from app.models.raw_payload import RawPayload
from app.models.user import User
from app.models.user_device import UserDevice
from scripts.reprocess_hc900 import find_payloads, reprocess_one


# ── Shared helpers ────────────────────────────────────────────────────────────

_HC900_PAYLOAD = {
    "measured_at": "2026-04-17T07:30:00+00:00",
    "decoded": {"decoder_version": "hc900_ble_v2", "weight_kg": 75.0},
    "user_profile_snapshot": {
        "height_cm": 175,
        "birth_date": "1990-01-01",
        "age": 36,
        "sex": 1,
    },
}


class _FakeProc:
    def __init__(self, returncode: int = 0, stdout: bytes = b"ok", stderr: bytes = b""):
        self.returncode = returncode
        self._out = stdout
        self._err = stderr

    async def communicate(self):
        return self._out, self._err

    def kill(self):
        pass

    async def wait(self):
        pass


class _SlowProc:
    """Simulates a hung subprocess — used for timeout tests."""
    returncode = None

    async def communicate(self):
        await asyncio.sleep(3600)
        return b"", b""

    def kill(self):
        pass

    async def wait(self):
        pass


def _mock_proc(monkeypatch, *, returncode: int = 0, stdout: bytes = b"ok", stderr: bytes = b""):
    """Replace asyncio.create_subprocess_exec in the integrations module."""
    captured: dict = {}

    async def _factory(*args, **kwargs):
        captured["args"] = args
        return _FakeProc(returncode, stdout, stderr)

    monkeypatch.setattr(integrations_mod.asyncio, "create_subprocess_exec", _factory)
    return captured


def _mock_proc_timeout(monkeypatch):
    """Simulate a subprocess that never returns, with a tiny timeout."""
    async def _factory(*args, **kwargs):
        return _SlowProc()

    monkeypatch.setattr(integrations_mod.asyncio, "create_subprocess_exec", _factory)
    monkeypatch.setattr(integrations_mod.settings, "scale_scan_timeout", 0.001)


async def _hc900_source_id(db: AsyncSession) -> int:
    return await db.scalar(select(DataSource.id).where(DataSource.slug == "hc900_ble"))


async def _make_hc900_raw_payload(db: AsyncSession, user: User) -> RawPayload:
    source_id = await _hc900_source_id(db)
    p = RawPayload(
        user_id=user.id,
        source_id=source_id,
        payload_type="hc900_scale",
        payload_json=_HC900_PAYLOAD,
    )
    db.add(p)
    await db.flush()
    return p


# ── A. Scan run lifecycle ─────────────────────────────────────────────────────


class TestScanRunLifecycleB4:
    async def test_successful_scan_creates_completed_run(
        self, db: AsyncSession, client, user: User, monkeypatch
    ):
        """A successful scan closes the run as completed."""
        _mock_proc(monkeypatch)
        resp = await client.post(f"/api/v1/integrations/scale/scan?user_id={user.id}")
        assert resp.status_code == 200

        run = await db.scalar(
            select(IngestionRun).where(
                IngestionRun.user_id == user.id,
                IngestionRun.operation_type == "ble_scan",
            )
        )
        assert run is not None
        assert run.status == "completed"
        assert run.finished_at is not None

    async def test_failed_subprocess_marks_run_failed(
        self, db: AsyncSession, client, user: User, monkeypatch
    ):
        """A non-zero exit from import_scale.py closes the run as failed."""
        _mock_proc(monkeypatch, returncode=1, stderr=b"ERROR scan error")
        resp = await client.post(f"/api/v1/integrations/scale/scan?user_id={user.id}")
        assert resp.status_code == 502

        run = await db.scalar(
            select(IngestionRun).where(
                IngestionRun.user_id == user.id,
                IngestionRun.operation_type == "ble_scan",
            )
        )
        assert run is not None
        assert run.status == "failed"
        assert run.finished_at is not None

    async def test_timeout_marks_run_failed(
        self, db: AsyncSession, client, user: User, monkeypatch
    ):
        """A BLE scan timeout closes the run as failed."""
        _mock_proc_timeout(monkeypatch)
        resp = await client.post(f"/api/v1/integrations/scale/scan?user_id={user.id}")
        assert resp.status_code == 504

        run = await db.scalar(
            select(IngestionRun).where(
                IngestionRun.user_id == user.id,
                IngestionRun.operation_type == "ble_scan",
            )
        )
        assert run is not None
        assert run.status == "failed"

    async def test_run_has_correct_operation_and_trigger(
        self, db: AsyncSession, client, user: User, monkeypatch
    ):
        """Scan runs use operation_type=ble_scan and trigger_type=ui_button."""
        _mock_proc(monkeypatch)
        resp = await client.post(f"/api/v1/integrations/scale/scan?user_id={user.id}")
        assert resp.status_code == 200

        run = await db.scalar(
            select(IngestionRun).where(
                IngestionRun.user_id == user.id,
                IngestionRun.operation_type == "ble_scan",
            )
        )
        assert run.operation_type == "ble_scan"
        assert run.trigger_type == "ui_button"

    async def test_run_status_is_running_when_subprocess_starts(
        self, db: AsyncSession, client, user: User, monkeypatch
    ):
        """The run is in 'running' status at the moment import_scale.py is invoked."""
        captured_status: dict = {}

        async def spy_proc(*args, **kwargs):
            cmd = list(args)
            run_id = uuid.UUID(cmd[cmd.index("--ingestion-run-id") + 1])
            run = await db.get(IngestionRun, run_id)
            captured_status["at_launch"] = run.status
            return _FakeProc(0)

        monkeypatch.setattr(integrations_mod.asyncio, "create_subprocess_exec", spy_proc)

        resp = await client.post(f"/api/v1/integrations/scale/scan?user_id={user.id}")
        assert resp.status_code == 200
        assert captured_status.get("at_launch") == "running"


# ── B. Idempotency ────────────────────────────────────────────────────────────


class TestScanIdempotencyB4:
    async def test_running_key_returns_409(
        self, db: AsyncSession, client, user: User, monkeypatch
    ):
        """A running run with the same idempotency key blocks the new request."""
        source_id = await _hc900_source_id(db)
        existing = IngestionRun(
            user_id=user.id,
            source_id=source_id,
            operation_type="ble_scan",
            trigger_type="ui_button",
            idempotency_key="scan-key-001",
            status="running",
        )
        db.add(existing)
        await db.flush()

        resp = await client.post(
            f"/api/v1/integrations/scale/scan?user_id={user.id}",
            headers={"X-Idempotency-Key": "scan-key-001"},
        )
        assert resp.status_code == 409

    async def test_completed_key_returns_200_without_new_run(
        self, db: AsyncSession, client, user: User, monkeypatch
    ):
        """A completed run with the same key is an idempotent success — no new run."""
        source_id = await _hc900_source_id(db)
        existing = IngestionRun(
            user_id=user.id,
            source_id=source_id,
            operation_type="ble_scan",
            trigger_type="ui_button",
            idempotency_key="scan-key-done",
            status="completed",
        )
        db.add(existing)
        await db.flush()

        count_before = await db.scalar(
            select(func.count()).select_from(IngestionRun).where(
                IngestionRun.user_id == user.id,
                IngestionRun.operation_type == "ble_scan",
            )
        )

        resp = await client.post(
            f"/api/v1/integrations/scale/scan?user_id={user.id}",
            headers={"X-Idempotency-Key": "scan-key-done"},
        )
        assert resp.status_code == 200

        count_after = await db.scalar(
            select(func.count()).select_from(IngestionRun).where(
                IngestionRun.user_id == user.id,
                IngestionRun.operation_type == "ble_scan",
            )
        )
        assert count_after == count_before

    async def test_failed_key_allows_retry(
        self, db: AsyncSession, client, user: User, monkeypatch
    ):
        """A failed run with the same key is retried — a new run is created."""
        _mock_proc(monkeypatch)
        source_id = await _hc900_source_id(db)
        failed = IngestionRun(
            user_id=user.id,
            source_id=source_id,
            operation_type="ble_scan",
            trigger_type="ui_button",
            idempotency_key="scan-key-retry",
            status="failed",
        )
        db.add(failed)
        await db.flush()

        resp = await client.post(
            f"/api/v1/integrations/scale/scan?user_id={user.id}",
            headers={"X-Idempotency-Key": "scan-key-retry"},
        )
        assert resp.status_code == 200

        # The old run's key was released; a new completed run was created
        new_run = await db.scalar(
            select(IngestionRun).where(
                IngestionRun.idempotency_key == "scan-key-retry",
                IngestionRun.status == "completed",
            )
        )
        assert new_run is not None
        assert new_run.id != failed.id

        await db.refresh(failed)
        assert failed.idempotency_key is None


# ── C. Anti-overlap ───────────────────────────────────────────────────────────


class TestScanAntiOverlapB4:
    async def test_running_scan_blocks_new_scan(
        self, db: AsyncSession, client, user: User, monkeypatch
    ):
        """A running ble_scan for the same user/source returns 409."""
        source_id = await _hc900_source_id(db)
        running = IngestionRun(
            user_id=user.id,
            source_id=source_id,
            operation_type="ble_scan",
            trigger_type="ui_button",
            status="running",
        )
        db.add(running)
        await db.flush()

        resp = await client.post(f"/api/v1/integrations/scale/scan?user_id={user.id}")
        assert resp.status_code == 409

    async def test_completed_scan_does_not_block_new_scan(
        self, db: AsyncSession, client, user: User, monkeypatch
    ):
        """A completed ble_scan does not prevent a new scan from starting."""
        _mock_proc(monkeypatch)
        source_id = await _hc900_source_id(db)
        completed = IngestionRun(
            user_id=user.id,
            source_id=source_id,
            operation_type="ble_scan",
            trigger_type="ui_button",
            status="completed",
        )
        db.add(completed)
        await db.flush()

        resp = await client.post(f"/api/v1/integrations/scale/scan?user_id={user.id}")
        assert resp.status_code == 200


# ── D. Provenance ─────────────────────────────────────────────────────────────


class TestScanProvenanceB4:
    async def test_subprocess_receives_ingestion_run_id(
        self, db: AsyncSession, client, user: User, monkeypatch
    ):
        """import_scale.py is always called with --ingestion-run-id."""
        captured = _mock_proc(monkeypatch)
        resp = await client.post(f"/api/v1/integrations/scale/scan?user_id={user.id}")
        assert resp.status_code == 200

        cmd = list(captured["args"])
        assert "--ingestion-run-id" in cmd
        run_id = uuid.UUID(cmd[cmd.index("--ingestion-run-id") + 1])
        run = await db.get(IngestionRun, run_id)
        assert run is not None

    async def test_user_device_id_passed_when_mac_matches(
        self, db: AsyncSession, client, user: User, monkeypatch
    ):
        """--user-device-id is included when a UserDevice for the MAC exists."""
        source_id = await _hc900_source_id(db)
        device = UserDevice(
            user_id=user.id,
            source_id=source_id,
            device_type="scale",
            identifier="a0915c92cf17",
            identifier_type="mac",
        )
        db.add(device)
        await db.flush()

        captured = _mock_proc(monkeypatch)
        resp = await client.post(
            f"/api/v1/integrations/scale/scan?user_id={user.id}&mac=A0:91:5C:92:CF:17"
        )
        assert resp.status_code == 200

        cmd = list(captured["args"])
        assert "--user-device-id" in cmd
        device_id = uuid.UUID(cmd[cmd.index("--user-device-id") + 1])
        assert device_id == device.id

    async def test_agent_instance_id_passed_when_active_agent_exists(
        self, db: AsyncSession, client, user: User, monkeypatch
    ):
        """--agent-instance-id is included when an active AgentInstance exists."""
        agent = AgentInstance(
            user_id=user.id,
            install_id="test-install-001",
            agent_type="local_pc",
            is_active=True,
        )
        db.add(agent)
        await db.flush()

        captured = _mock_proc(monkeypatch)
        resp = await client.post(f"/api/v1/integrations/scale/scan?user_id={user.id}")
        assert resp.status_code == 200

        cmd = list(captured["args"])
        assert "--agent-instance-id" in cmd
        agent_id = uuid.UUID(cmd[cmd.index("--agent-instance-id") + 1])
        assert agent_id == agent.id

    async def test_no_user_device_flag_for_unknown_mac(
        self, db: AsyncSession, client, user: User, monkeypatch
    ):
        """--user-device-id is omitted when no UserDevice matches the MAC."""
        captured = _mock_proc(monkeypatch)
        resp = await client.post(
            f"/api/v1/integrations/scale/scan?user_id={user.id}&mac=FF:FF:FF:FF:FF:FF"
        )
        assert resp.status_code == 200
        assert "--user-device-id" not in list(captured["args"])


# ── E. Reprocess tracking ─────────────────────────────────────────────────────


class TestReprocessTrackingB4:
    async def test_reprocess_creates_run_with_reprocessed_role(
        self, db: AsyncSession, user: User
    ):
        """reprocess_one creates an IngestionRun and links with role='reprocessed'."""
        from app.services.ingestion import IngestionService

        payload = await _make_hc900_raw_payload(db, user)
        source_id = await _hc900_source_id(db)
        svc = IngestionService(db)

        summary = await reprocess_one(db, svc, payload, source_id, dry_run=False)

        assert summary["action"] == "reprocessed"
        run = await db.scalar(
            select(IngestionRun).where(
                IngestionRun.user_id == user.id,
                IngestionRun.operation_type == "replay",
            )
        )
        assert run is not None
        assert run.status == "completed"
        assert run.trigger_type == "manual"

        link = await db.scalar(
            select(IngestionRunPayload).where(
                IngestionRunPayload.run_id == run.id,
                IngestionRunPayload.payload_id == payload.id,
            )
        )
        assert link is not None
        assert link.role == "reprocessed"

    async def test_reprocess_counters(
        self, db: AsyncSession, user: User
    ):
        """measurements_deleted and measurements_created are populated."""
        from app.services.ingestion import IngestionService

        payload = await _make_hc900_raw_payload(db, user)
        source_id = await _hc900_source_id(db)
        svc = IngestionService(db)

        # First pass — create measurements
        await svc._process(payload)
        await db.flush()
        before_count = await db.scalar(
            select(func.count()).select_from(Measurement)
            .where(Measurement.raw_payload_id == payload.id)
        )
        assert before_count >= 1

        # Reprocess
        summary = await reprocess_one(db, svc, payload, source_id, dry_run=False)

        run = await db.get(IngestionRun, uuid.UUID(summary["run_id"]))
        assert run.measurements_deleted == before_count
        assert run.measurements_created >= 1

    async def test_reprocess_skip_without_force(
        self, db: AsyncSession, user: User
    ):
        """Second call without --force is skipped when a completed run exists."""
        from app.services.ingestion import IngestionService

        payload = await _make_hc900_raw_payload(db, user)
        source_id = await _hc900_source_id(db)
        svc = IngestionService(db)

        # First reprocess completes normally
        s1 = await reprocess_one(db, svc, payload, source_id, dry_run=False)
        assert s1["action"] == "reprocessed"

        # Second call without --force → skip
        s2 = await reprocess_one(db, svc, payload, source_id, dry_run=False, force=False)
        assert s2["action"] == "skipped"

    async def test_reprocess_force_overrides_skip(
        self, db: AsyncSession, user: User
    ):
        """--force allows re-running a payload that was already reprocessed."""
        from app.services.ingestion import IngestionService

        payload = await _make_hc900_raw_payload(db, user)
        source_id = await _hc900_source_id(db)
        svc = IngestionService(db)

        s1 = await reprocess_one(db, svc, payload, source_id, dry_run=False)
        assert s1["action"] == "reprocessed"

        s2 = await reprocess_one(db, svc, payload, source_id, dry_run=False, force=True)
        assert s2["action"] == "reprocessed"

        # Two completed runs exist; old one had its key cleared
        run_count = await db.scalar(
            select(func.count()).select_from(IngestionRun).where(
                IngestionRun.user_id == user.id,
                IngestionRun.operation_type == "replay",
            )
        )
        assert run_count == 2

    async def test_reprocess_idempotency_key_is_per_payload(
        self, db: AsyncSession, user: User
    ):
        """Each payload gets a unique idempotency key based on payload_id."""
        from app.services.ingestion import IngestionService

        source_id = await _hc900_source_id(db)
        p1 = await _make_hc900_raw_payload(db, user)
        p2 = await _make_hc900_raw_payload(db, user)
        svc = IngestionService(db)

        s1 = await reprocess_one(db, svc, p1, source_id, dry_run=False)
        s2 = await reprocess_one(db, svc, p2, source_id, dry_run=False)

        assert s1["run_id"] != s2["run_id"]
        run1 = await db.get(IngestionRun, uuid.UUID(s1["run_id"]))
        run2 = await db.get(IngestionRun, uuid.UUID(s2["run_id"]))
        assert run1.idempotency_key != run2.idempotency_key
