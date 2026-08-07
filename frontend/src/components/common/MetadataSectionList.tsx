import { useState } from 'react';
import { Box, Link, Stack } from '@mui/material';
import { MetadataSection } from './MetadataSection';
import type { MetadataSectionData } from './MetadataSection';

// Renders an ordered list of metadata sections with a single "Expand all /
// Collapse all" control that drives every section at once. Each section is
// keyed by its title; the initial open/closed state mirrors each section's
// `defaultExpanded`. Used inside MetadataDrawer (once per pane/tab, so the
// acquisition drawer's tabs each get their own control).
export function MetadataSectionList({
  sections
}: {
  readonly sections: MetadataSectionData[];
}) {
  // MetadataSection drops empty sections (rows.length === 0); mirror that here
  // so the toggle only tracks sections the user can actually see.
  const visible = sections.filter(s => s.rows.length > 0);

  const [expanded, setExpanded] = useState<Record<string, boolean>>(() =>
    Object.fromEntries(visible.map(s => [s.title, s.defaultExpanded ?? false]))
  );

  if (visible.length === 0) {
    return null;
  }

  const allExpanded = visible.every(s => expanded[s.title]);

  const toggleAll = () => {
    const next = !allExpanded;
    setExpanded(Object.fromEntries(visible.map(s => [s.title, next])));
  };

  const setSection = (title: string) => (value: boolean) =>
    setExpanded(prev => ({ ...prev, [title]: value }));

  return (
    <Stack spacing={1.5}>
      <Box sx={{ display: 'flex', justifyContent: 'flex-end' }}>
        <Link
          component="button"
          onClick={toggleAll}
          type="button"
          variant="body2"
        >
          {allExpanded ? 'Collapse all' : 'Expand all'}
        </Link>
      </Box>
      {visible.map(section => (
        <MetadataSection
          key={section.title}
          {...section}
          expanded={expanded[section.title]}
          onChange={setSection(section.title)}
        />
      ))}
    </Stack>
  );
}
