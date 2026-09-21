import "@testing-library/jest-dom/vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AuthProvider } from "./AuthProvider";
import { SignInScreen } from "./SignInScreen";

/**
 * Exercises the real form: typing, the submit button's enabled state, the
 * request that goes out, and what the user is told when it fails.
 *
 * Browser automation could not drive this reliably — synthetic value-setting
 * does not reach a React controlled input — so the wiring is covered here,
 * where the events are real and the check is repeatable.
 */

function configure(): void {
  (window as unknown as { __APP_CONFIG__?: unknown }).__APP_CONFIG__ = {
    apiBaseUrl: "http://api.test",
  };
}

function sessionBody(email: string) {
  return {
    account_id: "11111111-1111-1111-1111-111111111111",
    email,
    access_token: "an-access-token",
    expires_in: 900,
  };
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  configure();
  fetchMock = vi.fn(async (input: unknown) => {
    const url = String(input);
    // The provider tries the refresh cookie on mount; there is none in a test.
    if (url.endsWith("/auth/refresh")) {
      return jsonResponse(
        { error: { code: "unauthenticated", message: "no" } },
        401,
      );
    }
    return jsonResponse(sessionBody("maya@example.com"));
  });
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
  (window as unknown as { __APP_CONFIG__?: unknown }).__APP_CONFIG__ =
    undefined;
});

function renderScreen() {
  return render(
    <AuthProvider>
      <SignInScreen />
    </AuthProvider>,
  );
}

describe("sign-in screen", () => {
  it("keeps submit disabled until both fields have something in them", async () => {
    const user = userEvent.setup();
    renderScreen();

    const submit = screen.getByRole("button", { name: "Sign in" });
    expect(submit).toBeDisabled();

    await user.type(screen.getByLabelText("Email"), "maya@example.com");
    expect(submit).toBeDisabled();

    await user.type(
      screen.getByLabelText("Password"),
      "a perfectly fine passphrase",
    );
    expect(submit).toBeEnabled();
  });

  it("sends the credentials to the sign-in endpoint", async () => {
    const user = userEvent.setup();
    renderScreen();

    await user.type(screen.getByLabelText("Email"), "maya@example.com");
    await user.type(
      screen.getByLabelText("Password"),
      "a perfectly fine passphrase",
    );
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(([url]) =>
        String(url).endsWith("/auth/sign-in"),
      );
      expect(call).toBeDefined();
      const [, init] = call as [string, RequestInit];
      // Without this the browser withholds the refresh cookie.
      expect(init.credentials).toBe("include");
      expect(JSON.parse(String(init.body))).toEqual({
        email: "maya@example.com",
        password: "a perfectly fine passphrase",
      });
    });
  });

  it("submits on Enter as well as on click", async () => {
    const user = userEvent.setup();
    renderScreen();

    await user.type(screen.getByLabelText("Email"), "maya@example.com");
    await user.type(
      screen.getByLabelText("Password"),
      "a perfectly fine passphrase{Enter}",
    );

    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(([url]) =>
          String(url).endsWith("/auth/sign-in"),
        ),
      ).toBe(true),
    );
  });

  it("shows the API's own message when sign-in is refused", async () => {
    fetchMock.mockImplementation(async (input: unknown) => {
      if (String(input).endsWith("/auth/refresh")) {
        return jsonResponse(
          { error: { code: "unauthenticated", message: "no" } },
          401,
        );
      }
      return jsonResponse(
        {
          error: {
            code: "unauthenticated",
            message: "That email and password do not match.",
          },
        },
        401,
      );
    });
    const user = userEvent.setup();
    renderScreen();

    await user.type(screen.getByLabelText("Email"), "maya@example.com");
    await user.type(screen.getByLabelText("Password"), "the wrong passphrase");
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    expect(
      await screen.findByText("That email and password do not match."),
    ).toBeInTheDocument();
  });

  it("switches to registration and posts to the register endpoint", async () => {
    const user = userEvent.setup();
    renderScreen();

    await user.click(screen.getByRole("button", { name: "Create one" }));
    expect(
      screen.getByRole("heading", { name: "Create an account" }),
    ).toBeInTheDocument();

    await user.type(screen.getByLabelText("Email"), "new@example.com");
    await user.type(
      screen.getByLabelText("Password"),
      "a perfectly fine passphrase",
    );
    await user.click(screen.getByRole("button", { name: "Create account" }));

    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(([url]) =>
          String(url).endsWith("/auth/register"),
        ),
      ).toBe(true),
    );
  });

  it("says plainly that there is no password reset yet", () => {
    renderScreen();
    expect(screen.getByText(/no password reset yet/i)).toBeInTheDocument();
  });
});

describe("field accessibility", () => {
  it("names the password field 'Password', not the whole hint sentence", async () => {
    const user = userEvent.setup();
    renderScreen();
    await user.click(screen.getByRole("button", { name: "Create one" }));

    const password = screen.getByLabelText("Password");
    // The hint is help text, announced as a description rather than a name.
    expect(password).toHaveAccessibleName("Password");
    expect(password).toHaveAccessibleDescription(/At least 12 characters/);
  });
});
