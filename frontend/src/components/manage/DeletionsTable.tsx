import { useMemo, useState } from 'react'
import { Box, Chip, MenuItem, Stack, TextField, Tooltip, Typography, alpha } from '@mui/material'
import {
  MaterialReactTable,
  MRT_TablePagination,
  useMaterialReactTable,
  type MRT_ColumnDef,
} from 'material-react-table'
import { CustomLink } from '~/components/CustomLink'
import type { DeletionEntityType, DeletionEvent } from '~/types'
import { type DeletionFilters, useDeletionsQuery } from '~/utils/queryOptions'

const ENTITY_TYPE_OPTIONS: DeletionEntityType[] = [
  'sample',
  'acquisition',
  'raw_tomogram',
  'post_processed_tomogram',
  'annotation',
  'tilt_series',
  'md_source',
]

const WITHIN_HOURS_OPTIONS = [
  { label: 'All time', value: undefined },
  { label: 'Last 24h', value: 24 },
  { label: 'Last 7 days', value: 24 * 7 },
  { label: 'Last 30 days', value: 24 * 30 },
]

// Detected-at is Unix seconds; render in the viewer's locale.
function formatTs(seconds: number): string {
  return new Date(seconds * 1000).toLocaleString(undefined, { timeZoneName: 'short' })
}

// Entity link: sample-scoped rows link to the sample; acquisition-scoped
// (and below) rows link to the acquisition. Renamed/deleted entities below
// acquisition level (tomogram, annotation, tilt series) have no detail page
// of their own, so they still link to their owning acquisition.
function EntityCell({ event }: { event: DeletionEvent }) {
  if (event.acquisition_id) {
    return (
      <CustomLink
        to="/acquisitions/$acquisitionId"
        params={{ acquisitionId: event.acquisition_id }}
        search={{ sampleId: event.sample_id }}
      >
        {`${event.sample_id} · ${event.acquisition_id}`}
      </CustomLink>
    )
  }
  return (
    <CustomLink to="/samples/$sampleId" params={{ sampleId: event.sample_id }}>
      {event.sample_id}
    </CustomLink>
  )
}

function KindPill({ kind }: { kind: DeletionEvent['kind'] }) {
  return (
    <Chip
      label={kind}
      size="small"
      color={kind === 'rename' ? 'info' : 'default'}
      variant="outlined"
    />
  )
}

// Renames carry `{"renamed_from": old_id, "renamed_to": new_id}` instead of a
// row snapshot; deletions carry a full last-known-row snapshot (or nothing).
function DetailCell({ event }: { event: DeletionEvent }) {
  if (event.kind === 'rename') {
    const parsed = event.last_known_json
      ? (JSON.parse(event.last_known_json) as { renamed_from: string; renamed_to: string })
      : null
    if (!parsed) return <>—</>
    return (
      <Typography variant="body2" sx={{ fontFamily: 'monospace', fontSize: 12.5 }}>
        {parsed.renamed_from} → {parsed.renamed_to}
      </Typography>
    )
  }
  if (!event.last_known_path) return <>—</>
  return (
    <Tooltip title={event.last_known_path}>
      <Typography
        variant="body2"
        sx={{
          fontFamily: 'monospace',
          fontSize: 12.5,
          color: 'text.secondary',
          maxWidth: 320,
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
        }}
      >
        {event.last_known_path}
      </Typography>
    </Tooltip>
  )
}

function useColumns(): MRT_ColumnDef<DeletionEvent>[] {
  return useMemo(
    () => [
      {
        accessorKey: 'kind',
        header: 'Kind',
        size: 100,
        Cell: ({ row }) => <KindPill kind={row.original.kind} />,
      },
      {
        id: 'entity',
        header: 'Sample / Acquisition',
        size: 220,
        Cell: ({ row }) => <EntityCell event={row.original} />,
      },
      {
        accessorKey: 'entity_type',
        header: 'Type',
        size: 160,
      },
      {
        accessorKey: 'entity_id',
        header: 'Id',
        size: 160,
        Cell: ({ cell }) => cell.getValue<string | null>() ?? '—',
      },
      {
        id: 'detail',
        header: 'Detail',
        size: 320,
        Cell: ({ row }) => <DetailCell event={row.original} />,
      },
      {
        accessorKey: 'detected_at',
        header: 'Detected',
        size: 200,
        Cell: ({ cell }) => formatTs(cell.getValue<number>()),
      },
    ],
    [],
  )
}

