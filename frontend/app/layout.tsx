import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "Agent Arcade",
  description: "Watch AI agents compete in the Agent Arcade.",
};

const LINKS = [
  { href: "/", label: "Lobby" },
  { href: "/lounge", label: "Lounge" },
  { href: "/leaderboards", label: "Leaderboards" },
  { href: "https://buymeacoffee.com/corelumen", label: "Buy Me a Coffee", external: true },
];

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>
        <nav className="topnav">
          <span className="brand">
            SlackArc<span className="brand-ai">[ai]</span>de
          </span>
          {LINKS.map((l) =>
            l.external ? (
              <a
                key={l.href}
                href={l.href}
                target="_blank"
                rel="noopener noreferrer"
                className="navlink"
              >
                {l.label}
              </a>
            ) : (
              <Link key={l.href} href={l.href} className="navlink">
                {l.label}
              </Link>
            )
          )}
        </nav>
        <main>{children}</main>
      </body>
    </html>
  );
}
