import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { completeCallback, parseCallback } from "./oauthCallback";

describe("parseCallback", () => {
  it("reads code and state from a Jira callback", () => {
    expect(
      parseCallback("/connections/jira/callback", "?code=abc&state=xyz"),
    ).toEqual({
      kind: "jira",
      code: "abc",
      state: "xyz",
    });
  });

  it("ignores a page that is not a callback", () => {
    expect(parseCallback("/", "?code=abc&state=xyz")).toBeNull();
    expect(parseCallback("/connections", "")).toBeNull();
  });

  it("ignores a connector we do not support", () => {
    expect(
      parseCallback("/connections/linkedin/callback", "?code=a&state=b"),
    ).toBeNull();
  });

  it("turns a declined consent into a sentence, not an error code", () => {
    const result = parseCallback(
      "/connections/jira/callback",
      "?error=access_denied",
    );
    expect(result).toEqual({
      kind: "jira",
      error: "Access was not granted, so nothing was connected.",
    });
  });

  it("prefers the provider's own description when it sends one", () => {
    const result = parseCallback(
      "/connections/github/callback",
      "?error=redirect_uri_mismatch&error_description=The+redirect_uri+is+not+registered",
    );
    expect(result).toEqual({
      kind: "github",
      error: "The redirect_uri is not registered",
    });
  });

  it("treats a callback missing its state as incomplete rather than posting half of it", () => {
    const result = parseCallback("/connections/jira/callback", "?code=abc");
    expect(result && "error" in result).toBe(true);
  });
});

describe("completeCallback", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    (window as unknown as { __APP_CONFIG__?: unknown }).__APP_CONFIG__ = {
      apiBaseUrl: "http://api.test",
    };
    fetchMock = vi.fn(async () => new Response("{}", { status: 201 }));
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("posts code and state to the API and reports success", async () => {
    const replaceUrl = vi.fn();
    const outcome = await completeCallback(
      { pathname: "/connections/jira/callback", search: "?code=abc&state=xyz" },
      replaceUrl,
    );

    expect(outcome).toEqual({
      kind: "jira",
      connected: true,
      message: "Jira is connected. The first sync is running now.",
    });
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://api.test/api/v1/connections/jira/callback");
    expect(JSON.parse(String(init.body))).toEqual({
      code: "abc",
      state: "xyz",
    });
  });

  it("clears the URL before the request, because the code is single-use", async () => {
    const order: string[] = [];
    const replaceUrl = vi.fn(() => order.push("replace"));
    fetchMock.mockImplementation(async () => {
      order.push("fetch");
      return new Response("{}", { status: 201 });
    });

    await completeCallback(
      { pathname: "/connections/jira/callback", search: "?code=abc&state=xyz" },
      replaceUrl,
    );

    expect(replaceUrl).toHaveBeenCalledWith("/");
    expect(order).toEqual(["replace", "fetch"]);
  });

  it("does not call the API when the person declined", async () => {
    const outcome = await completeCallback(
      {
        pathname: "/connections/jira/callback",
        search: "?error=access_denied",
      },
      vi.fn(),
    );
    expect(outcome?.connected).toBe(false);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("shows the API's reason when the exchange fails", async () => {
    fetchMock.mockImplementation(
      async () =>
        new Response(
          JSON.stringify({
            error: {
              code: "upstream_failed",
              message: "jira rejected the authorization code",
            },
          }),
          { status: 502 },
        ),
    );
    const outcome = await completeCallback(
      { pathname: "/connections/jira/callback", search: "?code=abc&state=xyz" },
      vi.fn(),
    );
    expect(outcome).toEqual({
      kind: "jira",
      connected: false,
      message: "jira rejected the authorization code",
    });
  });

  it("does nothing on an ordinary page load", async () => {
    const replaceUrl = vi.fn();
    expect(
      await completeCallback({ pathname: "/", search: "" }, replaceUrl),
    ).toBeNull();
    expect(replaceUrl).not.toHaveBeenCalled();
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
