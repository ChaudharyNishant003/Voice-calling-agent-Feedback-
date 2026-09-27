import { AppSidebar } from "@/components/app-sidebar";
import { DemoPasscodeCapture } from "@/components/demo-passcode-capture";

export default function ShellLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen">
      <DemoPasscodeCapture />
      <AppSidebar />
      <main className="flex-1 overflow-y-auto">{children}</main>
    </div>
  );
}
