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
import type { IssueGroup } from '~/types';
import { useDebounce } from '~/hooks/useDebounce';
import { SectionHeader } from './SectionHeader';
import {
  type IssueFilters,
  useOutstandingIssuesQuery
} from '~/utils/queryOptions';
import {
  EntityCell,
  FileCell,
  IssuesCell,
  SeverityPill,
  StillPresentCell,
  formatDate,
  issueRowId
} from './issueCells';

// Priority order (most to least severe) — plain alphabetical sort would put
// "info" between "error" and "warning".
const SEVERITY_RANK: Record<IssueGroup['severity'], number> = {
  error: 0,
  warning: 1,
  info: 2
};

function useColumns(): MRT_ColumnDef<IssueGroup>[] {
  return useMemo(
    () => [
      {
        id: 'entity',
        header: 'Sample / Acquisition',
        size: 220,
        Cell: ({ row }) => <EntityCell group={row.original} />
      },
      {
        id: 'file',
        header: 'File',
        size: 260,
        Cell: ({ row }) => <FileCell group={row.original} />
      },
      {
        accessorKey: 'severity',
        header: 'Severity',
        size: 110,
        sortingFn: (a, b) =>
          SEVERITY_RANK[a.original.severity] -
          SEVERITY_RANK[b.original.severity],
        Cell: ({ row }) => <SeverityPill severity={row.original.severity} />
      },
      {
        id: 'issues',
        header: 'Issues',
        Cell: ({ row }) => <IssuesCell group={row.original} />
      },
      {
        accessorKey: 'first_seen_at',
        header: 'First seen',
        size: 130,
        Cell: ({ cell }) => formatDate(cell.getValue<number>())
      },
      {
        id: 'still_present',
        header: 'Still present as of',
        size: 170,
        Cell: ({ row }) => <StillPresentCell group={row.original} />
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
  const { data = [], isFetching, isError } = useOutstandingIssuesQuery(filters);
  // Unfiltered denominator (same query key as the component's filtered fetch
  // when no filters are set, so they dedupe). Rows are *grouped* issues, so we
  // sum each group's issues to count actual warnings/errors, not table rows.
  const { data: allIssues = [] } = useOutstandingIssuesQuery({});
  const totalIssues = allIssues.reduce((n, g) => n + g.issues.length, 0);
  const matchCount = data.reduce((n, g) => n + g.issues.length, 0);
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

  const table = useMaterialReactTable<IssueGroup>({
    columns,
    data,
    getRowId: issueRowId,
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
