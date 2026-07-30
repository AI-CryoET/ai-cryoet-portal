# Neuroglancer viewer concurrency — Phase 1 stopgap design

- **Date:** 2026-07-28
- **Status:** Approved for spec review
- **Branch context:** builds on `perf-neuroglancer` (which added the mmap load
  path, the coordinate-transform flip, and the `NEUROGLANCER_MAX_VIEWERS` bump).

## Problem

"View in Neuroglancer" degrades badly under concurrent use in production:
opening several tabs makes all of them slow, with volumes rendering grey while
chunks trickle in. This is *worse* than the pre-mmap behaviour for concurrent
users.

### Diagnosis (measured on the live cluster)

- **Not memory-bound:** pod at ~1.5 GB of a 4 GB limit; no OOM, no restarts.
- **Not CPU-bound:** with the CPU limit raised to 8 cores the pod used
  9–14 millicores while slow — idle. Raising CPU changed nothing.
- **I/O / serialization bound:** loadavg ~11 against ~0 CPU means threads are
  *blocked*, not computing.
- **Root cause:** the mmap change (`read_mrc_volume` → `mrcfile.mmap`) moved the
  slow NFS read off launch and onto the **per-chunk serving path**, inside
  neuroglancer's single, process-global in-process server. Concurrent viewers
  serialize on blocking NFS reads in that one process, so each viewer waits
  behind every other viewer's cold reads. This explains all observations:
  slowness scales with the *number of open viewers*, a warm re-open is not
  faster (you wait behind others), and CPU/memory stay idle.

Confirmed serving path: `SubvolumeHandler.get` offloads to a threadpool but
`LocalVolume.get_encoded_subvolume` does `np.array(self.data[...])` — the mmap
read (and thus the NFS page-fault) happens here, in the shared server.

### Data reality

The production catalog currently serves tomograms up to **~1.3 GB**, and a
**single** tab at that size loads acceptably. The 10 GB `gouauxlab`
reconstructions are a different collection and are **not** in the portal today.
So this is a *pure concurrency* problem at ≤~1.3 GB, not a large-volume problem.

## Goals / Non-goals

**Goals**
- Concurrent viewers (target **10–25** simultaneous tabs) stop degrading each
  other; each behaves like a single tab does today.
- Ship quickly as a stopgap — minimal code change.
- Do not reintroduce the OOM crashes.

**Non-goals (Phase 1)**
- Making large (10 GB) volumes fast — deferred; portal doesn't serve them.
- Multiscale / client-side rendering / any `.mrc`→`.zarr` conversion (the
  project lead has ruled out persistent `.zarr` copies on storage grounds).
- Supporting 25–50 concurrent viewers — that is the Phase 2 trigger.

## Constraints

- **No persistent `.zarr` files.** (On-the-fly adapters / ephemeral caches would
  be allowed, but Phase 1 needs neither.)
- Anonymous, read-only portal — no per-user identity.
- Fileglancer not deployed in this cluster (yet).
- API stays single-replica / single-worker (neuroglancer server is
  process-global) — unchanged in Phase 1.

## Design — Phase 1

The diagnosis says the regression is *NFS reads on the serving path*. Phase 1
removes them by serving from RAM again, sized so several volumes fit at once.

### 1. Revert the load path to an in-RAM copy

`read_mrc_volume` reads the volume into RAM (`.copy()`) instead of returning a
memmap. Serving chunks is then in-memory slicing — fast, no NFS on the hot path,
no cross-viewer serialization. This is the pre-regression behaviour that was
fine, now with enough memory to hold several concurrently.

**Keep** the coordinate-transform flip introduced on `perf-neuroglancer`; it is
orthogonal to copy-vs-mmap and remains the correct shape. The *only* revert is
the mmap line.

### 2. Size guard against surprise large volumes

Copying assumes volumes stay small. To prevent a future large volume (e.g. a
10 GB `gouauxlab` reconstruction entering the catalog) from OOM-killing the pod:

- If a volume's on-disk size **≤ `COPY_MAX_BYTES` (1.5 GB)** → read into RAM
  (fast serving; covers all current ≤1.3 GB volumes).