export function DeletionsTable() {
  const [filters, setFilters] = useState<DeletionFilters>({})
  const { data = [], isFetching, isError } = useDeletionsQuery(filters)
  const columns = useColumns()

  const setFilter = <K extends keyof DeletionFilters>(
    key: K,
    value: DeletionFilters[K] | '',
  ) =>
    setFilters((prev) => {
      const next = { ...prev }
      if (value === '' || value == null) delete next[key]
      else next[key] = value as DeletionFilters[K]
      return next
    })

  const table = useMaterialReactTable<DeletionEvent>({
    columns,
    data,
    getRowId: (r) => String(r.id),
    state: { showProgressBars: isFetching, showAlertBanner: isError },
    muiToolbarAlertBannerProps: isError
      ? { color: 'error', children: 'Failed to load the deletion feed.' }
      : undefined,
    enableColumnActions: false,
    enableColumnFilters: false,
    enableDensityToggle: false,
    enableSorting: true,
    enableGlobalFilter: false,
    enablePagination: true,
    enableBottomToolbar: false,
    initialState: {
      density: 'comfortable',
      sorting: [{ id: 'detected_at', desc: true }],
      pagination: { pageSize: 10, pageIndex: 0 },
    },
    muiTablePaperProps: {
      elevation: 0,
      sx: { border: 1, borderColor: 'divider', borderRadius: 2 },
    },
    localization: { noRecordsToDisplay: 'No deletions or renames recorded yet.' },
    renderTopToolbar: ({ table }) => (
      <Box
        sx={{
          p: 1.5,
          bgcolor: (t) => alpha(t.palette.primary.main, 0.12),
          borderBottom: 1,
          borderColor: 'divider',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: 1.5,
          flexWrap: 'wrap',
        }}
      >
        <Stack
          direction="row"
          spacing={1.5}
          alignItems="center"
          flexWrap="wrap"
          useFlexGap
          sx={{ flex: 1 }}
        >
          <TextField
            size="small"
            placeholder="Filter by sample id…"
            value={filters.sample_id ?? ''}
            onChange={(e) => setFilter('sample_id', e.target.value)}
            sx={{ flex: 1, minWidth: 180, maxWidth: 260, bgcolor: 'common.white' }}
          />
          <TextField
            select
            size="small"
            label="Type"
            value={filters.entity_type ?? ''}
            onChange={(e) =>
              setFilter('entity_type', e.target.value as DeletionEntityType)
            }
            sx={{ minWidth: 180, bgcolor: 'common.white' }}
          >
            <MenuItem value="">All types</MenuItem>
            {ENTITY_TYPE_OPTIONS.map((t) => (
              <MenuItem key={t} value={t}>
                {t}
              </MenuItem>
            ))}
          </TextField>
          <TextField
            select
            size="small"
            label="Since"
            value={filters.within_hours ?? ''}
            onChange={(e) =>
              setFilter(
                'within_hours',
                e.target.value ? Number(e.target.value) : undefined,
              )
            }
            sx={{ minWidth: 150, bgcolor: 'common.white' }}
          >
            {WITHIN_HOURS_OPTIONS.map((opt) => (
              <MenuItem key={opt.label} value={opt.value ?? ''}>
                {opt.label}
              </MenuItem>
            ))}
          </TextField>
        </Stack>
        <MRT_TablePagination table={table} />
      </Box>
    ),
  })

  return <MaterialReactTable table={table} />
}
