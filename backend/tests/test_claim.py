import httpx
import pytest

from app import claim
from app.zenodo_client import ZenodoClient
from tests.conftest import make_record, make_user, make_version

VALID_V0_METADATA = {
    "authors": [{"name": "A.Uthor", "affiliation": "Somewhere"}],
    "summary": "CATMuS Medieval 1.5.0",
    "description": "A description.",
    "accuracy": 94.3,
    "license": "CC-BY-4.0",
    "script": ["Latn"],
    "name": "catmus-medieval.mlmodel",
    "graphemes": ["a", "b"],
}


class TestFetchLegacyV0MetadataRetry:
    async def test_retries_on_gateway_error_then_succeeds(self, respx_mock, monkeypatch):
        async def no_sleep(*_args, **_kwargs):
            return None

        monkeypatch.setattr("app.http_retry.asyncio.sleep", no_sleep)

        route = respx_mock.get("https://zenodo.org/records/12743230/files/metadata.json")
        route.side_effect = [httpx.Response(503), httpx.Response(200, json=VALID_V0_METADATA)]

        result = await claim._fetch_legacy_v0_metadata("10.5281/zenodo.12743230")

        assert result == VALID_V0_METADATA
        assert route.call_count == 2


class TestSyncMyDepositionsSelfHeal:
    async def test_upgrades_stuck_placeholder_to_real_v0(self, db_session, respx_mock, monkeypatch):
        user = make_user()
        db_session.add(user)
        await db_session.flush()

        record = make_record(
            owner_user_id=user.id,
            source="app",
            concept_doi="10.5281/zenodo.10066218",
            current_title="CATMuS Medieval",
        )
        db_session.add(record)
        await db_session.flush()

        version = make_version(
            record,
            version_doi="10.5281/zenodo.12743230",
            schema_version="v1",
            is_placeholder=True,
            files=[
                {"filename": "metadata.json", "size": 100},
                {"filename": "catmus-medieval.mlmodel", "size": 200},
            ],
        )
        db_session.add(version)
        await db_session.commit()

        deposition = {
            "id": "12743230",
            "doi": "10.5281/zenodo.12743230",
            "conceptdoi": "10.5281/zenodo.10066218",
            "modified": "2024-07-15T10:27:45Z",
            "metadata": {"communities": [{"identifier": "ocr_models"}]},
        }

        async def fake_list_my_depositions(self, status="published", size=100, all_versions=True):
            return [deposition]

        monkeypatch.setattr(ZenodoClient, "list_my_depositions", fake_list_my_depositions)
        respx_mock.get("https://zenodo.org/records/12743230/files/metadata.json").mock(
            return_value=httpx.Response(200, json=VALID_V0_METADATA)
        )

        summary = await claim.sync_my_depositions(user, db_session)

        assert summary["claimed"] == 1
        await db_session.refresh(version)
        await db_session.refresh(record)
        assert version.is_placeholder is False
        assert version.schema_version == "v0"
        assert "CATMuS Medieval 1.5.0" in version.card_yaml
        assert {"filename": "metadata.json", "size": 100} not in version.files
        assert record.license == "CC-BY-4.0"
        assert record.current_title == "CATMuS Medieval 1.5.0"

    async def test_leaves_non_legacy_placeholder_alone(self, db_session, respx_mock, monkeypatch):
        """A placeholder whose files don't look like legacy v0 (e.g. only a
        model file, no metadata.json -- like CATMuS Medieval 1.6.0) is left
        untouched: there's genuinely nothing to upgrade it to."""
        user = make_user()
        db_session.add(user)
        await db_session.flush()

        record = make_record(owner_user_id=user.id, source="app", concept_doi="10.5281/zenodo.10066218")
        db_session.add(record)
        await db_session.flush()

        version = make_version(
            record,
            version_doi="10.5281/zenodo.15030337",
            schema_version="v1",
            is_placeholder=True,
            files=[{"filename": "catmus-medieval-1.6.0.mlmodel", "size": 300}],
        )
        db_session.add(version)
        await db_session.commit()

        deposition = {
            "id": "15030337",
            "doi": "10.5281/zenodo.15030337",
            "conceptdoi": "10.5281/zenodo.10066218",
            "modified": "2025-03-15T00:00:00Z",
            "metadata": {"communities": [{"identifier": "ocr_models"}]},
        }

        async def fake_list_my_depositions(self, status="published", size=100, all_versions=True):
            return [deposition]

        monkeypatch.setattr(ZenodoClient, "list_my_depositions", fake_list_my_depositions)

        summary = await claim.sync_my_depositions(user, db_session)

        assert summary["skipped"] == 1
        await db_session.refresh(version)
        assert version.is_placeholder is True
        assert version.schema_version == "v1"
