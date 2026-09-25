"use client";

/**
 * Browser voice turn controller (Demo MVP spec §7) — the sequential state machine driving the
 * mic (Web Speech API SpeechRecognition) and speaker (SpeechSynthesis). Chrome desktop only, per
 * spec — this deliberately doesn't try to be cross-browser.
 *
 * IDLE -> STARTING -> AGENT_GREETING -> LISTENING -> PROCESSING -> AGENT_SPEAKING -> LISTENING ->
 * ... -> ENDING -> ENDED
 *
 * While AGENT_SPEAKING, listening is disabled; it re-enables once speech ends. Only the final
 * transcript is ever sent to the backend — no barge-in, no streaming, reliability over
 * sophistication (spec's own framing). Voice and manual text input both funnel through
 * `submitAndRespond`, so they always go through the exact same backend conversation engine — never
 * a second code path.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { demoApi, DemoApiError, type ProviderName, type TimelineEvent } from "@/lib/demo-api";

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

// Hindi/Hinglish family -> hi-IN (Chrome's hi-IN recognizer handles both Devanagari and
// romanized/Latin-script Hindi speech reasonably, and Hinglish code-switching within it), English
// -> en-IN (Indian English accent model, closer to the demo's expected speakers than en-US).
function recognitionLangFor(lockedLanguage: string | null): string {
  return lockedLanguage === "english" ? "en-IN" : "hi-IN";
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
  const [lockedLanguage, setLockedLanguage] = useState<string | null>(null);
  const [topics, setTopics] = useState<string[]>([]);
  const [summary, setSummary] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [voiceGender, setVoiceGender] = useState<"female" | "male">("female");
  const [micSupported] = useState(() => getSpeechRecognitionCtor() !== null);
  const [ttsSupported] = useState(() => speechSynthesisAvailable());

  const recognitionRef = useRef<MinimalSpeechRecognition | null>(null);
  const voicesRef = useRef<SpeechSynthesisVoice[]>([]);

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
        if (voice) utterance.voice = voice;
        utterance.lang = lang;
        utterance.onend = () => resolve();
        utterance.onerror = () => resolve(); // TTS failure never blocks the call (spec §17)
        window.speechSynthesis.speak(utterance);
      }),
    [ttsSupported, voiceGender],
  );

  const listenOnce = useCallback((lang: string): Promise<string | null> => {
    return new Promise((resolve) => {
      const Ctor = getSpeechRecognitionCtor();
      if (!Ctor) {
        resolve(null);
        return;
      }
      const recognition = new Ctor();
      recognitionRef.current = recognition;
      recognition.lang = lang;
      recognition.continuous = false;
      recognition.interimResults = false;

      let settled = false;
      const finish = (value: string | null) => {
        if (settled) return;
        settled = true;
        recognitionRef.current = null;
        resolve(value);
      };

      recognition.onresult = (event) => {
        const lastIndex = event.results.length - 1;
        const result = event.results[lastIndex];
        if (result?.isFinal) {
          finish(result[0]?.transcript ?? null);
        }
      };
      recognition.onerror = () => finish(null);
      recognition.onend = () => finish(null);

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

  // Submits one piece of text (from mic or manual fallback), speaks the reply, and reports
  // whether the call ended — the one shared path both input methods go through.
  const submitAndRespond = useCallback(
    async (
      id: string,
      provider: ProviderName,
      text: string,
    ): Promise<{ endCall: boolean; nextLang: string | null }> => {
      setTranscript((prev) => [...prev, { speaker: "patient", text }]);
      setPhase("processing");
      const result = await demoApi.submitTurn(id, provider, text);
      setLockedLanguage(result.locked_language || null);
      setTopics(result.topics);
      setTranscript((prev) => [...prev, { speaker: "agent", text: result.response_text }]);

      setPhase("agent_speaking");
      await speak(result.response_text, recognitionLangFor(result.locked_language));

      if (result.end_call) {
        setSummary(result.summary);
        setPhase("ended");
      }
      return { endCall: result.end_call, nextLang: result.locked_language || null };
    },
    [speak],
  );

  // Self-recursive: listen -> submit -> speak -> (if not ended) listen again. No sibling function
  // calls another that isn't yet defined — this only ever calls itself, safely (the recursive call
  // only executes once the whole hook body has already finished running).
  const listenLoop = useCallback(
    async (id: string, provider: ProviderName, lang: string | null): Promise<void> => {
      setPhase("listening");
      const text = await listenOnce(recognitionLangFor(lang));
      if (!text || !text.trim()) {
        setPhase("listening");
        return;
      }
      try {
        const { endCall, nextLang } = await submitAndRespond(id, provider, text);
        if (!endCall) {
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
    async (provider: ProviderName) => {
      setError(null);
      setTranscript([]);
      setTopics([]);
      setSummary(null);
      setLockedLanguage(null);
      setPhase("starting");
      try {
        const settings = await demoApi.getSettings();
        setVoiceGender(settings.voice_gender);
        const result = await demoApi.startCall(provider);
        setCallId(result.call_id);
        setTranscript([{ speaker: "agent", text: result.greeting_text }]);

        setPhase("agent_greeting");
        await speak(result.greeting_text, "hi-IN");
        await listenLoop(result.call_id, provider, null);
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
        const { endCall, nextLang } = await submitAndRespond(callId, provider, text);
        if (!endCall) {
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
    setTopics([]);
    setSummary(null);
    setLockedLanguage(null);
  }, [stopListening]);

  return {
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
    refreshEvents,
  };
}
