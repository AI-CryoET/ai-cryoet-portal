import { useMemo } from 'react'
import { Box } from '@mui/material'
import {
  MaterialReactTable,
  useMaterialReactTable,
  type MRT_ColumnDef,
} from 'material-react-table'
import type { AcquisitionOut } from '~/types'
import { CustomLink } from '~/components/CustomLink'
import { PreviewThumbnail, acquisitionThumbnailUrl } from '~/components/common/Thumbnail'
import { QualityBadge } from '~/components/common/QualityBadge'

// Mirrors the API's `n_tomograms` semantics: raw + post-processed combined.
function tomogramCount(a: AcquisitionOut): number {
  return (a.raw_tomogram ? 1 : 0) + a.post_processed_tomograms.length
}

export function SampleAcquisitionsTable(props: {
  sampleId: string
  acquisitions: AcquisitionOut[]
  // `compact` renders the denser, unsortable variant used in the landing-page
  // sample dropdown; the default is the roomier sample-detail-page styling.
  compact?: boolean
  isLoading?: boolean
}) {
  const { sampleId, acquisitions, compact = false, isLoading } = props

  const columns = useMemo<MRT_ColumnDef<AcquisitionOut>[]>(
    () => [
      {
        id: 'thumbnail',
        header: '',
        columnDefType: 'display',
        enableSorting: false,
        // Compact width is 84px (not 80) so this column spans the parent's
        // thumbnail→Sample-id gap exactly, landing the Acquisition-id column
        // under the Sample-id column. Combined with the 64px left inset in
        // AcquisitionsSubTable, the thumbnails line up too. 84 = parent thumb
        // col(80) + comfy-data-pad(16) − comfy-display-pad(12).
        size: compact ? 84 : 140,
        Cell: ({ row }) => {
          const alt = `Middle tilt-series image for ${row.original.acquisition_id}`
          const thumb = (
            <PreviewThumbnail
              src={acquisitionThumbnailUrl(sampleId, row.original.acquisition_id)}
              alt={alt}
              tooltipTitle={alt}
              width={compact ? 56 : 96}
              height={compact ? 40 : 64}
              clickable
            />
          )
          // MRT gives compact display cells zero vertical padding, so the row
          // would be exactly the thumbnail's height; add a little breathing room.
          return compact ? <Box sx={{ py: 0.5 }}>{thumb}</Box> : thumb
        },
      },
      {
        accessorKey: 'acquisition_id',
        header: 'Acquisition id',
        minSize: 160,
        Cell: ({ row }) => (
          <CustomLink
            to="/acquisitions/$acquisitionId"
            params={{ acquisitionId: row.original.acquisition_id }}
            search={{ sampleId }}
          >
            {row.original.acquisition_id}
          </CustomLink>
        ),
      },
      {
        accessorKey: 'acquisition_quality',
        header: 'Quality',
        size: 120,
        Cell: ({ row }) => (
          <QualityBadge quality={row.original.acquisition_quality} />
        ),
      },
      {
        id: 'n_tilt_series',
        header: 'Tilt series',
        accessorFn: (a) => a.tilt_series.length,
        size: 120,
      },
      {
        id: 'n_tomograms',
        header: 'Tomograms',
        accessorFn: tomogramCount,
        size: 120,
      },
      {
        id: 'n_annotations',
        header: 'Annotations',
        accessorFn: (a) => a.annotations.length,
        size: 120,
      },
    ],
    [sampleId, compact],
  )

  const table = useMaterialReactTable({
    columns,
    data: acquisitions,
    getRowId: (a) => a.acquisition_id,
    state: { isLoading },
    enableSorting: !compact,
    enableColumnActions: false,
    enableColumnFilters: false,
    enableTopToolbar: false,
    enableBottomToolbar: false,
    enableDensityToggle: false,
    enablePagination: false,
    // The nested (compact) table lives in a detail panel as wide as the parent
    // table, which is wider than its columns need. Semantic layout would stretch
    // its columns proportionally to fill that width, so they'd no longer line up
    // with the parent's fixed-width columns. `grid-no-grow` pins every column to
    // its declared size (a trailing spacer absorbs the slack) so the thumbnail
    // and Acquisition-id columns align with the parent (see AcquisitionsSubTable).
    layoutMode: compact ? 'grid-no-grow' : undefined,
    initialState: { density: compact ? 'compact' : 'comfortable' },
    muiTablePaperProps: {
      elevation: 0,
      sx: {
        border: 1,
        borderColor: 'divider',
        borderRadius: compact ? 1 : 2,
        // Shrink the compact dropdown table to its columns instead of filling
        // the full-width detail panel.
        ...(compact ? { width: 'fit-content' } : {}),
      },
    },
    localization: { noRecordsToDisplay: 'No acquisitions for this sample.' },
  })

  return <MaterialReactTable table={table} />
}
