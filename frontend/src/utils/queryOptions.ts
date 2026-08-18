import {
  keepPreviousData,
  queryOptions,
  useQuery,
  useSuspenseQuery
} from '@tanstack/react-query';
import { apiFetch } from '~/utils/api';
import {
  buildSamplesQueryString,
  type SamplesSearchParams
} from '~/utils/samplesSearch';
import type {
  DeletionEntityType,
  DeletionEvent,
  FiltersOptionsOut,
  IssueGroup,
  ManageSummary,
  SampleDetail,
  SampleSummary,
  ScanLogLine,
  ScanRun,
  StatsOverviewOut,
  WarningOut
} from '~/types';

// Endpoints scoped to "the latest completed scan" return 404 when no scan has
// completed yet. Callers want an empty list in that case rather than an error.
export async function fetchOrEmpty<T>(path: string): Promise<T[]> {
  try {
    return await apiFetch<T[]>(path);
  } catch (err) {
    if (err instanceof Error && err.message.includes('404')) {
      return [];
    }
    throw err;
  }
}

// ── /samples list ────────────────────────────────────────────────────────────

export const samplesQueryOptions = (params: SamplesSearchParams = {}) =>
  queryOptions({
    queryKey: ['samples', 'list', params],
    queryFn: () =>
      apiFetch<SampleSummary[]>(`/samples${buildSamplesQueryString(params)}`)
  });

// `useQuery` (not `useSuspenseQuery`) + `placeholderData: keepPreviousData`
// so filter edits don't suspend and unmount the table while the new fetch
// is in flight. The route loader still primes the cache via `ensureQueryData`,
// so the first render after navigation has data immediately.
export function useSamplesQuery(params: SamplesSearchParams = {}) {
  return useQuery({
    ...samplesQueryOptions(params),
    placeholderData: keepPreviousData
  });
}

// ── /samples/{id} detail ─────────────────────────────────────────────────────

export const sampleDetailQueryOptions = (sampleId: string) =>
  queryOptions({
    queryKey: ['samples', 'detail', sampleId],
    queryFn: () =>
      apiFetch<SampleDetail>(`/samples/${encodeURIComponent(sampleId)}`)
  });

export function useSampleDetailQuery(sampleId: string) {
  return useSuspenseQuery(sampleDetailQueryOptions(sampleId));
}

// ── /samples/{id}/warnings ───────────────────────────────────────────────────

export const sampleWarningsQueryOptions = (sampleId: string) =>
  queryOptions({
    queryKey: ['samples', 'warnings', sampleId],
    queryFn: () =>
      apiFetch<WarningOut[]>(
        `/samples/${encodeURIComponent(sampleId)}/warnings`
      )
  });

export function useSampleWarningsQuery(sampleId: string) {
  return useSuspenseQuery(sampleWarningsQueryOptions(sampleId));
}

// ── /filters/options ─────────────────────────────────────────────────────────

export const filtersOptionsQueryOptions = queryOptions({
  queryKey: ['filters', 'options'],
  queryFn: () => apiFetch<FiltersOptionsOut>('/filters/options')
});

export function useFiltersOptionsQuery() {
  return useSuspenseQuery(filtersOptionsQueryOptions);
}

// ── /stats/overview ──────────────────────────────────────────────────────────

export const statsOverviewQueryOptions = queryOptions({
  queryKey: ['stats', 'overview'],
  queryFn: () => apiFetch<StatsOverviewOut>('/stats/overview')
});

export function useStatsOverviewQuery() {
  return useSuspenseQuery(statsOverviewQueryOptions);
}

// ── /manage/summary ───────────────────────────────────────────────────────────

export const manageSummaryQueryOptions = queryOptions({
  queryKey: ['manage', 'summary'],
  queryFn: () => apiFetch<ManageSummary>('/manage/summary')
});

export function useManageSummaryQuery() {
  return useSuspenseQuery(manageSummaryQueryOptions);
}

// ── /manage/issues (outstanding) ────────────────────────────────────────────

// Server-side filters for the outstanding-issues table. All optional; empty
// values are dropped from the query string so they fall through to "no filter".
export type IssueFilters = {
  severity?: 'error' | 'warning' | 'info';
  file_kind?: string;
  q?: string;
};

function buildIssueQueryString(filters: IssueFilters): string {
  const params = new URLSearchParams();
  if (filters.severity) {
    params.set('severity', filters.severity);
  }
  if (filters.file_kind) {
    params.set('file_kind', filters.file_kind);
  }
  if (filters.q) {
    params.set('q', filters.q);
  }
  const qs = params.toString();
  return qs ? `?${qs}` : '';
}

