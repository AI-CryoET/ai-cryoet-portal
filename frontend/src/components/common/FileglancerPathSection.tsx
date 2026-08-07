import type { ReactNode } from 'react';
import { IconButton, Stack, Tooltip, Typography } from '@mui/material';
import OpenInNewIcon from '@mui/icons-material/OpenInNew';
import { CopyIconButton } from '~/components/common/CopyIconButton';
import { toFileglancerUrl } from '~/utils/fileglancer';

interface FileglancerPathSectionProps {
  // Absolute on-disk path of the entity's directory (sample or acquisition).
  readonly path: string | null;
  // Optional content rendered below the path row (e.g. the summary card on the
  // detail views).
  readonly children?: ReactNode;
}

// Shared path display used by the sample- and acquisition-detail views: the
// on-disk path with a copy-path button, a link out to Fileglancer, and
// optional inset content.
export function FileglancerPathSection({
  path,
  children
}: FileglancerPathSectionProps) {
  const fileglancerLink = path ? toFileglancerUrl(path) : null;

  return (
    <Stack spacing={2}>
      {path ? (
        <Stack alignItems="center" direction="row" flexWrap="wrap" spacing={1}>
          <Typography
            sx={{
              fontFamily: 'monospace',
              fontSize: '0.8125rem',
              wordBreak: 'break-all'
            }}
            variant="body2"
          >
            {path}
          </Typography>
          <CopyIconButton text={path} tooltip="Copy path" />
          {fileglancerLink ? (
            <Tooltip title="View data in Fileglancer">
              <IconButton
                aria-label="View data in Fileglancer"
                component="a"
                href={fileglancerLink}
                rel="noopener noreferrer"
                size="small"
                target="_blank"
              >
                <OpenInNewIcon fontSize="small" />
              </IconButton>
            </Tooltip>
          ) : null}
        </Stack>
      ) : null}

      {children}
    </Stack>
  );
}
