import { useLayoutEffect, useMemo, useRef, useState } from 'react';
import {
  Box,
  MenuItem,
  Stack,
  TextField,
  Typography,
  alpha
} from '@mui/material';
import {
  MaterialReactTable,
  MRT_TablePagination,
  useMaterialReactTable,
  type MRT_ColumnDef,
  type MRT_PaginationState
} from 'material-react-table';
import type { IssueGroup, IssueSeverity } from '~/types';
import { useDebounce } from '~/hooks/useDebounce';
import { SectionHeader } from './SectionHeader';
import {
  type IssueFilters,
  useOutstandingIssuesQuery
} from '~/utils/queryOptions';
import {
  AcquisitionListCell,
  ReconstructionsListCell,
  SampleCell,
  SeverityPill,
  StillPresentCell,
  WarningTypeCell,
  formatDate
} from './issueCells';
import {
  groupSampleWarnings,
  type SampleWarningRow
} from './groupSampleWarnings';

// Priority order (most to least severe) — plain alphabetical sort would put
// "info" between "error" and "warning".
const SEVERITY_RANK: Record<IssueSeverity, number> = {
  error: 0,
  warning: 1,
  info: 2
};

function useColumns(): MRT_ColumnDef<SampleWarningRow>[] {
  return useMemo(
    () => [
      {
        accessorKey: 'category',
        header: 'Warning type',
        size: 125,
        Cell: ({ row }) => <WarningTypeCell category={row.original.category} />
      },
      {
        accessorKey: 'severity',
        header: 'Severity',
        size: 95,
        sortingFn: (a, b) =>
          SEVERITY_RANK[a.original.severity] -
          SEVERITY_RANK[b.original.severity],
        Cell: ({ row }) => <SeverityPill severity={row.original.severity} />
      },
      {
        id: 'sample',
        header: 'Sample',
        size: 135,
        Cell: ({ row }) => (
          <SampleCell
            fileKind={row.original.file_kind}
            mdRunId={row.original.md_run_id}
            message={row.original.message}
            sampleId={row.original.sample_id}
            samplePath={row.original.sample_path}
            showActions={row.original.acquisitions.length === 0}
          />
        )
      },
      {
        id: 'acquisitions',
        header: 'Acquisition(s)',
        size: 180,
        // Zero the cell's own padding — the acquisition "bands" carry their
        // own inset (see issueCells.tsx) so their alternating background can
        // bleed edge-to-edge across the full column width instead of
        // stopping short at the cell's default padding, which read as a
        // vertical white gutter down both sides of the column.
        muiTableBodyCellProps: { sx: { p: 0 } },
        Cell: ({ row }) => <AcquisitionListCell row={row.original} />
      },
      {
        id: 'reconstructions',
        header: 'Reconstruction(s)',
        size: 165,
        muiTableBodyCellProps: { sx: { p: 0 } },
        Cell: ({ row }) => <ReconstructionsListCell row={row.original} />
      },
      {
        accessorKey: 'first_seen_at',
        header: 'First seen',
        size: 85,
        Cell: ({ cell }) => formatDate(cell.getValue<number>())
      },
      {
        id: 'still_present',
        header: 'Still present as of',
        // Wide enough for the full "M/D/YYYY, H:MM:SS AM/PM TZ" string
        // (`formatTs`) without clipping — verified in a real browser; a
        // narrower column silently truncated the timestamp (the cell's
        // overflow:hidden clips with no ellipsis/tooltip fallback).
        size: 190,
        Cell: ({ row }) => (
          <StillPresentCell
            reEvaluated={row.original.reEvaluated}
            timestamp={row.original.stillPresentAt}
          />
        )
      }
    ],
    []
  );
}

// Local toolbar filters — everything except the free-text search, which is
// owned by the URL (see `q`/`onQueryChange`).
type LocalFilters = Omit<IssueFilters, 'q' | 'file_kind'>;

