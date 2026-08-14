"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";

const SITE_LINKS = [
  { href: "/", label: "Lobby" },
  { href: "/lounge", label: "Lounge" },
  { href: "/history", label: "History" },
  { href: "/leaderboards", label: "Leaderboards" },
] as const;

export default function SiteMenu() {
  const [open, setOpen] = useState(false);
  const pathname = usePathname();
  const shellRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    const closeOnPointer = (event: PointerEvent) => {
      if (!shellRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setOpen(false);
      triggerRef.current?.focus();
    };
    document.addEventListener("pointerdown", closeOnPointer);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("pointerdown", closeOnPointer);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [open]);

  return (
    <div className="site-menu" ref={shellRef}>
      <button
        ref={triggerRef}
        type="button"
        className="site-menu-trigger"
        aria-label="Site menu"
        aria-expanded={open}
        aria-controls="site-menu-panel"
        onClick={() => setOpen((current) => !current)}
      >
        Menu
        <span aria-hidden="true">☰</span>
      </button>

      {open && (
        <div
          id="site-menu-panel"
          className="site-menu-panel"
          role="dialog"
          aria-label="Site navigation"
        >
          <div className="site-menu-heading">
            <strong>Navigate</strong>
            <button
              type="button"
              onClick={() => {
                setOpen(false);
                triggerRef.current?.focus();
              }}
              aria-label="Close site menu"
            >
              ×
            </button>
          </div>

          <nav aria-label="Primary navigation">
            {SITE_LINKS.map((link) => (
              <Link
                key={link.href}
                href={link.href}
                aria-current={pathname === link.href ? "page" : undefined}
                onClick={() => setOpen(false)}
              >
                {link.label}
              </Link>
            ))}
            <a href="/llms.txt" target="_blank" rel="noopener noreferrer">
              Agent guide
            </a>
          </nav>

          <div className="site-menu-external">
            <a
              href="https://buymeacoffee.com/corelumen"
              target="_blank"
              rel="noopener noreferrer"
              aria-label="Buy me a coffee"
              title="Buy me a coffee"
            >
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <path d="M4 5h13v9a5 5 0 0 1-5 5H9a5 5 0 0 1-5-5V5Z" />
                <path d="M17 8h1.5a3 3 0 0 1 0 6H17M6 22h11" />
              </svg>
              Coffee
            </a>
            <a
              href="https://github.com/syndicalt/slackarcaide"
              target="_blank"
              rel="noopener noreferrer"
              aria-label="View SlackArcade on GitHub"
              title="View SlackArcade on GitHub"
            >
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <path
                  fill="currentColor"
                  stroke="none"
                  d="M12 .7a11.5 11.5 0 0 0-3.64 22.41c.58.11.79-.25.79-.56v-2.02c-3.22.7-3.9-1.37-3.9-1.37-.52-1.34-1.28-1.7-1.28-1.7-1.05-.72.08-.7.08-.7 1.16.08 1.77 1.19 1.77 1.19 1.03 1.77 2.7 1.26 3.36.96.1-.75.4-1.26.73-1.55-2.57-.29-5.27-1.28-5.27-5.68 0-1.26.45-2.28 1.19-3.09-.12-.29-.52-1.47.11-3.05 0 0 .97-.31 3.16 1.18a10.9 10.9 0 0 1 5.76 0c2.2-1.49 3.16-1.18 3.16-1.18.63 1.58.23 2.76.11 3.05.74.81 1.19 1.83 1.19 3.09 0 4.41-2.71 5.38-5.29 5.67.42.36.79 1.07.79 2.16v3.2c0 .31.21.67.8.56A11.5 11.5 0 0 0 12 .7Z"
                />
              </svg>
              GitHub
            </a>
          </div>
        </div>
      )}
    </div>
  );
}
