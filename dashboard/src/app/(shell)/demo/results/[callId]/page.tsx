"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { demoApi } from "@/lib/demo-api";

function field(obj: Record<string, unknown>, key: string): string {
  const value = obj[key];
  if (value === null || value === undefined || value === "") return "—";
  return typeof value === "string" ? value : JSON.stringify(value);
}

// Next.js 14 App Router passes `params` as a plain object, not a Promise — no React `use()` here
// (that's a Next 15 pattern; this project pins Next 14.2.35, confirmed by the runtime error it
// throws when `use()` is called on a non-Promise, non-Context value).
export default function DemoResultDetailPage({ params }: { params: { callId: string } }) {
  const { callId } = params;

  const { data: detail, isLoading, isError } = useQuery({
    queryKey: ["demo-result-detail", callId],
    queryFn: () => demoApi.getResultDetail(callId),
  });

  return (
    <main className="min-h-screen bg-muted/30 p-6">
      <div className="mx-auto max-w-3xl space-y-6">
        <div className="flex items-center justify-between">
          <h1 className="text-xl font-semibold">Call Result</h1>
          <Link
            href="/demo/results"
            className="text-sm text-primary underline-offset-4 hover:underline"
          >
            ← Back to results
          </Link>
        </div>

        {isLoading && <p className="text-sm text-muted-foreground">Loading…</p>}
        {isError && <p className="text-sm text-red-700">Couldn&apos;t load this result.</p>}

        {detail && (
          <>
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Summary</CardTitle>
              </CardHeader>
              <CardContent className="grid grid-cols-2 gap-3 text-sm">
                <div>
                  <p className="text-muted-foreground">Patient</p>
                  <p>{detail.patient_first_name ?? "—"}</p>
                </div>
                <div>
                  <p className="text-muted-foreground">Visit</p>
                  <p>
                    {detail.visit_type} · {detail.visit_date}
                  </p>
                </div>
                <div>
                  <p className="text-muted-foreground">Department</p>
                  <p>{detail.department ?? "—"}</p>
                </div>
                <div>
                  <p className="text-muted-foreground">Doctor</p>
                  <p>{detail.doctor_name ?? "—"}</p>
                </div>
                <div>
                  <p className="text-muted-foreground">Outcome</p>
                  <p>{detail.outcome ?? "—"}</p>
                </div>
                <div>
                  <p className="text-muted-foreground">Rating</p>
                  <p>
                    {detail.rating ?? "—"}
                    {detail.rating_inferred ? " (inferred)" : ""}
                  </p>
                </div>
                <div>
                  <p className="text-muted-foreground">Respondent</p>
                  <p>{detail.respondent_type}</p>
                </div>
                <div>
                  <p className="text-muted-foreground">Language</p>
                  <p>{detail.language_mode ?? "—"}</p>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className="text-base">Topics ({detail.topics.length})</CardTitle>
              </CardHeader>
              <CardContent className="space-y-2">
                {detail.topics.length === 0 && (
                  <p className="text-sm text-muted-foreground">No topics recorded.</p>
                )}
                {detail.topics.map((t, i) => (
                  <div key={i} className="rounded-md border p-3 text-sm">
                    <div className="flex items-center gap-2">
                      <Badge variant="secondary">{field(t, "category")}</Badge>
                      <Badge
                        variant={
                          field(t, "sentiment") === "negative"
                            ? "destructive"
                            : field(t, "sentiment") === "positive"
                              ? "success"
                              : "secondary"
                        }
                      >
                        {field(t, "sentiment")}
                      </Badge>
                    </div>
                    <p className="mt-1 text-muted-foreground">&ldquo;{field(t, "verbatim")}&rdquo;</p>
                  </div>
                ))}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className="text-base">
                  Complaints ({detail.complaints.length})
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-2">
                {detail.complaints.length === 0 && (
                  <p className="text-sm text-muted-foreground">No complaints recorded.</p>
                )}
                {detail.complaints.map((c, i) => (
                  <div key={i} className="rounded-md border p-3 text-sm">
                    <div className="flex items-center gap-2">
                      <Badge variant="secondary">{field(c, "category")}</Badge>
                      {field(c, "severity") !== "—" && (
                        <Badge variant="destructive">{field(c, "severity")}</Badge>
                      )}
                    </div>
                    <p className="mt-1">{field(c, "description")}</p>
                    <p className="mt-1 text-xs text-muted-foreground">
                      When: {field(c, "when_text")} · Where: {field(c, "where_text")} · Wants
                      contact: {field(c, "wants_contact")}
                    </p>
                  </div>
                ))}
              </CardContent>
            </Card>

            {detail.escalations.length > 0 && (
              <Card>
                <CardHeader>
                  <CardTitle className="text-base">
                    Escalations ({detail.escalations.length})
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-2">
                  {detail.escalations.map((e, i) => (
                    <div
                      key={i}
                      className="rounded-md border border-red-300 bg-red-50 p-3 text-sm text-red-900"
                    >
                      <Badge variant="destructive">{field(e, "severity")}</Badge>{" "}
                      {field(e, "category")} — triggered by {field(e, "triggered_by")}
                    </div>
                  ))}
                </CardContent>
              </Card>
            )}

            <Card>
              <CardHeader>
                <CardTitle className="text-base">Transcript</CardTitle>
              </CardHeader>
              <CardContent className="max-h-96 space-y-2 overflow-y-auto">
                {detail.transcript.map((line, i) => (
                  <div key={i} className={line.speaker === "agent" ? "text-left" : "text-right"}>
                    <span
                      className={
                        line.speaker === "agent"
                          ? "inline-block max-w-[85%] rounded-lg bg-secondary px-3 py-2 text-sm"
                          : "inline-block max-w-[85%] rounded-lg bg-primary px-3 py-2 text-sm text-primary-foreground"
                      }
                    >
                      {line.text}
                    </span>
                  </div>
                ))}
              </CardContent>
            </Card>
          </>
        )}
      </div>
    </main>
  );
}
