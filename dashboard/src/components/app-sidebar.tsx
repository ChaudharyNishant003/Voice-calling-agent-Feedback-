"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Bug, LogIn, PhoneCall, Settings } from "lucide-react";

import { cn } from "@/lib/utils";

const NAV_ITEMS = [
  { href: "/demo", label: "Call", icon: PhoneCall, isActive: (path: string) => path === "/demo" },
  {
    href: "/demo/settings",
    label: "Settings",
    icon: Settings,
    isActive: (path: string) => path === "/demo/settings",
  },
  {
    href: "/demo/debug",
    label: "Debug",
    icon: Bug,
    isActive: (path: string) => path.startsWith("/demo/debug"),
  },
  { href: "/login", label: "Login", icon: LogIn, isActive: (path: string) => path === "/login" },
];

export function AppSidebar() {
  const pathname = usePathname();

  return (
    <aside className="flex w-56 shrink-0 flex-col border-r bg-card">
      <div className="border-b px-4 py-4">
        <p className="text-sm font-semibold">Patient Feedback Agent</p>
        <p className="text-xs text-muted-foreground">Demo</p>
      </div>
      <nav className="flex flex-col gap-1 p-2">
        {NAV_ITEMS.map(({ href, label, icon: Icon, isActive }) => {
          const active = isActive(pathname);
          return (
            <Link
              key={href}
              href={href}
              className={cn(
                "flex items-center gap-2 rounded-md px-3 py-2 text-sm transition-colors",
                active
                  ? "bg-secondary font-medium text-secondary-foreground"
                  : "text-muted-foreground hover:bg-secondary/50 hover:text-secondary-foreground",
              )}
            >
              <Icon className="h-4 w-4" />
              {label}
            </Link>
          );
        })}
      </nav>
    </aside>
  );
}
