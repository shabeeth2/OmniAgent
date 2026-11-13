"use client";

import dynamic from "next/dynamic";

// A2UI defines custom elements at module load and must only load in the browser.
const Renderer = dynamic(() => import("./PresentationRenderer"), {
  ssr: false,
  loading: () => <p role="status" className="text-sm text-muted-foreground">Loading visual…</p>,
});

export default function Presentation({ surfaces }: { surfaces: unknown[] }) {
  return <Renderer surfaces={surfaces} />;
}
