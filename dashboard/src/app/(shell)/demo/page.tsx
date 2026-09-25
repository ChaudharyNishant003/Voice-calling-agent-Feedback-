"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { demoApi, type ProviderName, type ProviderStatusValue } from "@/lib/demo-api";
import { useTurnController } from "@/hooks/useTurnController";

const STATUS_VARIANT: Record<ProviderStatusValue, "success" | "warning" | "destructive" | "secondary"> = {
  connected: "success",
  testing: "warning",
  not_configured: "secondary",
  invalid: "destructive",
  error: "destructive",
};

const STATUS_LABEL: Record<ProviderStatusValue, string> = {
  connected: "Connected",
  testing: "Testing",
  not_configured: "Not Configured",
  invalid: "Invalid",
  error: "Error",
};

function PhaseLabel({ phase }: { phase: string }) {
  const labels: Record<string, string> = {
    idle: "Ready to start",
    starting: "Starting call…",
    agent_greeting: "Agent is greeting…",
    listening: "Listening…",
    processing: "Thinking…",
    agent_speaking: "Agent is speaking…",
    ending: "Ending call…",
    ended: "Call ended",
  };
  return <span>{labels[phase] ?? phase}</span>;
}

export default function DemoCallPage() {
  const { data: providers } = useQuery({
    queryKey: ["demo-providers"],
    queryFn: () => demoApi.listProviders(),
  });

  const [provider, setProvider] = useState<ProviderName>("gemini");
  const [manualText, setManualText] = useState("");
  const transcriptEndRef = useRef<HTMLDivElement | null>(null);

  const {
    phase,
    callId,
    transcript,
    lockedLanguage,
    topics,
    summary,
    error,
    micSupported,
    ttsSupported,
    startCall,
    submitManualText,
    endCall,
    reset,
  } = useTurnController();

  useEffect(() => {
    transcriptEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [transcript]);

  const selectedStatus = providers?.find((p) => p.provider === provider);
  const isActive = !["idle", "ended"].includes(phase);
  const canListen = phase === "listening";

  return (
    <main className="min-h-screen bg-muted/30 p-6">
      <div className="mx-auto max-w-3xl space-y-6">
        <h1 className="text-xl font-semibold">Patient Feedback Voice Demo</h1>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Start a demo call</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-wrap items-center gap-3">
            <div className="w-40">
              <Select
                value={provider}
                disabled={isActive}
                onChange={(e) => setProvider(e.target.value as ProviderName)}
              >
                <option value="gemini">Gemini</option>
                <option value="openai">OpenAI</option>
              </Select>
            </div>
            {selectedStatus && (
              <Badge variant={STATUS_VARIANT[selectedStatus.status]}>
                {STATUS_LABEL[selectedStatus.status]}
                {selectedStatus.model ? ` · ${selectedStatus.model}` : ""}
              </Badge>
            )}
            {phase === "idle" ? (
              <Button
                onClick={() => startCall(provider)}
                disabled={!selectedStatus || selectedStatus.status !== "connected"}
              >
                Start Demo Call
              </Button>
            ) : phase === "ended" ? (
              <Button variant="outline" onClick={reset}>
                Start Another Call
              </Button>
            ) : (
              <Button variant="destructive" onClick={endCall}>
                End Call
              </Button>
            )}
            {selectedStatus && selectedStatus.status !== "connected" && (
              <span className="text-sm text-muted-foreground">
                Configure this provider in Settings first.
              </span>
            )}
          </CardContent>
        </Card>

        {(isActive || phase === "ended") && (
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0">
              <CardTitle className="text-base">
                <PhaseLabel phase={phase} />
              </CardTitle>
              <div className="flex items-center gap-2 text-xs text-muted-foreground">
                {lockedLanguage && <Badge variant="secondary">Language: {lockedLanguage}</Badge>}
                {topics.length > 0 && <Badge variant="secondary">Topics: {topics.join(", ")}</Badge>}
                {callId && (
                  <Link
                    href={`/demo/debug?call_id=${callId}`}
                    className="text-primary underline-offset-4 hover:underline"
                  >
                    View full debug timeline
                  </Link>
                )}
              </div>
            </CardHeader>
            <CardContent className="space-y-4">
              {!micSupported && (
                <p className="rounded-md bg-amber-50 p-3 text-sm text-amber-800">
                  Speech recognition isn&apos;t available in this browser. Use the text box below
                  instead — it goes through the exact same conversation engine.
                </p>
              )}
              {!ttsSupported && (
                <p className="rounded-md bg-amber-50 p-3 text-sm text-amber-800">
                  Speech synthesis isn&apos;t available — replies will show as text only.
                </p>
              )}
              {error && <p className="rounded-md bg-red-50 p-3 text-sm text-red-800">{error}</p>}

              <div className="max-h-96 space-y-3 overflow-y-auto rounded-md border bg-background p-4">
                {transcript.map((line, i) => (
                  <div
                    key={i}
                    className={line.speaker === "agent" ? "text-left" : "text-right"}
                  >
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
                <div ref={transcriptEndRef} />
              </div>

              {summary && (
                <p className="rounded-md bg-green-50 p-3 text-sm text-green-800">
                  <strong>Summary:</strong> {summary}
                </p>
              )}

              {phase !== "ended" && (
                <form
                  className="flex gap-2"
                  onSubmit={(e) => {
                    e.preventDefault();
                    const text = manualText;
                    setManualText("");
                    void submitManualText(provider, text);
                  }}
                >
                  <Input
                    placeholder={
                      canListen ? "Or type your reply here…" : "Waiting for the agent…"
                    }
                    value={manualText}
                    onChange={(e) => setManualText(e.target.value)}
                    disabled={phase === "processing" || phase === "agent_speaking"}
                  />
                  <Button
                    type="submit"
                    variant="outline"
                    disabled={!manualText.trim() || phase === "processing" || phase === "agent_speaking"}
                  >
                    Send
                  </Button>
                </form>
              )}
            </CardContent>
          </Card>
        )}
      </div>
    </main>
  );
}
