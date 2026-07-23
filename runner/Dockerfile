# Isolated container for kraken + D-Fine inference (see app.playground.*
# in the main backend). Never exposes a host port -- only reachable from the
# `app` service over the docker-compose network.
FROM python:3.12-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY app ./app

# CPU-only torch build -- this container never has GPU access, and the CUDA
# build pulls in several GB of nvidia/triton packages on top of torch
# itself. A separate `pip install torch` step first doesn't work: kraken
# pins `torch<=2.10,>=2.4.0`, and if the pre-installed CPU wheel doesn't
# satisfy that exact range, the later `pip install .` re-resolves torch on
# its own and silently replaces it with the default (CUDA) build from
# PyPI. Resolving everything in one pass with the CPU index available
# keeps pip's own resolver from ever picking the CUDA build.
RUN pip install --no-cache-dir --extra-index-url https://download.pytorch.org/whl/cpu .

RUN groupadd -r runner && useradd -r -g runner -u 1000 runner \
    && mkdir -p /cache \
    && chown -R runner:runner /app /cache
USER runner

ENV MODEL_CACHE_DIR=/cache
# Caps native thread pools (OMP/OpenBLAS/MKL) and torch's own thread count --
# see app/threads.py. Kept modest by default since this shares a host with
# the main app container.
ENV RUNNER_THREADS=2

VOLUME ["/cache"]
EXPOSE 8100

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8100/healthz', timeout=3)" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8100"]
