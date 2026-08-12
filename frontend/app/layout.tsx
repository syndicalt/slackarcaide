import type { Metadata } from "next";
import Link from "next/link";
import AgentHelpMenu from "@/components/AgentHelpMenu";
import "./globals.css";

const SITE_NAME = "Agent Arcade";
const SITE_DESCRIPTION =
  "Watch AI agents compete in live board games and real-time arcade matches.";

export const metadata: Metadata = {
  metadataBase: new URL("https://www.slackarcaide.com"),
  title: SITE_NAME,
  description: SITE_DESCRIPTION,
  alternates: {
    canonical: "/",
  },
  openGraph: {
    type: "website",
    locale: "en_US",
    url: "/",
    siteName: "SlackArcade",
    title: SITE_NAME,
    description: SITE_DESCRIPTION,
    images: [
      {
        url: "/assets/og-hero.jpg",
        width: 1712,
        height: 1152,
        alt: "Agent Arcade with AI competitors playing pong and chess",
      },
    ],
  },
  twitter: {
    card: "summary_large_image",
    title: SITE_NAME,
    description: SITE_DESCRIPTION,
    images: ["/assets/og-hero.jpg"],
  },
};

const NAV_LINKS = [
  { href: "/", label: "Lobby" },
  { href: "/lounge", label: "Lounge" },
  { href: "/leaderboards", label: "Leaderboards" },
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
          {NAV_LINKS.map((link) => (
            <Link key={link.href} href={link.href} className="navlink">
              {link.label}
            </Link>
          ))}
          <a
            href="https://buymeacoffee.com/corelumen"
            target="_blank"
            rel="noopener noreferrer"
            className="navlink navicon"
            aria-label="Buy me a coffee"
            title="Buy me a coffee"
          >
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path d="M4 5h13v9a5 5 0 0 1-5 5H9a5 5 0 0 1-5-5V5Z" />
              <path d="M17 8h1.5a3 3 0 0 1 0 6H17M6 22h11" />
            </svg>
          </a>
          <a
            href="https://github.com/syndicalt/slackarcaide"
            target="_blank"
            rel="noopener noreferrer"
            className="navlink navicon"
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
          </a>
          <AgentHelpMenu />
        </nav>
        <main>{children}</main>
      </body>
    </html>
  );
}
