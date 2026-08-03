#!/usr/bin/env python3
"""Migrate Reconstructions/{Tomograms,Annotations}/{id}/ folders (today's
on-disk layout) straight to the new 3D-alignment-grouped layout:

    Reconstructions/{reconstruction_alignment_id}/
      Tomograms/{tomogram_id}.<ext>
      Annotations/{annotation_id}.<ext>
      Alignment/                    # created empty

and rewrites the acquisition's acquisition.toml to match:
  - [raw_tomogram]              -> [[raw_tomogram]]
  - raw_tomogram.tilt_series_id  -> dropped; derived_from set to the group's
    tilt_series id (text)
  - [[annotation]].target_tomogram -> dropped
  - a new [[reconstruction_alignment]] block is added, one per group

The group id (`reconstruction_alignment_id`) is set to the acquisition's
single `[[tilt_series]]` id — it does not have to equal it going forward, but
reusing it is the only unambiguous choice available from today's data.

Warn-and-skip, never guess: an acquisition whose group id can't be resolved
unambiguously is reported and left alone rather than migrated into a made-up
group. Re-running after an --apply is a no-op (nothing left under the flat
Tomograms/ and Annotations/ dirs to move).

Usage
-----
    # dry run (prints planned actions, touches nothing)
    ./utils/migrate_reconstruction_groups.py --root /path/to/data

    # perform the moves + TOML rewrite
    ./utils/migrate_reconstruction_groups.py --root /path/to/data --apply
"""
import argparse
import os
import re
import sys
import tempfile
from pathlib import Path

# The two-arm data root (mirrors schema.layout.TOP_LEVEL_EXPERIMENTAL /
# TOP_LEVEL_MD_SIMULATION / DATASET_TYPE_BY_DIR) — kept as plain constants
# here since this script is standalone (no src/ import).
ROOT = Path("/groups/cryoet/cryoet/data")
TOP_LEVEL_EXPERIMENTAL = "Experimental"
TOP_LEVEL_MD_SIMULATION = "MdSimulation"
MD_SIMULATION_SUBDIRS = ("Bulk", "SingleMolecule", "Slab")

TOMOGRAM_FILE_EXTENSIONS = {".mrc"}
ANNOTATION_FILE_EXTENSIONS = {".star", ".mrc", ".png", ".tiff", ".tif", ".csv", ".json", ".npy"}

# Litter that shouldn't block deletion of an otherwise-empty old folder.
# `.DS_Store` / `Thumbs.db` are OS thumbnail caches, never data.
# `.gitkeep` is here because the starter skeletons ship placeholder
# Tomograms/{id}/ and Annotations/{id}/ folders containing nothing else — left
# in place they keep the flat Tomograms/Annotations dir alive, and the scanner
# then reads that leftover dir as a bogus (empty) reconstruction group.
IGNORED_JUNK = {".DS_Store", "Thumbs.db", ".gitkeep"}


def _atomic_write(path: Path, text: str) -> None:
    """Write text to path via a temp file + os.replace. os.replace repoints the
    directory entry at a NEW inode, so a hardlinked twin (e.g. a `cp -al` copy
    of the data root) is left untouched — a plain open('w')/write_text truncates
    the shared inode in place and would corrupt the original."""
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _rmdir_if_empty(d: Path) -> None:
    """rmdir d if it holds nothing but ignorable junk (.DS_Store), removing that
    junk first. No-op if d has real content or doesn't exist."""
    if not d.is_dir():
        return
    entries = list(d.iterdir())
    if any(e.name not in IGNORED_JUNK for e in entries):
        return
    for e in entries:
        e.unlink()
    d.rmdir()


def _prunable_dirs(kind_dir: Path) -> list[Path]:
    """Every directory under a Tomograms/ or Annotations/ dir that the migration
    may have emptied, deepest first.

    Includes ``{id}/`` folders that produced no moves at all — a placeholder
    holding only a ``.gitkeep`` is never a move source, so collecting only
    ``{src.parent for src, _ in moves}`` would leave it (and therefore the whole
    flat dir) behind. Zarr stores are entities, not containers: never descend
    into one, or an empty chunk dir inside a store that was skipped could be
    rmdir'd out from under it.
    """
    if not kind_dir.is_dir():
        return []

    def _subdirs(d: Path) -> list[Path]:
        return [
            p for p in d.iterdir() if p.is_dir() and not p.name.endswith(".zarr")
        ]

    out: list[Path] = []
    stack = _subdirs(kind_dir)
    while stack:
        d = stack.pop()
        out.append(d)
        stack += _subdirs(d)
    out.sort(key=lambda p: len(p.parts), reverse=True)
    return out


def _ext_of(entry: Path) -> str:
    """Extension used to name an entity file: '.ome.zarr'/'.zarr' for zarr
    stores (which are directories), else the plain suffix."""
    if entry.name.endswith(".ome.zarr"):
        return ".ome.zarr"
    if entry.is_dir() and entry.name.endswith(".zarr"):
        return ".zarr"
    return entry.suffix


