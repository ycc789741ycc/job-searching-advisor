import { describe, expect, it } from "vitest";
import {
  bubbleRadius,
  linearScale,
  paddedDomain,
  radarPoint,
  radarPolygon,
  ticks,
} from "./geometry";

const CENTRE = { x: 100, y: 100 };

describe("radar geometry", () => {
  it("puts the first axis at twelve o'clock", () => {
    const point = radarPoint(100, 0, 4, 50, CENTRE);
    expect(point.x).toBeCloseTo(100);
    expect(point.y).toBeCloseTo(50);
  });

  it("goes clockwise", () => {
    const second = radarPoint(100, 1, 4, 50, CENTRE);
    expect(second.x).toBeCloseTo(150);
    expect(second.y).toBeCloseTo(100);
  });

  it("puts a zero score at the centre", () => {
    const point = radarPoint(0, 2, 6, 50, CENTRE);
    expect(point.x).toBeCloseTo(CENTRE.x);
    expect(point.y).toBeCloseTo(CENTRE.y);
  });

  it("clamps a score outside the scale rather than drawing outside the chart", () => {
    const over = radarPoint(140, 0, 4, 50, CENTRE);
    const at100 = radarPoint(100, 0, 4, 50, CENTRE);
    expect(over).toEqual(at100);
  });

  it("builds one polygon vertex per dimension", () => {
    const points = radarPolygon([70, 80, 60, 55, 90], 50, CENTRE).split(" ");
    expect(points).toHaveLength(5);
  });

  it("returns nothing for no dimensions", () => {
    expect(radarPolygon([], 50, CENTRE)).toBe("");
  });
});

describe("linear scale", () => {
  it("maps the domain onto the range", () => {
    const scale = linearScale([0, 100], [0, 400]);
    expect(scale(0)).toBe(0);
    expect(scale(50)).toBe(200);
    expect(scale(100)).toBe(400);
  });

  it("centres marks when every value is identical", () => {
    // One role, or several on the same salary, must not divide by zero.
    const scale = linearScale([180, 180], [0, 400]);
    expect(scale(180)).toBe(200);
    expect(Number.isNaN(scale(180))).toBe(false);
  });

  it("supports an inverted range, which is how SVG y axes work", () => {
    const scale = linearScale([0, 100], [400, 0]);
    expect(scale(0)).toBe(400);
    expect(scale(100)).toBe(0);
  });
});

describe("padded domain", () => {
  it("keeps marks off the axis line", () => {
    const [min, max] = paddedDomain([10, 20]);
    expect(min).toBeLessThan(10);
    expect(max).toBeGreaterThan(20);
  });

  it("gives a single value a domain with width", () => {
    const [min, max] = paddedDomain([50]);
    expect(max).toBeGreaterThan(min);
  });

  it("handles no values", () => {
    expect(paddedDomain([])).toEqual([0, 1]);
  });
});

describe("bubble radius", () => {
  it("scales area, not radius, with the value", () => {
    // A 2x fit must not look 4x bigger.
    const half = bubbleRadius(50);
    const full = bubbleRadius(100);
    const none = bubbleRadius(0);
    const areaOf = (r: number) => r * r;
    expect(areaOf(half) - areaOf(none)).toBeCloseTo(
      (areaOf(full) - areaOf(none)) / 2,
      5,
    );
  });

  it("keeps the smallest bubble big enough to hover", () => {
    expect(bubbleRadius(0)).toBeGreaterThanOrEqual(8);
  });

  it("clamps a value outside the scale", () => {
    expect(bubbleRadius(140)).toBe(bubbleRadius(100));
    expect(bubbleRadius(-20)).toBe(bubbleRadius(0));
  });
});

describe("ticks", () => {
  it("includes both ends", () => {
    const values = ticks([0, 100], 5);
    expect(values[0]).toBe(0);
    expect(values.at(-1)).toBe(100);
    expect(values).toHaveLength(5);
  });
});
