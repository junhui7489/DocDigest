/**
 * DocDigest API Client
 *
 * Maps directly to the FastAPI backend routes in app/routers/documents.py.
 * In dev, Vite proxies /api → http://localhost:8000.
 * In prod, FastAPI serves the built frontend at the same origin.
 */

const BASE = `${import.meta.env.VITE_API_URL || ""}/api/v1/documents`;

class ApiError extends Error {
  constructor(status, detail) {
    super(detail);
    this.status = status;
    this.detail = detail;
  }
}

async function request(method, path, { body, params } = {}) {
  let url = `${BASE}${path}`;
  if (params) {
    const qs = new URLSearchParams(params).toString();
    if (qs) url += `?${qs}`;
  }
  const opts = { method, headers: {} };
  if (body instanceof FormData) {
    opts.body = body;
  } else if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(url, opts);
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try { const err = await res.json(); detail = err.detail || detail; } catch {}
    throw new ApiError(res.status, detail);
  }
  return res.json();
}

/** POST /upload */
export async function uploadDocument(file) {
  const fd = new FormData();
  fd.append("file", file);
  return request("POST", "/upload", { body: fd });
}

/** GET /{id}/status */
export async function getStatus(documentId) {
  return request("GET", `/${documentId}/status`);
}

/** GET /{id}/summary?level= */
export async function getSummary(documentId, level = "brief") {
  return request("GET", `/${documentId}/summary`, { params: { level } });
}

/** POST /{id}/ask */
export async function askQuestion(documentId, question) {
  return request("POST", `/${documentId}/ask`, { body: { question } });
}

/**
 * POST /{id}/ask/stream — Streaming Q&A via Server-Sent Events.
 *
 * Calls the SSE endpoint and invokes callbacks as events arrive:
 *   onDelta(text)     — each text token/chunk
 *   onSources(sources) — source citations after answer completes
 *   onError(msg)      — on failure
 *   onDone()          — stream finished
 *
 * Returns an abort function to cancel the stream.
 */
export function askQuestionStream(documentId, question, { onDelta, onSources, onError, onDone }) {
  const controller = new AbortController();

  (async () => {
    try {
      const res = await fetch(`${BASE}/${documentId}/ask/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question }),
        signal: controller.signal,
      });

      if (!res.ok) {
        let detail = `HTTP ${res.status}`;
        try { const err = await res.json(); detail = err.detail || detail; } catch {}
        onError?.(detail);
        return;
      }

      await readSSE(res.body, { onDelta, onSources, onError, onDone });
    } catch (e) {
      if (e.name !== "AbortError") {
        onError?.(e.message || "Stream failed");
      }
    }
  })();

  return () => controller.abort();
}

/**
 * GET /{id}/summary/stream?level= — Streaming summary via SSE.
 *
 * Streams the pre-computed summary text with a typing effect.
 *
 * Callbacks:
 *   onDelta(text)  — each text chunk
 *   onMeta(data)   — metadata (level, etc.)
 *   onDone()       — stream finished
 *
 * Returns an abort function.
 */
export function getSummaryStream(documentId, level, { onDelta, onMeta, onError, onDone }) {
  const controller = new AbortController();

  (async () => {
    try {
      const res = await fetch(
        `${BASE}/${documentId}/summary/stream?level=${level}`,
        { signal: controller.signal }
      );

      if (!res.ok) {
        let detail = `HTTP ${res.status}`;
        try { const err = await res.json(); detail = err.detail || detail; } catch {}
        onError?.(detail);
        return;
      }

      await readSSE(res.body, { onDelta, onMeta, onError, onDone });
    } catch (e) {
      if (e.name !== "AbortError") {
        onError?.(e.message || "Stream failed");
      }
    }
  })();

  return () => controller.abort();
}


/**
 * Read a Server-Sent Event stream from a ReadableStream body.
 *
 * Parses SSE format (event: type\ndata: json\n\n) and dispatches
 * to the appropriate callback.
 */
async function readSSE(body, { onDelta, onSources, onMeta, onError, onDone }) {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });

    // Process complete events (separated by double newline)
    const parts = buffer.split("\n\n");
    buffer = parts.pop(); // Keep incomplete part

    for (const part of parts) {
      if (!part.trim()) continue;

      let eventType = "message";
      let data = "";

      for (const line of part.split("\n")) {
        if (line.startsWith("event: ")) {
          eventType = line.slice(7).trim();
        } else if (line.startsWith("data: ")) {
          data = line.slice(6);
        }
      }

      if (!data) continue;

      try {
        const parsed = JSON.parse(data);

        switch (eventType) {
          case "delta":
            onDelta?.(parsed.text || "");
            break;
          case "sources":
            onSources?.(parsed.sources || []);
            break;
          case "meta":
            onMeta?.(parsed);
            break;
          case "error":
            onError?.(parsed.error || "Unknown error");
            break;
          case "done":
            onDone?.();
            break;
        }
      } catch {
        // Skip malformed JSON
      }
    }
  }

  // If stream ends without explicit done event
  onDone?.();
}

/** GET /{id}/export?level= */
export async function exportSummary(documentId, level = "brief") {
  return request("GET", `/${documentId}/export`, { params: { level } });
}

/** GET / */
export async function listDocuments() {
  return request("GET", "");
}

/** DELETE /{id} */
export async function deleteDocument(documentId) {
  return request("DELETE", `/${documentId}`);
}

export const STATUS_LABELS = {
  pending: "Queued for processing",
  parsing: "Parsing document structure",
  chunking: "Splitting into semantic sections",
  summarising: "Generating summaries with AI",
  embedding: "Indexing for search",
  completed: "Analysis complete",
  failed: "Processing failed",
};

export function isTerminal(status) {
  return status === "completed" || status === "failed";
}
