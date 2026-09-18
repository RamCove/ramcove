/**
 * Depth contours of a cove: concentric, gently wavering rings, like a bathymetric chart of a bay.
 * Drawn once on the server from fixed parameters, so it is deterministic and costs no JavaScript.
 */

type Props = {
  /** Centre of the rings in the 1440 × 900 drawing space. */
  cx?: number;
  cy?: number;
  rings?: number;
  gap?: number;
  className?: string;
};

function ringPath(cx: number, cy: number, r: number, i: number): string {
  // Two slow harmonics whose phase drifts ring by ring, so neighbouring lines stay roughly parallel
  // but the outer ones wander like real depth lines.
  const a1 = 0.055 + 0.0025 * i;
  const a2 = 0.028;
  const p1 = 0.35 * i;
  const p2 = 1.7 + 0.22 * i;
  const steps = 96;
  let d = "";
  for (let k = 0; k <= steps; k++) {
    const t = (k / steps) * Math.PI * 2;
    const rr = r * (1 + a1 * Math.sin(3 * t + p1) + a2 * Math.sin(5 * t + p2));
    // flatten slightly into an ellipse so the bay opens sideways
    const x = cx + rr * Math.cos(t) * 1.18;
    const y = cy + rr * Math.sin(t) * 0.9;
    d += `${k === 0 ? "M" : "L"}${x.toFixed(1)} ${y.toFixed(1)}`;
  }
  return d + "Z";
}

export function CoveContours({ cx = -120, cy = 470, rings = 26, gap = 44, className }: Props) {
  const paths = Array.from({ length: rings }, (_, i) => ringPath(cx, cy, 34 + i * gap, i));
  return (
    <svg
      aria-hidden
      className={className}
      viewBox="0 0 1440 900"
      preserveAspectRatio="xMinYMid slice"
      fill="none"
    >
      <g stroke="var(--contour)" strokeWidth="1">
        {paths.map((d, i) => (
          <path key={i} d={d} opacity={i % 5 === 4 ? 1 : 0.55} />
        ))}
      </g>
    </svg>
  );
}
