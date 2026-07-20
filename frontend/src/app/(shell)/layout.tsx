import type { ReactNode } from "react";

import { QueryProvider } from "@/components/providers/QueryProvider";
import { Sidebar } from "@/components/ui/Sidebar";

/**
 * Shell chrome for the attorney workspace: persistent left sidebar + scrollable
 * main. Wraps everything in the Query provider so every route group page shares
 * one cache. The root layout still owns <html>/<body> and the fonts.
 */
export default function ShellLayout({ children }: { children: ReactNode }) {
  return (
    <QueryProvider>
      <div className="flex min-h-full flex-1 flex-col md:flex-row">
        <Sidebar />
        <main className="min-w-0 flex-1 px-5 py-8 md:px-10">
          <div className="mx-auto w-full max-w-5xl">{children}</div>
        </main>
      </div>
    </QueryProvider>
  );
}
