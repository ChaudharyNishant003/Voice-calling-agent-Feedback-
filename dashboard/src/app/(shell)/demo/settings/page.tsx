"use client";

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import {
  demoApi,
  DemoApiError,
  type DemoSettings,
  type ProviderStatus,
  type ProviderStatusValue,
} from "@/lib/demo-api";

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

function ProviderCard({ status }: { status: ProviderStatus }) {
  const queryClient = useQueryClient();
  const [apiKey, setApiKey] = useState("");
  const [model, setModel] = useState(status.model ?? status.available_models[0]);

  const mutation = useMutation({
    mutationFn: () => demoApi.saveProviderKey(status.provider, apiKey, model),
    onSuccess: (updated) => {
      queryClient.setQueryData<ProviderStatus[]>(["demo-providers"], (prev) =>
        prev ? prev.map((p) => (p.provider === updated.provider ? updated : p)) : prev,
      );
      setApiKey("");
    },
  });

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0">
        <CardTitle className="text-base capitalize">{status.provider}</CardTitle>
        <Badge variant={STATUS_VARIANT[status.status]}>{STATUS_LABEL[status.status]}</Badge>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="space-y-1">
          <Label htmlFor={`${status.provider}-key`}>API Key</Label>
          <Input
            id={`${status.provider}-key`}
            type="password"
            autoComplete="off"
            placeholder={
              status.model ? "Saved — enter a new key to replace it" : "Paste your API key"
            }
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor={`${status.provider}-model`}>Model</Label>
          <Select
            id={`${status.provider}-model`}
            className="w-56"
            value={model}
            onChange={(e) => setModel(e.target.value)}
          >
            {status.available_models.map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </Select>
        </div>
        <Button onClick={() => mutation.mutate()} disabled={!apiKey.trim() || mutation.isPending}>
          {mutation.isPending ? "Testing…" : "Save & Test"}
        </Button>
        {mutation.isError && (
          <p className="text-sm text-red-700">
            {mutation.error instanceof DemoApiError
              ? mutation.error.message
              : "Couldn't save the key. Please try again."}
          </p>
        )}
        {status.tested_at && (
          <p className="text-xs text-muted-foreground">
            Last tested: {new Date(status.tested_at).toLocaleString()}
          </p>
        )}
      </CardContent>
    </Card>
  );
}

