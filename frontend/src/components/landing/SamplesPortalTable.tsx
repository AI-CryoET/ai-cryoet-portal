import { memo, useMemo } from 'react'
import { alpha, Box, Tooltip } from '@mui/material'
import {
  MaterialReactTable,
  useMaterialReactTable,
  type MRT_ColumnDef,
} from 'material-react-table'
import type { SampleSummary } from '~/types'
import type { SamplesSearchParams } from '~/utils/samplesSearch'
import { CustomLink } from '~/components/CustomLink'
import {
  PreviewThumbnail,
  thumbnailUrl,
  mdPreviewBySampleUrl,
} from '~/components/common/Thumbnail'
import { AcquisitionsSubTable } from './AcquisitionsSubTable'

const dash = (v: unknown) => (v == null || v === '' ? '—' : String(v))

// Shared truncation styles for cells whose content is wrapped (so the ellipsis
// belongs to the same element the tooltip is attached to).
const ellipsisSx = {
  overflow: 'hidden',
  textOverflow: 'ellipsis',
  whiteSpace: 'nowrap',
} as const

// memo: props (rows/filters/expandAllDetails) are all derived from the parent's
// debounced search, so they only change every 300ms. Without memo the whole
// table — and every mounted acquisition sub-table — re-renders on every
// keystroke as the URL search updates immediately. This is the filtering-lag fix.
export const SamplesPortalTable = memo(function SamplesPortalTable(props: {
  rows: SampleSummary[]
  loading?: boolean
  // Active search params threaded to each acquisition subtable for client-side
  // filtering (mirrors the server EXISTS).
  filters?: SamplesSearchParams
  // Set true (by the browser, from committed/debounced state) when any
  // acquisition-entity filter is active, so every detail panel opens to show
  // the filtered acquisitions.
  expandAllDetails?: boolean
}) {
  const { rows, loading, filters, expandAllDetails } = props

  const columns = useMemo<MRT_ColumnDef<SampleSummary>[]>(
    () => [
      {
        id: 'thumbnail',
        header: '',
        columnDefType: 'display',
        size: 80,
        Cell: ({ row }) => {
          const s = row.original
          // Simulation rows show the trajectory-level OVITO preview (the
          // sample-level image, matching the sample-detail hero); experimental
          // rows show the cached tilt-series thumbnail.
          const showMd = s.data_source === 'simulation'
          const src = showMd
            ? mdPreviewBySampleUrl(s.sample_id, s.path)
            : thumbnailUrl(s.thumbnail_path)
          const alt = showMd
            ? `OVITO preview for ${s.sample_id}`
            : `Middle tilt-series image for ${s.sample_id}`
          return (
            <PreviewThumbnail
              src={src}
              alt={alt}
              tooltipTitle={alt}
              clickable
            />
          )
        },
      },
      {
        accessorKey: 'sample_id',
        header: 'Sample id',
        size: 220,
        // grow: this is the only growing column, so at wide screens it absorbs
        // the leftover width and the row fills the whole table instead of
        // leaving dead space on the right.
        grow: true,
        Cell: ({ row }) => (
          <Tooltip title={row.original.sample_id}>
            <Box sx={ellipsisSx}>
              <CustomLink
                to="/samples/$sampleId"
                params={{ sampleId: row.original.sample_id }}
              >
                {row.original.sample_id}
              </CustomLink>
            </Box>
          </Tooltip>
        ),
      },
      { accessorKey: 'project', header: 'Project', size: 130 },
      {
        accessorKey: 'lab_name',
        header: 'Lab',
        size: 120,
        Cell: ({ cell }) => dash(cell.getValue()),
      },
      {
        accessorKey: 'type',
        header: 'Type',
        size: 150,
        Cell: ({ cell }) => {
          const v = cell.getValue<string | null>()
          return (
            <Tooltip title={v ?? ''}>
              <Box sx={ellipsisSx}>{dash(v)}</Box>
            </Tooltip>
          )
        },
      },
      { accessorKey: 'n_acquisitions', header: 'Acquisitions', size: 140 },
      { accessorKey: 'n_tilt_series', header: 'Tilt', size: 80 },
      { accessorKey: 'n_tomograms', header: 'Tomo', size: 80 },
    ],
    [],
  )

  const table = useMaterialReactTable({
    columns,
    data: rows,
    getRowId: (r) => r.sample_id,
    positionExpandColumn: 'first',
    // Fixed column widths: 'grid' layout sizes columns from their `size` (not
    // their content), so widths stay put as you page/filter instead of jumping
    // to fit each page's values. `grow: false` stops columns stretching to fill.
    layoutMode: 'grid',
    enableColumnResizing: false,
    defaultColumn: { grow: false },
    // Clip overflowing cell text to an ellipsis so a long value can't force a
    // column wider than its fixed size. sample_id/type wrap their own content
    // (for the tooltip); this covers the plain-text columns (project, lab).
    muiTableBodyCellProps: { sx: ellipsisSx },
    muiTableHeadCellProps: {
      sx: {
        '& .Mui-TableHeadCell-Content-Wrapper': {
          whiteSpace: 'nowrap',
          overflow: 'hidden',
          textOverflow: 'ellipsis',
        },
      },
    },
    // MRT wraps the panel in <Collapse mountOnEnter unmountOnExit>, so this
    // component only mounts (and fetches its sample detail) when the row is
    // expanded — acquisitions load lazily on demand, not N fetches up front.
    // Returning a truthy element here (rather than null when collapsed) is
    // what keeps each row's expand button enabled.
    renderDetailPanel: ({ row }) => (
      <AcquisitionsSubTable
        sampleId={row.original.sample_id}
        filters={filters}
      />
    ),
    enableColumnActions: false,
    enableColumnFilters: false,
    enableGlobalFilter: false,
    enableDensityToggle: false,
    // Drop the whole internal-actions cluster (search/hide-columns/fullscreen)
    // so the top toolbar holds only pagination, mirroring the /manage tables.
    enableToolbarInternalActions: false,
    enablePagination: true,
    positionPagination: 'both',
    // The bottom toolbar already reads as separate from the body via the last
    // row's border; add the same line under the top controls so both toolbars
    // are visually set off from the table the same way. Background matches
    // the /manage tables' top toolbar (e.g. RecentlyResolvedTable).
    muiTopToolbarProps: {
      sx: {
        bgcolor: (t) => alpha(t.palette.primary.main, 0.12),
        borderBottom: 1,
        borderColor: 'divider',
      },
    },
    // `expanded: true` opens every detail panel; MRT still mounts each panel
    // lazily (Collapse mountOnEnter), so a fetch fires per visible page row.
    // Leave `expanded` uncontrolled (undefined) when not expanding all.
    state: { isLoading: loading, ...(expandAllDetails ? { expanded: true } : {}) },
    initialState: {
      density: 'comfortable',
      pagination: { pageSize: 10, pageIndex: 0 },
    },
    muiTablePaperProps: {
      elevation: 0,
      sx: { border: 1, borderColor: 'divider', borderRadius: 2 },
    },
    muiDetailPanelProps: { sx: { p: 0 } },
  })

  return <MaterialReactTable table={table} />
})