def _stem_of(path: Path) -> str:
    """Entity id for a filename — the name minus its (possibly multi-suffix)
    extension. Mirrors schema.layout.entity_id_from_path."""
    ext = _ext_of(path)
    return path.name[: -len(ext)] if ext else path.name


def _is_leaf(entry: Path, allowed_exts: set[str]) -> bool:
    """True if entry is an entity file: an allowed-extension file or a
    .zarr/.ome.zarr store. Plain subdirs (e.g. ctf/even/odd) and stray files
    are not leaves."""
    if entry.is_dir():
        return entry.name.endswith(".zarr")  # covers .ome.zarr
    return entry.suffix.lower() in allowed_exts


def _entity_files(id_dir: Path, allowed_exts: set[str]):
    """Return {ext: file_or_dir_path} for one {id}/ folder, or None + a warning
    if two entries share the same extension (can't collapse to one stem).
    Plain subdirs and stray files are ignored."""
    by_ext: dict[str, Path] = {}
    for entry in sorted(id_dir.iterdir()):
        if not _is_leaf(entry, allowed_exts):
            continue
        ext = _ext_of(entry)
        if ext in by_ext:
            return None, f"{id_dir}: multiple '{ext}' entries, can't collapse to one stem"
        by_ext[ext] = entry
    return by_ext, None


def _expand_entity_folder(id_dir: Path, allowed_exts: set[str], dest_dir: Path, prepend_folder: bool = False):
    """Return (moves, warnings) flattening one Tomograms/{id}/ or
    Annotations/{id}/ folder into dest_dir, treating the folder's contents as
    separate entities rather than as one entity's artifacts:

      - a single leaf, no nested subfolders -> collapse to {id_dir.name}{ext}
        (folder name becomes the entity id, as in the normal per-folder path)
      - otherwise -> each leaf keeps its own filename, and each nested subfolder
        (e.g. ctf/even/odd) collapses its single leaf to {sub.name}_{filename}

    prepend_folder (used for Tomograms) preserves each file's own name and
    prefixes it with the source folder name -> {id_dir.name}_{filename}, so the
    descriptive recon filename isn't discarded by the collapse. With it set the
    single-leaf collapse no longer applies (the folder name is already carried
    in the prefix).

    Nested subfolders that don't collapse to one file, and destination-name
    collisions, are warned and skipped rather than silently overwritten.
    """
    entries = sorted(id_dir.iterdir())
    leaves = [e for e in entries if _is_leaf(e, allowed_exts)]
    subdirs = [e for e in entries if e.is_dir() and not _is_leaf(e, allowed_exts)]

    if not prepend_folder and len(leaves) == 1 and not subdirs:
        return [(leaves[0], dest_dir / f"{id_dir.name}{_ext_of(leaves[0])}")], []

    prefix = f"{id_dir.name}_" if prepend_folder else ""
    moves, warnings = [], []
    for leaf in leaves:
        moves.append((leaf, dest_dir / f"{prefix}{leaf.name}"))
    for sub in subdirs:
        by_ext, warning = _entity_files(sub, allowed_exts)
        if warning:
            warnings.append(warning)
            continue
        if len(by_ext) != 1:
            warnings.append(f"{sub}: expected one file to collapse to '{sub.name}', found {len(by_ext)}; skipping")
            continue
        (ext, entry), = by_ext.items()
        # Keep the original filename, prefixed with the variant subfolder name
        # (ctf/s207_8.00Apx.mrc -> ctf_s207_8.00Apx.mrc), so provenance survives
        # the collapse. entry.name already carries the extension.
        moves.append((entry, dest_dir / f"{prefix}{sub.name}_{entry.name}"))

    seen: dict[Path, Path] = {}
    deduped = []
    for src, dest in moves:
        if dest in seen:
            warnings.append(f"{src}: destination {dest} already taken by {seen[dest]}; skipping")
            continue
        seen[dest] = src
        deduped.append((src, dest))
    return deduped, warnings


def _plan_annotation_folder(id_dir: Path, dest_dir: Path) -> list[tuple[Path, Path]]:
    """Folder-preserve planner for ONE Annotations/{id}/ folder.

    A single allowlisted leaf with no non-junk subdirs collapses to a bare
    ``dest_dir/{id}.ext`` (the mixed single-file rule). Otherwise the WHOLE
    folder is relocated verbatim to ``dest_dir/{id}/`` — the annotation's files
    (same-extension pairs, sidecars, nested content, junk) stay together and the
    id is the folder name. Relocate, never rename or split.
    """
    entries = [e for e in id_dir.iterdir() if e.name not in IGNORED_JUNK]
    leaves = [e for e in entries if _is_leaf(e, ANNOTATION_FILE_EXTENSIONS)]
    subdirs = [
        e for e in entries if e.is_dir() and not _is_leaf(e, ANNOTATION_FILE_EXTENSIONS)
    ]
    if not leaves and not subdirs:
        # Only junk / stray non-annotation files — not an annotation. Leave it:
        # a junk-only placeholder gets pruned by the existing cleanup, and a real
        # stray file keeps its folder, exactly as before folder-preserve.
        return []
    if len(leaves) == 1 and not subdirs:
        return [(leaves[0], dest_dir / f"{id_dir.name}{_ext_of(leaves[0])}")]
    return [(id_dir, dest_dir / id_dir.name)]


