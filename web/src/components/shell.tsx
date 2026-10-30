"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "cn";

const links = [
  { href: "/", label: "Jobs" },
  { href: "/jobs/new", label: "New backup" },
  { href: "/settings", label: "Settings" },
];

export function Shell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  return (
    <div className="flex min-h-screen flex-col md:flex-row">
      <aside className="border-b border-border bg-card/70 md:w-60 md:border-r md:border-b-0">
        <div className="flex items-center justify-between gap-4 px-5 py-4 md:block md:px-6 md:py-7">
          <Link href="/" className="block">
            <span className="font-heading text-3xl leading-none tracking-tight">bgb</span>
            <span className="mt-1 block text-xs tracking-[0.16em] text-muted-foreground uppercase">
              Workspace backup
            </span>
          </Link>
          <nav className="flex gap-1 md:mt-8 md:flex-col">
            {links.map((link) => {
              const active = pathname === link.href;
              return (
                <Link
                  key={link.href}
                  href={link.href}
                  className={cn(
                    "rounded-lg px-3 py-2 text-sm text-muted-foreground hover:bg-accent hover:text-foreground",
                    active && "bg-accent text-foreground",
                  )}
                >
                  {link.label}
                </Link>
              );
            })}
          </nav>
        </div>
      </aside>
      <main className="flex-1 px-4 py-6 md:px-10 md:py-8">{children}</main>
    </div>
  );
}
