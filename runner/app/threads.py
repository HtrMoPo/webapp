"""Caps the CPU/thread footprint of kraken subprocesses spawned by this
service. Inference itself runs as a `kraken` CLI subprocess (see
app.inference), which inherits this process's environment -- so setting
these here, before any subprocess is spawned, is enough; no in-process
torch import is needed in this FastAPI process itself.

kraken's own `--threads` CLI flag (see app.inference.run_pipeline) is the
primary cap; these env vars are backup for any native thread pools
(OpenBLAS/MKL) that flag doesn't reach."""

import os

RUNNER_THREADS = os.environ.get("RUNNER_THREADS", "2")
os.environ.setdefault("OMP_NUM_THREADS", RUNNER_THREADS)
os.environ.setdefault("OPENBLAS_NUM_THREADS", RUNNER_THREADS)
os.environ.setdefault("MKL_NUM_THREADS", RUNNER_THREADS)
os.environ.setdefault("VECLIB_MAXIMUM_THREADS", RUNNER_THREADS)
os.environ.setdefault("NUMEXPR_NUM_THREADS", RUNNER_THREADS)
