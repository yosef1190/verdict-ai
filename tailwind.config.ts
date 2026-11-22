import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  darkMode: "class",
  corePlugins: { preflight: false },
  theme: {
    extend: {
      colors: {
        verdict: {
          forest: "#2F6B4A",
          forestDark: "#235539",
          mint: "#DDEFE3",
          cream: "#FAF9F6",
          paper: "#FDFDFC",
          ink: "#12151C",
          muted: "#5F646D",
          line: "#E4E2DC",
          gold: "#D6A23A",
          amber: "#B4650F",
          sand: "#FBEBD3",
          red: "#B83A2E",
          rose: "#FBE9E6",
          blue: "#2E5B92",
        },
      },
      fontFamily: {
        serif: ["var(--f-serif)", "Georgia", "serif"],
        sans: ["var(--f-sans)", "Inter", "sans-serif"],
        mono: ["var(--f-mono)", "ui-monospace", "monospace"],
      },
      boxShadow: {
        card: "0 20px 50px -32px rgba(18,21,28,.28)",
        lift: "0 24px 60px -28px rgba(18,21,28,.35)",
      },
      transitionDuration: { 180: "180ms" },
    },
  },
  plugins: [],
};

export default config;