export const outstandingIssuesQueryOptions = (filters: IssueFilters = {}) =>
  queryOptions({
    queryKey: ['manage', 'issues', 'outstanding', filters],
    queryFn: () =>
      apiFetch<IssueGroup[]>(`/manage/issues${buildIssueQueryString(filters)}`)
  });

// `useQuery` + `keepPreviousData` so toolbar filter edits don't unmount the
// table while the next fetch is in flight.
export function useOutstandingIssuesQuery(filters: IssueFilters = {}) {
  return useQuery({
    ...outstandingIssuesQueryOptions(filters),
    placeholderData: keepPreviousData
  });
}

// ── /manage/issues/resolved (recently resolved) ─────────────────────────────

export const recentlyResolvedQueryOptions = (withinHours = 24) =>
  queryOptions({
    queryKey: ['manage', 'issues', 'resolved', withinHours],
    queryFn: () =>
      apiFetch<IssueGroup[]>(
        `/manage/issues/resolved?within_hours=${withinHours}`
      )
  });

export function useRecentlyResolvedQuery(withinHours = 24) {
  return useSuspenseQuery(recentlyResolvedQueryOptions(withinHours));
}

// ── /manage/deletions (deletion/rename audit feed) ──────────────────────────

export type DeletionFilters = {
  entity_type?: DeletionEntityType;
  sample_id?: string;
  within_hours?: number;
};

function buildDeletionQueryString(filters: DeletionFilters): string {
  const params = new URLSearchParams();
  if (filters.entity_type) {
    params.set('entity_type', filters.entity_type);
  }
  if (filters.sample_id) {
    params.set('sample_id', filters.sample_id);
  }
  if (filters.within_hours) {
    params.set('within_hours', String(filters.within_hours));
  }
  const qs = params.toString();
  return qs ? `?${qs}` : '';
}

export const deletionsQueryOptions = (filters: DeletionFilters = {}) =>
  queryOptions({
    queryKey: ['manage', 'deletions', filters],
    queryFn: () =>
      apiFetch<DeletionEvent[]>(
        `/manage/deletions${buildDeletionQueryString(filters)}`
      )
  });

// `useQuery` + `keepPreviousData` so toolbar filter edits don't unmount the
// table while the next fetch is in flight.
export function useDeletionsQuery(filters: DeletionFilters = {}) {
  return useQuery({
    ...deletionsQueryOptions(filters),
    placeholderData: keepPreviousData
  });
}

// ── /manage/scans (run history) ─────────────────────────────────────────────

export const scanRunsQueryOptions = queryOptions({
  queryKey: ['manage', 'scans', 'list'],
  queryFn: () => apiFetch<ScanRun[]>('/manage/scans')
});

export function useScanRunsQuery() {
  return useSuspenseQuery(scanRunsQueryOptions);
}

// ── /manage/scans/{id} ──────────────────────────────────────────────────────

// A specific scan run by id. Rejects with a 404 Error when the scan is
// unknown, which the route loader turns into a `notFound()`.
export const scanRunQueryOptions = (scanId: string) =>
  queryOptions({
    queryKey: ['manage', 'scans', 'detail', scanId],
    queryFn: () =>
      apiFetch<ScanRun>(`/manage/scans/${encodeURIComponent(scanId)}`)
  });

export function useScanRunQuery(scanId: string) {
  return useSuspenseQuery(scanRunQueryOptions(scanId));
}

// ── /manage/scans/{id}/logs ─────────────────────────────────────────────────

export type ScanLogFilters = {
  level?: 'DEBUG' | 'INFO' | 'WARNING' | 'ERROR';
  q?: string;
};

function buildLogQueryString(filters: ScanLogFilters): string {
  const params = new URLSearchParams();
  if (filters.level) {
    params.set('level', filters.level);
  }
  if (filters.q) {
    params.set('q', filters.q);
  }
  const qs = params.toString();
  return qs ? `?${qs}` : '';
}

export const scanLogsQueryOptions = (
  scanId: string,
  filters: ScanLogFilters = {}
) =>
  queryOptions({
    queryKey: ['manage', 'scans', 'detail', scanId, 'logs', filters],
    queryFn: () =>
      apiFetch<ScanLogLine[]>(
        `/manage/scans/${encodeURIComponent(scanId)}/logs${buildLogQueryString(
          filters
        )}`
      )
  });

// `useQuery` + `keepPreviousData` so the within-run log filter doesn't unmount
// the panel between fetches.
export function useScanLogsQuery(scanId: string, filters: ScanLogFilters = {}) {
  return useQuery({
    ...scanLogsQueryOptions(scanId, filters),
    placeholderData: keepPreviousData
  });
}
