import type { Metadata } from "next";
import { ClerkProvider } from "@clerk/nextjs";
import "./globals.css";

export const metadata: Metadata = {
  title: "QB Auditor",
  description: "AI-powered audit layer for QuickBooks Online.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <ClerkProvider>
      <html lang="en">
        <body className="bg-gray-50 text-gray-900">{children}</body>
      </html>
    </ClerkProvider>
  );
}