- If **> 1.5 GB** → fall back to `mmap` (slow serving, but the pod does not
  crash) and log a warning naming the file.

A large volume thus becomes a *degraded* experience and a clear signal that it's
time for Phase 2 — never an outage.

### 3. Shared loaded-volume LRU cache

Concurrent viewers of the *same* tomogram must not each hold their own copy.
Wrap the load in a process-wide `functools.lru_cache` keyed on `(path, mtime)`
(mirroring the existing `_cached_preview_png` pattern), returning
`(data, voxel_size, axis_order)`. Multiple `LocalVolume`s then share one
read-only array. `mtime` in the key means a re-scan that rewrites a file
invalidates the entry automatically.

- Cache `maxsize = 12` (aligned with `MAX_VIEWERS`).
- Applies to both copy and mmap results (uniform); the big memory consumers are
  the copy entries.

### 4. Resource sizing (the load-bearing part)

Worst-case resident memory is bounded by **`MAX_VIEWERS × COPY_MAX_BYTES`** —
each live viewer pins its array (the shared cache only *reduces* this when
viewers share a volume; it does not change the worst case). Sized for 10–25:

| Setting | Value | Rationale |
|---|---|---|
| `NEUROGLANCER_MAX_VIEWERS` | **12** | down from 32 (that was for the cheap-mmap world) |
| `COPY_MAX_BYTES` | **1.5 GB** | copies all real ≤1.3 GB volumes; larger → mmap |
| volume LRU `maxsize` | **12** | matches `MAX_VIEWERS` |
| pod memory | **limit 24 Gi / request 6 Gi** | worst case 12 × 1.5 = 18 GB + ~2–3 GB base = ~21 GB < 24 GB |
| pod CPU | **limit 4 / request 1** | revert the useless `cpu: 8`; copy serving is light, a few cores for concurrent encodes |

### 5. Failure modes

- **Beyond `MAX_VIEWERS`:** the existing LRU evicts the oldest viewer, which
  breaks that still-open tab (no per-viewer `.stop()` exists). Acceptable
  because `MAX_VIEWERS=12` covers the stated peak; evicting an array now also
  frees its RAM (drops the ref → GC), which is desirable here.
- **Launch latency:** each cold launch reads up to 1.5 GB from NFS (seconds).
  This is the pre-mmap behaviour; the frontend already shows a spinner. The
  shared cache makes repeat launches of a popular volume instant.

## Testing

- **Unit:** `read_mrc_volume` returns an in-RAM array (not `np.memmap`) below the
  threshold and a memmap above it; the shared cache returns the *same* array
  object for a repeated `(path, mtime)`.
- **Regression:** existing `test_api_neuroglancer`, tilt-series, and annotations
  suites stay green (they patch `view_neuroglancer`, so the load-path change
  doesn't affect them).
- **Manual (prod):** 10–15 concurrent tabs — confirm grey-loading and cross-tab
  degradation are gone and pod memory stays under the limit (`oc adm top pod`).

## Rollout / deploy

- Code change lands via a new image tag (touches `src/`), so it needs an image
  build + the overlay `newTag` bump.
- Resource limits are a manifest change; the api Deployment uses
  `strategy: Recreate`, so applying recreates the pod (brief downtime, viewers
  reset — expected).

## Dependencies / risks

- **Node RAM (hard prerequisite):** the nfs-dmz node must be able to give the
  api pod ~24 Gi. Confirm with the platform team — namespace-scoped users can't
  read node capacity.
- If real concurrency exceeds ~12 distinct volumes, cache thrash / eviction
  degrades gracefully (reloads, or a broken oldest tab) rather than crashing —
  and is the signal to start Phase 2.

## Phase 2 (follow-on — separate spec)

Durable fix for 25–50 concurrent and/or large volumes: a **multi-process
neuroglancer pool in the api pod** — K subprocesses each hosting several viewers,
with a `token → subprocess` registry and the API reverse-proxying neuroglancer
paths (including the SSE `/events` stream) to the owning subprocess; idle-cull
lifecycle. Breaks the single-GIL serialization into K-way parallelism while
staying in one pod. To be specced separately once Phase 1 is live, since Phase 1
may cover real usage and its behaviour will inform Phase 2 sizing.
