import { createFileRoute } from '@tanstack/react-router';
import { Box, Breadcrumbs, Stack, Tab, Tabs, Typography } from '@mui/material';
import { CustomLink } from '~/components/CustomLink';
import { AuthoringForm } from '~/components/authoring/AuthoringForm';
import type { FormKind } from '~/utils/formFields';

// Keyed by FormKind so a new form kind fails to compile until it has a tab —
// a hand-written union in isTab silently sent ?tab=<new kind> to the default.
// Insertion order is the tab order.
const TAB_META: Record<FormKind, { label: string; blurb: string }> = {
  sample: {
    label: 'Sample',
    blurb: "Fill the sample's fields and download a clean value-only file."
  },
  acquisition: {
    label: 'Acquisition',
    blurb: "Fill the acquisition's fields and download a clean value-only file."
  },
  reconstruction: {
    label: 'Reconstruction',
    blurb:
      "Fill one alignment group's fields and download a clean value-only file."
  },
  md_run: {
    label: 'MD run',
    blurb: "Fill the run's fields and download a clean value-only file."
  }
};

const TABS = (Object.keys(TAB_META) as FormKind[]).map(value => ({
  value,
  ...TAB_META[value]
}));

// tab is optional so a bare `to="/manage/author"` link needs no search prop; the
// validator + component both default it to 'sample'. acquisitionId is the third
// part of the reconstruction form's identity.
type AuthorSearch = {
  tab?: FormKind;
  id?: string;
  sampleId?: string;
  acquisitionId?: string;
};

function isTab(v: unknown): v is FormKind {
  return typeof v === 'string' && Object.hasOwn(TAB_META, v);
}

export const Route = createFileRoute('/manage/author')({
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
    acquisitionId:
      typeof search.acquisitionId === 'string' && search.acquisitionId
        ? search.acquisitionId
        : undefined
  }),
  component: AuthorRoute
});

function AuthorRoute() {
  const { tab, id, sampleId, acquisitionId } = Route.useSearch();
  const navigate = Route.useNavigate();
  const active = TABS.find(t => t.value === tab) ?? TABS[0];

  return (
    <Stack spacing={3}>
      <Breadcrumbs aria-label="breadcrumb">
        <CustomLink color="inherit" sx={{ fontWeight: 700 }} to="/">
          Home
        </CustomLink>
        <CustomLink color="inherit" to="/manage">
          Manage
        </CustomLink>
        <Typography color="text.primary">Author metadata</Typography>
      </Breadcrumbs>

      <Box>
        <Typography component="h1" variant="h5">
          Author metadata
        </Typography>
        <Typography color="text.secondary" variant="body2">
          {active.blurb}
        </Typography>
      </Box>

      <Tabs
        onChange={(_e, value) => navigate({ search: { tab: value } })}
        // Light full-width rule under the tab row (matches the section dividers).
        sx={{ borderBottom: 1, borderColor: 'divider' }}
        // Switching tabs drops any loaded id / sampleId — they belong to the
        // tab that was open.
        value={active.value}
      >
        {TABS.map(t => (
          <Tab key={t.value} label={t.label} value={t.value} />
        ))}
      </Tabs>

      {/* key remounts the form per tab so switching resets its state. */}
      <AuthoringForm
        form={active.value}
        initialAcquisitionId={acquisitionId}
        initialId={id}
        initialSampleId={sampleId}
        key={active.value}
      />
    </Stack>
  );
}
