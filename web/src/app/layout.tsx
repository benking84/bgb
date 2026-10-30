import type { Metadata } from "next";
import { Fraunces, IBM_Plex_Mono, Source_Sans_3 } from "next/font/google";
import { Shell } from "@/components/shell";
import "./globals.css";

const sans = Source_Sans_3({
  subsets: ["latin"],
  variable: "--font-app-sans",
});

const heading = Fraunces({
  subsets: ["latin"],
  variable: "--font-app-heading",
});

const mono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500"],
  variable: "--font-app-mono",
});

export const metadata: Metadata = {
  title: "bgb — Workspace backup",
  description: "Block-level backup for Gmail and Google Drive, stored encrypted in Cloud Storage.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`dark ${sans.variable} ${heading.variable} ${mono.variable} h-full`}
    >
      <body className="min-h-full antialiased">
        <Shell>{children}</Shell>
      </body>
    </html>
  );
}
