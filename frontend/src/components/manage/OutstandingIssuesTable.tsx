import { useMemo, useState } from 'react'
import {
  Box,
  MenuItem,
  Stack,
  TextField,
  alpha,
} from '@mui/material'
import {
  MaterialReactTable,
  MRT_TablePagination,
  useMaterialReactTable,
  type MRT_ColumnDef,
} from 'material-react-table'
import type { IssueGroup } from '~/types'
import { useDebounce } from '~/hooks/useDebounce'
import {
  type IssueFilters,
  useOutstandingIssuesQuery,
} from '~/utils/queryOptions'
import {
  EntityCell,
  FileCell,
  IssuesCell,
  SeverityPill,
  StillPresentCell,
  formatDate,
  issueRowId,
} from './issueCells'

function useColumns(): MRT_ColumnDef<IssueGroup>[] {
  return useMemo(
    () => [
      {
        id: 'entity',
        header: 'Sample / Acquisition',
        size: 220,
        Cell: ({ row }) => <EntityCell group={row.original} />,
      },
      {
        id: 'file',
        header: 'File',
        size: 260,
        Cell: ({ row }) => <FileCell group={row.original} />,
      },
      {
        accessorKey: 'severity',
        header: 'Severity',
        size: 110,
        Cell: ({ row }) => <SeverityPill severity={row.original.severity} />,
      },
      {
        id: 'issues',
        header: 'Issues',
        Cell: ({ row }) => <IssuesCell group={row.original} />,
      },
      {
        accessorKey: 'first_seen_at',
        header: 'First seen',
        size: 130,
        Cell: ({ cell }) => formatDate(cell.getValue<number>()),
      },
      {
        id: 'still_present',
        header: 'Still present as of',
        size: 170,
        Cell: ({ row }) => <StillPresentCell group={row.original} />,
      },
    ],
    [],
  )
}

// Local toolbar filters — everything except the free-text search, which is
// owned by the URL (see `q`/`onQueryChange`).
type LocalFilters = Omit<IssueFilters, 'q' | 'file_kind'>

export function OutstandingIssuesTable({
  q = '',
  onQueryChange,
}: {
  // Free-text search. The URL is its source of truth so a filtered table is a
  // shareable link (a detail page's "view warnings" link seeds it, and typing
  // writes back through onQueryChange).
  q?: string
  onQueryChange?: (q: string) => void
}) {
  const [local, setLocal] = useState<LocalFilters>({})
  // Input + URL update on every keystroke (responsive, shareable); the query
  // only fires 300ms after typing stops (matches SamplesBrowser).
  const debouncedQ = useDebounce(q, 300)
  const filters: IssueFilters = { ...local, ...(debouncedQ ? { q: debouncedQ } : {}) }
  const { data = [], isFetching, isError } = useOutstandingIssuesQuery(filters)
  const columns = useColumns()

  const setFilter = <K extends keyof LocalFilters>(
    key: K,
    value: LocalFilters[K] | '',
  ) =>
    setLocal((prev) => {
      const next = { ...prev }
      if (value === '' || value == null) delete next[key]
      else next[key] = value as LocalFilters[K]
      return next
    })

  const table = useMaterialReactTable<IssueGroup>({
    columns,
    data,
    getRowId: issueRowId,
    state: { showProgressBars: isFetching, showAlertBanner: isError },
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
      sorting: [{ id: 'severity', desc: false }],
      pagination: { pageSize: 10, pageIndex: 0 },
    },
    // Match the portal tables (/data, /experimental, /md-simulation).
    muiTablePaperProps: {
      elevation: 0,
      sx: { border: 1, borderColor: 'divider', borderRadius: 2 },
    },
    localization: { noRecordsToDisplay: 'No outstanding warnings or errors.' },
    renderTopToolbar: ({ table }) => (
      <Box
        sx={{
          p: 1.5,
          bgcolor: (t) => alpha(t.palette.primary.main, 0.12),
          borderBottom: 1,
          borderColor: 'divider',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'flex-end',
          gap: 1,
          flexWrap: 'wrap',
        }}
      >
        <Stack direction="row" spacing={1.5} alignItems="center" useFlexGap>
          <TextField
            size="small"
            placeholder="Type to filter"
            value={q}
            onChange={(e) => onQueryChange?.(e.target.value)}
            sx={{
              minWidth: { xs: 330, sm: 375, md: 480 },
              maxWidth: 520,
              bgcolor: 'common.white',
            }}
          />
          <TextField
            select
            size="small"
            label="Severity"
            value={filters.severity ?? ''}
            onChange={(e) =>
              setFilter('severity', e.target.value as IssueFilters['severity'])
            }
            sx={{ minWidth: 150, bgcolor: 'common.white' }}
          >
            <MenuItem value="">All severities</MenuItem>
            <MenuItem value="error">Errors only</MenuItem>
            <MenuItem value="warning">Warnings only</MenuItem>
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
    ),
  })

  return <MaterialReactTable table={table} />
}
