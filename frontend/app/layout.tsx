import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "InsightDOC — Softnix AI Document Platform",
  description: "AI-powered document extraction and processing by Softnix",
};

import { AuthProvider } from "@/components/auth-provider";

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className="antialiased font-sans">
        <AuthProvider>
          {children}
        </AuthProvider>
      </body>
    </html>
  );
}
