import type { Metadata } from "next";
import "./globals.css";
import "./grid.css";

export const metadata: Metadata = {
  title: "Verdict | Dispute operations",
  description: "Know which disputes to fight.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className="h-full antialiased"
    >
      <body className="min-h-full flex flex-col">{children}</body>
    </html>
  );
}
