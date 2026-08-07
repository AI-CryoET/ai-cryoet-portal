import { useState } from 'react';
import type { ReactNode } from 'react';
import {
  Box,
  Divider,
  Drawer,
  IconButton,
  Stack,
  Tab,
  Tabs,
  Typography
} from '@mui/material';
import CloseIcon from '@mui/icons-material/Close';

export type MetadataTab = { label: string; content: ReactNode };

// Right-anchored drawer that surfaces the full metadata tree for an entity.
// Header mirrors the data-portal reference: a small eyebrow label, the entity
// name as the heading, and a close button.
//
// Pass `children` for a single-pane drawer (sample page), or `tabs` for a
// tabbed drawer (acquisition page) — the first tab is focused on open.
export function MetadataDrawer({
  open,
  onClose,
  eyebrow,
  title,
  tabs,
  children
}: {
  readonly open: boolean;
  readonly onClose: () => void;
  readonly eyebrow: string;
  readonly title: string;
  readonly tabs?: MetadataTab[];
  readonly children?: ReactNode;
}) {
  const [tab, setTab] = useState(0);
  const active = tabs ? Math.min(tab, tabs.length - 1) : 0;

  return (
    <Drawer
      anchor="right"
      onClose={onClose}
      open={open}
      slotProps={{ paper: { sx: { width: { xs: '100%', sm: 460 } } } }}
    >
      <Box sx={{ px: 3, pt: 2.5, pb: tabs ? 0 : 2 }}>
        <Box
          sx={{
            display: 'flex',
            alignItems: 'flex-start',
            justifyContent: 'space-between',
            gap: 2
          }}
        >
          <Typography
            color="text.secondary"
            sx={{ letterSpacing: 1, fontWeight: 700 }}
            variant="overline"
          >
            {eyebrow}
          </Typography>
          <IconButton
            aria-label="Close metadata"
            edge="end"
            onClick={onClose}
            sx={{ mt: -1 }}
          >
            <CloseIcon />
          </IconButton>
        </Box>
        <Typography component="h2" sx={{ mt: 0.5 }} variant="h6">
          {title}
        </Typography>
        {tabs ? (
          <Tabs
            onChange={(_e, value) => setTab(value)}
            sx={{ mt: 1 }}
            value={active}
          >
            {tabs.map(t => (
              <Tab key={t.label} label={t.label} />
            ))}
          </Tabs>
        ) : null}
      </Box>
      <Divider />
      <Box sx={{ overflowY: 'auto', px: 3, py: 2 }}>
        <Stack spacing={1.5}>{tabs ? tabs[active].content : children}</Stack>
      </Box>
    </Drawer>
  );
}
