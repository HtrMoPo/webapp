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
