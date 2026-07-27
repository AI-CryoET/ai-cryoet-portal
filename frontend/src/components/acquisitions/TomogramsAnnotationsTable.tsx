import { useMemo } from 'react'
import {
  Box,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Typography,
} from '@mui/material'
import {
  MaterialReactTable,
  useMaterialReactTable,
  type MRT_ColumnDef,
} from 'material-react-table'
import type {
  AcquisitionOut,
  AnnotationOut,
  PostProcessedTomogramOut,
  RawTomogramOut,
} from '~/types'
import { PreviewThumbnail, annotationPreviewUrl, tomogramPreviewUrl } from '~/components/common/Thumbnail'
import { NeuroglancerButton } from '~/components/common/NeuroglancerButton'

// Discriminated row so raw vs. post-processed tomograms share one table while
// keeping the fields that only post-processed rows carry (e.g. `size_bytes`).
type TomogramRow =
  | ({ kind: 'raw' } & RawTomogramOut)
  | ({ kind: 'post' } & PostProcessedTomogramOut)

const dash = '—'

function formatShape(
  x: number | null | undefined,
  y: number | null | undefined,
  z: number | null | undefined,
) {
  if (x == null || y == null || z == null) return dash
  return `${x}×${y}×${z}`
}

function formatVoxel(v: number | null | undefined) {
  return v == null ? dash : `${v.toFixed(2)} Å`
}

function formatBytes(n: number | null | undefined) {
  if (n == null) return dash
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let value = n
  let i = 0
  while (value >= 1024 && i < units.length - 1) {
    value /= 1024
    i++
  }
  return `${i === 0 ? value : value.toFixed(1)} ${units[i]}`
}


function combinedTomograms(acquisition: AcquisitionOut): TomogramRow[] {
  const rows: TomogramRow[] = []
  for (const t of acquisition.raw_tomograms) {
    rows.push({ kind: 'raw', ...t })
  }
  for (const t of acquisition.post_processed_tomograms) {
    rows.push({ kind: 'post', ...t })
  }
  return rows
}

// Nested table of the annotations belonging to one alignment group. Plain MUI
// `Table` (rather than another MRT instance) keeps the detail panel light;
// annotations carry no shape/voxel/size metadata in the schema, so those
// columns render em-dashes for parity with the tomogram header row.
function AnnotationsSubTable(props: {
  sampleId: string
  acquisitionId: string
  annotations: AnnotationOut[]
}) {
  const { sampleId, acquisitionId, annotations } = props
  if (annotations.length === 0) {
    return (
      <Typography variant="body2" color="text.secondary">
        No annotations in this 3D alignment group.
      </Typography>
    )
  }
  return (
    <Table size="small" aria-label="annotations">
      <TableHead>
        <TableRow>
          <TableCell />
          <TableCell>Id</TableCell>
          <TableCell>Shape</TableCell>
          <TableCell>Voxel size</TableCell>
          <TableCell>File size</TableCell>
          <TableCell />
        </TableRow>
      </TableHead>
      <TableBody>
        {annotations.map((a) => {
          const alt = `Center XY slice of ${a.annotation_id}`
          return (
          <TableRow key={`${a.reconstruction_alignment_id}/${a.annotation_id}`}>
            <TableCell sx={{ width: 112 }}>
              <PreviewThumbnail
                src={annotationPreviewUrl(
                  sampleId,
                  acquisitionId,
                  a.reconstruction_alignment_id,
                  a.annotation_id,
                )}
                alt={alt}
                tooltipTitle={alt}
                width={96}
                height={56}
                clickable
              />
            </TableCell>
            <TableCell>
              {a.annotation_id}
              {a.type ? (
                <Typography variant="caption" color="text.secondary" display="block">
                  {a.type}
                </Typography>
              ) : null}
            </TableCell>
            <TableCell>{dash}</TableCell>
            <TableCell>{dash}</TableCell>
            <TableCell>{dash}</TableCell>
            <TableCell align="right">
              <NeuroglancerButton
                source={
                  a.files.some((f) => f.toLowerCase().endsWith('.mrc'))
                    ? {
                        kind: 'launch',
                        entity: 'annotation',
                        sampleId,
                        acquisitionId,
                        groupId: a.reconstruction_alignment_id,
                        entityId: a.annotation_id,
                      }
                    : null
                }
              />
            </TableCell>
          </TableRow>
          )
        })}
      </TableBody>
    </Table>
  )
}