def shared_name_groups(recon_dir: Path) -> list[str]:
    """Return ids that appear as BOTH a Tomograms/{id}/ and Annotations/{id}/
    folder under one acquisition's Reconstructions/.

    A tomogram and annotation sharing a name (e.g. a "Missalignment" QC
    tomogram + its matching annotation) form their own
    Reconstructions/{id}/ group — independent of the acquisition's main
    group id — since that pairing is itself evidence of a distinct
    reconstruction/alignment attempt, not part of the primary one.
    """
    tomos_dir = recon_dir / "Tomograms"
    anns_dir = recon_dir / "Annotations"
    tomo_names = {p.name for p in tomos_dir.iterdir() if p.is_dir()} if tomos_dir.is_dir() else set()
    ann_names = {p.name for p in anns_dir.iterdir() if p.is_dir()} if anns_dir.is_dir() else set()
    return sorted(tomo_names & ann_names)


def _plan_folder_as_group(recon_dir: Path, gid: str):
    """Return (moves, mkdirs, warnings) moving Tomograms/{gid}/ and
    Annotations/{gid}/ into their own Reconstructions/{gid}/ group, flattening
    each side via _expand_entity_folder."""
    moves, warnings = [], []
    group_dir = recon_dir / gid
    for kind, allowed_exts in (("Tomograms", TOMOGRAM_FILE_EXTENSIONS), ("Annotations", ANNOTATION_FILE_EXTENSIONS)):
        id_dir = recon_dir / kind / gid
        if not id_dir.is_dir():
            continue
        if kind == "Annotations":
            moves += _plan_annotation_folder(id_dir, group_dir / kind)
            continue
        # No prepend here: when the folder itself becomes the group, its name is
        # already preserved as the group dir, so prefixing each file with it too
        # would only duplicate it (bp_3dctf_bin4/Tomograms/bp_3dctf_bin4_recon).
        m, w = _expand_entity_folder(id_dir, allowed_exts, group_dir / kind)
        moves += m
        warnings += w
    return moves, [group_dir / "Alignment"], warnings


def plan_shared_name_group(recon_dir: Path, shared_id: str):
    """Return (moves, mkdirs, warnings) moving the Tomograms/{shared_id}/ and
    Annotations/{shared_id}/ folders into their own Reconstructions/{shared_id}/
    group (see shared_name_groups)."""
    return _plan_folder_as_group(recon_dir, shared_id)


def plan_folder_groups(recon_dir: Path):
    """Return (moves, mkdirs, warnings, group_ids) for the no-usable-group-id
    case: every Tomograms/{id}/ and Annotations/{id}/ folder becomes its own
    Reconstructions/{id}/ group, named after the folder.

    Used when the acquisition has no single tilt series to name the group
    (group_id_for -> None): a lone tomogram, a QC "Missalignment" tomogram +
    matching annotation, and per-variant tomogram folders (denoised, gaussian,
    reconstruct_halves) each resolve to their own group unambiguously.
    """
    moves, mkdirs, warnings = [], [], []
    tomos_dir = recon_dir / "Tomograms"
    anns_dir = recon_dir / "Annotations"
    tomo_ids = {p.name for p in tomos_dir.iterdir() if p.is_dir()} if tomos_dir.is_dir() else set()
    ann_ids = {p.name for p in anns_dir.iterdir() if p.is_dir()} if anns_dir.is_dir() else set()
    group_ids = sorted(tomo_ids | ann_ids)
    for gid in group_ids:
        m, k, w = _plan_folder_as_group(recon_dir, gid)
        moves += m
        mkdirs += k
        warnings += w
    return moves, mkdirs, warnings, group_ids


def loose_file_warnings(recon_dir: Path) -> list[str]:
    """Warn about files sitting DIRECTLY under Reconstructions/Tomograms/ or
    Reconstructions/Annotations/ instead of inside an {id}/ subfolder.

    The group migration only relocates {id}/ subdirs, so a loose file is left
    in place — which keeps the flat Tomograms/Annotations dir alive, and the
    scanner then reads that leftover dir as a bogus reconstruction group. A
    loose file can't be placed automatically (no {id}/ folder says which group
    it belongs to), so surface it for manual filing rather than guessing.
    """
    warnings = []
    for kind in ("Tomograms", "Annotations"):
        d = recon_dir / kind
        if not d.is_dir():
            continue
        for entry in sorted(d.iterdir()):
            if entry.is_file() and entry.name not in IGNORED_JUNK:
                warnings.append(
                    f"{entry}: loose file directly under {kind}/ (not in an "
                    f"{{id}}/ folder) — NOT migrated; move it under "
                    f"Reconstructions/{{group}}/{kind}/ manually"
                )
    return warnings


