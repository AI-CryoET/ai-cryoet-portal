// Shared gating + chip derivation for the filter browsers (SamplesBrowser /
// AllDataBrowser). All pure functions over the registry + current URL search,
// so notices/chips/disabled-state clear automatically (resolved decision 10:
// derived state, no dismissal flag).
import {
  FIELDS,
  GROUPS,
  PROJECT_REQUIRES_DATA_SOURCE,
  type Field
} from '~/utils/filterFields';
import type { SamplesSearchParams } from '~/utils/samplesSearch';
import { prettyDatasetType } from '~/components/landing/LandingFilters';

export type DataSource = 'experimental' | 'simulation';

// field.key -> owning Group (for auto-select + disable lookups).
const GROUP_BY_FIELD = new Map<string, (typeof GROUPS)[number]>();
for (const g of GROUPS) {
  for (const f of g.fields) {
    GROUP_BY_FIELD.set(f.key, g);
  }
}

// The single data_source value, if the URL pins exactly one arm. `string[]`
// per the Phase 3 contract; only a one-element array means "this arm".
function soleDataSource(s: SamplesSearchParams): DataSource | undefined {
  const v = (s as Record<string, unknown>).data_source as string[] | undefined;
  if (v?.length === 1 && (v[0] === 'experimental' || v[0] === 'simulation')) {
    return v[0];
  }
  return undefined;
}

function projectIncludes(s: SamplesSearchParams, p: string): boolean {
  const v = (s as Record<string, unknown>).project as string[] | undefined;
  return !!v && v.includes(p);
}
function selectedProjects(s: SamplesSearchParams): string[] {
  const v = (s as Record<string, unknown>).project as string[] | undefined;
  return Array.isArray(v) ? v : [];
}
function projectSet(s: SamplesSearchParams): boolean {
  return selectedProjects(s).length > 0;
}

// Group ids to disable given the current search and (on single-arm routes) a
// locked data_source. A group is disabled when its arm is excluded, or when it
// requires chromatin but project is set to something else.
export function computeDisabledGroups(
  s: SamplesSearchParams,
  lockedDataSource?: DataSource
): Set<string> {
  const arm = lockedDataSource ?? soleDataSource(s);
  const disabled = new Set<string>();
  const projs = selectedProjects(s);
  for (const g of GROUPS) {
    if (g.appliesTo && arm && g.appliesTo !== arm) {
      disabled.add(g.id);
    }
    // ADR-0003: an arm-gated group is disabled when every selected project
    // forbids that arm (e.g. synapse ⇒ experimental disables the simulation
    // arm). With no project set, or one project that allows the arm, it stays.
    if (
      g.appliesTo &&
      projs.length > 0 &&
      !projs.some(p => {
        const req = PROJECT_REQUIRES_DATA_SOURCE[p];
        return req === undefined || req === g.appliesTo;
      })
    ) {
      disabled.add(g.id);
    }
    if (
      g.requiresProject === 'chromatin' &&
      projectSet(s) &&
      !projectIncludes(s, 'chromatin')
    ) {
      disabled.add(g.id);
    }
  }
  return disabled;
}

// Auto-select wrapper for the patch handler: when the user sets a field whose
// GROUP is arm- or chromatin-gated and the relevant gating control is still
// unset, also set that control. The gating fields themselves (data_source /
// project) never auto-trigger — they ARE the controls. On single-arm routes
// data_source is locked, so we skip the arm auto-select there.
export function applyGating(
  prev: SamplesSearchParams,
  patch: Partial<SamplesSearchParams>,
  lockedDataSource?: DataSource
): Partial<SamplesSearchParams> {
  const out: Partial<SamplesSearchParams> = { ...patch };
  const p = patch as Record<string, unknown>;
  const armUnset = !lockedDataSource && !soleDataSource(prev);
  const projUnset = !projectSet(prev);

  for (const key of Object.keys(patch)) {
    if (p[key] === undefined) {
      continue;
    }
    // Range keys are `${field.key}_min`/`_max`; map back to the field key.
    const base = key.replace(/_(min|max)$/, '');
    const field: Field | undefined =
      FIELDS.find(f => f.key === base) ?? FIELDS.find(f => f.key === key);
    if (!field || field.gating) {
      continue;
    }
    const g = GROUP_BY_FIELD.get(field.key);
    if (!g) {
      continue;
    }
    if (g.appliesTo && armUnset && !('data_source' in out)) {
      (out as Record<string, unknown>).data_source = [g.appliesTo];
    }
    if (g.requiresProject === 'chromatin' && projUnset && !('project' in out)) {
      (out as Record<string, unknown>).project = ['chromatin'];
    }
  }
  return out;
}

