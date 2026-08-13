import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import AgentHelpMenu from "./AgentHelpMenu";

afterEach(() => {
  cleanup();
});

describe("AgentHelpMenu", () => {
  it("opens with actionable agent instructions and canonical resources", () => {
    render(<AgentHelpMenu />);

    const trigger = screen.getByRole("button", { name: "How agents play" });
    expect(trigger.getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByRole("dialog")).toBeNull();

    fireEvent.click(trigger);

    expect(trigger.getAttribute("aria-expanded")).toBe("true");
    const dialog = screen.getByRole("dialog", { name: "How agents play" });
    expect(dialog.textContent).toContain("POST /agents/register");
    expect(dialog.textContent).toContain("GET /games");
    expect(dialog.textContent).toContain("legal_actions");
    expect(
      screen
        .getByRole("link", { name: "Full agent guide" })
        .getAttribute("href"),
    ).toBe("/llms.txt");
    expect(
      screen.getByRole("link", { name: "OpenAPI schema" }).getAttribute("href"),
    ).toBe("http://localhost:8000/openapi.json");
    expect(
      screen
        .getByRole("link", { name: "Downloadable MCP bridge" })
        .getAttribute("href"),
    ).toBe("http://localhost:8000/mcp/slackarcaide_mcp.py");
  });

  it("closes on Escape and returns focus to its trigger", () => {
    render(<AgentHelpMenu />);
    const trigger = screen.getByRole("button", { name: "How agents play" });

    fireEvent.click(trigger);
    fireEvent.keyDown(document, { key: "Escape" });

    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(trigger);
  });

  it("closes when the user clicks outside the menu", () => {
    render(<AgentHelpMenu />);
    fireEvent.click(screen.getByRole("button", { name: "How agents play" }));

    fireEvent.pointerDown(document.body);

    expect(screen.queryByRole("dialog")).toBeNull();
  });
});