def plan_reconstructions(recon_dir: Path, group_id: str | None, exclude_ids: frozenset[str] = frozenset()):
    """Return (moves, mkdirs, warnings) for one acquisition's Reconstructions/,
    excluding any id already handled by plan_shared_name_group.

    ``group_id`` may be None (acquisition's tilt series is ambiguous/missing) —
    in that case nothing can be moved safely, so every remaining id_dir is
    left in place and warned about instead.

    A ``{id}/`` folder normally collapses onto its own name: every file in it is
    one entity's artifact, so ``recon.mrc`` + ``recon.ome.zarr`` become
    ``{id}.mrc`` + ``{id}.ome.zarr``. Tomograms are the exception: they keep
    their descriptive filename prefixed with the folder name, so
    ``{id}/some_name.mrc`` becomes ``{id}_some_name.mrc`` rather than
    discarding ``some_name``. When two files share an extension that is
    impossible — one name, two files — so the folder's contents are treated as
    *separate* entities keeping their own filenames, the same policy
    :func:`_plan_folder_as_group` applies. Either way the authored block for
    ``{id}`` is rewritten to match by :func:`_expand_blocks`, so no declaration
    is left dangling.
    """
    moves = []
    mkdirs = []
    warnings = []
    group_dir = recon_dir / group_id if group_id is not None else None

    for kind, allowed_exts in (("Tomograms", TOMOGRAM_FILE_EXTENSIONS), ("Annotations", ANNOTATION_FILE_EXTENSIONS)):
        src_dir = recon_dir / kind
        if not src_dir.is_dir():
            continue
        for id_dir in sorted(p for p in src_dir.iterdir() if p.is_dir()):
            if id_dir.name in exclude_ids:
                continue
            entity_id = id_dir.name
            if group_dir is None:
                warnings.append(
                    f"{id_dir}: no group id for this acquisition (ambiguous or "
                    "missing tilt series) — leaving in place"
                )
                continue
            if kind == "Annotations":
                moves += _plan_annotation_folder(id_dir, group_dir / kind)
                continue

            by_ext, _collision = _entity_files(id_dir, allowed_exts)
            if by_ext is None:
                expanded, expand_warnings = _expand_entity_folder(
                    id_dir, allowed_exts, group_dir / kind, prepend_folder=True
                )
                moves += expanded
                warnings += expand_warnings
                stems = sorted({_stem_of(dest) for _src, dest in expanded})
                warnings.append(
                    f"{id_dir}: contents do not collapse onto '{entity_id}' "
                    f"(two files share an extension) — keeping filenames, so "
                    f"this becomes {len(stems)} entities: " + ", ".join(stems)
                )
                continue
            for ext, entry in by_ext.items():
                stem = f"{entity_id}_{_stem_of(entry)}"
                dest = group_dir / kind / f"{stem}{ext}"
                moves.append((entry, dest))

    if group_dir is not None:
        mkdirs.append(group_dir / "Alignment")
    return moves, mkdirs, warnings


def _expand_blocks(text: str, header: str, id_map: dict[str, list[str]]) -> str:
    """Rewrite each ``[[header]]`` block whose ``id`` is a key in id_map into one
    block per mapped id, copying all other fields verbatim. Used to turn a block
    authored under an old folder name (e.g. id = "Missalignment") into one block
    per flattened file stem (ctf, even, odd, ...). Blocks whose id maps to just
    itself (single-file collapse, e.g. denoised -> denoised.mrc) are untouched,
    as are commented-out template blocks (no real id line)."""
    pattern = re.compile(rf"^\[\[{re.escape(header)}\]\]\n(.*?)(?=\n\[|\Z)", flags=re.S | re.M)

    def repl(match: re.Match) -> str:
        body = match.group(1)
        id_match = re.search(r'^[ \t]*id[ \t]*=[ \t]*"([^"]+)"', body, flags=re.M)
        if not id_match:
            return match.group(0)
        old_id = id_match.group(1)
        new_ids = id_map.get(old_id)
        if not new_ids or new_ids == [old_id]:
            return match.group(0)
        base = body.rstrip("\n")
        copies = []
        for nid in new_ids:
            new_body = re.sub(
                r'^([ \t]*id[ \t]*=[ \t]*)"[^"]+"',
                lambda m: f'{m.group(1)}"{nid}"',
                base, count=1, flags=re.M,
            )
            copies.append(f"[[{header}]]\n{new_body}\n")
        return "\n".join(copies)

    return pattern.sub(repl, text)