// Derived notices (pure): (a) an arm-specific filter is set while data_source is
// unset — only possible on /data, where data_source is selectable; (b) explain
// an auto-set. Clears automatically when the condition no longer holds.
export function filterNotices(
  s: SamplesSearchParams,
  lockedDataSource?: DataSource
): string[] {
  if (lockedDataSource) {
    return [];
  }
  const notices: string[] = [];
  const arm = soleDataSource(s);
  if (!arm) {
    // Which gated groups have an active field while no arm is chosen?
    const armsHit = new Set<DataSource>();
    for (const f of FIELDS) {
      if (f.gating) {
        continue;
      }
      const g = GROUP_BY_FIELD.get(f.key);
      if (g?.appliesTo && isFieldActive(s, f)) {
        armsHit.add(g.appliesTo);
      }
    }
    for (const a of armsHit) {
      notices.push(
        `Some active filters only apply to ${a} data — only ${a} samples and acquisitions matching them are shown.`
      );
    }
  }
  return notices;
}

// ── Active-field detection + chips (Phase 7, generalized over the registry) ──

export function isFieldActive(s: SamplesSearchParams, f: Field): boolean {
  const v = s as Record<string, unknown>;
  switch (f.kind) {
    case 'range':
      return v[`${f.key}_min`] !== undefined || v[`${f.key}_max`] !== undefined;
    case 'boolean':
    case 'existence':
      return v[f.key] !== undefined;
    default: {
      const arr = v[f.key] as unknown[] | undefined;
      return Array.isArray(arr) && arr.length > 0;
    }
  }
}

export type FilterChip = { id: string; label: string; clear: () => void };

// `clearKey` drops one URL key (used for text/boolean/existence and per-bound
// for range — caller wires it to navigate/replace).
export function buildChips(
  s: SamplesSearchParams,
  lockedDataSource: DataSource | undefined,
  clearKey: (key: string) => void
): FilterChip[] {
  const v = s as Record<string, unknown>;
  const chips: FilterChip[] = [];
  const display = (f: Field, val: string) =>
    f.key === 'dataset_type'
      ? prettyDatasetType(val)
      : f.key === 'data_source'
        ? val.charAt(0).toUpperCase() + val.slice(1)
        : val;

  for (const f of FIELDS) {
    if (f.key === 'data_source' && lockedDataSource) {
      continue;
    }
    switch (f.kind) {
      case 'range': {
        const lo = v[`${f.key}_min`];
        const hi = v[`${f.key}_max`];
        if (lo !== undefined) {
          chips.push({
            id: `${f.key}_min`,
            label: `${f.label} ≥ ${lo}`,
            clear: () => clearKey(`${f.key}_min`)
          });
        }
        if (hi !== undefined) {
          chips.push({
            id: `${f.key}_max`,
            label: `${f.label} ≤ ${hi}`,
            clear: () => clearKey(`${f.key}_max`)
          });
        }
        break;
      }
      case 'boolean': {
        const b = v[f.key];
        if (b !== undefined) {
          chips.push({
            id: f.key,
            label: `${f.label}: ${b ? 'Yes' : 'No'}`,
            clear: () => clearKey(f.key)
          });
        }
        break;
      }
      case 'existence': {
        if (v[f.key] !== undefined) {
          chips.push({
            id: f.key,
            label: f.label,
            clear: () => clearKey(f.key)
          });
        }
        break;
      }
      default: {
        const arr = v[f.key] as string[] | undefined;
        if (Array.isArray(arr) && arr.length) {
          chips.push({
            id: f.key,
            label: `${f.label}: ${arr.map(x => display(f, x)).join(', ')}`,
            clear: () => clearKey(f.key)
          });
        }
      }
    }
  }
  return chips;
}

// True when any acquisition-entity field is active in the (committed) search —
// drives SamplesPortalTable's expand-all.
export function anyAcquisitionFilterActive(s: SamplesSearchParams): boolean {
  return FIELDS.some(f => f.entity === 'acquisition' && isFieldActive(s, f));
}
