import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Assistant — SCIOS",
  description: "AI-powered academic research assistant",
};

export default function AssistantLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return <>{children}</>;
}
