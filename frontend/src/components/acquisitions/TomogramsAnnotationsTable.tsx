import { useMemo, useState } from 'react'
import {
  Box,
  Collapse,
  IconButton,
  Link,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Typography,
} from '@mui/material'
import ExpandLessIcon from '@mui/icons-material/ExpandLess'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
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
import { CustomLink } from '~/components/CustomLink'


// Discriminated row so raw vs. post-processed tomograms share one table while
// keeping the fields that only post-processed rows carry (e.g. `size_bytes`).
type TomogramRow =
  | ({ kind: 'raw' } & RawTomogramOut)
  | ({ kind: 'post' } & PostProcessedTomogramOut)

const dash = '—'

// Shared fixed width for the trailing "View in Neuroglancer" column so the
// buttons line up (and stay the same size) across the tomogram and annotation
// tables, both of which are full-width and right-align the button.
const NEUROGLANCER_COL = 210

// Shared thumbnail column width so the tomogram and annotation tables' first
// column (and therefore the start of the id column) line up. Fits the 96px
// thumbnail plus 16px left / 16px right cell padding, matching MUI's small
// TableCell padding used by the annotation table.
const THUMBNAIL_COL = 128

// Shared minimum width so both tables clamp and start scrolling at the same
// point (the tomogram table's natural min); below it the annotation table
// scrolls too instead of shrinking its columns and drifting the buttons out of
// alignment. Tune together with the column sizes above.
const TABLE_MIN_WIDTH = 980

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

// Reconstruction/3D-alignment group ids in the order they should appear: the
// declared reconstruction_alignment groups first (authoritative), then any
// group referenced only by a tomogram or annotation. First-seen order matches
// the API's group-then-id ordering.
function orderedGroupIds(acquisition: AcquisitionOut): string[] {
  const ids: string[] = []
  const seen = new Set<string>()
  const add = (id: string) => {
    if (!seen.has(id)) {
      seen.add(id)
      ids.push(id)
    }
  }
  for (const g of acquisition.reconstruction_alignment) {
    add(g.reconstruction_alignment_id)
  }
  for (const t of acquisition.raw_tomograms) add(t.reconstruction_alignment_id)
  for (const t of acquisition.post_processed_tomograms) {
    add(t.reconstruction_alignment_id)
  }
  for (const a of acquisition.annotations) add(a.reconstruction_alignment_id)
  return ids
}

