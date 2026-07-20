import { MatterDetailView } from "@/components/matters/MatterDetailView";

/**
 * Dynamic matter route (web/dev). Delegates to the shared MatterDetailView, the
 * same component the desktop static twin (`/matter?id=`) renders.
 *
 * Static-export compatibility: a client page with an arbitrary dynamic segment
 * cannot be statically exported. On web/dev this returns `[]` so ids resolve on
 * demand. Under `output: export` Next forbids a dynamic route with zero params,
 * so the desktop build emits a single inert sentinel page — the desktop app
 * never links to path-style URLs (it uses the `/matter?id=` twin), so this page
 * is dead weight, present only to satisfy the exporter. No `[id]` folder ends
 * up in `out/`.
 */
export function generateStaticParams() {
  if (process.env.NEXT_PUBLIC_DESKTOP === "1") {
    return [{ id: "_" }];
  }
  return [];
}

export default async function MatterDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return <MatterDetailView matterId={id} />;
}
