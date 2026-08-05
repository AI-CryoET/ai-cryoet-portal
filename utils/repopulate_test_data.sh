#!/usr/bin/env bash
# Repopulate scratch/data/ test set from the real data root.
#
# Hardlinks files where possible (same filesystem, files you own) and falls
# back to a real copy where the NFS refuses a hardlink (files owned by other
# users -> "Operation not permitted"). --delete resets each sample to the
# source layout, undoing anything the migration script rearranged in place.
#
# Edit SAMPLES below to change the test set. Paths are relative to SRC.
set -euo pipefail

SRC=/groups/cryoet/cryoet/data
DEST=/groups/cryoet/cryoet/data/scratch/data

SAMPLES=(
  Experimental/gouauxlab_20250210_HippWaffle
  Experimental/gouauxlab_20241211_HippWaffle
  Experimental/rosenlab_1210_example30bp_PORTAL_V2
  Experimental/Villalab_Nanogold_labeled_80S
  MdSimulation/Slab/12mer_25_0.073
)

warned=0
for rel in "${SAMPLES[@]}"; do
  parent=$(dirname "$rel")
  mkdir -p "$DEST/$parent"
  echo "==> $rel"
  # rc 23 = partial: happens when --delete can't remove stale files owned by
  # another user (permission wall only they/root can clear). Content still
  # copies fine, so warn and keep going rather than abort.
  rsync -a --delete --exclude='.DS_Store' \
    --link-dest="$SRC/$parent" \
    "$SRC/$rel" "$DEST/$parent/" \
    || { echo "  WARN: rsync rc=$? (stale foreign-owned files left in place)"; warned=1; }

  # Break hardlinks on .toml files: the migration (and editors) rewrite these
  # in place, which would corrupt the real source data through a shared inode.
  # cp --remove-destination unlinks the hardlinked copy first, giving the test
  # tree its own inode. Big .mrc stay hardlinked (moved, never edited).
  find "$DEST/$rel" -name '*.toml' -type f 2>/dev/null | while read -r f; do
    src="${f/#$DEST/$SRC}"
    # Skip tomls with no source (e.g. stale foreign-owned junk like a0aa that
    # exists only in the test copy) — nothing to re-copy.
    [ -f "$src" ] && cp -p --remove-destination "$src" "$f"
  done
done

echo "Done. Repopulated ${#SAMPLES[@]} sample(s) into $DEST"
[ "$warned" = 1 ] && echo "Some stale files couldn't be deleted (not owned by you) — ask their owner or root."
exit 0
