import { describe, expect, it } from "vitest";
import { readSignInError, withoutSignInError } from "./signInError";

describe("Google sign-in errors", () => {
  it("reads nothing from an ordinary URL", () => {
    expect(readSignInError("")).toBeNull();
    expect(readSignInError("?tab=roles")).toBeNull();
  });

  it("turns a known code into something a person can act on", () => {
    expect(readSignInError("?sign_in_error=declined")).toMatch(/cancelled/);
    expect(readSignInError("?sign_in_error=unverified_email")).toMatch(
      /not verified/,
    );
  });

  it("still says something for a code it does not know", () => {
    expect(readSignInError("?sign_in_error=something_new")).toMatch(
      /did not finish/,
    );
  });

  it("strips only the error from the URL", () => {
    expect(withoutSignInError("/", "?sign_in_error=declined")).toBe("/");
    expect(withoutSignInError("/", "?sign_in_error=declined&tab=roles")).toBe(
      "/?tab=roles",
    );
  });
});
