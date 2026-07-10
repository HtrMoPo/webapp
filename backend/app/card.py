"""Model card (YAML front matter + Markdown body) parsing/validation.

Mirrors HTRMoPo's v1 schema (see app/schema/NOTICE.md) and its custom
jsonschema format checkers for licenses / ISO 639-3 / ISO 15924 codes.
"""

import json
import re
from dataclasses import dataclass
from importlib import resources

import markdown as md
import yaml
from jsonschema import FormatChecker
from jsonschema.exceptions import ValidationError
from jsonschema.validators import Draft7Validator

from app import vocab

_YAML_DELIM = r"(?:---|\+\+\+)"
_YAML_REGEX = re.compile(r"^\s*" + _YAML_DELIM + r"(.*?)" + _YAML_DELIM + r"\s*(.+)$", re.S | re.M)

_ORCID_ID_RE = re.compile(r"(\d{4}-\d{4}-\d{4}-\d{3}[\dX])")

with resources.files("app.schema").joinpath("v1.metadata.schema.json").open() as fp:
    V1_SCHEMA = json.load(fp)

with resources.files("app.schema").joinpath("v0.metadata.schema.json").open() as fp:
    V0_SCHEMA = json.load(fp)

format_checker = FormatChecker()


@format_checker.checks("okfn-license")
def _check_license(instance: object) -> bool:
    if not isinstance(instance, str):
        return True
    return instance in vocab.licenses()


@format_checker.checks("iso-639-3")
def _check_iso_639_3(instance: object) -> bool:
    if not isinstance(instance, str):
        return True
    return instance in vocab.iso639_3()


@format_checker.checks("iso-15924")
def _check_iso_15924(instance: object) -> bool:
    if not isinstance(instance, str):
        return True
    return instance in vocab.iso15924()


class CardValidationError(Exception):
    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("; ".join(errors))


@dataclass
class ParsedCard:
    metadata: dict
    body_md: str


def parse_card(card_text: str) -> ParsedCard:
    match = _YAML_REGEX.match(card_text)
    if not match:
        raise CardValidationError(["Card is not valid: missing YAML front matter delimited by '---'."])
    header, body = match.groups()
    metadata = yaml.safe_load(header) or {}
    return ParsedCard(metadata=metadata, body_md=body)


def validate_metadata(metadata: dict) -> None:
    validator_errors: list[str] = []
    validator = Draft7Validator(V1_SCHEMA, format_checker=format_checker)
    for error in validator.iter_errors(metadata):
        validator_errors.append(_format_error(error))
    if validator_errors:
        raise CardValidationError(validator_errors)


def validate_v0_metadata(metadata: dict) -> None:
    """Validates a legacy v0 `metadata.json` payload (see V0_SCHEMA). v0 is
    the pre-HTRMoPo-v1 format: a standalone JSON file rather than YAML front
    matter in a README.md, only ever used for kraken text-recognition models.
    This app never *writes* v0 metadata (publishing is always v1), but v0
    records still exist on Zenodo and are read here so they show up in the
    catalog and can be upgraded to v1 by their owner (see v0_to_v1_metadata,
    app.harvest, app.claim)."""
    validator_errors: list[str] = []
    validator = Draft7Validator(V0_SCHEMA, format_checker=format_checker)
    for error in validator.iter_errors(metadata):
        validator_errors.append(_format_error(error))
    if validator_errors:
        raise CardValidationError(validator_errors)


def v0_to_v1_metadata(v0: dict) -> tuple[dict, str]:
    """Best-effort conversion of a legacy v0 `metadata.json` dict to the v1
    metadata structure used everywhere else in this app, returning
    ``(metadata, body_md)``.

    Mirrors htrmopo.repo._build_v0_record's field mapping:
      * the v0 long-form ``description`` becomes the card body (v1's README
        Markdown), not a metadata field;
      * ``accuracy`` (a 0-100 percentage) becomes a ``cer`` metric
        (``100 - accuracy``);
      * ``authors`` (name + affiliation, no ORCID in v0) carry over as-is;
      * ``name`` (the model filename) and ``graphemes`` have no v1 equivalent
        and are dropped.

    Fields the v1 schema requires but v0 has no source for are filled with
    the only sensible defaults for these records: ``model_type`` is
    ``["recognition"]`` and ``software_name`` is ``"kraken"`` (v0 only ever
    described kraken recognition models). ``language`` is left empty -- v0
    records carry no language, and the owner supplies it when upgrading to v1
    (card.validate_metadata gates on it at publish time)."""
    authors = []
    for a in v0.get("authors", []):
        author = {"name": a.get("name", "")}
        if a.get("affiliation"):
            author["affiliation"] = a["affiliation"]
        authors.append(author)

    metadata: dict = {
        "summary": v0.get("summary", ""),
        "authors": authors or [{"name": ""}],
        "license": v0.get("license", ""),
        "software_name": "kraken",
        "language": [],
        "script": list(v0.get("script", [])),
        "model_type": ["recognition"],
    }

    accuracy = v0.get("accuracy")
    if accuracy is not None:
        try:
            metadata["metrics"] = {"cer": round(100 - float(accuracy), 4)}
        except (TypeError, ValueError):
            pass

    return metadata, v0.get("description", "") or ""


def _format_error(error: ValidationError) -> str:
    path = "/".join(str(p) for p in error.path) or "<root>"
    return f"{path}: {error.message}"


def render_body_html(body_md: str) -> str:
    """Renders the card body (real Markdown -- the frontend's WYSIWYG editor
    converts its HTML to Markdown before ever sending it here) to HTML for
    Zenodo's `description` field. The README.md file itself keeps the
    Markdown source as-is (see build_card_text), matching the HTRMoPo
    convention and what harvested community records' READMEs already are."""
    return md.markdown(body_md)


def _normalize_orcid(value: str) -> str:
    """The v1 schema requires authors[].orcid as a full URI (format: uri),
    but typing that prefix by hand is cumbersome -- the form only asks for
    the bare id (e.g. "0000-0002-1825-0097") and this turns it into
    "https://orcid.org/0000-0002-1825-0097" here instead. Already-full
    values (e.g. from app.harvest/app.claim, which get them straight from
    Zenodo in bare form and build the URI themselves) pass through as-is."""
    match = _ORCID_ID_RE.search(value)
    return f"https://orcid.org/{match.group(1)}" if match else value


def _normalize_people(metadata: dict) -> dict:
    metadata = dict(metadata)
    for key in ("authors", "contributors"):
        people = metadata.get(key)
        if not people:
            continue
        metadata[key] = [
            {**p, "orcid": _normalize_orcid(p["orcid"])} if p.get("orcid") else p for p in people
        ]
    return metadata


def build_card_text(metadata: dict, body_md: str) -> str:
    header = yaml.dump(_normalize_people(metadata), sort_keys=False, allow_unicode=True)
    return f"---\n{header}---\n{body_md}"
