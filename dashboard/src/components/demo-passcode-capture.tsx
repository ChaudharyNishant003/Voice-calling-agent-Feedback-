"use client";

import { useEffect } from "react";

const PASSCODE_STORAGE_KEY = "pfa_demo_passcode";

/**
 * Lets a demo link carry its passcode inline (`.../demo?passcode=XXXX`) so a recipient doesn't
 * have to be told a separate step — captured into localStorage once, then stripped from the
 * visible URL so it doesn't linger in browser history or get left in a shared screenshot. A no-op
 * when no `passcode` param is present (including every local-dev request, where the backend has
 * no DEMO_PASSCODE configured and ignores this entirely).
 */
export function DemoPasscodeCapture() {
  useEffect(() => {
    const url = new URL(window.location.href);
    const passcode = url.searchParams.get("passcode");
    if (!passcode) return;
    try {
      localStorage.setItem(PASSCODE_STORAGE_KEY, passcode);
    } catch {
      // localStorage unavailable (private mode, etc.) — the passcode just won't persist.
    }
    url.searchParams.delete("passcode");
    window.history.replaceState({}, "", url.toString());
  }, []);

  return null;
}
