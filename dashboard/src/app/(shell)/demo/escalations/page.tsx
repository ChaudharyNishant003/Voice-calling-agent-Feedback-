"use client";

import Link from "next/link";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { demoApi, type Escalation } from "@/lib/demo-api";

function AckButton({ escalation }: { escalation: Escalation }) {
  const queryClient = useQueryClient();
  const mutation = useMutation({
    mutationFn: () => demoApi.acknowledgeEscalation(escalation.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["demo-escalations"] });
    },
  });

  if (escalation.status !== "open") {
    return <Badge variant="secondary">{escalation.status}</Badge>;
  }
  return (
    <Button size="sm" onClick={() => mutation.mutate()} disabled={mutation.isPending}>
      {mutation.isPending ? "Acknowledging…" : "Acknowledge"}
    </Button>
  );
}

export default function DemoEscalationsPage() {
  const [statusFilter, setStatusFilter] = useState<"open" | "all">("open");

  const { data: escalations, isLoading, isError } = useQuery({
    queryKey: ["demo-escalations", statusFilter],
    queryFn: () => demoApi.listEscalations(statusFilter === "open" ? "open" : undefined),
    refetchInterval: 5000,
  });

  return (
    <main className="min-h-screen bg-muted/30 p-6">
      <div className="mx-auto max-w-4xl space-y-6">
        <h1 className="text-xl font-semibold">Escalations Queue</h1>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0">
            <CardTitle className="text-base">
              {statusFilter === "open" ? "Open escalations" : "All escalations"}
            </CardTitle>
            <div className="flex gap-2">
              <Button
                size="sm"
                variant={statusFilter === "open" ? "default" : "outline"}
                onClick={() => setStatusFilter("open")}
              >
                Open
              </Button>
              <Button
                size="sm"
                variant={statusFilter === "all" ? "default" : "outline"}
                onClick={() => setStatusFilter("all")}
              >
                All
              </Button>
            </div>
          </CardHeader>
          <CardContent className="space-y-2">
            {isLoading && <p className="text-sm text-muted-foreground">Loading…</p>}
            {isError && <p className="text-sm text-red-700">Couldn&apos;t load escalations.</p>}
            {escalations && escalations.length === 0 && (
              <p className="text-sm text-muted-foreground">Nothing here.</p>
            )}
            {escalations?.map((e) => (
              <div
                key={e.id}
                className={`flex items-center justify-between rounded-md border p-3 text-sm ${
                  e.type === "urgent" ? "border-red-300 bg-red-50" : "bg-background"
                }`}
              >
                <div className="space-y-1">
                  <div className="flex items-center gap-2">
                    <Badge variant={e.type === "urgent" ? "destructive" : "warning"}>
                      {e.type}
                    </Badge>
                    <span className="font-medium">{e.category}</span>
                    <span className="text-xs text-muted-foreground">
                      triggered by {e.triggered_by}
                    </span>
                  </div>
                  <p className="text-xs text-muted-foreground">
                    {new Date(e.created_at).toLocaleString()} ·{" "}
                    <Link
                      href={`/demo/results/${e.call_id}`}
                      className="text-primary underline-offset-4 hover:underline"
                    >
                      View call
                    </Link>
                  </p>
                </div>
                <AckButton escalation={e} />
              </div>
            ))}
          </CardContent>
        </Card>
      </div>
    </main>
  );
}
