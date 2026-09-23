import { describe, expect, it } from "vitest";
import {
  DEFAULT_SCREEN,
  JOURNEY,
  hashFor,
  metaOf,
  screenFromHash,
} from "./navigation";

describe("screen navigation", () => {
  it("numbers the journey 01 to 06 in the prototype's order", () => {
    expect(JOURNEY.map((item) => `${item.num} ${item.label}`)).toEqual([
      "01 Sources",
      "02 Questions",
      "03 Strengths",
      "04 Role map",
      "05 Gap plan",
      "06 Résumé",
    ]);
  });

  it("reads the screen back from the hash it wrote", () => {
    for (const item of [...JOURNEY.map((j) => j.id), "model" as const]) {
      expect(screenFromHash(hashFor(item))).toBe(item);
    }
  });

  it("lands on the first screen for an empty or unknown hash", () => {
    expect(screenFromHash("")).toBe(DEFAULT_SCREEN);
    expect(screenFromHash("#/nowhere")).toBe(DEFAULT_SCREEN);
  });

  it("gives settings its own title outside the numbered journey", () => {
    expect(metaOf("model")).toMatchObject({
      title: "Bring your own model",
      kicker: "System configuration",
    });
    expect(metaOf("model").num).toBeUndefined();
  });
});
