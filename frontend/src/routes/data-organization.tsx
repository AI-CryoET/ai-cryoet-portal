import { createFileRoute } from '@tanstack/react-router'
import {
  Box,
  Breadcrumbs,
  Button,
  Divider,
  Stack,
  Typography,
} from '@mui/material'
import DownloadIcon from '@mui/icons-material/Download'
import { CustomLink } from '~/components/CustomLink'
import { FileTree } from '~/components/dataOrganization/FileTree'
import {
  dataRootTree,
  experimentalTree,
  simulationTree,
} from '~/components/dataOrganization/trees'

export const Route = createFileRoute('/data-organization')({
  component: DataOrganization,
})

function SectionHeading({ children }: { children: React.ReactNode }) {
  return (
    <Typography variant="h6" component="h2">
      {children}
    </Typography>
  )
}

function AuthorLinks({
  tabs,
}: {
  tabs: { tab: 'sample' | 'acquisition' | 'md_run'; label: string }[]
}) {
  return (
    <Typography variant="body2" color="text.secondary">
      Author these files:{' '}
      {tabs.map((t, i) => (
        <span key={t.tab}>
          {i > 0 && ' · '}
          <CustomLink to="/author" search={{ tab: t.tab }}>
            {t.label}
          </CustomLink>
        </span>
      ))}
    </Typography>
  )
}

function DownloadTemplate({ name, label }: { name: string; label: string }) {
  return (
    <Button
      component="a"
      href={`/templates/${name}.zip`}
      download
      variant="outlined"
      size="small"
      startIcon={<DownloadIcon />}
      sx={{ alignSelf: 'flex-start' }}
    >
      {label}
    </Button>
  )
}

function DataOrganization() {
  return (
    <Stack spacing={4}>
      <Breadcrumbs aria-label="breadcrumb">
        <CustomLink to="/" color="inherit" sx={{ fontWeight: 700 }}>
          Home
        </CustomLink>
        <Typography color="text.primary">Data organization</Typography>
      </Breadcrumbs>

      <Box>
        <Typography variant="h5" component="h1">
          Organizing data for ingestion
        </Typography>
        <Typography variant="body2" color="text.secondary">
          How to place new cryoET data on the Janelia file share so the catalog
          scanner ingests it correctly.
        </Typography>
      </Box>

      {/* Section 1 — where the data lives */}
      <Stack spacing={2}>
        <SectionHeading>1. Where to find the data</SectionHeading>
        <Typography variant="body2">
          All data lives on the Janelia file share, reachable over the{' '}
          <strong>Janelia VPN</strong>, under the <code>cryoet</code> share's{' '}
          <code>data/</code> directory (the data root). Starter templates for a
          new sample live on the same share at <code>scratch/templates/</code>{' '}
          (<code>scratch</code> is a checkout of this repository).
        </Typography>
        <Typography variant="body2">
          The data root has two top-level arms. The arm a sample lives under is
          the source of truth for its <code>data_source</code> (and, for
          simulation, its <code>dataset_type</code>) — these are derived from
          directory placement, never authored in a <code>.toml</code> file.
        </Typography>
        <FileTree nodes={dataRootTree} />
      </Stack>

      <Divider />

      {/* Section 2 — experimental */}
      <Stack spacing={2}>
        <SectionHeading>2. Adding an experimental dataset</SectionHeading>
        <Typography variant="body2">
          Copy the starter template at{' '}
          <code>scratch/templates/sample_id_experimental/</code> into{' '}
          <code>Experimental/</code>, rename the sample directory, and add an
          acquisition subdirectory per acquisition. Author{' '}
          <code>sample.toml</code> at the sample root and{' '}
          <code>acquisition.toml</code> in each acquisition directory.
        </Typography>
        <DownloadTemplate
          name="sample_id_experimental"
          label="Download experimental template"
        />
        <FileTree nodes={experimentalTree} />
        <AuthorLinks
          tabs={[
            { tab: 'sample', label: 'Sample' },
            { tab: 'acquisition', label: 'Acquisition' },
          ]}
        />
      </Stack>

      <Divider />

      {/* Section 3 — simulation */}
      <Stack spacing={2}>
        <SectionHeading>3. Adding an MD simulation dataset</SectionHeading>
        <Typography variant="body2">
          Copy the starter template at{' '}
          <code>scratch/templates/sample_id_simulation/</code> into the matching{' '}
          <code>MdSimulation/{'{Bulk|SingleMolecule|Slab}'}/</code> arm. Author{' '}
          <code>sample.toml</code>, one <code>md_run.toml</code> per MD run under{' '}
          <code>MdRuns/</code>, and an <code>acquisition.toml</code> per
          synthetic-cryoET acquisition under <code>SyntheticCryoET/</code>.
        </Typography>
        <DownloadTemplate
          name="sample_id_simulation"
          label="Download simulation template"
        />
        <FileTree nodes={simulationTree} />
        <AuthorLinks
          tabs={[
            { tab: 'sample', label: 'Sample' },
            { tab: 'md_run', label: 'MD run' },
            { tab: 'acquisition', label: 'Acquisition' },
          ]}
        />
      </Stack>

      <Divider />

      {/* Section 4 — processing log */}
      <Stack spacing={2}>
        <SectionHeading>
          4. Append to the processing log as outputs are produced
        </SectionHeading>
        <Typography variant="body2">
          Each <code>acquisition.toml</code> grows over time. Record the raw
          reconstruction once in <code>[raw_tomogram]</code>; for each new output
          — a denoised version, a segmentation, an STA result — append a new{' '}
          <code>[[post_processed_tomogram]]</code> or <code>[[annotation]]</code>{' '}
          entry to the relevant acquisition's file.
        </Typography>
        <Box component="ul" sx={{ m: 0, pl: 3 }}>
          <Typography component="li" variant="body2">
            Do not delete or modify a tomogram or annotation entry once added.
            Reprocessing produces a new entry with a new <code>id</code>, placed
            at the bottom of the file.
          </Typography>
          <Typography component="li" variant="body2">
            The <code>id</code> must match a folder name under{' '}
            <code>TiltSeries/</code>, <code>Reconstructions/Tomograms/</code>, or{' '}
            <code>Reconstructions/Annotations/</code>.
          </Typography>
          <Typography component="li" variant="body2">
            Use <code>derived_from</code> and <code>target_tomogram</code> to
            record lineage between entries.
          </Typography>
        </Box>
      </Stack>
    </Stack>
  )
}
