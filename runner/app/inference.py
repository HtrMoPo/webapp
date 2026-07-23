"""Runs kraken (segmentation + recognition, optionally with a D-Fine region
model) via kraken's internal Python API (kraken.tasks.*TaskModel), rather
than shelling out to the `kraken` CLI.

Verified against a real kraken 7.0.2 + dfine_kraken 0.4.2 install
(2026-07-23) by loading real models and inspecting the actual objects
returned -- notably:

- `SegmentationTaskModel.load_model(path)` only loads from a SINGLE file,
  and using a D-Fine region model there alone (as its own README's CLI
  example does) only ever produced regions, 0 lines, on a real test image
  -- despite the README's claim that its default training config learns
  lines and regions jointly, the plugin's line output apparently isn't
  wired up the same way blla's is. The combination that actually works,
  confirmed by inspecting `SegmentationTaskModel.__init__`/`load_model`'s
  own source: `load_models(path)` (plural, in `kraken.models`) returns a
  *list* of models from one file, and `SegmentationTaskModel` just takes a
  list -- so loading both the baseline (blla) and region (D-Fine) files
  separately and concatenating their model lists into one
  `SegmentationTaskModel` produces both real baselines/lines *and*
  D-Fine's regions in a single predict() call.
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
    from kraken.models import load_models
    from kraken.tasks import RecognitionTaskModel, SegmentationTaskModel

    im = open_image(str(image_path))
    text_direction = _DIRECTION_MAP[direction]

    seg_models = load_models(str(segmentation_model_path))
    if region_model_path is not None:
        seg_models = seg_models + load_models(str(region_model_path))
    seg_model = SegmentationTaskModel(seg_models)
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
