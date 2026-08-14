import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import SiteMenu from "./SiteMenu";

vi.mock("next/navigation", () => ({ usePathname: () => "/" }));

describe("SiteMenu", () => {
  afterEach(cleanup);

  it("keeps navigation hidden until requested", () => {
    render(<SiteMenu />);

    expect(
      screen.queryByRole("dialog", { name: "Site navigation" }),
    ).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Site menu" }));

    expect(
      screen.getByRole("dialog", { name: "Site navigation" }),
    ).not.toBeNull();
    expect(
      screen.getByRole("link", { name: "Lobby" }).getAttribute("href"),
    ).toBe("/");
    expect(
      screen.getByRole("link", { name: "Lounge" }).getAttribute("href"),
    ).toBe("/lounge");
    expect(screen.getByRole("link", { name: "History" })).not.toBeNull();
    expect(screen.getByRole("link", { name: "Leaderboards" })).not.toBeNull();
    expect(screen.getByRole("link", { name: "Agent guide" })).not.toBeNull();
    expect(
      screen.getByRole("link", { name: "Buy me a coffee" }),
    ).not.toBeNull();
    expect(
      screen.getByRole("link", { name: "View SlackArcade on GitHub" }),
    ).not.toBeNull();
  });

  it("closes on Escape and restores focus", () => {
    render(<SiteMenu />);
    const trigger = screen.getByRole("button", { name: "Site menu" });
    fireEvent.click(trigger);
    fireEvent.keyDown(document, { key: "Escape" });

    expect(
      screen.queryByRole("dialog", { name: "Site navigation" }),
    ).toBeNull();
    expect(document.activeElement).toBe(trigger);
  });
});
