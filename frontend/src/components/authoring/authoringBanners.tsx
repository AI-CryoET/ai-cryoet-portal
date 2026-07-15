import { Alert, Divider } from '@mui/material'

// Shared authoring-form banners/dividers so wording + styling live in one place
// (both the sectioned and composite renderers use them).

// Shown whenever an existing record is loaded: edits stay in the browser until
// the file is downloaded and saved back over the original on disk.
export function NotSavedToDiskWarning() {
  return (
    <Alert severity="warning">
      Changes made in this form are not saved to disk. Download the updated file
      and save it to disk to apply your changes.
    </Alert>
  )
}

// Shown for portal/API-loaded records: the database copy may lag the on-disk
// file if it changed since the last scan (ADR-0004).
export function StaleValuesWarning() {
  return (
    <Alert severity="warning">
      Values are loaded from the database — this may lag the on-disk file if you
      have updated it since the last scan.
    </Alert>
  )
}

// The heavy primary rule that separates authoring sections.
export function SectionDivider() {
  return (
    <Divider sx={{ mb: 1.5, borderBottomWidth: 2, borderColor: 'primary.main' }} />
  )
}
