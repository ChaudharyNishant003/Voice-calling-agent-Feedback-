"use client";

/**
 * Browser voice turn controller (PRD v2 §11) — the sequential state machine driving the mic (Web
 * Speech API SpeechRecognition) and speaker (SpeechSynthesis). Chrome desktop only, per spec —
 * this deliberately doesn't try to be cross-browser.
 *
 * IDLE -> STARTING -> AGENT_GREETING -> LISTENING -> PROCESSING -> AGENT_SPEAKING -> LISTENING ->
 * ... -> ENDING -> ENDED
 *
 * While AGENT_SPEAKING, listening is disabled; it re-enables once speech ends. Only the final
 * transcript is ever sent to the backend — no barge-in, no streaming, reliability over
 * sophistication (spec's own framing). Voice and manual text input both funnel through
 * `submitAndRespond`, so they always go through the exact same backend conversation engine — never
 * a second code path.
 *
 * Unlike the old Demo MVP engine, the backend now tells every turn's `speech_lang` directly
 * (derived from the locked language family) — the STT recognizer's `lang` and the TTS voice
 * selection both follow that value turn-by-turn instead of re-deriving it client-side.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import {
  demoApi,
  DemoApiError,
  type ProviderName,
  type StartCallRequest,
  type TimelineEvent,
} from "@/lib/demo-api";

export type TurnPhase =
  | "idle"
  | "starting"
  | "agent_greeting"
  | "listening"
  | "processing"
  | "agent_speaking"
  | "ending"
  | "ended";

export interface TranscriptLine {
  speaker: "agent" | "patient";
  text: string;
}

// PRD §6.6: a silence is only declared after 7s of listening with no final result.
const SILENCE_TIMEOUT_MS = 7000;

interface MinimalSpeechRecognition extends EventTarget {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  start(): void;
  stop(): void;
  abort(): void;
  onresult: ((event: SpeechRecognitionResultEvent) => void) | null;
  onerror: ((event: { error: string }) => void) | null;
  onend: (() => void) | null;
}

interface SpeechRecognitionResultEvent {
  results: {
    [index: number]: { [index: number]: { transcript: string }; isFinal: boolean };
    length: number;
  };
}

type ListenResult = { kind: "text"; text: string } | { kind: "silence" } | { kind: "none" };

function getSpeechRecognitionCtor(): (new () => MinimalSpeechRecognition) | null {
  if (typeof window === "undefined") return null;
  const w = window as unknown as {
    SpeechRecognition?: new () => MinimalSpeechRecognition;
    webkitSpeechRecognition?: new () => MinimalSpeechRecognition;
  };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

function speechSynthesisAvailable(): boolean {
  return typeof window !== "undefined" && "speechSynthesis" in window;
}

function pickVoice(
  voices: SpeechSynthesisVoice[],
  lang: string,
  gender: "female" | "male",
): SpeechSynthesisVoice | null {
  const langPrefix = lang.split("-")[0];
  const sameLang = voices.filter((v) => v.lang.toLowerCase().startsWith(langPrefix));
  const pool = sameLang.length > 0 ? sameLang : voices;
  // Voice objects don't reliably expose gender — name-substring heuristics are the practical
  // option every browser-TTS demo ends up using. Falls back to the first available voice in the
  // language (or overall) if nothing matches the requested gender, per spec §14's explicit "fall
  // back gracefully instead of failing silently."
  const genderHints =
    gender === "female"
      ? ["female", "woman", "zira", "susan", "heera"]
      : ["male", "man", "ravi", "david"];
  const byGender = pool.find((v) => genderHints.some((hint) => v.name.toLowerCase().includes(hint)));
  return byGender ?? pool[0] ?? voices[0] ?? null;
}

export function useTurnController() {
  const [phase, setPhase] = useState<TurnPhase>("idle");
  const [callId, setCallId] = useState<string | null>(null);
  const [transcript, setTranscript] = useState<TranscriptLine[]>([]);
  const [node, setNode] = useState<string | null>(null);
  const [callOutcome, setCallOutcome] = useState<string | null>(null);
  const [escalated, setEscalated] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [voiceGender, setVoiceGender] = useState<"female" | "male">("female");
  const [micSupported] = useState(() => getSpeechRecognitionCtor() !== null);
  const [ttsSupported] = useState(() => speechSynthesisAvailable());

  const recognitionRef = useRef<MinimalSpeechRecognition | null>(null);
  const voicesRef = useRef<SpeechSynthesisVoice[]>([]);
  const chosenVoiceNameRef = useRef<string | null>(null);

  useEffect(() => {
    if (!ttsSupported) return;
    const loadVoices = () => {
      voicesRef.current = window.speechSynthesis.getVoices();
    };
    loadVoices();
    window.speechSynthesis.onvoiceschanged = loadVoices;
    return () => {
      window.speechSynthesis.onvoiceschanged = null;
    };
  }, [ttsSupported]);

  const speak = useCallback(
    (text: string, lang: string) =>
      new Promise<void>((resolve) => {
        if (!ttsSupported) {
          // No TTS available — spec §17: show the text response and let the demo continue.
          resolve();
          return;
        }
        const utterance = new SpeechSynthesisUtterance(text);
        const voice = pickVoice(voicesRef.current, lang, voiceGender);
        if (voice) {
          utterance.voice = voice;
          chosenVoiceNameRef.current = voice.name;
        }
        utterance.lang = lang;
        utterance.onend = () => resolve();
        utterance.onerror = () => resolve(); // TTS failure never blocks the call (spec §17)
        window.speechSynthesis.speak(utterance);
      }),
    [ttsSupported, voiceGender],
  );

  // Races recognition against a 7s silence timeout (PRD §6.6) — whichever settles first wins;
  // the loser is aborted/ignored.
  const listenOnce = useCallback((lang: string): Promise<ListenResult> => {
    return new Promise((resolve) => {
      const Ctor = getSpeechRecognitionCtor();
      if (!Ctor) {
        resolve({ kind: "none" });
        return;
      }
      const recognition = new Ctor();
      recognitionRef.current = recognition;
      recognition.lang = lang;
      recognition.continuous = false;
      recognition.interimResults = false;

      let settled = false;
      const timer = setTimeout(() => {
        if (settled) return;
        settled = true;
        recognition.abort();
        recognitionRef.current = null;
        resolve({ kind: "silence" });
      }, SILENCE_TIMEOUT_MS);

      const finish = (value: ListenResult) => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        recognitionRef.current = null;
        resolve(value);
      };

      recognition.onresult = (event) => {
        const lastIndex = event.results.length - 1;
        const result = event.results[lastIndex];
        if (result?.isFinal) {
          const text = result[0]?.transcript ?? "";
          finish(text.trim() ? { kind: "text", text } : { kind: "none" });
        }
      };
      recognition.onerror = () => finish({ kind: "none" });
      recognition.onend = () => finish({ kind: "none" });

      recognition.start();
    });
  }, []);

  const stopListening = useCallback(() => {
    recognitionRef.current?.abort();
    recognitionRef.current = null;
  }, []);

  const refreshEvents = useCallback(async (id: string): Promise<TimelineEvent[]> => {
    try {
      return await demoApi.getEvents(id);
    } catch {
      return [];
    }
  }, []);

  // Submits one turn (a real utterance, a silence, or an STT error) and speaks the reply — the
  // one shared path every input source goes through.
  const submitAndRespond = useCallback(
    async (
      id: string,
      provider: ProviderName,
      type: "utterance" | "silence" | "stt_error",
      text?: string,
    ): Promise<{ ended: boolean; nextLang: string }> => {
      if (type === "utterance" && text) {
        setTranscript((prev) => [...prev, { speaker: "patient", text }]);
      }
      setPhase("processing");
      const result = await demoApi.submitTurn(id, provider, type, text);
      setNode(result.node);
      setCallOutcome(result.call_outcome);
      if (result.escalated) setEscalated(true);
      setTranscript((prev) => [...prev, { speaker: "agent", text: result.display_text }]);

      setPhase("agent_speaking");
      await speak(result.speech_text, result.speech_lang);

      if (result.ended) {
        setPhase("ended");
      }
      return { ended: result.ended, nextLang: result.speech_lang };
    },
    [speak],
  );

  // Self-recursive: listen -> submit -> speak -> (if not ended) listen again. No sibling function
  // calls another that isn't yet defined — this only ever calls itself, safely (the recursive call
  // only executes once the whole hook body has already finished running).
  const listenLoop = useCallback(
    async (id: string, provider: ProviderName, lang: string): Promise<void> => {
      setPhase("listening");
      const heard = await listenOnce(lang);
      if (heard.kind === "none") {
        setPhase("listening");
        return;
      }
      try {
        const { ended, nextLang } =
          heard.kind === "text"
            ? await submitAndRespond(id, provider, "utterance", heard.text)
            : await submitAndRespond(id, provider, "silence");
        if (!ended) {
          await listenLoop(id, provider, nextLang);
        }
      } catch (err) {
        setError(
          err instanceof DemoApiError ? err.message : "Something went wrong. Please try again.",
        );
        setPhase("listening");
      }
    },
    [listenOnce, submitAndRespond],
  );

  const startCall = useCallback(
    async (input: StartCallRequest) => {
      setError(null);
      setTranscript([]);
      setNode(null);
      setCallOutcome(null);
      setEscalated(false);
      setPhase("starting");
      try {
        const settings = await demoApi.getSettings();
        setVoiceGender(settings.voice_gender);
        const result = await demoApi.startCall(input);
        setCallId(result.call_id);
        setNode(result.node);
        setTranscript([{ speaker: "agent", text: result.display_text }]);

        setPhase("agent_greeting");
        await speak(result.speech_text, result.speech_lang);
        await listenLoop(result.call_id, input.provider, result.speech_lang);
      } catch (err) {
        setError(
          err instanceof DemoApiError ? err.message : "Couldn't start the call. Please try again.",
        );
        setPhase("idle");
      }
    },
    [speak, listenLoop],
  );

  const submitManualText = useCallback(
    async (provider: ProviderName, text: string) => {
      if (!callId || !text.trim()) return;
      stopListening();
      try {
        const { ended, nextLang } = await submitAndRespond(callId, provider, "utterance", text);
        if (!ended) {
          await listenLoop(callId, provider, nextLang);
        }
      } catch (err) {
        setError(
          err instanceof DemoApiError ? err.message : "Something went wrong. Please try again.",
        );
        setPhase("listening");
      }
    },
    [callId, stopListening, submitAndRespond, listenLoop],
  );

  const endCall = useCallback(async () => {
    stopListening();
    window.speechSynthesis?.cancel();
    setPhase("ending");
    if (callId) {
      try {
        await demoApi.endCall(callId);
      } catch {
        // best-effort — the call still ends locally even if this request fails
      }
    }
    setPhase("ended");
  }, [callId, stopListening]);

  const reset = useCallback(() => {
    stopListening();
    window.speechSynthesis?.cancel();
    setPhase("idle");
    setCallId(null);
    setTranscript([]);
    setError(null);
    setNode(null);
    setCallOutcome(null);
    setEscalated(false);
  }, [stopListening]);

  return {
    phase,
    callId,
    transcript,
    node,
    callOutcome,
    escalated,
    error,
    micSupported,
    ttsSupported,
    chosenVoiceName: chosenVoiceNameRef,
    startCall,
    submitManualText,
    endCall,
    reset,
    refreshEvents,
  };
}
