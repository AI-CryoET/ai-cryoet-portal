import { Box } from '@mui/material';
import snowflakeLogo from '~/assets/snowflake-logo.svg';

// Decorative hero backdrop: the snowflake icon nestled into a corner, with a
// trail of fading dots extending outward from each of its six primary apexes —
// continuing the direction each arm already points. Purely cosmetic, so it's
// `aria-hidden` and ignores pointer events.

// Icon-native coordinates (matches snowflake-logo.svg's 512x512 frame).
const CENTER = { x: 256, y: 256 };
// The six outer apex nodes the trails grow from.
const APEXES = [
  { x: 256, y: 101 },
  { x: 390.23, y: 178.5 },
  { x: 390.23, y: 333.5 },
  { x: 256, y: 411 },
  { x: 121.77, y: 333.5 },
  { x: 121.77, y: 178.5 }
];
const ICY = '#a8d4f0';

const TRAIL_DOTS = 8; // dots per apex
const TRAIL_START = 36; // distance from apex to the first dot
const TRAIL_GAP = 36; // spacing between dots

// Shift the whole composition up-and-left so the icon pokes out of the top-left
// corner while the inward (down/right) trails fan across the banner. The
// up/left trails run off-canvas and are clipped — reads as the icon emerging
// from the corner. Tune these to reposition the icon within the corner.
const OFFSET = { x: -132, y: -186 };
const VIEW = 720;

type Dot = { x: number; y: number; r: number; o: number };

function buildTrails(): Dot[] {
  const dots: Dot[] = [];
  for (const apex of APEXES) {
    const dx = apex.x - CENTER.x;
    const dy = apex.y - CENTER.y;
    const len = Math.hypot(dx, dy);
    const ux = dx / len;
    const uy = dy / len;
    for (let i = 0; i < TRAIL_DOTS; i++) {
      const dist = TRAIL_START + i * TRAIL_GAP;
      const t = i / (TRAIL_DOTS - 1); // 0 at apex → 1 at the tail
      dots.push({
        x: apex.x + ux * dist,
        y: apex.y + uy * dist,
        r: 7 - t * 5.5, // 7 → 1.5
        o: 0.6 * (1 - t) // fade to nothing
      });
    }
  }
  return dots;
}

const TRAILS = buildTrails();

export function HeroBackdrop() {
  return (
    <Box
      aria-hidden
      sx={{
        position: 'absolute',
        top: 0,
        left: 0,
        width: { xs: 375, md: 600 },
        height: { xs: 375, md: 600 },
        opacity: 0.35,
        pointerEvents: 'none',
        zIndex: 0
      }}
    >
      <svg
        height="100%"
        preserveAspectRatio="xMidYMid meet"
        viewBox={`0 0 ${VIEW} ${VIEW}`}
        width="100%"
      >
        <g transform={`translate(${OFFSET.x} ${OFFSET.y})`}>
          <image height={512} href={snowflakeLogo} width={512} x={0} y={0} />
          {TRAILS.map((d, i) => (
            <circle
              cx={d.x}
              cy={d.y}
              fill={ICY}
              key={i}
              opacity={d.o}
              r={d.r}
            />
          ))}
        </g>
      </svg>
    </Box>
  );
}
