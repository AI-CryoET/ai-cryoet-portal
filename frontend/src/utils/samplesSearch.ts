import { z } from 'zod';
import { FIELDS } from './filterFields';

// Coerce single-value query params into single-element arrays so that a URL
// like `?camera=Falcon` validates against `z.array(z.string())`. TanStack
// Router's default search parser returns a string for a single occurrence and
// an array for repeated keys — handle both.
function toArray(v: unknown): unknown {
  if (v == null) {
    return v;
  }
  return Array.isArray(v) ? v : [v];
}

// `z.coerce.boolean()` treats EVERY non-empty string as true — including
// "false" — so coerce the spellings explicitly instead. Accepts a native
// boolean (TanStack Router's default search parser JSON-decodes `true`/`false`)
// and the common string forms; anything unrecognized becomes `undefined` so
// it's dropped rather than silently read as true.
function toBoolean(v: unknown): boolean | undefined {
  if (typeof v === 'boolean') {
    return v;
  }
  if (v === 'true' || v === '1') {
    return true;
  }
  if (v === 'false' || v === '0') {
    return false;
  }
  return undefined;
}

const stringArray = z.preprocess(toArray, z.array(z.string()).optional());
const booleanish = z.preprocess(toBoolean, z.boolean().optional());
const rangeBound = z.coerce.number().optional();

// Registry-driven field shapes. Reduce over FIELDS so the schema stays in sync
// with filterFields.ts: text → string[], existence/boolean → tri-state bool via
// presence, range → {key}_min + {key}_max coerced numbers.
//
// ponytail: voltage is `text` in the registry (discrete kV multi-select), so it
// becomes string[] here — values are stringified in the query string anyway and
// the backend voltage param parses them. Same for the `‡` JSON facets
// (linker_pattern / nucleosome_footprint / label_aunp_size_nm): stored strings
// matched verbatim.
//
// Note: `data_source` and `project` are string[] (multi-select per the
// registry), not single strings — consumers (FilterPanel, filterGating) read
// them as arrays.
const registryShape: Record<string, z.ZodTypeAny> = {};
for (const f of FIELDS) {
  if (f.kind === 'range') {
    registryShape[`${f.key}_min`] = rangeBound;
    registryShape[`${f.key}_max`] = rangeBound;
  } else if (f.kind === 'existence' || f.kind === 'boolean') {
    registryShape[f.key] = booleanish;
  } else {
    registryShape[f.key] = stringArray;
  }
}

// Search-param schema for the /samples route. Lives in utils (not the route or
// the hook) so neither owner has to import the other (avoids circular deps).
// Registry fields MERGED with the hand-written canonical fields below.
export const samplesSearchSchema = z.object({
  ...registryShape,
  // URL-canonical fields (§9.1) — kept exactly as before, including the sort enum.
  q: z.string().optional(),
  sort: z.enum(['sample_id', 'project', 'type']).optional(),
  order: z.enum(['asc', 'desc']).optional(),
  limit: z.coerce.number().int().positive().optional(),
  offset: z.coerce.number().int().nonnegative().optional()
});

// The registry params are folded into the schema at runtime (reduced over
// FIELDS), so `z.infer` only sees the canonical fields statically. Re-expose the
// registry params via an index signature so callers can set/read them (e.g.
// `data_source: string[]`, `pixel_size_min: number`). Intersecting with the
// canonical inferred type keeps `sort`/`limit`/etc. precisely typed
// (`X & unknown = X`); registry params read back as `unknown` and are narrowed
// at the use site (the browsers + filterGating already treat them dynamically).
// ponytail: index-typed rather than a precise per-key mapped type — that would
// need the registry declared `as const`; the drift test already pins parity.
export type SamplesSearchParams = z.infer<typeof samplesSearchSchema> & {
  [key: string]: unknown;
};

export function buildSamplesQueryString(params: SamplesSearchParams): string {
  const sp = new URLSearchParams();
  const addOne = (k: string, v: unknown) => {
    if (v === undefined || v === null || v === '') {
      return;
    }
    sp.append(k, String(v));
  };
  const addMany = (k: string, v: unknown[] | undefined) => {
    if (!v) {
      return;
    }
    for (const item of v) {
      addOne(k, item);
    }
  };
  const p = params as Record<string, unknown>;
  // Registry fields — mirror the schema reduction above.
  for (const f of FIELDS) {
    if (f.kind === 'range') {
      addOne(`${f.key}_min`, p[`${f.key}_min`]);
      addOne(`${f.key}_max`, p[`${f.key}_max`]);
    } else if (f.kind === 'existence' || f.kind === 'boolean') {
      if (p[f.key] !== undefined) {
        addOne(f.key, p[f.key]);
      }
    } else {
      addMany(f.key, p[f.key] as unknown[] | undefined);
    }
  }
  // Hand-written canonical fields.
  addOne('q', params.q);
  addOne('sort', params.sort);
  addOne('order', params.order);
  addOne('limit', params.limit);
  addOne('offset', params.offset);
  const qs = sp.toString();
  return qs ? `?${qs}` : '';
}
