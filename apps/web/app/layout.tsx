import "./globals.css";
import type { ReactNode } from "react";

export const metadata = { title: "ColdSync AI", description: "Investigative research and evidence correlation workspace" };
export default function RootLayout({ children }: { children: ReactNode }) {
  return <html lang="en"><body>{children}</body></html>;
}
