"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import {
  demoApi,
  type ProviderName,
  type ProviderStatusValue,
  type VisitType,
} from "@/lib/demo-api";
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

const NODE_LABEL: Record<string, string> = {
  open_and_identify: "Confirming identity",
  caregiver: "Talking to caregiver",
  purpose_consent_time: "Asking consent",
  open_experience: "Open question",
  overall_rating: "Rating",
  probe_topics: "Probing topics",
  complaint_detail: "Complaint detail",
  severity_gate: "Assessing severity",
  anything_else: "Anything else?",
  readback_and_next_steps: "Reading back",
  close: "Closing",
  callback: "Scheduling callback",
  opt_out: "Opted out",
  close_wrong: "Wrong number",
  escalate_standard: "Escalating (standard)",
  escalate_urgent: "Escalating (urgent)",
};

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

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

  // Patient & visit form (PRD v2 §11).
  const [patientFirstName, setPatientFirstName] = useState("Ramesh");
  const [patientPhone, setPatientPhone] = useState("");
  const [visitType, setVisitType] = useState<VisitType>("OPD");
  const [visitDate, setVisitDate] = useState(todayIso());
  const [department, setDepartment] = useState("");
  const [doctorName, setDoctorName] = useState("");

  const {
    phase,
    callId,
    transcript,
    node,
    callOutcome,
    escalated,
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
          <CardContent className="space-y-4">
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <Label htmlFor="patient-first-name">Patient first name *</Label>
                <Input
                  id="patient-first-name"
                  value={patientFirstName}
                  disabled={isActive}
                  onChange={(e) => setPatientFirstName(e.target.value)}
                />
              </div>
              <div className="space-y-1">
                <Label htmlFor="patient-phone">Phone (optional)</Label>
                <Input
                  id="patient-phone"
                  placeholder="+91…"
                  value={patientPhone}
                  disabled={isActive}
                  onChange={(e) => setPatientPhone(e.target.value)}
                />
              </div>
              <div className="space-y-1">
                <Label htmlFor="visit-type">Visit type *</Label>
                <Select
                  id="visit-type"
                  value={visitType}
                  disabled={isActive}
                  onChange={(e) => setVisitType(e.target.value as VisitType)}
                >
                  <option value="OPD">OPD</option>
                  <option value="IPD">IPD</option>
                  <option value="DIAGNOSTICS">Diagnostics</option>
                  <option value="EMERGENCY">Emergency</option>
                </Select>
              </div>
              <div className="space-y-1">
                <Label htmlFor="visit-date">Visit date *</Label>
                <Input
                  id="visit-date"
                  type="date"
                  value={visitDate}
                  disabled={isActive}
                  onChange={(e) => setVisitDate(e.target.value)}
                />
              </div>
              <div className="space-y-1">
                <Label htmlFor="department">Department (optional)</Label>
                <Input
                  id="department"
                  value={department}
                  disabled={isActive}
                  onChange={(e) => setDepartment(e.target.value)}
                />
              </div>
              <div className="space-y-1">
                <Label htmlFor="doctor-name">Doctor name (optional)</Label>
                <Input
                  id="doctor-name"
                  value={doctorName}
                  disabled={isActive}
                  onChange={(e) => setDoctorName(e.target.value)}
                />
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-3">
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
                  onClick={() =>
                    startCall({
                      provider,
                      patient_first_name: patientFirstName,
                      patient_phone: patientPhone || null,
                      visit_type: visitType,
                      visit_date: visitDate,
                      department: department || null,
                      doctor_name: doctorName || null,
                    })
                  }
                  disabled={
                    !selectedStatus ||
                    selectedStatus.status !== "connected" ||
                    !patientFirstName.trim()
                  }
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
            </div>
          </CardContent>
        </Card>

        {(isActive || phase === "ended") && (
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0">
              <CardTitle className="text-base">
                <PhaseLabel phase={phase} />
              </CardTitle>
              <div className="flex items-center gap-2 text-xs text-muted-foreground">
                {node && <Badge variant="secondary">{NODE_LABEL[node] ?? node}</Badge>}
                {callOutcome && <Badge variant="secondary">Outcome: {callOutcome}</Badge>}
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
              {escalated && (
                <p className="rounded-md border border-red-300 bg-red-50 p-3 text-sm font-medium text-red-900">
                  ⚠ This call has been escalated. Check the escalations queue.
                </p>
              )}
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

              {phase === "ended" && callId && (
                <p className="rounded-md bg-green-50 p-3 text-sm text-green-800">
                  <Link href={`/demo/results/${callId}`} className="underline underline-offset-4">
                    View the structured result for this call
                  </Link>
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
