import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        bg: "#0b0e14",
        panel: "#141824",
        panel2: "#1b2030",
        edge: "#252c40",
        text: "#e7e9ee",
        muted: "#9aa4bd",
        accent: "#7c7cff",
        neon: "#22ffd1",
        danger: "#ff5470",
        warn: "#ffb547",
      },
      fontFamily: {
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      boxShadow: {
        neon: "0 0 18px rgba(124,124,255,0.35)",
        "neon-cyan": "0 0 18px rgba(34,255,209,0.35)",
      },
    },
  },
  plugins: [],
};

export default config;