export function TomogramsAnnotationsTable(props: {
  sampleId: string
  acquisition: AcquisitionOut
}) {
  const { sampleId, acquisition } = props

  // An annotation belongs to its 3D-alignment group (any of the group's sibling
  // tomograms represents the same inferred biological structure) rather than to
  // a single tomogram — so a row shows its own group's annotations, not the
  // acquisition's whole list. An acquisition can hold several groups.
  const annotationsByGroup = useMemo(() => {
    const byGroup = new Map<string, AnnotationOut[]>()
    for (const a of acquisition.annotations) {
      const list = byGroup.get(a.reconstruction_alignment_id)
      if (list) list.push(a)
      else byGroup.set(a.reconstruction_alignment_id, [a])
    }
    return byGroup
  }, [acquisition.annotations])

  const groupAnnotations = (t: TomogramRow) =>
    annotationsByGroup.get(t.reconstruction_alignment_id) ?? []

  const data = useMemo(
    () => combinedTomograms(acquisition),
    [acquisition],
  )

  const columns = useMemo<MRT_ColumnDef<TomogramRow>[]>(
    () => [
      {
        id: 'thumbnail',
        header: '',
        columnDefType: 'display',
        enableSorting: false,
        size: 140,
        Cell: ({ row }) => {
          const alt = `Center XY slice of ${row.original.tomogram_id}`
          return (
            <PreviewThumbnail
              src={tomogramPreviewUrl(
                sampleId,
                acquisition.acquisition_id,
                row.original.reconstruction_alignment_id,
                row.original.tomogram_id,
              )}
              alt={alt}
              tooltipTitle={alt}
              width={96}
              height={64}
              clickable
            />
          )
        },
      },
      {
        accessorKey: 'tomogram_id',
        header: 'Id',
        minSize: 160,
      },
      {
        id: 'shape',
        header: 'Shape',
        accessorFn: (t) =>
          formatShape(t.image_size_x, t.image_size_y, t.image_size_z),
        size: 140,
      },
      {
        id: 'voxel_size',
        header: 'Voxel size',
        accessorFn: (t) => formatVoxel(t.voxel_size),
        size: 120,
      },
      {
        id: 'file_size',
        header: 'File size',
        accessorFn: (t) => (t.kind === 'post' ? formatBytes(t.size_bytes) : dash),
        size: 120,
      },
      {
        id: 'neuroglancer',
        header: '',
        columnDefType: 'display',
        enableSorting: false,
        size: 200,
        Cell: ({ row }) => (
          <NeuroglancerButton
            source={
              row.original.mrc_path
                ? {
                    kind: 'launch',
                    entity: 'tomogram',
                    sampleId,
                    acquisitionId: acquisition.acquisition_id,
                    groupId: row.original.reconstruction_alignment_id,
                    entityId: row.original.tomogram_id,
                  }
                : null
            }
          />
        ),
      },
      {
        id: 'n_annotations',
        header: 'Annotations',
        accessorFn: (t) => groupAnnotations(t).length,
        size: 120,
      },
    ],
    [sampleId, acquisition.acquisition_id, annotationsByGroup],
  )

  const table = useMaterialReactTable({
    columns,
    data,
    getRowId: (t) => `${t.reconstruction_alignment_id}/${t.tomogram_id}`,
    enableExpanding: true,
    enableSorting: true,
    enableColumnActions: false,
    enableColumnFilters: false,
    enableTopToolbar: false,
    enableBottomToolbar: false,
    enableDensityToggle: false,
    enablePagination: false,
    initialState: { density: 'comfortable' },
    muiTablePaperProps: {
      elevation: 0,
      sx: { border: 1, borderColor: 'divider', borderRadius: 2 },
    },
    localization: {
      noRecordsToDisplay: 'No tomograms for this acquisition.',
    },
    // Always return a panel (never null) so the expand control stays enabled —
    // MRT disables the toggle for rows whose detail panel renders nothing.
    renderDetailPanel: ({ row }) => (
      <Box sx={{ px: 2, py: 1.5, bgcolor: 'action.hover' }}>
        <Typography variant="overline" color="text.secondary">
          Annotations for this 3D alignment group
        </Typography>
        <Box sx={{ mt: 1 }}>
          <AnnotationsSubTable
            sampleId={sampleId}
            acquisitionId={acquisition.acquisition_id}
            annotations={groupAnnotations(row.original)}
          />
        </Box>
      </Box>
    ),
  })

  return <MaterialReactTable table={table} />
}
