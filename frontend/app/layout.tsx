import type { Metadata, Viewport } from "next";
import { Gotu } from "next/font/google";
import "./globals.css";

const gotu = Gotu({ weight: "400", subsets: ["latin"], display: "swap" });

export const metadata: Metadata = {
  title: "Svaar",
  description:
    "A voice-enabled agent for engineering incidents: it rebuilds what happened, checks claims against evidence and calls engineers to verify them.",
  icons: { icon: "/swan.png" },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className={gotu.className}>{children}</body>
    </html>
  );
}
