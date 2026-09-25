import { redirect } from "next/navigation";

export default function RootPage() {
  // Sprint 6 (docs/11_BUILD_PLAN.md S6.1) adds the real app shell + auth-aware redirect; until
  // then the Demo MVP is the actual working entry point (`/login` is a stub with nothing behind
  // it yet — see app/(shell)/login/page.tsx).
  redirect("/demo");
}
