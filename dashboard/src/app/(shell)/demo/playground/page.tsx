"use client";

import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import {
  demoApi,
  DemoApiError,
  type PlaygroundEndCeilingResult,
  type PlaygroundEndJudgmentResult,
  type PlaygroundLanguageDetectionResult,
  type PlaygroundLanguageLockResult,
  type PlaygroundResponseGenerationResult,
  type PlaygroundTopicExtractionResult,
  type PlaygroundTopicTrackingResult,
  type ProviderName,
  type ProviderStatus,
} from "@/lib/demo-api";

const TOPIC_OPTIONS = [
  "doctor",
  "staff",
  "waiting_time",
  "cleanliness",
  "billing",
  "overall_experience",
];

interface ModelChoice {
  provider: ProviderName;
  model: string;
}

// The <select>'s displayed value falls back to its first <option> when `value` matches nothing —
// so an empty-string `model` LOOKS like a model is selected even though `canRun` (checking
// `!!choice.model`) correctly sees nothing chosen yet. This seeds a real model once the provider
// list loads, without ever overwriting a choice the user already made themselves.
function useDefaultModelChoice(
  providers: ProviderStatus[] | undefined,
  preferredProvider: ProviderName = "gemini",
) {
  const [choice, setChoice] = useState<ModelChoice>({ provider: preferredProvider, model: "" });
  useEffect(() => {
    if (!providers || choice.model) return;
    const status = providers.find((p) => p.provider === choice.provider);
    const defaultModel = status?.model ?? status?.available_models[0];
    if (defaultModel) setChoice((c) => ({ ...c, model: defaultModel }));
  }, [providers, choice.provider, choice.model]);
  return [choice, setChoice] as const;
}

function useStageRunner<TResult>() {
  const [result, setResult] = useState<TResult | null>(null);
  const [isRunning, setIsRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = async (fn: () => Promise<TResult>) => {
    setIsRunning(true);
    setError(null);
    try {
      const r = await fn();
      setResult(r);
    } catch (err) {
      setError(err instanceof DemoApiError ? err.message : "Something went wrong. Please retry.");
    } finally {
      setIsRunning(false);
    }
  };

  return { result, isRunning, error, run };
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex justify-between gap-3 text-sm">
      <span className="text-muted-foreground">{label}</span>
      <span className="text-right font-medium">{children}</span>
    </div>
  );
}

function ModelPicker({
  providers,
  value,
  onChange,
  disabled,
}: {
  providers: ProviderStatus[] | undefined;
  value: ModelChoice;
  onChange: (v: ModelChoice) => void;
  disabled?: boolean;
}) {
  const status = providers?.find((p) => p.provider === value.provider);
  const models = status?.available_models ?? [];
  return (
    <div className="flex gap-2">
      <Select
        className="w-28"
        value={value.provider}
        disabled={disabled}
        onChange={(e) => {
          const provider = e.target.value as ProviderName;
          const newStatus = providers?.find((p) => p.provider === provider);
          onChange({ provider, model: newStatus?.model ?? newStatus?.available_models[0] ?? "" });
        }}
      >
        <option value="gemini">Gemini</option>
        <option value="openai">OpenAI</option>
      </Select>
      <Select
        className="w-48"
        value={value.model}
        disabled={disabled}
        onChange={(e) => onChange({ ...value, model: e.target.value })}
      >
        {models.map((m) => (
          <option key={m} value={m}>
            {m}
          </option>
        ))}
      </Select>
    </div>
  );
}

function StageCard({
  index,
  title,
  description,
  modelPicker,
  onRun,
  canRun,
  cannotRunReason,
  isRunning,
  error,
  input,
  output,
}: {
  index: number;
  title: string;
  description: string;
  modelPicker?: React.ReactNode;
  onRun: () => void;
  canRun: boolean;
  cannotRunReason?: string;
  isRunning: boolean;
  error: string | null;
  input: React.ReactNode;
  output: React.ReactNode | null;
}) {
  return (
    <Card>
      <CardHeader className="space-y-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <CardTitle className="text-base">
            {index}. {title}
          </CardTitle>
          {modelPicker}
        </div>
        <p className="text-sm text-muted-foreground">{description}</p>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="space-y-1 rounded-md border bg-muted/40 p-3">{input}</div>
        <div className="flex items-center gap-3">
          <Button onClick={onRun} disabled={!canRun || isRunning} size="sm">
            {isRunning ? "Running…" : "Run"}
          </Button>
          {!canRun && cannotRunReason && (
            <span className="text-xs text-muted-foreground">{cannotRunReason}</span>
          )}
        </div>
        {error && <p className="rounded-md bg-red-50 p-3 text-sm text-red-800">{error}</p>}
        {output && <div className="space-y-1 rounded-md border bg-background p-3">{output}</div>}
      </CardContent>
    </Card>
  );
}