def _rewrite_derived_from(text: str, tomo_id_map: dict[str, list[str]]) -> str:
    """Rewrite post_processed_tomogram.derived_from lineage refs from their old
    (pre-migration folder) tomogram ids to the flattened stems the migration
    renamed those tomograms to, so the reference still resolves after the
    prepend rename. One old id may map to several new stems (an
    extension-collision split) — the ref expands to all of them; an id that was
    not renamed is left untouched."""
    if not tomo_id_map:
        return text

    def _remap(old_ids: list[str]) -> list[str]:
        out: list[str] = []
        for oid in old_ids:
            for nid in tomo_id_map.get(oid, [oid]):
                if nid not in out:
                    out.append(nid)
        return out

    def _fix_df(dm: re.Match) -> str:
        new_ids = _remap(re.findall(r'"([^"]+)"', dm.group(2)))
        joined = ", ".join('"' + i + '"' for i in new_ids)
        return f"{dm.group(1)}[{joined}]"

    def _fix_block(bm: re.Match) -> str:
        block = re.sub(
            r"^([ \t]*derived_from[ \t]*=[ \t]*)\[([^\]]*)\]",
            _fix_df, bm.group(1), flags=re.M,
        )
        return "[[post_processed_tomogram]]\n" + block

    return re.sub(
        r"\[\[post_processed_tomogram\]\]\n(.*?)(?=\n\[|\Z)",
        _fix_block, text, flags=re.S,
    )


def prepare_processing_log(text: str, group_id: str | None) -> str:
    """Field-level normalization of the acquisition's processing log, applied
    once (to the whole acquisition.toml text) before it gets split out into
    per-group reconstruction.toml files: convert singular [raw_tomogram] to
    the array form, fill/insert raw_tomogram.derived_from with the
    acquisition's tilt series id (skipped if group_id is None — ambiguous or
    missing tilt series, see group_id_for), and drop the now-removed
    tilt_series_id / target_tomogram fields.
    """
    new_text = text

    # Always convert singular [raw_tomogram] tables to the array form the new
    # schema (raw_tomogram: list) requires — safe regardless of group_id, and
    # needed by the single-tomogram fallback, which has no tilt series and so
    # passes group_id=None. There may be MULTIPLE [raw_tomogram] blocks (the
    # case this migration enables) — convert every header.
    new_text = re.sub(r"^\[raw_tomogram\]\n", "[[raw_tomogram]]\n", new_text, flags=re.M)

    if group_id is not None and "[[raw_tomogram]]" in new_text:
        # Fill/insert raw_tomogram.derived_from = "<group_id>"; drop any
        # tilt_series_id line inside each raw_tomogram block.
        def _fix_raw_block(match: re.Match) -> str:
            block = match.group(1)
            block = re.sub(r"^#?\s*tilt_series_id\s*=.*\n", "", block, flags=re.M)
            derived_from_line = f'derived_from   = "{group_id}"   # text, tilt_series id (under TiltSeries/) this was reconstructed from\n'
            if re.search(r"^#?\s*derived_from\s*=.*\n", block, flags=re.M):
                block = re.sub(r"^#?\s*derived_from\s*=.*\n", derived_from_line, block, count=1, flags=re.M)
            else:
                block = block.rstrip("\n") + "\n" + derived_from_line
            return "[[raw_tomogram]]\n" + block

        new_text = re.sub(
            r"\[\[raw_tomogram\]\]\n(.*?)(?=\n\[|\Z)", _fix_raw_block, new_text, flags=re.S
        )

    # Drop tilt_series_id from post_processed_tomogram blocks and
    # target_tomogram from annotation blocks (both are now dropped fields) —
    # safe unconditionally, regardless of whether group_id resolved.
    new_text = re.sub(r"^#?\s*tilt_series_id\s*=.*\n", "", new_text, flags=re.M)
    new_text = re.sub(r"^#?\s*target_tomogram\s*=.*\n", "", new_text, flags=re.M)

    return new_text


def _collect_group_blocks(
    prepared_text: str, tomo_renames: dict[str, list[str]], ann_renames: dict[str, list[str]]
) -> str:
    """Return the text of every [[raw_tomogram]]/[[post_processed_tomogram]]/
    [[annotation]] block belonging to ONE reconstruction group.

    ``tomo_renames``/``ann_renames`` here must already be scoped to that one
    group's moves (old Tomograms|Annotations/{id}/ folder name -> the
    flattened file stems that folder produced *in this group*) — see
    group_tomo_renames/group_ann_renames in main(). A block belongs to the
    group iff its (post-_expand_blocks-rename) id is one of those stems.
    """
    expanded = prepared_text
    for header in ("raw_tomogram", "post_processed_tomogram"):
        expanded = _expand_blocks(expanded, header, tomo_renames)
    expanded = _expand_blocks(expanded, "annotation", ann_renames)

    tomo_ids = {nid for ids in tomo_renames.values() for nid in ids}
    ann_ids = {nid for ids in ann_renames.values() for nid in ids}
    wanted = {
        "raw_tomogram": tomo_ids,
        "post_processed_tomogram": tomo_ids,
        "annotation": ann_ids,
    }

    parts = []
    for header in ("raw_tomogram", "post_processed_tomogram", "annotation"):
        ids_wanted = wanted[header]
        if not ids_wanted:
            continue
        for match in re.finditer(
            rf"^\[\[{header}\]\]\n(.*?)(?=\n\[|\Z)", expanded, flags=re.S | re.M
        ):
            block_body = match.group(1)
            id_match = re.search(r'^[ \t]*id[ \t]*=[ \t]*"([^"]+)"', block_body, flags=re.M)
            if id_match and id_match.group(1) in ids_wanted:
                parts.append(f"[[{header}]]\n{block_body.rstrip(chr(10))}\n\n")
    return "".join(parts)


