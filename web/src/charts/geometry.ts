/**
 * Chart geometry, kept pure so it can be unit-tested without a DOM.
 *
 * Both charts here are inline SVG. Nothing in this file knows about colour —
 * that lives in the tokens and is applied at render time.
 */

export interface Point {
  x: number;
  y: number;
}

/** Where one radar axis' value sits, given its index among `count` axes. */
export function radarPoint(
  value: number,
  index: number,
  count: number,
  radius: number,
  centre: Point,
): Point {
  const fraction = Math.max(0, Math.min(100, value)) / 100;
  // Start at twelve o'clock and go clockwise, which is how people read a dial.
  const angle = (index / count) * Math.PI * 2 - Math.PI / 2;
  return {
    x: centre.x + Math.cos(angle) * radius * fraction,
    y: centre.y + Math.sin(angle) * radius * fraction,
  };
}

export function radarPolygon(
  values: number[],
  radius: number,
  centre: Point,
): string {
  if (values.length === 0) return "";
  return values
    .map((value, index) => {
      const point = radarPoint(value, index, values.length, radius, centre);
      return `${point.x.toFixed(2)},${point.y.toFixed(2)}`;
    })
    .join(" ");
}

export interface Scale {
  (value: number): number;
  domain: [number, number];
}

/**
 * A linear scale with a guard for the degenerate case.
 *
 * One role, or several roles all on the same salary, would otherwise divide by
 * zero and put every bubble at NaN.
 */
export function linearScale(
  domain: [number, number],
  range: [number, number],
): Scale {
  const [d0, d1] = domain;
  const [r0, r1] = range;
  const span = d1 - d0;
  const scale = ((value: number) => {
    if (span === 0) return (r0 + r1) / 2;
    return r0 + ((value - d0) / span) * (r1 - r0);
  }) as Scale;
  scale.domain = domain;
  return scale;
}

/** Pads a domain so marks never sit on the axis line. */
export function paddedDomain(values: number[], padRatio = 0.12): [number, number] {
  if (values.length === 0) return [0, 1];
  const min = Math.min(...values);
  const max = Math.max(...values);
  if (min === max) {
    const pad = Math.abs(min) * padRatio || 1;
    return [min - pad, max + pad];
  }
  const pad = (max - min) * padRatio;
  return [min - pad, max + pad];
}

/**
 * Bubble radius from fit.
 *
 * Area, not radius, is proportional to the value — scaling the radius linearly
 * makes a 2x value look 4x bigger.
 */
export function bubbleRadius(fit: number, minRadius = 8, maxRadius = 34): number {
  const clamped = Math.max(0, Math.min(100, fit)) / 100;
  const minArea = minRadius * minRadius;
  const maxArea = maxRadius * maxRadius;
  return Math.sqrt(minArea + clamped * (maxArea - minArea));
}

/** Evenly spaced ticks, inclusive of both ends. */
export function ticks(domain: [number, number], count = 5): number[] {
  const [min, max] = domain;
  if (count < 2) return [min];
  const step = (max - min) / (count - 1);
  return Array.from({ length: count }, (_, i) => min + step * i);
}
