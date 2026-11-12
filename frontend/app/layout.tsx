import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Agent Workspace",
  description: "Your workspace for focused conversations with AI.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className="dark h-full antialiased">
      <body className="min-h-full flex flex-col">{children}</body>
    </html>
  );
}
