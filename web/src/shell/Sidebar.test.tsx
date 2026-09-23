import "@testing-library/jest-dom/vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { Credential } from "../api/types";
import { initialsOf } from "./PageHeader";
import type { ShellStatus } from "./ShellContext";
import { Sidebar } from "./Sidebar";

const credential: Credential = {
  provider: "anthropic",
  model: "claude-opus-5",
  base_url: null,
  last_four: "abcd",
  status: "active",
  last_error: null,
};

function status(overrides: Partial<ShellStatus> = {}): ShellStatus {
  return {
    me: null,
    credential,
    openQuestions: 0,
    confidence: null,
    ...overrides,
  };
}

describe("sidebar", () => {
  it("marks the current screen and navigates on click", async () => {
    const onNavigate = vi.fn();
    render(
      <Sidebar current="roles" status={status()} onNavigate={onNavigate} />,
    );

    const nav = screen.getByRole("navigation", { name: "Screens" });
    expect(
      within(nav).getByRole("button", { name: /Role map/ }),
    ).toHaveAttribute("aria-current", "page");

    await userEvent.click(
      within(nav).getByRole("button", { name: /Gap plan/ }),
    );
    expect(onNavigate).toHaveBeenCalledWith("plan");
  });

  it("flags how many questions are still unanswered", () => {
    render(
      <Sidebar
        current="sources"
        status={status({ openQuestions: 3 })}
        onNavigate={() => {}}
      />,
    );
    expect(screen.getByLabelText("3 unanswered")).toBeInTheDocument();
  });

  it("flags the model when no key is set, and names the model once it is", () => {
    const { rerender } = render(
      <Sidebar
        current="sources"
        status={status({ credential: null })}
        onNavigate={() => {}}
      />,
    );
    expect(screen.getByLabelText("needs a key")).toBeInTheDocument();
    expect(screen.getByText("No key yet")).toBeInTheDocument();

    rerender(
      <Sidebar current="sources" status={status()} onNavigate={() => {}} />,
    );
    expect(screen.queryByLabelText("needs a key")).not.toBeInTheDocument();
    expect(screen.getByText("claude-opus-5")).toBeInTheDocument();
  });

  it("shows confidence only once there is an analysis", () => {
    const { rerender } = render(
      <Sidebar current="sources" status={status()} onNavigate={() => {}} />,
    );
    expect(screen.getByText(/Run the analysis/)).toBeInTheDocument();

    rerender(
      <Sidebar
        current="sources"
        status={status({ confidence: 91 })}
        onNavigate={() => {}}
      />,
    );
    expect(
      screen.getByRole("progressbar", { name: "Profile confidence" }),
    ).toHaveAttribute("aria-valuenow", "91");
    expect(
      screen.getByText("Enough to trust the salary bands."),
    ).toBeInTheDocument();
  });
});

describe("account initials", () => {
  it("takes one letter from each of the first two parts of the address", () => {
    expect(initialsOf("maya.chen@example.com")).toBe("MC");
    expect(initialsOf("maya_lin-chen@example.com")).toBe("ML");
  });

  it("falls back to the first two letters, or a placeholder", () => {
    expect(initialsOf("maya@example.com")).toBe("MA");
    expect(initialsOf(null)).toBe("?");
  });
});
