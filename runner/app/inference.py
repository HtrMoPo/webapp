"""Runs kraken (segmentation + recognition, optionally with a D-Fine region
model) via kraken's internal Python API (kraken.tasks.*TaskModel), rather
than shelling out to the `kraken` CLI.

Verified against a real kraken 7.0.2 + dfine_kraken 0.4.2 install
(2026-07-23) by loading real models and inspecting the actual objects
returned -- notably:

- `SegmentationTaskModel.load_model(path)` / `RecognitionTaskModel.load_model(path)`
  each load from a SINGLE file. The CLI's `segment -i` looks pluralized
  ("Baseline/region detection model(s) to use") but the underlying click
  option is not `multiple=True` and `load_model` takes one path -- there is
  no supported way to merge a separate baseline (blla) model with a
  separate D-Fine region model in one segmentation pass. A D-Fine region
  model (per dfine_kraken's own README: "The default configuration trains
  lines and regions jointly") is a complete, standalone replacement for the
  plain segmentation model, not an add-on to it -- so when one is given
  here it's used *instead of* the segmentation model, not alongside it.
- The recognized text on each predicted line lives on a `.prediction`
  property (backed by a private `_prediction` attribute), NOT on the
  dataclass's own `text` field -- `dataclasses.asdict()` on a prediction
  silently gives `text: None`. The JSON below is therefore built by hand
  from `.prediction`/`.baseline`/`.boundary` rather than via `asdict()`.

Known limitation versus the previous subprocess-based implementation: this
runs in-process via a thread executor. A timeout here abandons the
executor thread rather than killing a subprocess -- the underlying kraken
call keeps consuming CPU in the background until it finishes on its own,
since CPython threads can't be forcibly stopped. Acceptable given the
runner only ever has one job in flight at a time, but worth knowing if
this is ever changed.
"""

import asyncio
import dataclasses
import functools
from pathlib import Path

_DIRECTION_MAP = {
    "ltr": "horizontal-lr",
    "rtl": "horizontal-rl",
}


class InferenceError(Exception):
    pass


def _region_boundary(region) -> list | None:
    boundary = getattr(region, "boundary", None)
    return [list(p) for p in boundary] if boundary else None


def _run_sync(
    image_path: Path,
    segmentation_model_path: Path,
    recognition_model_path: Path,
    region_model_path: Path | None,
    direction: str,
    threads: int,
) -> dict:
    from kraken.configs import RecognitionInferenceConfig, SegmentationInferenceConfig
    from kraken.lib.util import open_image
    from kraken.tasks import RecognitionTaskModel, SegmentationTaskModel

    im = open_image(str(image_path))
    text_direction = _DIRECTION_MAP[direction]

    # See module docstring: a region model replaces the segmentation model
    # rather than combining with it.
    seg_path = region_model_path or segmentation_model_path
    seg_model = SegmentationTaskModel.load_model(str(seg_path))
    seg_config = SegmentationInferenceConfig(text_direction=text_direction, num_threads=threads)
    segmentation = seg_model.predict(im=im, config=seg_config)

    reco_model = RecognitionTaskModel.load_model(str(recognition_model_path))
    reco_config = RecognitionInferenceConfig(num_threads=threads)
    predictions = list(reco_model.predict(im=im, segmentation=segmentation, config=reco_config))

    lines = [
        {
            "text": pred.prediction,
            "baseline": [list(p) for p in pred.baseline] if pred.baseline else None,
            "boundary": [list(p) for p in pred.boundary] if pred.boundary else None,
        }
        for pred in predictions
    ]

    regions = {}
    for region_type, region_list in (segmentation.regions or {}).items():
        boundaries = [b for r in region_list if (b := _region_boundary(r))]
        if boundaries:
            regions[region_type] = boundaries

    return {"direction": direction, "image_size": list(im.size), "lines": lines, "regions": regions}


async def run_pipeline(
    image_path: Path,
    segmentation_model_path: Path,
    recognition_model_path: Path,
    region_model_path: Path | None,
    direction: str,
    threads: int,
    timeout_seconds: int,
) -> dict:
    loop = asyncio.get_running_loop()
    call = functools.partial(
        _run_sync,
        image_path,
        segmentation_model_path,
        recognition_model_path,
        region_model_path,
        direction,
        threads,
    )
    try:
        return await asyncio.wait_for(loop.run_in_executor(None, call), timeout=timeout_seconds)
    except asyncio.TimeoutError as exc:
        raise InferenceError(f"kraken timed out after {timeout_seconds}s") from exc
    except Exception as exc:
        raise InferenceError(str(exc)) from exc
