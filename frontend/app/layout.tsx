import type { Metadata } from "next";
import { Public_Sans, Source_Serif_4 } from "next/font/google";
import { AmplifyConfig } from "@/components/amplify-config";
import "./globals.css";

const publicSans = Public_Sans({
  variable: "--font-public-sans",
  subsets: ["latin"],
});

const sourceSerif = Source_Serif_4({
  variable: "--font-source-serif",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Casefile",
  description: "Ask questions about your firm's documents and get answers with citations.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${publicSans.variable} ${sourceSerif.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col">
        <AmplifyConfig />
        {children}
      </body>
    </html>
  );
}
