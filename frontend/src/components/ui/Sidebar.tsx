"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

type NavItem = {
  href: string;
  label: string;
  /** Match this route and everything under it for the active state. */
  match: string;
};

const NAV: NavItem[] = [
  { href: "/matters", label: "Matters", match: "/matters" },
  { href: "/inbox", label: "Inbox", match: "/inbox" },
  { href: "/packages", label: "Packages", match: "/packages" },
];

function isActive(pathname: string, match: string): boolean {
  return pathname === match || pathname.startsWith(`${match}/`);
}

export function Sidebar() {
  const pathname = usePathname();
  return (
    <aside className="flex shrink-0 flex-col border-r border-line bg-surface/70 backdrop-blur md:w-60">
      <div aria-hidden className="h-1 bg-accent" />
      <div className="border-b border-line px-5 py-4">
        <Link href="/" className="flex flex-col gap-0.5">
          <span className="font-display text-xl tracking-tight">Yunaki</span>
          <span className="text-[10px] font-semibold uppercase tracking-[0.18em] text-ink-soft">
            Attorney workspace
          </span>
        </Link>
      </div>
      <nav aria-label="Workspace" className="flex flex-1 flex-col gap-1 p-3">
        {NAV.map((item) => {
          const active = isActive(pathname, item.match);
          return (
            <Link
              key={item.href}
              href={item.href}
              aria-current={active ? "page" : undefined}
              className={`rounded-lg px-3 py-2 text-sm font-medium transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent ${
                active
                  ? "bg-accent-wash text-accent-deep"
                  : "text-ink-soft hover:bg-line/40 hover:text-ink"
              }`}
            >
              {item.label}
            </Link>
          );
        })}
      </nav>
      <div className="border-t border-line px-5 py-3">
        <span className="text-[11px] leading-relaxed text-ink-faint">
          Runs locally · never submits or signs
        </span>
      </div>
    </aside>
  );
}
