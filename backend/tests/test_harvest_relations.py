import httpx
import pytest
import respx

from app.harvest import _fetch_paper_title, _parse_related_identifiers, refresh_download_stats
from tests.conftest import make_record, make_version


class TestParseRelatedIdentifiers:
    def test_obsoleted_by(self):
        result = _parse_related_identifiers(
            [{"relation": "isObsoletedBy", "identifier": "10.5281/zenodo.1", "scheme": "doi"}]
        )
        assert result["obsoleted_by_doi"] == "10.5281/zenodo.1"
        assert result["variant_of_doi"] is None
        assert result["documented_by"] == []

    def test_variant_of_accepted_when_doi_and_model(self):
        result = _parse_related_identifiers(
            [
                {
                    "relation": "isVariantFormOf",
                    "identifier": "10.5281/zenodo.2",
                    "scheme": "doi",
                    "resource_type": "model",
                }
            ]
        )
        assert result["variant_of_doi"] == "10.5281/zenodo.2"

    def test_variant_of_rejected_when_not_doi_scheme(self):
        result = _parse_related_identifiers(
            [
                {
                    "relation": "isVariantFormOf",
                    "identifier": "https://example.com/x",
                    "scheme": "url",
                    "resource_type": "model",
                }
            ]
        )
        assert result["variant_of_doi"] is None

    def test_variant_of_rejected_when_not_model_resource_type(self):
        result = _parse_related_identifiers(
            [
                {
                    "relation": "isVariantFormOf",
                    "identifier": "10.5281/zenodo.2",
                    "scheme": "doi",
                    "resource_type": "dataset",
                }
            ]
        )
        assert result["variant_of_doi"] is None

    def test_multiple_documented_by_collected(self):
        result = _parse_related_identifiers(
            [
                {
                    "relation": "isDocumentedBy",
                    "identifier": "10.5334/johd.97",
                    "scheme": "doi",
                    "resource_type": "publication-datapaper",
                },
                {
                    "relation": "isDocumentedBy",
                    "identifier": "https://hal.science/hal-02577236",
                    "scheme": "url",
                    "resource_type": "publication-article",
                },
            ]
        )
        assert result["documented_by"] == [
            {"identifier": "10.5334/johd.97", "scheme": "doi", "resource_type": "publication-datapaper"},
            {
                "identifier": "https://hal.science/hal-02577236",
                "scheme": "url",
                "resource_type": "publication-article",
            },
        ]

    def test_missing_identifier_skipped(self):
        result = _parse_related_identifiers([{"relation": "isDocumentedBy"}])
        assert result["documented_by"] == []


class TestFetchPaperTitle:
    async def test_doi_scheme_uses_csl_json(self, respx_mock):
        respx_mock.get("https://doi.org/10.5334/johd.97").mock(
            return_value=httpx.Response(200, json={"title": "A Paper Title"})
        )
        async with httpx.AsyncClient() as client:
            title = await _fetch_paper_title(client, "10.5334/johd.97", "doi")
        assert title == "A Paper Title"

    async def test_url_scheme_scrapes_title_tag(self, respx_mock):
        respx_mock.get("https://hal.science/hal-1").mock(
            return_value=httpx.Response(200, text="<html><head><title>HAL Paper &amp; Co</title></head></html>")
        )
        async with httpx.AsyncClient() as client:
            title = await _fetch_paper_title(client, "https://hal.science/hal-1", "url")
        assert title == "HAL Paper & Co"

    async def test_failure_returns_none(self, respx_mock):
        respx_mock.get("https://hal.science/missing").mock(return_value=httpx.Response(404))
        async with httpx.AsyncClient() as client:
            title = await _fetch_paper_title(client, "https://hal.science/missing", "url")
        assert title is None


@pytest.mark.usefixtures("db_session")
class TestRefreshDownloadStatsCaching:
    async def test_cached_paper_title_is_never_refetched(self, db_session, respx_mock):
        record = make_record(concept_doi="10.5281/zenodo.100")
        db_session.add(record)
        await db_session.flush()
        version = make_version(record, version_doi="10.5281/zenodo.101")
        db_session.add(version)
        await db_session.commit()

        related_identifiers = [
            {
                "relation": "isDocumentedBy",
                "identifier": "10.1234/paper",
                "scheme": "doi",
                "resource_type": "publication",
            }
        ]
        respx_mock.get("https://zenodo.org/api/records/101").mock(
            return_value=httpx.Response(
                200,
                json={"stats": {"downloads": 1, "views": 2}, "metadata": {"related_identifiers": related_identifiers}},
            )
        )
        doi_route = respx_mock.get("https://doi.org/10.1234/paper").mock(
            return_value=httpx.Response(200, json={"title": "Resolved Title"})
        )

        await refresh_download_stats(db_session)
        await refresh_download_stats(db_session)

        assert doi_route.call_count == 1
        await db_session.refresh(record)
        assert record.documented_by == [
            {"identifier": "10.1234/paper", "scheme": "doi", "resource_type": "publication", "title": "Resolved Title"}
        ]
