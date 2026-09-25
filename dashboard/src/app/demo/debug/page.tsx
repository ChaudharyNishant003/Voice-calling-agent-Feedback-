"use client";

import Link from "next/link";
import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { demoApi, type TimelineEvent } from "@/lib/demo-api";

const ERROR_TYPES = new Set(["ERROR"]);

function fieldsOf(data: Record<string, unknown>): Array<[string, unknown]> {
  return Object.entries(data).filter(([, v]) => v !== null && v !== undefined && v !== "");
}

function EventRow({ event }: { event: TimelineEvent }) {
  const [expanded, setExpanded] = useState(false);
  const isError = ERROR_TYPES.has(event.type);
  const fields = fieldsOf(event.data);

  return (
    <div
      className={`rounded-md border p-3 text-sm ${isError ? "border-red-300 bg-red-50 text-red-950" : "bg-background"}`}
    >
      <button
        type="button"
        className="flex w-full items-center justify-between gap-2 text-left"
        onClick={() => setExpanded((v) => !v)}
      >
        <span className="flex items-center gap-2">
          <Badge variant={isError ? "destructive" : "secondary"}>{event.type}</Badge>
          <span className={isError ? "text-red-800" : "text-muted-foreground"}>
            {new Date(event.ts).toLocaleTimeString()}
          </span>
        </span>
        <span className={`text-xs ${isError ? "text-red-800" : "text-muted-foreground"}`}>
          {expanded ? "Hide" : "Show"} details
        </span>
      </button>
      {expanded && fields.length > 0 && (
        <dl className="mt-2 space-y-1 border-t pt-2">
          {fields.map(([key, value]) => (
            <div key={key} className="flex gap-2">
              <dt className={`w-32 shrink-0 font-medium ${isError ? "text-red-800" : "text-muted-foreground"}`}>
                {key}
              </dt>
              <dd className="break-all">
                {typeof value === "string" ? value : JSON.stringify(value)}
              </dd>
            </div>
          ))}
        </dl>
      )}
    </div>
  );
}

function DebugContent() {
  const searchParams = useSearchParams();
  const [callIdInput, setCallIdInput] = useState(searchParams.get("call_id") ?? "");
  const callId = searchParams.get("call_id") ?? callIdInput;

  const { data: events, isLoading, isError } = useQuery({
    queryKey: ["demo-events", callId],
    queryFn: () => demoApi.getEvents(callId),
    enabled: !!callId,
    refetchInterval: 3000,
  });

  const failedStep = events?.find((e) => ERROR_TYPES.has(e.type));
  const lastEvent = events?.[events.length - 1];

  return (
    <main className="min-h-screen bg-muted/30 p-6">
      <div className="mx-auto max-w-3xl space-y-6">
        <div className="flex items-center justify-between">
          <h1 className="text-xl font-semibold">Call Debug Timeline</h1>
          <Link href="/demo" className="text-sm text-primary underline-offset-4 hover:underline">
            Back to Call
          </Link>
        </div>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Call ID</CardTitle>
          </CardHeader>
          <CardContent className="flex gap-2">
            <Input
              placeholder="Paste a call ID to inspect"
              value={callIdInput}
              onChange={(e) => setCallIdInput(e.target.value)}
            />
          </CardContent>
        </Card>

        {callId && (
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0">
              <CardTitle className="text-base">Status</CardTitle>
              {failedStep ? (
                <Badge variant="destructive">Failed at {failedStep.type}</Badge>
              ) : lastEvent?.type === "CALL_ENDED" ? (
                <Badge variant="success">Completed</Badge>
              ) : (
                <Badge variant="secondary">In progress</Badge>
              )}
            </CardHeader>
            <CardContent className="space-y-1 text-sm text-muted-foreground">
              <p>Call ID: {callId}</p>
              {lastEvent && <p>Last event: {lastEvent.type}</p>}
              {isLoading && <p>Loading events…</p>}
              {isError && <p className="text-red-700">Couldn&apos;t load events for this call.</p>}
            </CardContent>
          </Card>
        )}

        {callId && (
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Event Timeline</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              {events && events.length === 0 && (
                <p className="text-sm text-muted-foreground">No events yet.</p>
              )}
              {events?.map((event) => (
                <EventRow key={event.event_id} event={event} />
              ))}
            </CardContent>
          </Card>
        )}
      </div>
    </main>
  );
}

export default function DemoDebugPage() {
  return (
    <Suspense fallback={null}>
      <DebugContent />
    </Suspense>
  );
}
