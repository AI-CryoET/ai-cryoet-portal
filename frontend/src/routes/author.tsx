import { createFileRoute } from '@tanstack/react-router'
import { Box, Breadcrumbs, Stack, Tab, Tabs, Typography } from '@mui/material'
import { CustomLink } from '~/components/CustomLink'
import { AuthoringForm } from '~/components/authoring/AuthoringForm'
import type { FormKind } from '~/utils/formFields'

const TABS: { value: FormKind; label: string; blurb: string }[] = [
  {
    value: 'sample',
    label: 'Sample',
    blurb: "Fill the sample's fields and download a clean value-only file.",
  },
  {
    value: 'acquisition',
    label: 'Acquisition',
    blurb: "Fill the acquisition's fields and download a clean value-only file.",
  },
  {
    value: 'md_run',
    label: 'MD run',
    blurb: "Fill the run's fields and download a clean value-only file.",
  },
]

// tab is optional so a bare `to="/author"` link needs no search prop; the
// validator + component both default it to 'sample'.
type AuthorSearch = { tab?: FormKind; id?: string; sampleId?: string }

function isTab(v: unknown): v is FormKind {
  return v === 'sample' || v === 'acquisition' || v === 'md_run'
}

export const Route = createFileRoute('/author')({
  // One page, three tabs. Deep links carry `tab` (+ id / sampleId) so an edit
  // link from a sample / acquisition / warning row opens on the right tab and
  // auto-loads that record (ADR-0004).
  validateSearch: (search: Record<string, unknown>): AuthorSearch => ({
    tab: isTab(search.tab) ? search.tab : 'sample',
    id: typeof search.id === 'string' && search.id ? search.id : undefined,
    sampleId:
      typeof search.sampleId === 'string' && search.sampleId
        ? search.sampleId
        : undefined,
  }),
  component: AuthorRoute,
})

function AuthorRoute() {
  const { tab, id, sampleId } = Route.useSearch()
  const navigate = Route.useNavigate()
  const active = TABS.find((t) => t.value === tab) ?? TABS[0]

  return (
    <Stack spacing={3}>
      <Breadcrumbs aria-label="breadcrumb">
        <CustomLink to="/" color="inherit" sx={{ fontWeight: 700 }}>
          Home
        </CustomLink>
        <Typography color="text.primary">Author metadata</Typography>
      </Breadcrumbs>

      <Box>
        <Typography variant="h5" component="h1">
          Author metadata
        </Typography>
        <Typography variant="body2" color="text.secondary">
          {active.blurb}
        </Typography>
      </Box>

      <Tabs
        value={active.value}
        // Light full-width rule under the tab row (matches the section dividers).
        sx={{ borderBottom: 1, borderColor: 'divider' }}
        // Switching tabs drops any loaded id / sampleId — they belong to the
        // tab that was open.
        onChange={(_e, value) => navigate({ search: { tab: value } })}
      >
        {TABS.map((t) => (
          <Tab key={t.value} value={t.value} label={t.label} />
        ))}
      </Tabs>

      {/* key remounts the form per tab so switching resets its state. */}
      <AuthoringForm
        key={active.value}
        form={active.value}
        initialId={id}
        initialSampleId={sampleId}
      />
    </Stack>
  )
}
