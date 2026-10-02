import "./globals.css";
import "leaflet/dist/leaflet.css";
import "react-leaflet-cluster/dist/assets/MarkerCluster.css";
import "react-leaflet-cluster/dist/assets/MarkerCluster.Default.css";
import type { ReactNode } from "react";

export const metadata = { title: "ColdSync AI", description: "Investigative research and evidence correlation workspace" };
export default function RootLayout({ children }: { children: ReactNode }) {
  return <html lang="en"><body>{children}</body></html>;
}