export function OutstandingIssuesTable({
  q = '',
  onQueryChange
}: {
  // Free-text search. The URL is its source of truth so a filtered table is a
  // shareable link (a detail page's "view warnings" link seeds it, and typing
  // writes back through onQueryChange).
  readonly q?: string;
  readonly onQueryChange?: (q: string) => void;
}) {
  const [local, setLocal] = useState<LocalFilters>({});
  // Controlled so we can measure the table's on-screen position before a page
  // change and restore it after (see the layout effect below).
  const [pagination, setPagination] = useState<MRT_PaginationState>({
    pageIndex: 0,
    pageSize: 10
  });
  // Bottom edge of the table (bottom toolbar) in viewport coords, captured the
  // instant the user clicks a pager — before the new rows re-render.
  const tableRef = useRef<HTMLDivElement>(null);
  const anchorBottom = useRef<number | null>(null);
  // Input + URL update on every keystroke (responsive, shareable); the query
  // only fires 300ms after typing stops (matches SamplesBrowser).
  const debouncedQ = useDebounce(q, 300);
  const filters: IssueFilters = {
    ...local,
    ...(debouncedQ ? { q: debouncedQ } : {})
  };
  const {
    data: rawData = [],
    isFetching,
    isError
  } = useOutstandingIssuesQuery(filters);
  // Unfiltered denominator (same query key as the component's filtered fetch
  // when no filters are set, so they dedupe). Sum each group's issues to
  // count actual warnings/errors, not table rows (rows are now regrouped by
  // sample + warning category, so they undercount individual issues).
  const { data: allIssues = [] } = useOutstandingIssuesQuery({});
  const totalIssues = allIssues.reduce(
    (n: number, g: IssueGroup) => n + g.issues.length,
    0
  );
  const matchCount = rawData.reduce(
    (n: number, g: IssueGroup) => n + g.issues.length,
    0
  );
  const data = useMemo(() => groupSampleWarnings(rawData), [rawData]);
  const columns = useColumns();

  const setFilter = <K extends keyof LocalFilters>(
    key: K,
    value: LocalFilters[K] | ''
  ) =>
    setLocal(prev => {
      const next = { ...prev };
      if (value === '' || value == null) {
        delete next[key];
      } else {
        next[key] = value as LocalFilters[K];
      }
      return next;
    });

  const table = useMaterialReactTable<SampleWarningRow>({
    columns,
    data,
    getRowId: row => row.key,
    onPaginationChange: updater => {
      // Row heights vary, so a page swap changes the table's total height and
      // shoves everything below it. Remember where the bottom edge sits now;
      // the layout effect scrolls it back there once the new page renders.
      anchorBottom.current =
        tableRef.current?.getBoundingClientRect().bottom ?? null;
      setPagination(updater);
    },
    state: {
      pagination,
      showProgressBars: isFetching,
      showAlertBanner: isError
    },
    muiToolbarAlertBannerProps: isError
      ? { color: 'error', children: 'Failed to load outstanding issues.' }
      : undefined,
    // Fixed column widths that the user can drag-resize, sized to fit without
    // horizontal scroll (see column `size`s above). The 1440px viewport's
    // actual table content area is ~1150px wide (the page's centered
    // MuiContainer + card padding eat the rest) — verified in a real browser,
    // not just by summing the `size`s against the raw viewport width.
    layoutMode: 'grid',
    enableColumnResizing: true,
    columnResizeMode: 'onChange',
    mrtTheme: theme => ({ draggingBorderColor: theme.palette.grey[300] }),
    defaultColumn: { grow: 1 },
    muiTableBodyRowProps: { hover: false },
    enableColumnActions: false,
    enableColumnFilters: false,
    enableDensityToggle: false,
    enableSorting: true,
    // The toolbar is our own filter controls; MRT's built-ins are off.
    enableGlobalFilter: false,
    // Paginated, 10 rows by default; the page-size selector (5/10/15/20/25)
    // lives in the top toolbar beside the filters, and the bottom toolbar
    // duplicates the pagination bar (matches the portal tables on /data).
    enablePagination: true,
    enableBottomToolbar: true,
    initialState: {
      density: 'comfortable',
      sorting: [{ id: 'severity', desc: false }]
    },
    // Match the portal tables (/data, /experimental, /md-simulation).
    muiTablePaperProps: {
      elevation: 0,
      sx: { border: 1, borderColor: 'divider', borderRadius: 2 }
    },
    localization: { noRecordsToDisplay: 'No outstanding warnings or errors.' },
    renderTopToolbar: ({ table }) => (
      <Box
        sx={{
          p: 1.5,
          bgcolor: t => alpha(t.palette.primary.main, 0.12),
          borderBottom: 1,
          borderColor: 'divider',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'flex-end',
          gap: 1,
          flexWrap: 'wrap'
        }}
      >
        <Stack alignItems="center" direction="row" spacing={1.5} useFlexGap>
          <TextField
            onChange={e => onQueryChange?.(e.target.value)}
            placeholder="Type to filter"
            size="small"
            sx={{
              minWidth: { xs: 330, sm: 375, md: 480 },
              maxWidth: 520,
              bgcolor: 'common.white'
            }}
            value={q}
          />
          <TextField
            label="Severity"
            onChange={e =>
              setFilter('severity', e.target.value as IssueFilters['severity'])
            }
            select
            size="small"
            sx={{ minWidth: 150, bgcolor: 'common.white' }}
            value={filters.severity ?? ''}
          >
            <MenuItem value="">All severities</MenuItem>
            <MenuItem value="error">Errors only</MenuItem>
            <MenuItem value="warning">Warnings only</MenuItem>
            <MenuItem value="info">Info only</MenuItem>
          </TextField>
        </Stack>
        {/* ml:auto (on a wrapper Box we control, so the margin is reliably a
            flex-item margin) pushes pagination to the right edge on the wide
            single-row layout, keeping the filters left; when it wraps below,
            the Box's justifyContent:flex-end right-aligns both rows. */}
        <Box sx={{ ml: 'auto', alignSelf: 'flex-end' }}>
          <MRT_TablePagination table={table} />
        </Box>
      </Box>
    )
  });

  // After the new page renders, nudge the scroll position by exactly how far
  // the table's bottom edge moved, so it looks like nothing shifted at all.
  // useLayoutEffect (not useEffect) so the correction happens before paint — no
  // visible flicker.
  useLayoutEffect(() => {
    if (anchorBottom.current == null) {
      return;
    }
    const after = tableRef.current?.getBoundingClientRect().bottom;
    if (after != null) {
      window.scrollBy(0, after - anchorBottom.current);
    }
    anchorBottom.current = null;
  }, [pagination]);

  return (
    <Box>
      <SectionHeader
        count={totalIssues}
        title="Outstanding data warnings & errors"
      />
      <Typography color="text.secondary" sx={{ mb: 2 }} variant="body1">
        {matchCount.toLocaleString()} match the selected filters
      </Typography>
      <Box ref={tableRef}>
        <MaterialReactTable table={table} />
      </Box>
    </Box>
  );
}
