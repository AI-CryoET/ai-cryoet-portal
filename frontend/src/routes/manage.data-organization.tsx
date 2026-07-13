import { createFileRoute } from '@tanstack/react-router'
import {
  Box,
  Breadcrumbs,
  Button,
  Divider,
  Stack,
  Tab,
  Tabs,
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
import { SchemaExplorer } from '~/components/dataOrganization/schema/SchemaExplorer'

type DataOrgSearch = { tab: 'placing' | 'schema' }

export const Route = createFileRoute('/manage/data-organization')({
  validateSearch: (search: Record<string, unknown>): DataOrgSearch => ({
    tab: search.tab === 'schema' ? 'schema' : 'placing',
  }),
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
  tabs: ('sample' | 'acquisition' | 'md_run')[]
}) {
  return (
    <>
      {tabs.map((tab, i) => (
        <span key={tab}>
          {i > 0 && (
            <Box component="span" aria-hidden>
              {' · '}
            </Box>
          )}
          <CustomLink to="/manage/author" search={{ tab }}>
            {tab}.toml
          </CustomLink>
        </span>
      ))}
      </>
  )
}

// Lettered step list (a, b, c) shared by the how-to sections.
function Steps({ children }: { children: React.ReactNode }) {
  return (
    <Box component="ol" sx={{ m: 0, pl: 3, listStyleType: 'lower-alpha' }}>
      {children}
    </Box>
  )
}

function Step({ children }: { children: React.ReactNode }) {
  return (
    <Typography component="li" variant="body1" sx={{ '&:not(:last-child)': { mb: 1 } }}>
      {children}
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
      sx={{ alignSelf: 'flex-start', mb: '8px' }}
    >
      {label}
    </Button>
  )
}

function DataOrganization() {
  const { tab } = Route.useSearch()
  const navigate = Route.useNavigate()
  return (
    <Stack spacing={4}>
      <Breadcrumbs aria-label="breadcrumb">
        <CustomLink to="/" color="inherit" sx={{ fontWeight: 700 }}>
          Home
        </CustomLink>
        <CustomLink to="/manage" color="inherit">
          Manage
        </CustomLink>
        <Typography color="text.primary">Data organization</Typography>
      </Breadcrumbs>

      <Tabs
        value={tab}
        sx={{ borderBottom: 1, borderColor: 'divider' }}
        onChange={(_e, value) =>
          navigate({ search: (prev) => ({ ...prev, tab: value }) })
        }
      >
        <Tab value="placing" label="Directory layout" />
        <Tab value="schema" label="Data schema" />
      </Tabs>

      {tab === 'schema' ? (
        <SchemaExplorer />
      ) : (
        <>
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
        <Typography variant="body1">
          All data lives on the Janelia file share, reachable over the{' '}
          <strong>Janelia VPN</strong>, under the <code>cryoet</code> share's{' '}
          <code>data/</code> directory. Starter templates for a
          new sample live on the same share at <code>data/scratch/templates/</code>.
        </Typography>
        <Typography variant="body1">
          Under the <code>data/</code> directory are two top-level arms: <code>Experimental/</code> and <code>MdSimulation/</code>. The arm a sample lives under is
          the source of truth for its <code>data_source</code>. </Typography>
          <Typography variant="body1">
            Within <code>MdSimulation/</code>, there are three subdirectories: <code>Bulk/</code>, <code>SingleMolecule/</code>, and <code>Slab/</code>.
          The subdirectory a sample lives under determines its <code>dataset_type</code>.
        </Typography>
        <FileTree nodes={dataRootTree} />
      </Stack>

      <Divider />

      {/* Section 2 — experimental */}
      <Stack spacing={2}>
        <SectionHeading>2. Adding an experimental dataset</SectionHeading>
        <Steps>
          <Step>
            Either copy the starter template at{' '}
            <code>data/scratch/templates/sample_id_experimental/</code> into{' '}
            <code>data/Experimental/</code> or download the template.
          </Step>
                  <DownloadTemplate
          name="sample_id_experimental"
          label="Download experimental template"
        />
          <Step>
            Rename the sample directory and add an acquisition subdirectory per
            acquisition.
          </Step>
          <Step>
            Author <code>sample.toml</code> at the sample root and{' '}
            <code>acquisition.toml</code> in each acquisition directory. This can be done by manually editing the template files or by filling out the online form and downloading a completed file: <AuthorLinks tabs={['sample', 'acquisition']} />
          </Step>
          
        </Steps>

        
        <FileTree nodes={experimentalTree} />

      </Stack>

      <Divider />

      {/* Section 3 — simulation */}
      <Stack spacing={2}>
        <SectionHeading>3. Adding an MD simulation dataset</SectionHeading>
        <Steps>
          <Step>
            Copy the starter template at{' '}
            <code>data/scratch/templates/sample_id_simulation/</code> into the
            matching{' '}
            <code>data/MdSimulation/{'{Bulk|SingleMolecule|Slab}'}/</code> arm,
            or download the starter template.
          </Step>
                  <DownloadTemplate
          name="sample_id_simulation"
          label="Download simulation template"
        />
          <Step>
            Author <code>sample.toml</code>, one <code>md_run.toml</code> per MD
            run under <code>MdRuns/</code>, and an <code>acquisition.toml</code>{' '}
            per synthetic-cryoET acquisition under <code>SyntheticCryoET/</code>. This can be done by manually editing the template files or by filling out the online form and downloading a completed file: <AuthorLinks tabs={['sample', 'md_run', 'acquisition']} />
          </Step>
        </Steps>

        
        <FileTree nodes={simulationTree} />

      </Stack>

      <Divider />

      {/* Section 4 — processing log */}
      <Stack spacing={2}>
        <SectionHeading>
          4. Append to the processing log as outputs are produced
        </SectionHeading>
        <Typography variant="body1">
          Each <code>acquisition.toml</code> grows over time. 
        </Typography>
        <Steps>
          <Step>
            Record the raw
          reconstruction once in <code>[raw_tomogram]</code>.</Step>
          <Step>
            For each new output
          — a denoised version, a segmentation, an STA result — append a new{' '}
          <code>[[post_processed_tomogram]]</code> or <code>[[annotation]]</code>{' '}
          entry to the relevant acquisition's file. Do not delete or modify a tomogram or annotation entry once added.
            Reprocessing produces a new entry with a new <code>id</code>, placed
            at the bottom of the file.
          </Step>
          <Step>
            The <code>id</code> under the <code>[raw_tomogram]</code>, <code>[[post_processed_tomogram]]</code> or <code>[[annotation]]</code> block must match the folder name for the corresponding{' '}
            tomogram or annotation.
          </Step>
          <Step>
            Use <code>derived_from</code> under <code>[[post_processed_tomogram]]</code> and <code>target_tomogram</code> under <code>[[annotation]]</code> to
            record lineage between entries.
          </Step>
        </Steps>
      </Stack>
        </>
      )}
    </Stack>
  )
}
