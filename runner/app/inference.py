"""Runs kraken (segmentation + recognition, optionally with a D-Fine region
model) by shelling out to the `kraken` CLI, rather than calling internal
kraken/dfine_kraken Python APIs directly.

Verified against kraken 7.0.2 + dfine_kraken 0.4.2 (2026-07-23):
  kraken --threads N -d cpu -a -i IN OUT \
      segment -bl -i SEG_MODEL [-i REGION_MODEL] -d TEXT_DIRECTION \
      ocr -m RECO_MODEL

- `-bl`/`--baseline` selects the neural baseline segmenter (blla-style
  models); the default is the legacy box segmenter, which is not what
  published .mlmodel baseline models expect.
- `segment -i` can be repeated: kraken merges a baseline-detection model
  (blla.mlmodel) with a region-only detection model (a D-Fine
  .safetensors, loaded via dfine_kraken's `kraken.models` plugin entry
  point) rather than requiring a special combined model.
- `-a` (ALTO output) is used instead of the default "native" output
  because native output means JSON for a bare `segment` but plain text
  (no coordinates at all) once `ocr` is chained on -- ALTO is the only
  built-in format that keeps both per-line text and geometry after a
  combined segment+ocr run. Chaining `segment`+`ocr` in one process (mn a
  single kraken invocation) also avoids re-loading the segmentation
  model just to hand off to a second process.
- No `ketos convert` step is needed for D-Fine models: pretrained ones
  published to Zenodo are already inference-ready .safetensors files,
  used directly with `segment -i`.
"""

import asyncio
import xml.etree.ElementTree as ET
from pathlib import Path

_ALTO_NS = {"a": "http://www.loc.gov/standards/alto/ns-v4#"}

_DIRECTION_MAP = {
    "ltr": "horizontal-lr",
    "rtl": "horizontal-rl",
}


class InferenceError(Exception):
    pass


def _parse_alto(xml_path: Path) -> dict:
    tree = ET.parse(xml_path)
    root = tree.getroot()

    page = root.find(".//a:Page", _ALTO_NS)
    width = int(page.get("WIDTH")) if page is not None else None
    height = int(page.get("HEIGHT")) if page is not None else None

    # TextBlock/TextLine reference a tag by ID (e.g. TAGREFS="TYPE_2"); the
    # human-readable region/line type ("text", "default", ...) is only
    # available indirectly via <Tags><OtherTag ID=... LABEL=.../></Tags>.
    tag_labels = {
        tag.get("ID"): tag.get("LABEL")
        for tag in root.findall(".//a:Tags/a:OtherTag", _ALTO_NS)
        if tag.get("ID")
    }

    def polygon_points(shape_el):
        if shape_el is None:
            return None
        poly = shape_el.find("a:Polygon", _ALTO_NS)
        if poly is None or not poly.get("POINTS"):
            return None
        coords = [int(round(float(v))) for v in poly.get("POINTS").split()]
        return [[coords[i], coords[i + 1]] for i in range(0, len(coords), 2)]

    def baseline_points(text_line_el):
        raw = text_line_el.get("BASELINE")
        if not raw:
            return None
        coords = [int(round(float(v))) for v in raw.split()]
        return [[coords[i], coords[i + 1]] for i in range(0, len(coords), 2)]

    regions = {}
    for block in root.findall(".//a:TextBlock", _ALTO_NS):
        region_type = tag_labels.get(block.get("TAGREFS")) or block.get("TAGREFS") or "region"
        boundary = polygon_points(block.find("a:Shape", _ALTO_NS))
        if boundary:
            regions.setdefault(region_type, []).append(boundary)

    lines = []
    for text_line in root.findall(".//a:TextLine", _ALTO_NS):
        strings = text_line.findall("a:String", _ALTO_NS)
        text = " ".join(s.get("CONTENT", "") for s in strings)
        lines.append(
            {
                "text": text,
                "baseline": baseline_points(text_line),
                "boundary": polygon_points(text_line.find("a:Shape", _ALTO_NS)),
            }
        )

    return {"image_size": [width, height], "lines": lines, "regions": regions}


async def run_pipeline(
    image_path: Path,
    segmentation_model_path: Path,
    recognition_model_path: Path,
    region_model_path: Path | None,
    direction: str,
    threads: int,
    timeout_seconds: int,
) -> dict:
    text_direction = _DIRECTION_MAP[direction]
    output_path = image_path.with_suffix(".alto.xml")

    cmd = [
        "kraken",
        "--threads", str(threads),
        "-d", "cpu",
        "-a",
        "-i", str(image_path), str(output_path),
        "segment", "-bl", "-i", str(segmentation_model_path),
    ]
    if region_model_path is not None:
        cmd += ["-i", str(region_model_path)]
    cmd += ["-d", text_direction, "ocr", "-m", str(recognition_model_path)]

    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
    )
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout_seconds)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise InferenceError(f"kraken timed out after {timeout_seconds}s")

    if proc.returncode != 0 or not output_path.exists():
        raise InferenceError(f"kraken exited {proc.returncode}: {stdout.decode(errors='replace')[-4000:]}")

    result = _parse_alto(output_path)
    result["direction"] = direction
    return result
