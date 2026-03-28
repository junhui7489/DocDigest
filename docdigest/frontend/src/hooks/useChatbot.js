import { useState, useRef, useCallback } from "react";
import {
  uploadDocument,
  getStatus,
  getSummary,
  askQuestion,
  askQuestionStream,
  getSummaryStream,
  exportSummary,
  isTerminal,
  STATUS_LABELS,
} from "../services/api.js";

/**
 * Message shape:
 * {
 *   id: string,
 *   role: "user" | "bot",
 *   type: "text" | "file" | "status" | "summary" | "qa" | "actions" | "error" | "typing",
 *   content: string,
 *   file?: { name, size, type },
 *   status?: { stage, progress },
 *   summary?: { level, content, metadata },
 *   qa?: { answer, sources },
 *   actions?: [{ id, label }],
 *   timestamp: number,
 * }
 */

let msgCounter = 0;
function makeId() {
  return `msg_${Date.now()}_${++msgCounter}`;
}

export function useChatbot() {
  const [messages, setMessages] = useState([]);
  const [isProcessing, setIsProcessing] = useState(false);
  const [activeDocId, setActiveDocId] = useState(null);
  const [activeDocName, setActiveDocName] = useState(null);
  const pollingRef = useRef(null);

  // ─── Message helpers ─────────────────────────────────────────────

  const addMessage = useCallback((msg) => {
    const m = { id: makeId(), timestamp: Date.now(), ...msg };
    setMessages((prev) => [...prev, m]);
    return m.id;
  }, []);

  const updateMessage = useCallback((id, updates) => {
    setMessages((prev) =>
      prev.map((m) => (m.id === id ? { ...m, ...updates } : m))
    );
  }, []);

  const removeMessage = useCallback((id) => {
    setMessages((prev) => prev.filter((m) => m.id !== id));
  }, []);

  // ─── Typing indicator ────────────────────────────────────────────

  const showTyping = useCallback(() => {
    const id = makeId();
    setMessages((prev) => [
      ...prev,
      { id, role: "bot", type: "typing", timestamp: Date.now() },
    ]);
    return id;
  }, []);

  // ─── Welcome message ────────────────────────────────────────────

  const sendWelcome = useCallback(() => {
    addMessage({
      role: "bot",
      type: "text",
      content:
        "Welcome to DocDigest! I can help you understand any document — books, research papers, legal contracts, or lengthy reports.\n\nJust attach a file using the paperclip button below, or drop it into the chat. I support PDF, EPUB, DOCX, and TXT formats.",
    });
    addMessage({
      role: "bot",
      type: "actions",
      content: "Here's what I can do:",
      actions: [
        { id: "help_upload", label: "Upload a document" },
        { id: "help_features", label: "What can you do?" },
      ],
    });
  }, [addMessage]);

  // ─── File upload flow ────────────────────────────────────────────

  const handleFileUpload = useCallback(
    async (file) => {
      const ext = file.name.split(".").pop().toLowerCase();
      const allowed = ["pdf", "epub", "docx", "txt"];

      // User message showing the file
      addMessage({
        role: "user",
        type: "file",
        content: file.name,
        file: { name: file.name, size: file.size, type: ext },
      });

      if (!allowed.includes(ext)) {
        addMessage({
          role: "bot",
          type: "error",
          content: `I can't process .${ext} files. Please upload a PDF, EPUB, DOCX, or TXT file.`,
        });
        return;
      }

      const typingId = showTyping();
      setIsProcessing(true);

      try {
        const res = await uploadDocument(file);
        removeMessage(typingId);

        setActiveDocId(res.document_id);
        setActiveDocName(file.name);

        // Status message that will update during polling
        const statusMsgId = addMessage({
          role: "bot",
          type: "status",
          content: "I've received your document. Let me analyse it…",
          status: { stage: "pending", progress: 0 },
        });

        // Start polling
        startPolling(res.document_id, statusMsgId);
      } catch (e) {
        removeMessage(typingId);
        setIsProcessing(false);
        addMessage({
          role: "bot",
          type: "error",
          content: `Upload failed: ${e.detail || e.message}. Please try again.`,
        });
      }
    },
    [addMessage, removeMessage, showTyping]
  );

  // ─── Status polling ──────────────────────────────────────────────

  const startPolling = useCallback(
    (docId, statusMsgId) => {
      if (pollingRef.current) clearInterval(pollingRef.current);

      pollingRef.current = setInterval(async () => {
        try {
          const res = await getStatus(docId);

          updateMessage(statusMsgId, {
            content: STATUS_LABELS[res.status] || res.status,
            status: { stage: res.status, progress: res.progress },
          });

          if (isTerminal(res.status)) {
            clearInterval(pollingRef.current);
            pollingRef.current = null;

            if (res.status === "completed") {
              // Fetch and deliver the brief summary with streaming
              updateMessage(statusMsgId, {
                content: "Analysis complete!",
                status: { stage: "completed", progress: 1 },
              });

              try {
                // Get metadata via non-streaming call
                const briefRes = await getSummary(docId, "brief");

                // Create streaming message
                const briefMsgId = addMessage({
                  role: "bot",
                  type: "summary-stream",
                  content: "Here's the executive brief:",
                  summary: {
                    level: "brief",
                    content: "",
                    metadata: briefRes.metadata,
                  },
                  streaming: true,
                });

                // Stream the brief text
                await new Promise((resolve) => {
                  getSummaryStream(docId, "brief", {
                    onDelta: (text) => {
                      setMessages((prev) =>
                        prev.map((m) =>
                          m.id === briefMsgId
                            ? { ...m, summary: { ...m.summary, content: m.summary.content + text } }
                            : m
                        )
                      );
                    },
                    onDone: () => {
                      setMessages((prev) =>
                        prev.map((m) =>
                          m.id === briefMsgId ? { ...m, streaming: false, type: "summary" } : m
                        )
                      );
                      resolve();
                    },
                    onError: () => resolve(),
                  });
                });

                addMessage({
                  role: "bot",
                  type: "actions",
                  content: "What would you like to explore next?",
                  actions: [
                    { id: "summary_takeaways", label: "Key takeaways" },
                    { id: "summary_chapters", label: "Chapter summaries" },
                    { id: "ask_hint", label: "Ask a question" },
                    { id: "export_brief", label: "Export as Markdown" },
                  ],
                });
              } catch (e) {
                addMessage({
                  role: "bot",
                  type: "error",
                  content: `Couldn't fetch the summary: ${e.detail || e.message}`,
                });
              }
            } else {
              addMessage({
                role: "bot",
                type: "error",
                content: `Processing failed: ${res.error_message || "Unknown error"}. You can try uploading the document again.`,
              });
            }
            setIsProcessing(false);
          }
        } catch (err) {
          // Transient network error — keep polling unless it's a hard failure
          if (err?.status >= 400 && err?.status < 500) {
            clearInterval(pollingRef.current);
            pollingRef.current = null;
            setIsProcessing(false);
            addMessage({
              role: "bot",
              type: "error",
              content: `Processing failed: ${err.detail || err.message}. You can try uploading the document again.`,
            });
          }
        }
      }, 2000);
    },
    [addMessage, removeMessage, updateMessage, showTyping, setMessages]
  );

  // ─── Text message handling ───────────────────────────────────────

  const handleSendMessage = useCallback(
    async (text) => {
      const trimmed = text.trim();
      if (!trimmed) return;

      addMessage({ role: "user", type: "text", content: trimmed });

      // Handle action-like messages
      const lower = trimmed.toLowerCase();

      if (!activeDocId) {
        if (
          lower.includes("upload") ||
          lower.includes("attach") ||
          lower.includes("document") ||
          lower.includes("file") ||
          lower.includes("analyse") ||
          lower.includes("analyze")
        ) {
          addMessage({
            role: "bot",
            type: "text",
            content:
              "Sure! Click the paperclip button below or drag a file into the chat to upload your document. I support PDF, EPUB, DOCX, and TXT.",
          });
          return;
        }

        if (lower.includes("what can") || lower.includes("help") || lower.includes("feature")) {
          addMessage({
            role: "bot",
            type: "text",
            content:
              "I can analyse documents and give you:\n\n• **Executive brief** — A one-paragraph summary of the entire document\n• **Key takeaways** — The 5–8 most important insights\n• **Chapter summaries** — A detailed breakdown of each chapter\n• **Follow-up Q&A** — Ask me any question and I'll answer based on the document with page citations\n• **Export** — Download summaries as Markdown\n\nTo get started, just upload a document!",
          });
          return;
        }

        addMessage({
          role: "bot",
          type: "text",
          content:
            "I don't have a document loaded yet. Upload a file using the paperclip button below and I'll analyse it for you.",
        });
        return;
      }

      if (isProcessing) {
        addMessage({
          role: "bot",
          type: "text",
          content:
            "I'm still processing your document. I'll let you know as soon as it's ready — hang tight!",
        });
        return;
      }

      // Route summary requests
      if (lower.includes("brief") || lower.includes("overview") || lower.includes("executive")) {
        await fetchSummary("brief", "executive brief");
        return;
      }
      if (lower.includes("takeaway") || lower.includes("key point") || lower.includes("key insight")) {
        await fetchSummary("takeaways", "key takeaways");
        return;
      }
      if (lower.includes("chapter") || lower.includes("deep dive") || lower.includes("detailed")) {
        await fetchSummary("chapters", "chapter summaries");
        return;
      }
      if (lower.includes("export") || lower.includes("download") || lower.includes("markdown")) {
        await handleExport();
        return;
      }
      if (lower.includes("new document") || lower.includes("upload another") || lower.includes("different file")) {
        setActiveDocId(null);
        setActiveDocName(null);
        addMessage({
          role: "bot",
          type: "text",
          content: "Sure! Upload a new document using the paperclip button below.",
        });
        return;
      }

      // Default: treat as a Q&A question
      await handleQuestion(trimmed);
    },
    [activeDocId, isProcessing, addMessage]
  );

  // ─── Action button handling ──────────────────────────────────────

  const handleAction = useCallback(
    async (actionId) => {
      switch (actionId) {
        case "help_upload":
          addMessage({ role: "user", type: "text", content: "Upload a document" });
          addMessage({
            role: "bot",
            type: "text",
            content:
              "Click the paperclip button in the input bar below, or simply drag and drop a file into the chat. I support PDF, EPUB, DOCX, and TXT files up to any size.",
          });
          break;

        case "help_features":
          addMessage({ role: "user", type: "text", content: "What can you do?" });
          addMessage({
            role: "bot",
            type: "text",
            content:
              "Once you upload a document, I can provide:\n\n• **Executive brief** — The whole document in one paragraph\n• **Key takeaways** — 5–8 most important insights\n• **Chapter summaries** — Detailed breakdown per chapter\n• **Q&A** — Ask any question, I answer from the document with page citations\n• **Export** — Download any summary as Markdown",
          });
          break;

        case "summary_takeaways":
          addMessage({ role: "user", type: "text", content: "Show me the key takeaways" });
          await fetchSummary("takeaways", "key takeaways");
          break;

        case "summary_chapters":
          addMessage({ role: "user", type: "text", content: "Show me the chapter summaries" });
          await fetchSummary("chapters", "chapter summaries");
          break;

        case "summary_brief":
          addMessage({ role: "user", type: "text", content: "Show me the executive brief" });
          await fetchSummary("brief", "executive brief");
          break;

        case "ask_hint":
          addMessage({
            role: "bot",
            type: "text",
            content:
              "Go ahead — type any question about the document and I'll answer it using the source text with page citations. For example:\n\n• \"What are the main arguments?\"\n• \"What evidence supports the conclusion?\"\n• \"Summarise chapter 3\"",
          });
          break;

        case "export_brief":
          addMessage({ role: "user", type: "text", content: "Export as Markdown" });
          await handleExport();
          break;

        default:
          break;
      }
    },
    [activeDocId, addMessage]
  );

  // ─── Fetch a summary level (streaming for brief/takeaways) ───────

  const fetchSummary = useCallback(
    async (level, label) => {
      if (!activeDocId) return;

      // Chapters need structured rendering — use non-streaming
      if (level === "chapters") {
        const typingId = showTyping();
        try {
          const res = await getSummary(activeDocId, level);
          removeMessage(typingId);
          addMessage({
            role: "bot",
            type: "summary",
            content: `Here are the ${label}:`,
            summary: { level, content: res.content, metadata: res.metadata },
          });
        } catch (e) {
          removeMessage(typingId);
          addMessage({ role: "bot", type: "error", content: `Couldn't fetch ${label}: ${e.detail || e.message}` });
          return;
        }
      } else {
        // Brief & takeaways — stream text token by token
        // First fetch metadata via non-streaming for the summary card header
        let metadata = null;
        try {
          const res = await getSummary(activeDocId, level);
          metadata = res.metadata;
        } catch {}

        // Create a streaming summary message
        const msgId = addMessage({
          role: "bot",
          type: "summary-stream",
          content: `Here are the ${label}:`,
          summary: { level, content: "", metadata },
          streaming: true,
        });

        // Stream the text
        await new Promise((resolve) => {
          getSummaryStream(activeDocId, level, {
            onDelta: (text) => {
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === msgId
                    ? {
                        ...m,
                        summary: {
                          ...m.summary,
                          content: m.summary.content + text,
                        },
                      }
                    : m
                )
              );
            },
            onError: (err) => {
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === msgId ? { ...m, streaming: false, type: "error", content: err } : m
                )
              );
              resolve();
            },
            onDone: () => {
              // Mark streaming complete — remove cursor
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === msgId ? { ...m, streaming: false, type: "summary" } : m
                )
              );
              resolve();
            },
          });
        });
      }

      // Follow-up actions
      const actions = [{ id: "ask_hint", label: "Ask a question" }];
      if (level !== "brief") actions.unshift({ id: "summary_brief", label: "Executive brief" });
      if (level !== "takeaways") actions.unshift({ id: "summary_takeaways", label: "Key takeaways" });
      if (level !== "chapters") actions.unshift({ id: "summary_chapters", label: "Chapters" });
      addMessage({ role: "bot", type: "actions", content: "Want to see more?", actions });
    },
    [activeDocId, addMessage, removeMessage, showTyping, setMessages]
  );

  // ─── Q&A (streaming) ──────────────────────────────────────────────

  const handleQuestion = useCallback(
    async (question) => {
      if (!activeDocId) return;

      // Create a streaming QA message with empty content
      const msgId = addMessage({
        role: "bot",
        type: "qa-stream",
        content: "",
        qa: { answer: "", sources: [] },
        streaming: true,
      });

      // Stream the answer token by token
      await new Promise((resolve) => {
        askQuestionStream(activeDocId, question, {
          onDelta: (text) => {
            setMessages((prev) =>
              prev.map((m) =>
                m.id === msgId
                  ? {
                      ...m,
                      content: m.content + text,
                      qa: { ...m.qa, answer: m.qa.answer + text },
                    }
                  : m
              )
            );
          },
          onSources: (sources) => {
            setMessages((prev) =>
              prev.map((m) =>
                m.id === msgId
                  ? { ...m, qa: { ...m.qa, sources } }
                  : m
              )
            );
          },
          onError: (err) => {
            setMessages((prev) =>
              prev.map((m) =>
                m.id === msgId
                  ? {
                      ...m,
                      streaming: false,
                      type: "error",
                      content: `Sorry, something went wrong: ${err}`,
                    }
                  : m
              )
            );
            resolve();
          },
          onDone: () => {
            // Mark streaming complete — remove cursor, finalise type
            setMessages((prev) =>
              prev.map((m) =>
                m.id === msgId ? { ...m, streaming: false, type: "qa" } : m
              )
            );
            resolve();
          },
        });
      });
    },
    [activeDocId, addMessage, setMessages]
  );

  // ─── Export ──────────────────────────────────────────────────────

  const handleExport = useCallback(async () => {
    if (!activeDocId) return;
    try {
      const res = await exportSummary(activeDocId, "brief");
      const blob = new Blob([res.markdown], { type: "text/markdown" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${activeDocName || "summary"}_brief.md`;
      a.click();
      URL.revokeObjectURL(url);
      addMessage({
        role: "bot",
        type: "text",
        content: "Done! The Markdown file has been downloaded.",
      });
    } catch (e) {
      addMessage({
        role: "bot",
        type: "error",
        content: `Export failed: ${e.detail || e.message}`,
      });
    }
  }, [activeDocId, activeDocName, addMessage]);

  return {
    messages,
    isProcessing,
    activeDocId,
    activeDocName,
    sendWelcome,
    handleSendMessage,
    handleFileUpload,
    handleAction,
  };
}