def build_reconstruction_toml(
    group_id: str,
    prepared_text: str,
    tomo_renames: dict[str, list[str]],
    ann_renames: dict[str, list[str]],
) -> str:
    """Return Reconstructions/{group_id}/reconstruction.toml text: a
    [reconstruction_alignment] table (the id is implied by the folder name —
    not authored, see schema) + this group's raw_tomogram/
    post_processed_tomogram/annotation blocks pulled out of the acquisition's
    processing log (prepare_processing_log'd acquisition.toml text) and
    renamed to the flattened file stems this group's moves produced.
    """
    header = (
        "#:schema file:///groups/cryoet/cryoet/data/scratch/src/schema/reconstruction.schema.json\n"
        "[reconstruction_alignment]\n"
        f'# reconstruction_alignment_id is this folder\'s name ("{group_id}") — not authored here\n'
        '# alignment_software = "<FILL IN>"   # text, e.g. "IMOD 4.12", "RELION", "AreTomo3"\n'
        '# alignment_method   = "<FILL IN>"   # text, e.g. patch_tracking | fiducial | subtomogram_averaging\n\n'
    )
    return header + _collect_group_blocks(prepared_text, tomo_renames, ann_renames)


def strip_processing_log(acq_text: str) -> str:
    """Remove every [[raw_tomogram]]/[[post_processed_tomogram]]/[[annotation]]/
    [[reconstruction_alignment]] block from acquisition.toml text (that
    metadata now lives in each group's reconstruction.toml), leaving
    [acquisition]/[[tilt_series]]/[md_source] untouched."""
    text = acq_text
    for header in ("raw_tomogram", "post_processed_tomogram", "annotation", "reconstruction_alignment"):
        text = re.sub(rf"^\[\[?{header}\]\]?\n(.*?)(?=\n\[|\Z)", "", text, flags=re.S | re.M)
    return re.sub(r"\n{3,}", "\n\n", text)


def _gouauxlab_group_for(name: str) -> str | None:
    """Map a gouauxlab Tomograms/Annotations folder name to its reconstruction
    group by alignment marker: ``_az{N}`` / ``_liza_az{N}`` (``_rerun`` allowed
    after) -> ``cryosnail_az{N}`` (literal N); ``_warp`` -> ``warp``;
    ``_best_alignment`` -> ``best_alignment``; otherwise None (unmarked). The
    group is the alignment marker, not the leading ``activezone_M`` index."""
    m = re.search(r"_(?:liza_)?az(\d+)", name)
    if m:
        return f"cryosnail_az{m.group(1)}"
    if "_warp" in name:
        return "warp"
    if "_best_alignment" in name:
        return "best_alignment"
    return None


def _plan_gouaux_one(kind: str, exts: set[str], id_dir: Path, dest_dir: Path):
    """Route one folder into its group: annotations folder-preserve, tomograms
    flatten+prepend. Returns (moves, warnings)."""
    if kind == "Annotations":
        return _plan_annotation_folder(id_dir, dest_dir), []
    return _expand_entity_folder(id_dir, exts, dest_dir, prepend_folder=True)


def plan_gouauxlab(recon_dir: Path):
    """Split a gouauxlab acquisition's Reconstructions/ into per-alignment
    groups (see _gouauxlab_group_for). Single alignment -> every folder (marked
    and unmarked) into the one group; multiple -> marked folders split, unmarked
    (bounding_boxes) left in place + warned. Returns
    (moves, mkdirs, warnings, group_ids), or None if no marker is present at all
    (caller falls back to the generic path)."""
    kinds = (
        ("Tomograms", TOMOGRAM_FILE_EXTENSIONS),
        ("Annotations", ANNOTATION_FILE_EXTENSIONS),
    )
    folders = []  # (kind, exts, id_dir, group_or_None)
    for kind, exts in kinds:
        src = recon_dir / kind
        if not src.is_dir():
            continue
        for id_dir in sorted(p for p in src.iterdir() if p.is_dir()):
            folders.append((kind, exts, id_dir, _gouauxlab_group_for(id_dir.name)))

    marked = sorted({g for _, _, _, g in folders if g is not None})
    if not marked:
        return None

    moves, mkdirs, warnings = [], [], []
    if len(marked) == 1:
        single = marked[0]
        for kind, exts, id_dir, _g in folders:
            m, w = _plan_gouaux_one(kind, exts, id_dir, recon_dir / single / kind)
            moves += m
            warnings += w
        group_ids = [single]
    else:
        for kind, exts, id_dir, g in folders:
            if g is None:
                warnings.append(
                    f"{id_dir}: no alignment marker (az/warp/best_alignment) and "
                    "this acquisition has multiple alignments — leaving in place"
                )
                continue
            m, w = _plan_gouaux_one(kind, exts, id_dir, recon_dir / g / kind)
            moves += m
            warnings += w
        group_ids = marked

    for g in group_ids:
        mkdirs.append(recon_dir / g / "Alignment")
    return moves, mkdirs, warnings, group_ids