// One tomogram table for a single reconstruction group. MRT gives sorting and
// the shared metadata columns; a fresh hook per group keeps the tables
// independent (useMaterialReactTable can't run in a loop, so this must be a
// component).
function TomogramsTable(props: {
  sampleId: string
  acquisitionId: string
  tomograms: TomogramRow[]
}) {
  const { sampleId, acquisitionId, tomograms } = props

  const columns = useMemo<MRT_ColumnDef<TomogramRow>[]>(
    () => [
      {
        id: 'thumbnail',
        header: '',
        columnDefType: 'display',
        enableSorting: false,
        size: THUMBNAIL_COL,
        grow: false,
        // Pin 16px left / 16px right so the thumbnail's edges line up with the
        // annotation table's (MUI small default), independent of MRT density.
        muiTableBodyCellProps: { sx: { px: 2 } },
        muiTableHeadCellProps: { sx: { px: 2 } },
        Cell: ({ row }) => {
          const alt = `Center XY slice of ${row.original.tomogram_id}`
          return (
            <PreviewThumbnail
              src={tomogramPreviewUrl(
                sampleId,
                acquisitionId,
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
        // Grows to fill spare width; long ids truncate rather than force the
        // table to scroll (see layoutMode: 'grid' below).
        size: 200,
        grow: true,
        // 16px left padding to match the annotation table's id column start.
        muiTableBodyCellProps: { sx: { pl: 2 } },
        muiTableHeadCellProps: { sx: { pl: 2 } },
        Cell: ({ row }) => (
          <Box
            title={row.original.tomogram_id}
            sx={{
              whiteSpace: 'nowrap',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
            }}
          >
            {row.original.tomogram_id}
          </Box>
        ),
      },
      {
        id: 'shape',
        header: 'Shape',
        accessorFn: (t) =>
          formatShape(t.image_size_x, t.image_size_y, t.image_size_z),
        size: 140,
        grow: false,
        // 16px left padding so the label lines up with the annotation table's
        // Type column, which widens to this same left edge at xl (see below).
        muiTableBodyCellProps: { sx: { pl: 2 } },
        muiTableHeadCellProps: { sx: { pl: 2 } },
      },
      {
        id: 'voxel_size',
        header: 'Voxel size',
        accessorFn: (t) => formatVoxel(t.voxel_size),
        size: 120,
        grow: false,
      },
      {
        id: 'file_size',
        header: 'File size',
        accessorFn: (t) => (t.kind === 'post' ? formatBytes(t.size_bytes) : dash),
        size: 120,
        grow: false,
      },
      {
        id: 'neuroglancer',
        header: '',
        columnDefType: 'display',
        enableSorting: false,
        size: NEUROGLANCER_COL,
        grow: false,
        muiTableBodyCellProps: { align: 'right' },
        Cell: ({ row }) => (
          <NeuroglancerButton
            source={
              row.original.mrc_path
                ? {
                    kind: 'launch',
                    entity: 'tomogram',
                    sampleId,
                    acquisitionId,
                    groupId: row.original.reconstruction_alignment_id,
                    entityId: row.original.tomogram_id,
                  }
                : null
            }
          />
        ),
      },
    ],
    [sampleId, acquisitionId],
  )

  const table = useMaterialReactTable({
    columns,
    data: tomograms,
    getRowId: (t) => `${t.reconstruction_alignment_id}/${t.tomogram_id}`,
    // Grid layout makes columns flex to fill the container so the table never
    // scrolls horizontally on md+; the id column truncates instead.
    layoutMode: 'grid',
    enableSorting: true,
    enableColumnActions: false,
    enableColumnFilters: false,
    enableTopToolbar: false,
    enableBottomToolbar: false,
    enableDensityToggle: false,
    enablePagination: false,
    initialState: { density: 'comfortable' },
    // No row hover highlight — the tables sit on the group's grey band and the
    // highlight added visual noise without meaning (rows aren't clickable).
    muiTableBodyRowProps: { hover: false },
    // Clamp width so the table scrolls (rather than shrinks) below the shared
    // breakpoint, keeping the button aligned with the annotation table.
    muiTableProps: { sx: { minWidth: TABLE_MIN_WIDTH } },
    muiTablePaperProps: {
      elevation: 0,
      sx: { border: 1, borderColor: 'divider', borderRadius: 2 },
    },
    localization: {
      noRecordsToDisplay: 'No tomograms in this 3D alignment group.',
    },
  })

  return <MaterialReactTable table={table} />
}

// Annotations table for a single reconstruction group. Plain MUI table — the
// requested columns (thumbnail, id + derived-from tomogram, type, launch)
// carry no sortable metadata, so MRT would be dead weight.
function AnnotationsTable(props: {
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
    <Box
      sx={{
        border: 1,
        borderColor: 'divider',
        borderRadius: 2,
        // White card on the group's grey band, matching the tomogram table.
        bgcolor: 'background.paper',
        // Scroll (don't shrink) below the shared min width so the button stays
        // aligned with the tomogram table.
        overflowX: 'auto',
      }}
    >
      {/* Fixed layout so long ids truncate (below) instead of widening the
          table into a horizontal scroll. */}
      <Table
        size="small"
        aria-label="annotations"
        sx={{ tableLayout: 'fixed', minWidth: TABLE_MIN_WIDTH }}
      >
        <TableHead>
          <TableRow>
            <TableCell sx={{ width: THUMBNAIL_COL }} />
            <TableCell>Id</TableCell>
            {/* Extra right padding keeps the Type value from crowding the
                neuroglancer button at wide widths. At xl (~1536px) the column
                widens to span the tomogram table's shape+voxel+file band
                (140+120+120) so its left edge lines up with the Shape column. */}
            <TableCell sx={{ width: { xs: 200, xl: 380 }, pr: 4 }}>Type</TableCell>
            <TableCell sx={{ width: NEUROGLANCER_COL }} />
          </TableRow>
        </TableHead>
        <TableBody>
          {annotations.map((a) => {
            const alt = `Center XY slice of ${a.annotation_id}`
            return (
              <TableRow
                key={`${a.reconstruction_alignment_id}/${a.annotation_id}`}
              >
                <TableCell sx={{ width: THUMBNAIL_COL }}>
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
                  <Box
                    title={a.annotation_id}
                    sx={{
                      whiteSpace: 'nowrap',
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                    }}
                  >
                    {a.annotation_id}
                  </Box>
                  {a.derived_from ? (
                    <Typography
                      variant="caption"
                      color="text.secondary"
                      display="block"
                      title={a.derived_from}
                      sx={{
                        whiteSpace: 'nowrap',
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                      }}
                    >
                      <Box component="span" sx={{ fontWeight: 700 }}>
                        Derived from:
                      </Box>{' '}
                      {a.derived_from}
                    </Typography>
                  ) : null}
                </TableCell>
                <TableCell sx={{ pr: 4 }}>{a.type ?? dash}</TableCell>
                <TableCell align="right">
                  <NeuroglancerButton
                    source={
                      a.files.some(
                        (f) =>
                          f.toLowerCase().endsWith('.mrc') ||
                          f.toLowerCase().endsWith('.json'),
                      )
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
    </Box>
  )
}

// One block per reconstruction/3D-alignment group: a subheader naming the
// group, its tomograms, then its annotations. Both tomograms and annotations
// carry `reconstruction_alignment_id`, so they group directly.
export function TomogramsAnnotationsTable(props: {
  sampleId: string
  acquisition: AcquisitionOut
}) {
  const { sampleId, acquisition } = props
  const acquisitionId = acquisition.acquisition_id

  const tomogramsByGroup = useMemo(() => {
    const byGroup = new Map<string, TomogramRow[]>()
    for (const t of combinedTomograms(acquisition)) {
      const list = byGroup.get(t.reconstruction_alignment_id)
      if (list) list.push(t)
      else byGroup.set(t.reconstruction_alignment_id, [t])
    }
    return byGroup
  }, [acquisition])

  const annotationsByGroup = useMemo(() => {
    const byGroup = new Map<string, AnnotationOut[]>()
    for (const a of acquisition.annotations) {
      const list = byGroup.get(a.reconstruction_alignment_id)
      if (list) list.push(a)
      else byGroup.set(a.reconstruction_alignment_id, [a])
    }
    return byGroup
  }, [acquisition.annotations])

  const groupIds = useMemo(() => orderedGroupIds(acquisition), [acquisition])

  // Track collapsed groups (default: all open). Storing the collapsed set means
  // a group not yet seen is open by default, so new groups need no migration.
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set())
  const allOpen = groupIds.every((id) => !collapsed.has(id))
  const toggleAll = () =>
    setCollapsed(allOpen ? new Set(groupIds) : new Set())
  const toggleGroup = (id: string) =>
    setCollapsed((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })

  return (
    <Box>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, mb: 2 }}>
        <Typography variant="h6" component="h2">
          Reconstructions
        </Typography>
        {/* "Expand all / Collapse all" text link, copying the metadata drawer
            (MetadataSectionList) control. */}
        {groupIds.length > 0 && (
          <Link
            component="button"
            type="button"
            variant="body2"
            onClick={toggleAll}
          >
            {allOpen ? 'Collapse all' : 'Expand all'}
          </Link>
        )}
      </Box>

      {groupIds.length === 0 ? (
        <Typography variant="body2" color="text.secondary">
          No reconstructions for this acquisition.
        </Typography>
      ) : (
        <Stack spacing={4}>
          {groupIds.map((groupId) => {
            const open = !collapsed.has(groupId)
            return (
              // Grey band extends behind the whole group (id + both tables) to
              // visually bind them; the tables read as white cards on it.
              <Box
                key={groupId}
                sx={{ bgcolor: 'action.hover', borderRadius: 2, p: 2 }}
              >
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                  <IconButton
                    size="small"
                    onClick={() => toggleGroup(groupId)}
                    aria-label={
                      open ? `Collapse ${groupId}` : `Expand ${groupId}`
                    }
                  >
                    {open ? <ExpandLessIcon /> : <ExpandMoreIcon />}
                  </IconButton>
                  <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
                    {groupId}
                  </Typography>
                </Box>
                <Collapse in={open}>
                  <Stack spacing={2} sx={{ mt: 2 }}>
                    <CustomLink
                      to="/manage/author"
                      search={{
                        tab: 'reconstruction',
                        id: groupId,
                        sampleId,
                        acquisitionId,
                      }}
                      variant="body2"
                    >
                      Edit reconstruction.toml
                    </CustomLink>
                    <Stack spacing={0.75}>
                      <Typography variant="subtitle2">Tomograms</Typography>
                      <TomogramsTable
                        sampleId={sampleId}
                        acquisitionId={acquisitionId}
                        tomograms={tomogramsByGroup.get(groupId) ?? []}
                      />
                    </Stack>
                    <Stack spacing={0.75} sx={{pb:2}}>
                      <Typography variant="subtitle2">Annotations</Typography>
                      <AnnotationsTable
                        sampleId={sampleId}
                        acquisitionId={acquisitionId}
                        annotations={annotationsByGroup.get(groupId) ?? []}
                      />
                    </Stack>
                  </Stack>
                </Collapse>
              </Box>
            )
          })}
        </Stack>
      )}
    </Box>
  )
}
