import { useState } from 'react'
import type { ReactNode } from 'react'
import { createFileRoute, notFound } from '@tanstack/react-router'
import { Box, Breadcrumbs, Divider, Paper, Stack, Typography } from '@mui/material'
import LayersOutlinedIcon from '@mui/icons-material/LayersOutlined'
import type { AcquisitionOut, WarningOut } from '~/types'
import { CustomLink } from '~/components/CustomLink'
import {
  PreviewThumbnail,
  acquisitionPolarUrl,
  acquisitionRepTiltSeriesId,
  acquisitionThumbnailUrl,
  tiltSeriesPreviewUrl,
} from '~/components/common/Thumbnail'
import { FileglancerPathSection } from '~/components/common/FileglancerPathSection'
import { DetailHero } from '~/components/common/DetailHero'
import { DetailPageHeader } from '~/components/common/DetailPageHeader'
import { SectionHeading } from '~/components/common/SectionHeading'
import { QualityBadge } from '~/components/common/QualityBadge'
import { MetadataDrawer } from '~/components/common/MetadataDrawer'
import { MetadataSectionList } from '~/components/common/MetadataSectionList'
import type { MetadataSectionData } from '~/components/common/MetadataSection'
import {
  acquisitionMetadataSections,
  sampleMetadataSections,
} from '~/components/common/metadataSections'
import { TomogramsAnnotationsTable } from '~/components/acquisitions/TomogramsAnnotationsTable'
import { EntityFreshnessCard } from '~/components/manage/EntityFreshnessCard'
import {
  sampleDetailQueryOptions,
  sampleWarningsQueryOptions,
  useSampleDetailQuery,
  useSampleWarningsQuery,
} from '~/utils/queryOptions'

export const Route = createFileRoute('/acquisitions/$acquisitionId')({
  validateSearch: (search: Record<string, unknown>) => ({
    sampleId: typeof search.sampleId === 'string' ? search.sampleId : '',
  }),
  loaderDeps: ({ search }) => ({ sampleId: search.sampleId }),
  loader: async ({
    context: { queryClient },
    params: { acquisitionId },
    deps: { sampleId },
  }) => {
    if (!sampleId) throw notFound()
    const [sample] = await Promise.all([
      queryClient.ensureQueryData(sampleDetailQueryOptions(sampleId)),
      queryClient.ensureQueryData(sampleWarningsQueryOptions(sampleId)),
    ])
    if (!sample.acquisitions.some((a) => a.acquisition_id === acquisitionId)) {
      throw notFound()
    }
  },
  component: AcquisitionDetailRoute,
})

// Warnings are recorded per-sample with a dotted `location` like
// `acquisitions.{id}` or `acquisitions.{id}.tomogram[...]` (see
// catalog/assembler.py). Match the acquisition's own location and any
// nested child location, but not a sibling whose id shares a prefix.
function warningsForAcquisition(
  warnings: WarningOut[],
  acquisitionId: string,
): WarningOut[] {
  const prefix = `acquisitions.${acquisitionId}`
  return warnings.filter(
    (w) => w.location === prefix || w.location.startsWith(`${prefix}.`),
  )
}

// A single grey metadata card mirroring the former "Acquisition summary" box
// style: a subtitle and a stack of label/value rows. Empty values show the same
// "—" placeholder as the metadata drawer so every applicable field stays
// visible.
function AcquisitionSummaryCard(props: MetadataSectionData) {
  const { title, rows } = props
  return (
    <Paper
      elevation={0}
      sx={{ px: 2.5, py: 2, borderRadius: 2, bgcolor: 'grey.100' }}
    >
      <Typography variant="subtitle2" gutterBottom>
        {title}
      </Typography>
      <Stack spacing={0.5}>
        {rows.map((row, i) => {
          const empty = row.value == null || row.value === ''
          return (
            <Box
              key={`${row.label}-${i}`}
              sx={{ display: 'flex', justifyContent: 'space-between', gap: 4 }}
            >
              <Typography variant="body2" color="text.secondary">
                {row.label}
              </Typography>
              <Typography
                variant="body2"
                color={empty ? 'text.disabled' : undefined}
              >
                {empty ? '—' : row.value}
              </Typography>
            </Box>
          )
        })}
      </Stack>
    </Paper>
  )
}