def group_id_for(acquisition_dir: Path):
    """Extract the acquisition's tilt_series id via regex, not tomllib — some
    real acquisition.toml files are already invalid TOML (e.g. a duplicated
    [raw_tomogram] table, the exact bug this migration fixes), so a full
    parse would crash on the very files we most need to migrate."""
    toml_path = acquisition_dir / "acquisition.toml"
    if not toml_path.is_file():
        return None, f"{acquisition_dir}: no acquisition.toml, can't determine tilt_series id"
    text = toml_path.read_text()
    ts_blocks = re.findall(r"^\[\[tilt_series\]\]\n(.*?)(?=\n\[|\Z)", text, flags=re.M | re.S)
    ts_ids = []
    for block in ts_blocks:
        id_match = re.search(r'^id\s*=\s*"([^"]+)"', block, flags=re.M)
        if id_match:
            ts_ids.append(id_match.group(1))
    if len(ts_ids) != 1:
        return None, f"{acquisition_dir}: expected exactly one [[tilt_series]] id, found {len(ts_ids)}; skipping"
    return ts_ids[0], None


def find_acquisition_dirs(lab_prefix: str, root: Path = ROOT):
    """Yield every acquisition dir with a Reconstructions/ folder, across
    both arms.

    - Experimental: {root}/Experimental/{lab_prefix}*/{acq}/
    - Simulation:   {root}/MdSimulation/{Bulk,SingleMolecule,Slab}/{lab_prefix}*/SyntheticCryoET/{acq}/
    """
    exp_root = root / TOP_LEVEL_EXPERIMENTAL
    for lab_dir in sorted(exp_root.glob(f"{lab_prefix}*")):
        if not lab_dir.is_dir():
            continue
        for acq_dir in sorted(lab_dir.iterdir()):
            if (acq_dir / "Reconstructions").is_dir():
                yield acq_dir

    md_root = root / TOP_LEVEL_MD_SIMULATION
    for subdir in MD_SIMULATION_SUBDIRS:
        for sample_dir in sorted((md_root / subdir).glob(f"{lab_prefix}*")):
            synth = sample_dir / "SyntheticCryoET"
            if not synth.is_dir():
                continue
            for acq_dir in sorted(synth.iterdir()):
                if (acq_dir / "Reconstructions").is_dir():
                    yield acq_dir


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lab-prefix", default="", help="Only samples starting with this prefix (default: all)")
    parser.add_argument(
        "--root", type=Path, default=ROOT,
        help=f"Two-arm data root, holding Experimental/ and MdSimulation/ (default: {ROOT})",
    )
    parser.add_argument("--apply", action="store_true", help="Perform the moves + TOML rewrite (default: dry-run)")
    args = parser.parse_args()

    total_moves = total_mkdirs = total_tomls = total_skipped = 0
    for acq_dir in find_acquisition_dirs(args.lab_prefix, args.root):
        group_id, warning = group_id_for(acq_dir)
        if warning:
            print(f"# NOTE: {warning}", file=sys.stderr)
            # Fall through instead of skipping the acquisition outright — a
            # shared-name group (see shared_name_groups) can still be planned
            # even when the acquisition's main group is ambiguous/missing.
            group_id = None

        recon_dir = acq_dir / "Reconstructions"

        is_gouaux = acq_dir.parent.name.startswith("gouauxlab")
        gouaux_plan = plan_gouauxlab(recon_dir) if is_gouaux else None

        if gouaux_plan is not None:
            # gouauxlab: groups are alignment markers, not the tilt-series id.
            moves, mkdirs, warnings, all_group_ids = gouaux_plan
            derived_from_id = group_id  # tilt-series id for raw_tomogram.derived_from
        elif group_id is None:
            # No usable tilt-series group id (missing or 2+ tilt series): every
            # Tomograms/{id}/ + matching Annotations/{id}/ folder becomes its own
            # group, named after the folder. group_id stays None so no
            # raw_tomogram derived_from gets a bogus tilt-series ref; the groups
            # are declared only as extra reconstruction_alignment blocks.
            moves, mkdirs, warnings, extra_ids = plan_folder_groups(recon_dir)
            all_group_ids = extra_ids
            derived_from_id = None
        else:
            # Single tilt series: it names the acquisition's main group; a
            # shared Tomograms+Annotations name (e.g. Missalignment) still splits
            # into its own group.
            extra_ids = shared_name_groups(recon_dir)
            moves, mkdirs, warnings = [], [], []
            for shared_id in extra_ids:
                m, k, w = plan_shared_name_group(recon_dir, shared_id)
                moves += m
                mkdirs += k
                warnings += w
            m, k, w = plan_reconstructions(recon_dir, group_id, exclude_ids=frozenset(extra_ids))
            moves += m
            mkdirs += k
            warnings += w
            all_group_ids = ([group_id] if group_id is not None else []) + extra_ids
            derived_from_id = group_id

        warnings += loose_file_warnings(recon_dir)

        for w in warnings:
            print(f"# NOTE: {w}", file=sys.stderr)

        # Map each old Tomograms/{id}/ and Annotations/{id}/ folder name to the
        # file stems it flattened to, so the authored blocks get renamed to
        # match (e.g. one id="Missalignment" block -> ctf/even/odd/... blocks)
        # — scoped per destination GROUP (dest's first path segment under
        # Reconstructions/), since one old folder name can belong to any one
        # group (a plain entity id under the main group, or a group-named
        # folder for a shared-name/no-tilt-series group).
        group_tomo_renames: dict[str, dict[str, list[str]]] = {gid: {} for gid in all_group_ids}
        group_ann_renames: dict[str, dict[str, list[str]]] = {gid: {} for gid in all_group_ids}
        for src, dest in moves:
            rel = src.relative_to(recon_dir)
            if len(rel.parts) < 2:
                continue
            kind, old_folder = rel.parts[0], rel.parts[1]
            dest_group = dest.relative_to(recon_dir).parts[0]
            new_id = _stem_of(dest)
            renames = group_tomo_renames if kind == "Tomograms" else group_ann_renames
            ids = renames.setdefault(dest_group, {}).setdefault(old_folder, [])
            if new_id not in ids:  # same entity can collapse to 2+ moves (.mrc + .zarr) -> same id twice
                ids.append(new_id)

        # Flatten the per-group tomogram renames into one old-id -> new-id(s)
        # map for rewriting derived_from lineage refs (which may resolve across
        # sibling groups, so this is intentionally not group-scoped).
        tomo_id_map: dict[str, list[str]] = {}
        for gid_map in group_tomo_renames.values():
            for old, news in gid_map.items():
                bucket = tomo_id_map.setdefault(old, [])
                for nid in news:
                    if nid not in bucket:
                        bucket.append(nid)

        toml_path = acq_dir / "acquisition.toml"
        recon_tomls: dict[str, str] = {}
        new_toml = None
        if toml_path.is_file():
            orig_text = toml_path.read_text()
            prepared = prepare_processing_log(orig_text, derived_from_id)
            prepared = _rewrite_derived_from(prepared, tomo_id_map)
            for gid in all_group_ids:
                recon_tomls[gid] = build_reconstruction_toml(
                    gid, prepared, group_tomo_renames.get(gid, {}), group_ann_renames.get(gid, {})
                )
            stripped = strip_processing_log(prepared)
            new_toml = stripped if stripped != orig_text else None

        if not args.apply:
            for src, dest in moves:
                print(f"mv {src} -> {dest}")
            for d in mkdirs:
                print(f"mkdir {d}")
            for gid in recon_tomls:
                print(f"# would write {recon_dir / gid / 'reconstruction.toml'}")
            if new_toml is not None:
                print(f"# would rewrite {toml_path} (processing log moved to reconstruction.toml)")
            continue

        # Apply per acquisition, isolating failures: an acquisition owned by
        # another user (unwritable dir/toml) shouldn't abort the whole run —
        # warn and move on.
        try:
            for src, dest in moves:
                dest.parent.mkdir(parents=True, exist_ok=True)
                src.rename(dest)
            for d in mkdirs:
                d.mkdir(parents=True, exist_ok=True)
            written = 0
            for gid, text in recon_tomls.items():
                recon_toml_path = recon_dir / gid / "reconstruction.toml"
                # Never clobber an existing file. On a re-run there are no moves
                # left, so the blocks would rebuild EMPTY and overwrite the
                # migrated metadata; after migration the file is also
                # researcher-authored, so hand edits must survive too.
                if recon_toml_path.exists():
                    continue
                recon_toml_path.parent.mkdir(parents=True, exist_ok=True)
                recon_toml_path.write_text(text)  # fresh file — no existing inode to preserve
                written += 1
            if new_toml is not None:
                _atomic_write(toml_path, new_toml)

            # Remove now-emptied source folders (e.g. Tomograms/Missalignment/
            # and its ctf/even/odd subfolders) once their content has moved out,
            # plus any {id}/ folder that held nothing but junk to begin with.
            # Deepest-first so a parent is emptied of its subdirs before its own
            # rmdir. Skip any left non-empty by a stray file the allowlist ignored.
            for kind in ("Tomograms", "Annotations"):
                for id_dir in _prunable_dirs(recon_dir / kind):
                    _rmdir_if_empty(id_dir)

            # Clean up now-empty flat Tomograms/Annotations dirs.
            for kind in ("Tomograms", "Annotations"):
                _rmdir_if_empty(recon_dir / kind)
        except OSError as e:
            print(f"# NOTE: {acq_dir}: apply failed ({e}); skipping — may be partially migrated", file=sys.stderr)
            total_skipped += 1
            continue

        total_moves += len(moves)
        total_mkdirs += len(mkdirs)
        total_tomls += written + (1 if new_toml is not None else 0)

    if args.apply:
        skipped = f", skipped {total_skipped} acquisition(s) on error" if total_skipped else ""
        print(
            f"Applied {total_moves} move(s), {total_mkdirs} mkdir(s), "
            f"wrote {total_tomls} toml file(s){skipped}.",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
