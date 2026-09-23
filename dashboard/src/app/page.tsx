import { redirect } from "next/navigation";

export default function RootPage() {
  // Sprint 6 (docs/11_BUILD_PLAN.md S6.1) adds the real app shell + auth-aware redirect.
  redirect("/login");
}
