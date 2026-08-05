# Annotation reorg — questions for the project lead

> **Status:** Theme 1 (identity/container) is resolved by [`docs/superpowers/specs/2026-08-03-annotation-folders-gouauxlab-alignment-split-design.md`](docs/superpowers/specs/2026-08-03-annotation-folders-gouauxlab-alignment-split-design.md). Theme 2 (neuroglancer "open in viewer" composition) remains open.

Context: the `Reconstructions/` reorg flattens `Annotations/` so each file's stem
is its id. That breaks down when one annotation is made of several files sharing
an extension (real cases: `activezone_0.png` + `activezone_0_selected_aunps.png`;
`..._box.json` + `..._box_neuroglancer.json`). Before choosing a folder layout we
need the lead to settle what an annotation *is* and what the "open in
neuroglancer" button should compose per type. The layout falls out of these
answers.

Two things are independent and shouldn't be conflated:
- **Identity** — what container holds one annotation's files together (its id).
- **Type** — a category label used to drive portal/neuroglancer behavior. Type
  can live *in the path* (a `{type}/` folder) or *as metadata* (an id-keyed
  field in `reconstruction.toml`, as today). It does not have to be a folder.

## Theme 1 — What "is" an annotation (identity + metadata)

Today an annotation's id is a file stem, and `type` / `derived_from` /
`bounding_box` hang off that stem. Once one annotation has two same-extension
files, stem-as-id can't hold them together, so we need to define the unit.

1. Is a single annotation ever made of **multiple files**? (e.g. a zonogram =
   `.star` + `.mrc` + `.npy` + two `.png`.) If yes, *those* annotations need a
   container. But it needn't be all-or-nothing: a lone single file can stay a
   bare file whose stem is the id, so identity may be **mixed** — a folder when
   multi-file, a file stem when it's a single loose file. (The tomogram
   migration already works this way: single leaf collapses to a name, otherwise
   the folder is the entity.)
2. **What is the container, and can loose single files coexist with it?** The
   natural options (each can allow bare stem-id'd files alongside folders):
   - `Annotations/{annotation_id}/` — a folder per multi-file annotation; the
     folder name is the id. Single-file annotations stay a bare
     `Annotations/{annotation_id}.ext`. Type stays an id-keyed field in
     `reconstruction.toml` (as today). Multiple annotations of the same type are
     free — separate folders/files with the same `type` value.
   - `Annotations/{type}/{annotation_id}(/ or .ext)` — same, but with a type
     folder above it. Bakes the category into the path.
   - `Annotations/{type}/` where the type folder *is* the annotation. Simplest,
     but only one annotation per type per group.

   (These differ mainly in whether/where `type` appears in the path — see Q3.)
3. **How should `type` be carried** — as an id-keyed field in
   `reconstruction.toml` (today's mechanism, keeps identity and category
   orthogonal), or as a folder level in the path (self-evident on disk, but
   couples the two and needs a rule when a folder holds a mixed bag)?
4. Is `type` a **closed, controlled vocabulary** the lab will commit to
   (bounding_box, segmentation, gold-points/zonogram, …), and **who owns adding
   to it**? Or open-ended? **Can it be absent** (an untyped annotation that still
   surfaces in the portal but gets no type-specific button)?
5. What metadata must **every** annotation carry beyond today's `type` /
   `derived_from` / `bounding_box`? (Author? annotation software/method? date?
   voxel spacing? source tomogram?) Which are required vs optional?
6. Is `bounding_box` a **type** of annotation, or a **property** of another
   annotation — or both? Today it's both a candidate type *and* a link field
   pointing at a sibling; worth resolving explicitly.
7. Can an annotation **derive from more than one tomogram**? (`derived_from` is
   a single value today.)

## Theme 2 — The neuroglancer "open in viewer" composition

The button loads a *set* of layers whose membership depends on type. So (a) type
must be reliably attached to every annotation (however Q3 lands), and (b) each
known type needs an explicit recipe the lead defines.

8. **Fill in this table** — for each known type, which layers and in what role:

   | Type          | Annotation layer     | Bounding box? | Target tomogram (`derived_from`)? |
   |---------------|----------------------|---------------|-----------------------------------|
   | gold points   | ✓ (points)           | ✓             | ✓                                 |
   | bounding box  | — (box *is* the ann) | ✓             | ✓                                 |
   | segmentation  | ✓ (volume)           | ?             | ✓                                 |
   | *(future…)*   | ?                    | ?             | ?                                 |

9. For each type, **which specific file is the viewable artifact, and in what
   format**? (segmentation → `.mrc`/`.zarr` volume; bounding box → the
   `_neuroglancer.json` state vs the raw box `.json`; gold points → `.star`?
   `.npy`?) Neuroglancer must know how to read each.
10. Should we **consume existing `_neuroglancer.json` state files directly**, or
    build the neuroglancer state ourselves from the raw annotation + tomogram?
11. Where multiple candidate files exist (star + npy + mrc + two pngs), **which
    is authoritative for the viewer vs which are supplementary/preview**?
12. Does the target tomogram come **only from `derived_from`**, or fall back to a
    tomogram in the same group if `derived_from` is missing?
13. **Fallback for an unknown type or untyped annotation**: no button, disabled
    button, or best-effort single-layer view?

## Cross-cutting decisions the lead should own

14. Are current annotation ids/paths **referenced anywhere external** (papers,
    scripts, existing portal links)? Bounds how freely the migration can rename.
15. Is the lead **OK with annotation ids changing** in this reorg, and who signs
    off on the old→new mapping?

---

**Lead with Q2/Q3 and Q8.** The identity container + where type lives fix the
on-disk model; the per-type layer table fixes the neuroglancer wiring. Everything
else snaps into place once those are settled.
