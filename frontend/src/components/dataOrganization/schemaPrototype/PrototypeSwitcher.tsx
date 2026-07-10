// PROTOTYPE — throwaway floating variant switcher. Hidden in production builds
// so a stray merge can't ship it. Delete with the rest of the prototype.
import { useEffect } from 'react'
import { Box, IconButton, Paper, Typography } from '@mui/material'
import ChevronLeftIcon from '@mui/icons-material/ChevronLeft'
import ChevronRightIcon from '@mui/icons-material/ChevronRight'

export interface VariantDef {
  key: string
  name: string
}

export function PrototypeSwitcher({
  variants,
  current,
  onSelect,
}: {
  variants: VariantDef[]
  current: string
  onSelect: (key: string) => void
}) {
  const idx = Math.max(0, variants.findIndex((v) => v.key === current))
  const cycle = (delta: number) =>
    onSelect(variants[(idx + delta + variants.length) % variants.length].key)

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = document.activeElement
      if (el && /^(INPUT|TEXTAREA)$/.test(el.tagName)) return
      if ((el as HTMLElement)?.isContentEditable) return
      if (e.key === 'ArrowLeft') cycle(-1)
      if (e.key === 'ArrowRight') cycle(1)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  if (import.meta.env.PROD) return null

  return (
    <Paper
      elevation={6}
      sx={{
        position: 'fixed',
        bottom: 24,
        left: '50%',
        transform: 'translateX(-50%)',
        display: 'flex',
        alignItems: 'center',
        gap: 1,
        px: 1,
        py: 0.5,
        borderRadius: 999,
        bgcolor: 'grey.900',
        color: 'common.white',
        zIndex: 1300,
      }}
    >
      <IconButton size="small" onClick={() => cycle(-1)} sx={{ color: 'inherit' }}>
        <ChevronLeftIcon />
      </IconButton>
      <Box sx={{ minWidth: 180, textAlign: 'center' }}>
        <Typography variant="caption" sx={{ opacity: 0.6 }}>
          prototype · ← → to switch
        </Typography>
        <Typography variant="body2" sx={{ fontWeight: 700 }}>
          {variants[idx].key} — {variants[idx].name}
        </Typography>
      </Box>
      <IconButton size="small" onClick={() => cycle(1)} sx={{ color: 'inherit' }}>
        <ChevronRightIcon />
      </IconButton>
    </Paper>
  )
}