function DemoSettingsCard() {
  const queryClient = useQueryClient();
  const { data: settings } = useQuery({
    queryKey: ["demo-settings"],
    queryFn: () => demoApi.getSettings(),
  });

  const [hospitalName, setHospitalName] = useState("");
  const [agentName, setAgentName] = useState("");
  const [voiceGender, setVoiceGender] = useState<"female" | "male">("female");
  const [hospitalPhone, setHospitalPhone] = useState("");
  const [escalationSlaText, setEscalationSlaText] = useState("");
  const [ttsScript, setTtsScript] = useState<"devanagari" | "roman">("devanagari");
  const [voices, setVoices] = useState<SpeechSynthesisVoice[]>([]);
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    if (settings && !hydrated) {
      setHospitalName(settings.hospital_name);
      setAgentName(settings.agent_name);
      setVoiceGender(settings.voice_gender);
      setHospitalPhone(settings.hospital_phone ?? "");
      setEscalationSlaText(settings.escalation_sla_text ?? "");
      setTtsScript(settings.tts_script);
      setHydrated(true);
    }
  }, [settings, hydrated]);

  useEffect(() => {
    if (typeof window === "undefined" || !("speechSynthesis" in window)) return;
    const load = () => setVoices(window.speechSynthesis.getVoices());
    load();
    window.speechSynthesis.onvoiceschanged = load;
    return () => {
      window.speechSynthesis.onvoiceschanged = null;
    };
  }, []);

  const mutation = useMutation({
    mutationFn: () =>
      demoApi.saveSettings({
        hospital_name: hospitalName,
        agent_name: agentName,
        voice_gender: voiceGender,
        hospital_phone: hospitalPhone || null,
        escalation_sla_text: escalationSlaText || null,
        tts_script: ttsScript,
      }),
    onSuccess: (data) => queryClient.setQueryData<DemoSettings>(["demo-settings"], data),
  });

  const genderHints =
    voiceGender === "female"
      ? ["female", "woman", "zira", "susan", "heera"]
      : ["male", "man", "ravi", "david"];
  const hasGenderMatch = (langPrefix: string) =>
    voices
      .filter((v) => v.lang.toLowerCase().startsWith(langPrefix))
      .some((v) => genderHints.some((hint) => v.name.toLowerCase().includes(hint)));
  const hiMatch = hasGenderMatch("hi");
  const enMatch = hasGenderMatch("en");

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Demo Settings</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1">
            <Label htmlFor="hospital-name">Hospital Name</Label>
            <Input
              id="hospital-name"
              value={hospitalName}
              onChange={(e) => setHospitalName(e.target.value)}
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor="agent-name">Agent Name</Label>
            <Input
              id="agent-name"
              value={agentName}
              onChange={(e) => setAgentName(e.target.value)}
            />
          </div>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1">
            <Label htmlFor="voice-gender">Agent Voice</Label>
            <Select
              id="voice-gender"
              value={voiceGender}
              onChange={(e) => setVoiceGender(e.target.value as "female" | "male")}
            >
              <option value="female">Female</option>
              <option value="male">Male</option>
            </Select>
          </div>
          <div className="space-y-1">
            <Label htmlFor="tts-script">Hindi script for speech</Label>
            <Select
              id="tts-script"
              value={ttsScript}
              onChange={(e) => setTtsScript(e.target.value as "devanagari" | "roman")}
            >
              <option value="devanagari">Devanagari</option>
              <option value="roman">Roman (Hinglish)</option>
            </Select>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1">
            <Label htmlFor="hospital-phone">Hospital phone (optional)</Label>
            <Input
              id="hospital-phone"
              placeholder="For the close-out line, e.g. +91…"
              value={hospitalPhone}
              onChange={(e) => setHospitalPhone(e.target.value)}
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor="escalation-sla">Escalation SLA text (optional)</Label>
            <Input
              id="escalation-sla"
              placeholder="e.g. chaubees ghante"
              value={escalationSlaText}
              onChange={(e) => setEscalationSlaText(e.target.value)}
            />
          </div>
        </div>

        {voices.length > 0 && (
          <div className="space-y-1 rounded-md border bg-muted/40 p-3 text-sm">
            <p className={hiMatch ? "text-green-700" : "text-amber-700"}>
              {hiMatch
                ? `Hindi ${voiceGender} voice available in this browser.`
                : `No ${voiceGender} Hindi voice found in this browser — will fall back to the closest available voice.`}
            </p>
            <p className={enMatch ? "text-green-700" : "text-amber-700"}>
              {enMatch
                ? `English ${voiceGender} voice available in this browser.`
                : `No ${voiceGender} English voice found in this browser — will fall back to the closest available voice.`}
            </p>
          </div>
        )}

        <Button
          onClick={() => mutation.mutate()}
          disabled={mutation.isPending || !hospitalName.trim() || !agentName.trim()}
        >
          {mutation.isPending ? "Saving…" : "Save Settings"}
        </Button>
        {mutation.isSuccess && <p className="text-sm text-green-700">Saved.</p>}
        {mutation.isError && (
          <p className="text-sm text-red-700">
            {mutation.error instanceof DemoApiError
              ? mutation.error.message
              : "Couldn't save settings. Please try again."}
          </p>
        )}
      </CardContent>
    </Card>
  );
}

export default function DemoSettingsPage() {
  const { data: providers, isLoading } = useQuery({
    queryKey: ["demo-providers"],
    queryFn: () => demoApi.listProviders(),
  });

  return (
    <main className="min-h-screen bg-muted/30 p-6">
      <div className="mx-auto max-w-3xl space-y-6">
        <h1 className="text-xl font-semibold">Demo Settings</h1>

        {isLoading && <p className="text-sm text-muted-foreground">Loading…</p>}
        {providers?.map((p) => (
          <ProviderCard key={p.provider} status={p} />
        ))}

        <DemoSettingsCard />
      </div>
    </main>
  );
}
