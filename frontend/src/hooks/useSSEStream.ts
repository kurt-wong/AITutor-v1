/**
 * useSSEStream — SSE stream hook (fetch-based, no AbortController)
 */

import { useCallback } from "react";
import type { SSEEvent } from "../types";

interface UseSSEStreamOptions {
  onEvent: (event: SSEEvent) => void;
  onError?: (error: Error) => void;
  onDone?: () => void;
}

export function useSSEStream() {
  const connect = useCallback(
    async (url: string, body: FormData | BodyInit | null, options: UseSSEStreamOptions) => {
      const { onEvent, onError, onDone } = options;

      try {
        const init: RequestInit = {
          method: "POST",
          body,
        };
        if (!(body instanceof FormData) && body != null) {
          (init.headers as Record<string, string>) = { "Content-Type": "application/json" };
        }

        const res = await fetch(url, init);
        if (!res.ok || !res.body) {
          let detail = "";
          try {
            const errJson = await res.json();
            detail = errJson?.error?.message || errJson?.detail || "";
          } catch { /* ignore */ }
          throw new Error(`SSE connect failed [${url}]: HTTP ${res.status}${detail ? " — " + detail : ""}`);
        }

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const parts = buffer.split("\n\n");
          buffer = parts.pop() || "";

          for (const part of parts) {
            const trimmed = part.trim();
            if (!trimmed) continue;
            const lines = trimmed.split("\n");
            let dataLine = "";
            for (const line of lines) {
              if (line.startsWith("data: ")) dataLine = line.slice(6);
              else if (line.startsWith("data:")) dataLine = line.slice(5);
            }
            if (dataLine) {
              try {
                const parsed = JSON.parse(dataLine);
                onEvent(parsed);
              } catch {
                // SSE data parse failure — skip malformed event
              }
            }
          }
        }
        onDone?.();
      } catch (err) {
        onError?.(err instanceof Error ? err : new Error(String(err)));
      }
    },
    []
  );

  const abort = useCallback(() => {}, []);

  return { connect, abort };
}
