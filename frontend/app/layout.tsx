import type { Metadata } from "next";
import Link from "next/link";
import SiteMenu from "@/components/SiteMenu";
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

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>
        <header className="site-header">
          <Link href="/" className="brand" aria-label="SlackArcade lobby">
            SlackArc<span className="brand-ai">[ai]</span>de
          </Link>
          <SiteMenu />
        </header>
        <main>{children}</main>
      </body>
    </html>
  );
}
