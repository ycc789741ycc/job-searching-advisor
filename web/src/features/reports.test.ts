import { describe, expect, it } from "vitest";
import type { Fit, Role, SalaryBand } from "../api/types";
import { pickBand } from "./Roles";
import { bestRoleFit } from "./Strengths";

const band = (mid: number, is_confident: boolean): SalaryBand => ({
  low: mid - 10_000,
  mid,
  high: mid + 10_000,
  currency: "EUR",
  sample_size: is_confident ? 20 : 2,
  is_confident,
});

const role = (id: string): Role => ({
  id,
  name: `Role ${id}`,
  hiring_bar: 60,
  bar_basis: "estimated",
  bar_confidence: 0.5,
  bar_reasoning: null,
  opening_count: 3,
  salary_bands: {},
  is_coherent: true,
  requirements: [],
});

const fit = (role_id: string | null, score: number): Fit => ({
  role_id,
  private_posting_id: role_id ? null : "p1",
  score,
  reasoning: "",
  gaps: [],
  uncovered: [],
  model_id: "m",
  computed_at: "2026-09-23T00:00:00Z",
});

describe("salary band choice", () => {
  const bands = {
    Berlin: band(70_000, false),
    "Remote EU": band(80_000, true),
  };

  it("prefers a well-sampled band when no market is picked", () => {
    expect(pickBand(bands)?.mid).toBe(80_000);
  });

  it("uses the picked market's band, even a thin one", () => {
    expect(pickBand(bands, "Berlin")?.mid).toBe(70_000);
  });

  it("has nothing for a market the role has no band in", () => {
    expect(pickBand(bands, "Lisbon")).toBeNull();
    expect(pickBand({})).toBeNull();
  });
});

describe("the role strengths are compared against", () => {
  it("is the analysed role with the highest fit", () => {
    const best = bestRoleFit(
      [fit("a", 60), fit("b", 82), fit(null, 99)],
      [role("a"), role("b")],
    );
    expect(best?.role.id).toBe("b");
  });

  it("ignores fits for roles no longer on the map", () => {
    expect(bestRoleFit([fit("gone", 90)], [role("a")])).toBeNull();
  });
});
