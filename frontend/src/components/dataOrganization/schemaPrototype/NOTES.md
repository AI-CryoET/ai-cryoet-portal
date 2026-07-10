# Schema-explorer layout prototype — THROWAWAY

**Question:** which layout for the Data schema tab — accordion of field tables
(Variant A) or a two-pane tree + field table (Variant C)?

**How to view:** `pnpm dev`, then open `/data-organization?tab=schema`. Use the
floating bar at the bottom (or ← / → keys) to switch variants. `?variant=A` and
`?variant=C` are shareable/reload-stable. The bar is hidden in production builds.

Both share the hybrid control bar (arm + project filter rows; source = always a
visible badge, filterable via All / Authored / Derived) and a common
`FieldsTable` + `SourceBadge`. Only the entity *layout* differs.

**Decided design (locked before prototyping):**
- Controls: hybrid (arm/project filter rows; source always a badge, also filterable).
- Data source: generate the real data from `docs/schema.md` (build script + drift
  test, mirroring `formFields.ts`). This prototype uses a hand-stubbed subset in
  `schemaData.ts` — NOT the real data. Replace it when folding the winner in.

**Verdict:** **Variant C (tree + two-pane) wins.** User found the two-pane tree
clearest for nesting. Tweak applied: the right pane shows the parent entity
(Sample / Acquisition) as an overline above the sub-entity title, for orientation.

Also decided: **one true source = `schema.py`.** Generate both `docs/schema.md`
and the frontend schema data from structured metadata on `schema.py` (drift-tested),
rather than parsing `schema.md`. Avoids `schema.md` drifting from the model.

Fold-in TODO: delete Variant A + `PrototypeSwitcher` + the `?variant` param + the
switcher wiring; move Variant C into the real page; replace `schemaData.ts` with
the generated data.
