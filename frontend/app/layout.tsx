import type { Metadata } from "next";
import "./globals.css";
import { AstryxProvider } from "@/components/astryx-provider";
import { AuthProvider } from "@/components/auth-provider";

export const metadata: Metadata = {
  title: "InsightDOC — Softnix AI Document Platform",
  description: "AI-powered document extraction and processing by Softnix",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" data-theme="light" data-astryx-theme="neutral">
      <body className="antialiased font-sans">
        <AuthProvider>
          <AstryxProvider>
            {children}
          </AstryxProvider>
        </AuthProvider>
      </body>
    </html>
  );
}
