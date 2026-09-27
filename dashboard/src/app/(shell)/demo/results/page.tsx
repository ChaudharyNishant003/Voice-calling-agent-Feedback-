"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";

import { Badge } from "@/components/ui/badge";
import { buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { demoApi } from "@/lib/demo-api";

const SEVERITY_VARIANT: Record<string, "destructive" | "warning" | "secondary"> = {
  S4: "destructive",
  S3: "destructive",
  S2: "warning",
  S1: "secondary",
  S0: "secondary",
};

export default function DemoResultsPage() {
  const { data: results, isLoading, isError } = useQuery({
    queryKey: ["demo-results"],
    queryFn: () => demoApi.listResults(),
    refetchInterval: 5000,
  });

  return (
    <main className="min-h-screen bg-muted/30 p-6">
      <div className="mx-auto max-w-5xl space-y-6">
        <div className="flex items-center justify-between">
          <h1 className="text-xl font-semibold">Call Results</h1>
          <a href={demoApi.resultsExportCsvUrl()} className={buttonVariants({ variant: "outline" })}>
            Export CSV
          </a>
        </div>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Recent calls</CardTitle>
          </CardHeader>
          <CardContent>
            {isLoading && <p className="text-sm text-muted-foreground">Loading…</p>}
            {isError && <p className="text-sm text-red-700">Couldn&apos;t load results.</p>}
            {results && results.length === 0 && (
              <p className="text-sm text-muted-foreground">No calls yet.</p>
            )}
            {results && results.length > 0 && (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b text-left text-muted-foreground">
                      <th className="py-2 pr-4 font-medium">Started</th>
                      <th className="py-2 pr-4 font-medium">Patient</th>
                      <th className="py-2 pr-4 font-medium">Visit</th>
                      <th className="py-2 pr-4 font-medium">Department</th>
                      <th className="py-2 pr-4 font-medium">Outcome</th>
                      <th className="py-2 pr-4 font-medium">Rating</th>
                      <th className="py-2 pr-4 font-medium">Severity</th>
                      <th className="py-2 pr-4 font-medium">Complaints</th>
                      <th className="py-2 pr-4 font-medium">Escalated</th>
                    </tr>
                  </thead>
                  <tbody>
                    {results.map((r) => (
                      <tr key={r.call_id} className="border-b last:border-0">
                        <td className="py-2 pr-4">
                          <Link
                            href={`/demo/results/${r.call_id}`}
                            className="text-primary underline-offset-4 hover:underline"
                          >
                            {r.started_at ? new Date(r.started_at).toLocaleString() : "—"}
                          </Link>
                        </td>
                        <td className="py-2 pr-4">{r.patient_first_name ?? "—"}</td>
                        <td className="py-2 pr-4">{r.visit_type}</td>
                        <td className="py-2 pr-4">{r.department ?? "—"}</td>
                        <td className="py-2 pr-4">{r.outcome ?? "—"}</td>
                        <td className="py-2 pr-4">{r.rating ?? "—"}</td>
                        <td className="py-2 pr-4">
                          {r.severity_max ? (
                            <Badge variant={SEVERITY_VARIANT[r.severity_max] ?? "secondary"}>
                              {r.severity_max}
                            </Badge>
                          ) : (
                            "—"
                          )}
                        </td>
                        <td className="py-2 pr-4">{r.complaint_count}</td>
                        <td className="py-2 pr-4">
                          {r.escalated ? <Badge variant="destructive">Yes</Badge> : "No"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </main>
  );
}
