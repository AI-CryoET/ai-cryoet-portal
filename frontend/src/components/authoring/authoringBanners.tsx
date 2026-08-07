import { Alert, Divider } from '@mui/material';

// Shared authoring-form banners/dividers so wording + styling live in one place
// (both the sectioned and composite renderers use them).

// Shown whenever an existing record is loaded: edits stay in the browser until
// they are written back to the file share (or downloaded and copied there).
export function NotSavedToDiskWarning() {
  return (
    <Alert severity="warning">
      Changes made in this form live only in your browser until you save them.
      Use “Save to file share” to write them back, or download the updated file
      and copy it to the file share manually.
    </Alert>
  );
}

// Shown for portal/API-loaded records: the database copy may lag the on-disk
// file if it changed since the last scan (ADR-0004).
export function StaleValuesWarning() {
  return (
    <Alert severity="warning">
      Values are loaded from the database — this may lag the on-disk file if you
      have updated it since the last scan.
    </Alert>
  );
}

// The heavy primary rule that separates authoring sections.
export function SectionDivider() {
  return (
    <Divider
      sx={{ mb: 1.5, borderBottomWidth: 2, borderColor: 'primary.main' }}
    />
  );
}