// "Acquisition summary" section: a heading on the page background above two
// side-by-side grey cards. The card data reuses the metadata-drawer section
// builders so the two stay in sync.
function AcquisitionSummary(props: {
  acquisition: AcquisitionOut
  tiltSeriesPlot?: ReactNode
}) {
  const sections = acquisitionMetadataSections(props.acquisition)
  const microscope = sections.find((s) => s.title === 'Microscope & Imaging')
  // The drawer's full tilt geometry / per–tilt-series sections carry many rows;
  // the summary box shows only the overall tilt count and range, kept under the
  // "Tilt Series" heading it has always used.
  const tiltGeometrySection = sections.find(
    (s) => s.title === 'Tilt Geometry & Dose',
  )
  const tiltSeries = tiltGeometrySection
    ? {
        title: 'Tilt Series',
        rows: tiltGeometrySection.rows.filter((r) =>
          ['Tilt count', 'Tilt range'].includes(r.label),
        ),
      }
    : undefined
  return (
    <Box>
      <Typography variant="subtitle1" sx={{ fontWeight: 600, mb: 1.5 }}>
        Acquisition summary
      </Typography>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1.5 }}>
        <Typography variant="body2" color="text.secondary">
          Quality
        </Typography>
        <QualityBadge quality={props.acquisition.acquisition_quality} />
      </Box>
      {/* Boxes sit side by side and wrap to a single column only when they no
          longer fit (flex-basis + flexWrap), rather than at a fixed breakpoint.
          flex-start keeps the lighter tilt series box from stretching to match
          the microscope box; the tilt-angle plot sits beneath that box. */}
      <Box
        sx={{
          display: 'flex',
          flexWrap: 'wrap',
          gap: 2,
          alignItems: 'flex-start',
        }}
      >
        {microscope ? (
          <Box sx={{ flex: '1 1 220px', minWidth: 0 }}>
            <AcquisitionSummaryCard {...microscope} />
          </Box>
        ) : null}
        {tiltSeries ? (
          <Box
            sx={{
              flex: '1 1 220px',
              minWidth: 0,
              display: 'flex',
              flexDirection: 'column',
              gap: 2,
            }}
          >
            <AcquisitionSummaryCard {...tiltSeries} />
            {props.tiltSeriesPlot}
          </Box>
        ) : null}
      </Box>
    </Box>
  )
}

