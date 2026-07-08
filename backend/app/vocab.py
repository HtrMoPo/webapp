"""Loads HTRMoPo's vendored controlled vocabularies (see app/schema/NOTICE.md)."""

import json
from functools import lru_cache
from importlib import resources


@lru_cache
def iso15924() -> dict[str, str]:
    codes: dict[str, str] = {}
    text = resources.files("app.schema").joinpath("iso15924.txt").read_text()
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        parts = line.split(";")
        if len(parts) < 3:
            continue
        code, _, name = parts[0], parts[1], parts[2]
        codes[code] = name
    return codes


@lru_cache
def iso639_3() -> dict[str, str]:
    codes: dict[str, str] = {}
    text = resources.files("app.schema").joinpath("iso639-3.txt").read_text()
    for line in text.splitlines()[1:]:
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        codes[parts[0]] = parts[1]
    return codes


@lru_cache
def licenses() -> dict[str, dict]:
    text = resources.files("app.schema").joinpath("licenses.json").read_text()
    return json.loads(text)
