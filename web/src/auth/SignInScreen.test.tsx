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
    privacyContactEmail: "privacy@example.test",
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
  it("links to the privacy policy before anyone signs in", () => {
    renderScreen();
    expect(
      screen.getByRole("link", { name: "Privacy policy" }),
    ).toHaveAttribute("href", "/privacy");
  });

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

    await user.click(screen.getByRole("button", { name: "Create an account" }));
    expect(
      screen.getByRole("heading", { name: "Create your account" }),
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

  it("welcomes back by default", async () => {
    renderScreen();
    expect(
      await screen.findByRole("heading", { name: "Welcome back" }),
    ).toBeInTheDocument();
  });

  it("shows how CareerPolaris works as one named figure", async () => {
    renderScreen();
    expect(
      await screen.findByRole("figure", {
        name: /^How CareerPolaris works: 1, evidence/,
      }),
    ).toBeInTheDocument();
  });

  it("switches back to signing in from registration", async () => {
    const user = userEvent.setup();
    renderScreen();

    await user.click(screen.getByRole("button", { name: "Create an account" }));
    // Registering, the submit is "Create account" and "Sign in" only switches.
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    expect(
      screen.getByRole("heading", { name: "Welcome back" }),
    ).toBeInTheDocument();
  });
});

describe("field accessibility", () => {
  it("names the password field 'Password', not the whole hint sentence", async () => {
    const user = userEvent.setup();
    renderScreen();
    await user.click(screen.getByRole("button", { name: "Create an account" }));

    const password = screen.getByLabelText("Password");
    // The hint is help text, announced as a description rather than a name.
    expect(password).toHaveAccessibleName("Password");
    expect(password).toHaveAccessibleDescription(/At least 12 characters/);
  });
});

describe("signing in with Google", () => {
  function methods(google: boolean, platformAi = false) {
    fetchMock.mockImplementation(async (input: unknown) => {
      const url = String(input);
      if (url.endsWith("/auth/refresh")) {
        return jsonResponse(
          { error: { code: "unauthenticated", message: "no" } },
          401,
        );
      }
      if (url.endsWith("/auth/methods")) {
        return jsonResponse({
          password: true,
          google,
          platform_ai: platformAi,
        });
      }
      return jsonResponse(sessionBody("maya@example.com"));
    });
  }

  afterEach(() => {
    window.history.replaceState(null, "", "/");
  });

  it("offers Google as a link to the API when the server has it", async () => {
    methods(true);
    renderScreen();

    const link = await screen.findByRole("link", {
      name: "Continue with Google",
    });
    expect(link).toHaveAttribute(
      "href",
      "http://api.test/api/v1/auth/google/start",
    );
  });

  it("does not offer Google when the server is not set up for it", async () => {
    methods(false);
    renderScreen();

    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(([url]) =>
          String(url).endsWith("/auth/methods"),
        ),
      ).toBe(true),
    );
    expect(
      screen.queryByRole("link", { name: "Continue with Google" }),
    ).not.toBeInTheDocument();
  });

  it("offers Google before the email form", async () => {
    methods(true);
    renderScreen();

    const link = await screen.findByRole("link", {
      name: "Continue with Google",
    });
    expect(
      link.compareDocumentPosition(screen.getByLabelText("Email")) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it("says a Google account starts on CareerPolaris AI when the platform is on", async () => {
    methods(true, true);
    renderScreen();

    expect(
      await screen.findByText(/start on CareerPolaris AI's free monthly quota/),
    ).toBeInTheDocument();
  });

  it("says to bring your own provider and key when the platform is off", async () => {
    methods(true, false);
    renderScreen();

    await screen.findByRole("link", { name: "Continue with Google" });
    expect(
      screen.getByText(/you add your own AI provider and key/),
    ).toBeInTheDocument();
    expect(screen.queryByText(/CareerPolaris AI/)).not.toBeInTheDocument();
  });

  it("warns that Google takes over a password account only when Google is offered", async () => {
    methods(true);
    const { unmount } = renderScreen();
    expect(
      await screen.findByText(/any password on it stops working/),
    ).toBeInTheDocument();
    unmount();

    methods(false);
    renderScreen();
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.filter(([url]) =>
          String(url).endsWith("/auth/methods"),
        ).length,
      ).toBe(2),
    );
    expect(
      screen.queryByText(/any password on it stops working/),
    ).not.toBeInTheDocument();
  });

  it("says why a Google sign-in did not finish, and clears it from the URL", async () => {
    methods(true);
    window.history.replaceState(null, "", "/?sign_in_error=declined");
    renderScreen();

    expect(await screen.findByText(/cancelled/)).toBeInTheDocument();
    expect(window.location.search).toBe("");
  });
});