function AcquisitionDetailRoute() {
  const { acquisitionId } = Route.useParams()
  const { sampleId } = Route.useSearch()
  const { data: sample } = useSampleDetailQuery(sampleId)
  const { data: warnings } = useSampleWarningsQuery(sampleId)
  const [metadataOpen, setMetadataOpen] = useState(false)

  // Guaranteed present — the loader throws notFound otherwise.
  const acquisition = sample.acquisitions.find(
    (a) => a.acquisition_id === acquisitionId,
  ) as AcquisitionOut

  const acqWarnings = warningsForAcquisition(warnings, acquisitionId)

  return (
    <Stack spacing={3}>
      <Breadcrumbs aria-label="breadcrumb">
        <CustomLink to="/" color="inherit">
          Home
        </CustomLink>
        <CustomLink
          to={sample.data_source === 'simulation' ? '/md-simulation' : '/experimental'}
          color="inherit"
        >
          Browse
        </CustomLink>
        <CustomLink
          to="/samples/$sampleId"
          params={{ sampleId }}
          color="inherit"
        >
          {sampleId}
        </CustomLink>
        <Typography color="text.primary">{acquisitionId}</Typography>
      </Breadcrumbs>

      {/* ── Title section ──────────────────────────────────────────── */}
      <DetailPageHeader
        title={acquisitionId}
        onViewMetadata={() => setMetadataOpen(true)}
        warning={
          acqWarnings.length > 0
            ? {
                // Opens the manage page with outstanding issues filtered to
                // this acquisition (read from the URL search params there).
                href: `/manage?sample=${encodeURIComponent(
                  sampleId,
                )}&acquisition=${encodeURIComponent(acquisitionId)}`,
                text: "*There are warnings for this acquisition's metadata. Click to view",
              }
            : null
        }
      />

      {/* Edit links carry the composite identity so the form auto-loads the
          right acquisition (acquisition_id alone isn't unique). */}
      <CustomLink
        to="/author"
        search={{ tab: 'acquisition', id: acquisitionId, sampleId }}
        variant="body2"
        fontWeight={700}
      >
        Edit acquisition.toml
      </CustomLink>

      <Divider />

      {/* ── Tilt series + path ─────────────────────────────────────── */}
      <DetailHero
        thumbnail={(() => {
          const tsId = acquisitionRepTiltSeriesId(acquisition)
          // The cached 512px thumbnail is rendered from the acquisition's
          // raw Frames/ even when no tilt series is declared, so show it
          // whenever it loads (matching the tables); PreviewThumbnail falls
          // back to the labeled placeholder if no thumbnail exists. Click
          // always enlarges: when a tilt_series_id exists the lightbox
          // fetches the sharper on-demand render (showing a spinner over
          // the thumbnail until it arrives); otherwise it just enlarges the
          // thumbnail.
          return (
            <PreviewThumbnail
              src={acquisitionThumbnailUrl(sampleId, acquisitionId)}
              lightboxSrc={
                tsId
                  ? tiltSeriesPreviewUrl(sampleId, acquisitionId, tsId)
                  : undefined
              }
              alt={`Middle tilt-series image for ${acquisitionId}`}
              width="100%"
              aspectRatio={1}
              objectFit="contain"
              elevated={false}
              clickable
              tooltipTitle="Click to enlarge middle tilt-series image"
              placeholderIcon={<LayersOutlinedIcon />}
              placeholderLabel="Tilt series"
            />
          )
        })()}
        details={
          <FileglancerPathSection path={acquisition.path}>
            <Stack spacing={2}>
            <AcquisitionSummary
              acquisition={acquisition}
              tiltSeriesPlot={(() => {
                const n = acquisition.tilt_angles?.length ?? 0
                if (n === 0) return null
                return (
                  <PreviewThumbnail
                    src={acquisitionPolarUrl(sampleId, acquisitionId)}
                    alt={`Tilt-angle plot for ${acquisitionId}`}
                    width="100%"
                    // Match the rendered figure's 5:3 ratio (render_polar_png
                    // uses figsize=(5, 3)) so the box hugs the plot instead of
                    // padding it with white space top and bottom.
                    aspectRatio={5 / 3}
                    objectFit="contain"
                    clickable
                    tooltipTitle={`Tilt-angle plot — each line is a tilt image; color shows acquisition order (image 1 to ${n}).`}
                  />
                )
              })()}
            />
            <EntityFreshnessCard
              status={acquisition.scan_status}
              kind="acquisition"
            />
            </Stack>
          </FileglancerPathSection>
        }
      />

      <Divider />

      {/* ── Tomograms and annotations ──────────────────────────────── */}
      <Box>
        <SectionHeading>Tomograms and annotations</SectionHeading>
        <TomogramsAnnotationsTable
          sampleId={sampleId}
          acquisition={acquisition}
        />
      </Box>

      <MetadataDrawer
        open={metadataOpen}
        onClose={() => setMetadataOpen(false)}
        eyebrow="Acquisition details"
        title={acquisitionId}
        tabs={[
          // Acquisition tab is focused first; the Sample tab mirrors the
          // drawer shown on this acquisition's sample page.
          {
            label: 'Acquisition',
            content: (
              <MetadataSectionList
                sections={acquisitionMetadataSections(acquisition)}
              />
            ),
          },
          {
            label: 'Sample',
            content: (
              <MetadataSectionList sections={sampleMetadataSections(sample)} />
            ),
          },
        ]}
      />
    </Stack>
  )
}
