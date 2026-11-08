"""One worker thread for ALL model (torch) work in the backend process.

Why a single process-wide thread: on Apple MPS, two threads issuing Metal
work at the same time hard-crashes the whole process with an uncatchable
assertion ("A command encoder is already encoding to this command buffer").
Reproduced two ways before this module existed:

- POST /api/live/configure while Live was streaming — the detector build
  (weights -> GPU) ran on the default executor while a live detection ran
  on the live-detect worker.
- An Extract job running while Live streamed — the analyze runner's
  detection ran on the default executor alongside live detection.

Every router that touches a model (Live detect/build, Extract build/run,
Generate) submits its GPU work here, so at most one piece of model work runs
at a time. Long jobs must submit work in small steps (Extract steps its
per-batch generator one ``next()`` at a time) so live detection interleaves
between batches instead of waiting for a whole video.

Serializing also on CPU/CUDA costs a little throughput only when two model
consumers are active at once, and torch's own intra-op thread pool already
uses all cores, so the single worker doesn't leave the machine idle.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

GPU_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="gpu")