export default function PlaygroundPage() {
  const { data: providers } = useQuery({
    queryKey: ["demo-providers"],
    queryFn: () => demoApi.listProviders(),
  });

  // Shared scenario — what the conversation looked like *before* this hypothetical turn.
  const [patientText, setPatientText] = useState("");
  const [priorLockedLanguage, setPriorLockedLanguage] = useState<string>("");
  const [priorStreak, setPriorStreak] = useState(0);
  const [priorTopicsCovered, setPriorTopicsCovered] = useState<string[]>([]);
  const [turnCount, setTurnCount] = useState(1);

  const toggleTopic = (topic: string, list: string[], setList: (v: string[]) => void) => {
    setList(list.includes(topic) ? list.filter((t) => t !== topic) : [...list, topic]);
  };

  const [s1Choice, setS1Choice] = useDefaultModelChoice(providers);
  const s1 = useStageRunner<PlaygroundLanguageDetectionResult>();

  const [s2Choice, setS2Choice] = useDefaultModelChoice(providers);
  const s2 = useStageRunner<PlaygroundTopicExtractionResult>();

  const s3 = useStageRunner<PlaygroundLanguageLockResult>();
  const s4 = useStageRunner<PlaygroundTopicTrackingResult>();

  const [s5Choice, setS5Choice] = useDefaultModelChoice(providers);
  const s5 = useStageRunner<PlaygroundEndJudgmentResult>();

  const [s6ManualEnd, setS6ManualEnd] = useState(false);
  const s6 = useStageRunner<PlaygroundEndCeilingResult>();

  const [s7Choice, setS7Choice] = useDefaultModelChoice(providers);
  const s7 = useStageRunner<PlaygroundResponseGenerationResult>();

  const topicsForStage5and7 = s4.result?.topics_covered ?? priorTopicsCovered;
  const lockedLanguageForStage7 = s3.result?.locked_language ?? (priorLockedLanguage || null);
  const isEndingForStage7 = s6.result?.ends ?? false;
  const llmWantsToEndForStage6 = s5.result ? s5.result.wants_to_end : s6ManualEnd;

  const hasPatientText = patientText.trim().length > 0;

  return (
    <main className="min-h-screen bg-muted/30 p-6">
      <div className="mx-auto max-w-3xl space-y-6">
        <div>
          <h1 className="text-xl font-semibold">Pipeline Playground</h1>
          <p className="text-sm text-muted-foreground">
            Run each stage of the conversation engine by hand, on sample input, with any model —
            separate from the live demo call. Nothing here changes what the real call uses.
          </p>
        </div>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Sample scenario</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-1">
              <Label htmlFor="patient-text">Patient&apos;s message (this turn)</Label>
              <Input
                id="patient-text"
                placeholder="e.g. Overall theek tha lekin waiting bahut zyada thi"
                value={patientText}
                onChange={(e) => setPatientText(e.target.value)}
              />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <Label htmlFor="prior-locked">Prior locked language</Label>
                <Select
                  id="prior-locked"
                  value={priorLockedLanguage}
                  onChange={(e) => setPriorLockedLanguage(e.target.value)}
                >
                  <option value="">None (first turn)</option>
                  <option value="hindi_hinglish">Hindi/Hinglish</option>
                  <option value="english">English</option>
                </Select>
              </div>
              <div className="space-y-1">
                <Label htmlFor="turn-count">Turn number (this message)</Label>
                <Input
                  id="turn-count"
                  type="number"
                  min={1}
                  value={turnCount}
                  onChange={(e) => setTurnCount(Number(e.target.value) || 1)}
                />
              </div>
            </div>
            {priorLockedLanguage && (
              <div className="space-y-1">
                <Label htmlFor="prior-streak">
                  Prior consecutive off-family turns (0-2, only relevant with a locked language)
                </Label>
                <Input
                  id="prior-streak"
                  type="number"
                  min={0}
                  max={2}
                  value={priorStreak}
                  onChange={(e) => setPriorStreak(Number(e.target.value) || 0)}
                />
              </div>
            )}
            <div className="space-y-1">
              <Label>Topics already covered before this turn</Label>
              <div className="flex flex-wrap gap-3">
                {TOPIC_OPTIONS.map((topic) => (
                  <label key={topic} className="flex items-center gap-1.5 text-sm">
                    <input
                      type="checkbox"
                      checked={priorTopicsCovered.includes(topic)}
                      onChange={() =>
                        toggleTopic(topic, priorTopicsCovered, setPriorTopicsCovered)
                      }
                    />
                    {topic}
                  </label>
                ))}
              </div>
            </div>
          </CardContent>
        </Card>

        <StageCard
          index={1}
          title="Language Detection"
          description="Which language family the patient's message is in, and whether they explicitly asked to switch."
          modelPicker={<ModelPicker providers={providers} value={s1Choice} onChange={setS1Choice} />}
          onRun={() =>
            s1.run(() =>
              demoApi.playgroundLanguageDetection(s1Choice.provider, s1Choice.model, patientText),
            )
          }
          canRun={hasPatientText && !!s1Choice.model}
          cannotRunReason={!hasPatientText ? "Type a patient message above first." : undefined}
          isRunning={s1.isRunning}
          error={s1.error}
          input={<Field label="Patient text">{patientText || "—"}</Field>}
          output={
            s1.result && (
              <>
                <Field label="Detected language">{s1.result.detected_language}</Field>
                <Field label="Requested language">{s1.result.requested_language ?? "none"}</Field>
                <Field label="Latency">{s1.result.latency_ms} ms</Field>
                <Field label="Tokens">
                  {s1.result.input_tokens} in / {s1.result.output_tokens} out
                </Field>
              </>
            )
          }
        />

        <StageCard
          index={2}
          title="Topic Extraction"
          description="Which feedback topics (if any) the patient's message touches on."
          modelPicker={<ModelPicker providers={providers} value={s2Choice} onChange={setS2Choice} />}
          onRun={() =>
            s2.run(() =>
              demoApi.playgroundTopicExtraction(s2Choice.provider, s2Choice.model, patientText),
            )
          }
          canRun={hasPatientText && !!s2Choice.model}
          cannotRunReason={!hasPatientText ? "Type a patient message above first." : undefined}
          isRunning={s2.isRunning}
          error={s2.error}
          input={<Field label="Patient text">{patientText || "—"}</Field>}
          output={
            s2.result && (
              <>
                <Field label="Topics">{s2.result.topics.join(", ") || "none"}</Field>
                <Field label="Latency">{s2.result.latency_ms} ms</Field>
                <Field label="Tokens">
                  {s2.result.input_tokens} in / {s2.result.output_tokens} out
                </Field>
              </>
            )
          }
        />

        <StageCard
          index={3}
          title="Language Lock Decision"
          description="Deterministic — no model. Hindi/Hinglish count as one family; a real switch needs 3 consecutive off-family turns, or an explicit request."
          onRun={() =>
            s3.run(() =>
              demoApi.playgroundLanguageLock({
                detectedLanguage: s1.result!.detected_language,
                requestedLanguage: s1.result!.requested_language,
                priorLockedLanguage: priorLockedLanguage || null,
                priorStreak,
              }),
            )
          }
          canRun={s1.result !== null}
          cannotRunReason={s1.result === null ? "Run Language Detection first." : undefined}
          isRunning={s3.isRunning}
          error={s3.error}
          input={
            <>
              <Field label="Detected language">{s1.result?.detected_language ?? "—"}</Field>
              <Field label="Requested language">{s1.result?.requested_language ?? "none"}</Field>
              <Field label="Prior locked language">{priorLockedLanguage || "none"}</Field>
              <Field label="Prior streak">{priorStreak}</Field>
            </>
          }
          output={
            s3.result && (
              <>
                <Field label="Locked language">{s3.result.locked_language ?? "none"}</Field>
                <Field label="Consecutive other-family count">
                  {s3.result.consecutive_other_count}
                </Field>
                <Field label="Switched this turn">{s3.result.switched ? "yes" : "no"}</Field>
              </>
            )
          }
        />

        <StageCard
          index={4}
          title="Topic Tracking Update"
          description="Deterministic — no model. Merges this turn's topics into what's been covered so far."
          onRun={() =>
            s4.run(() =>
              demoApi.playgroundTopicTracking(s2.result!.topics, priorTopicsCovered),
            )
          }
          canRun={s2.result !== null}
          cannotRunReason={s2.result === null ? "Run Topic Extraction first." : undefined}
          isRunning={s4.isRunning}
          error={s4.error}
          input={
            <>
              <Field label="Topics mentioned">{s2.result?.topics.join(", ") || "none"}</Field>
              <Field label="Prior topics covered">{priorTopicsCovered.join(", ") || "none"}</Field>
            </>
          }
          output={
            s4.result && (
              <Field label="Topics covered">{s4.result.topics_covered.join(", ") || "none"}</Field>
            )
          }
        />

        <StageCard
          index={5}
          title="Should-End Judgment"
          description="Has enough useful feedback been collected to close the call now?"
          modelPicker={<ModelPicker providers={providers} value={s5Choice} onChange={setS5Choice} />}
          onRun={() =>
            s5.run(() =>
              demoApi.playgroundEndJudgment({
                provider: s5Choice.provider,
                model: s5Choice.model,
                patientText,
                topicsCovered: topicsForStage5and7,
                turnCount,
              }),
            )
          }
          canRun={hasPatientText && !!s5Choice.model}
          cannotRunReason={!hasPatientText ? "Type a patient message above first." : undefined}
          isRunning={s5.isRunning}
          error={s5.error}
          input={
            <>
              <Field label="Patient text">{patientText || "—"}</Field>
              <Field label="Topics covered">{topicsForStage5and7.join(", ") || "none"}</Field>
              <Field label="Turn number">{turnCount}</Field>
            </>
          }
          output={
            s5.result && (
              <>
                <Field label="Wants to end">{s5.result.wants_to_end ? "yes" : "no"}</Field>
                <Field label="Summary">{s5.result.summary ?? "—"}</Field>
                <Field label="Latency">{s5.result.latency_ms} ms</Field>
                <Field label="Tokens">
                  {s5.result.input_tokens} in / {s5.result.output_tokens} out
                </Field>
              </>
            )
          }
        />

        <StageCard
          index={6}
          title="End-of-Call Ceiling"
          description="Deterministic — no model. Forces the call to continue below turn 3, and to end at turn 8 regardless of what the model in step 5 said."
          onRun={() =>
            s6.run(() =>
              demoApi.playgroundEndCeiling(turnCount, llmWantsToEndForStage6),
            )
          }
          canRun={true}
          isRunning={s6.isRunning}
          error={s6.error}
          input={
            <>
              <Field label="Turn number">{turnCount}</Field>
              <Field label="Model wanted to end (step 5)">
                {s5.result ? (
                  s5.result.wants_to_end ? "yes" : "no"
                ) : (
                  <label className="flex items-center gap-1.5">
                    <input
                      type="checkbox"
                      checked={s6ManualEnd}
                      onChange={(e) => setS6ManualEnd(e.target.checked)}
                    />
                    not run — set manually
                  </label>
                )}
              </Field>
            </>
          }
          output={s6.result && <Field label="Call ends">{s6.result.ends ? "yes" : "no"}</Field>}
        />

        <StageCard
          index={7}
          title="Response Generation"
          description="The actual reply text, given everything already decided above."
          modelPicker={<ModelPicker providers={providers} value={s7Choice} onChange={setS7Choice} />}
          onRun={() =>
            s7.run(() =>
              demoApi.playgroundResponseGeneration({
                provider: s7Choice.provider,
                model: s7Choice.model,
                patientText,
                lockedLanguage: lockedLanguageForStage7,
                topicsCovered: topicsForStage5and7,
                isEnding: isEndingForStage7,
              }),
            )
          }
          canRun={hasPatientText && !!s7Choice.model}
          cannotRunReason={!hasPatientText ? "Type a patient message above first." : undefined}
          isRunning={s7.isRunning}
          error={s7.error}
          input={
            <>
              <Field label="Patient text">{patientText || "—"}</Field>
              <Field label="Locked language">{lockedLanguageForStage7 ?? "none"}</Field>
              <Field label="Topics covered">{topicsForStage5and7.join(", ") || "none"}</Field>
              <Field label="Is closing turn">{isEndingForStage7 ? "yes" : "no"}</Field>
            </>
          }
          output={
            s7.result && (
              <>
                <Field label="Response">{s7.result.response}</Field>
                <Field label="Next action">{s7.result.next_action}</Field>
                <Field label="Latency">{s7.result.latency_ms} ms</Field>
                <Field label="Tokens">
                  {s7.result.input_tokens} in / {s7.result.output_tokens} out
                </Field>
              </>
            )
          }
        />
      </div>
    </main>
  );
}
