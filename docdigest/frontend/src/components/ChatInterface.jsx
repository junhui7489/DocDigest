import { useState, useEffect, useRef, useCallback } from "react";
import { useChatbot } from "../hooks/useChatbot.js";

export default function ChatInterface() {
  const {
    messages,
    isProcessing,
    activeDocId,
    activeDocName,
    sendWelcome,
    handleSendMessage,
    handleFileUpload,
    handleAction,
  } = useChatbot();

  const [input, setInput] = useState("");
  const [dragOver, setDragOver] = useState(false);
  const dragDepth = useRef(0);
  const scrollRef = useRef(null);
  const fileRef = useRef(null);
  const inputRef = useRef(null);
  const welcomeSent = useRef(false);

  // Send welcome on mount
  useEffect(() => {
    if (!welcomeSent.current) {
      welcomeSent.current = true;
      sendWelcome();
    }
  }, [sendWelcome]);

  // Auto-scroll on new messages
  useEffect(() => {
    const el = scrollRef.current;
    if (el) {
      requestAnimationFrame(() => {
        el.scrollTop = el.scrollHeight;
      });
    }
  }, [messages]);

  const onSend = useCallback(() => {
    if (!input.trim()) return;
    handleSendMessage(input);
    setInput("");
    inputRef.current?.focus();
  }, [input, handleSendMessage]);

  const onFileSelect = useCallback(
    (files) => {
      if (files?.[0]) handleFileUpload(files[0]);
    },
    [handleFileUpload]
  );

  const onDragEnter = useCallback((e) => {
    e.preventDefault();
    dragDepth.current += 1;
    setDragOver(true);
  }, []);

  const onDragLeave = useCallback(() => {
    dragDepth.current -= 1;
    if (dragDepth.current === 0) setDragOver(false);
  }, []);

  const onDrop = useCallback(
    (e) => {
      e.preventDefault();
      dragDepth.current = 0;
      setDragOver(false);
      const files = e.dataTransfer.files;
      if (files.length === 0) return;
      onFileSelect(files);
    },
    [onFileSelect]
  );

  return (
    <div style={S.root}>
      {/* ── Header ── */}
      <header style={S.header}>
        <div style={S.headerLeft}>
          <BrandIcon />
          <div>
            <div style={S.headerTitle}>DocDigest</div>
            <div style={S.headerSub}>
              {activeDocName
                ? `Analysing: ${activeDocName}`
                : "Document analysis chatbot"}
            </div>
          </div>
        </div>
        {activeDocId && (
          <div style={S.headerBadge}>
            <span style={S.headerDot} />
            Document loaded
          </div>
        )}
      </header>

      {/* ── Chat area ── */}
      <div
        ref={scrollRef}
        style={{
          ...S.chatArea,
          borderColor: dragOver ? "var(--accent)" : "transparent",
          backgroundColor: dragOver ? "var(--accent-bg)" : "transparent",
        }}
        onDragOver={(e) => e.preventDefault()}
        onDragEnter={onDragEnter}
        onDragLeave={onDragLeave}
        onDrop={onDrop}
      >
        <div style={S.chatInner}>
          {messages.map((msg) => (
            <MessageBubble
              key={msg.id}
              msg={msg}
              onAction={handleAction}
            />
          ))}
          {dragOver && (
            <div style={S.dropOverlay}>
              <svg width="36" height="36" viewBox="0 0 40 40" fill="none">
                <path d="M20 6v20M12 14l8-8 8 8" stroke="var(--accent)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                <path d="M6 28v4a2 2 0 002 2h24a2 2 0 002-2v-4" stroke="var(--accent)" strokeWidth="2" strokeLinecap="round" />
              </svg>
              <span style={S.dropText}>Drop your document here</span>
            </div>
          )}
        </div>
      </div>

      {/* ── Input bar ── */}
      <div style={S.inputBar}>
        <div style={S.inputRow}>
          <button
            style={S.attachBtn}
            onClick={() => fileRef.current?.click()}
            title="Attach a document"
          >
            <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
              <path
                d="M17.5 9.31l-7.78 7.78a4.5 4.5 0 01-6.36-6.36l7.78-7.78a3 3 0 014.24 4.24l-7.78 7.79a1.5 1.5 0 01-2.12-2.12l7.07-7.08"
                stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"
              />
            </svg>
            <input
              ref={fileRef}
              type="file"
              accept=".pdf,.epub,.docx,.txt"
              style={{ display: "none" }}
              onChange={(e) => {
                onFileSelect(e.target.files);
                e.target.value = "";
              }}
            />
          </button>

          <textarea
            ref={inputRef}
            style={S.input}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                onSend();
              }
            }}
            placeholder={
              isProcessing
                ? "Processing your document…"
                : activeDocId
                ? "Ask a question about your document…"
                : "Type a message or attach a document…"
            }
            rows={1}
          />

          <button
            style={{
              ...S.sendBtn,
              opacity: input.trim() ? 1 : 0.4,
            }}
            onClick={onSend}
            disabled={!input.trim()}
          >
            <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
              <path d="M3 10h14M12 5l5 5-5 5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </button>
        </div>
        <div style={S.inputHint}>
          PDF, EPUB, DOCX, TXT supported · Shift+Enter for new line
        </div>
      </div>
    </div>
  );
}


// ─── Message Bubble Router ───────────────────────────────────────────

function MessageBubble({ msg, onAction }) {
  const isBot = msg.role === "bot";

  if (msg.type === "typing") return <TypingIndicator />;

  return (
    <div style={{ ...S.msgRow, justifyContent: isBot ? "flex-start" : "flex-end", animation: "fadeUp 0.3s ease" }}>
      {isBot && <BotAvatar />}
      <div style={{ maxWidth: "78%", minWidth: 0 }}>
        {msg.type === "text" && <TextMessage msg={msg} />}
        {msg.type === "file" && <FileMessage msg={msg} />}
        {msg.type === "status" && <StatusMessage msg={msg} />}
        {msg.type === "summary" && <SummaryMessage msg={msg} />}
        {msg.type === "summary-stream" && <StreamingSummaryMessage msg={msg} />}
        {msg.type === "qa" && <QAMessage msg={msg} />}
        {msg.type === "qa-stream" && <StreamingQAMessage msg={msg} />}
        {msg.type === "actions" && <ActionsMessage msg={msg} onAction={onAction} />}
        {msg.type === "error" && <ErrorMessage msg={msg} />}
      </div>
    </div>
  );
}


// ─── Message Types ───────────────────────────────────────────────────

function TextMessage({ msg }) {
  const isBot = msg.role === "bot";
  // Render markdown-like bold
  const renderContent = (text) => {
    const parts = text.split(/(\*\*.*?\*\*)/g);
    return parts.map((part, i) => {
      if (part.startsWith("**") && part.endsWith("**")) {
        return <strong key={i}>{part.slice(2, -2)}</strong>;
      }
      return part;
    });
  };

  return (
    <div style={isBot ? S.bubbleBot : S.bubbleUser}>
      <p style={isBot ? S.botText : S.userText}>{renderContent(msg.content)}</p>
    </div>
  );
}

function FileMessage({ msg }) {
  const f = msg.file;
  const sizeLabel = f.size > 1048576
    ? `${(f.size / 1048576).toFixed(1)} MB`
    : `${(f.size / 1024).toFixed(0)} KB`;

  return (
    <div style={S.bubbleUser}>
      <div style={S.fileCard}>
        <div style={S.fileIcon}>
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none">
            <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8l-6-6z" stroke="#fff" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
            <path d="M14 2v6h6" stroke="#fff" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </div>
        <div>
          <div style={S.fileName}>{f.name}</div>
          <div style={S.fileMeta}>{f.type.toUpperCase()} · {sizeLabel}</div>
        </div>
      </div>
    </div>
  );
}

function StatusMessage({ msg }) {
  const { stage, progress } = msg.status || {};
  const pct = Math.round((progress || 0) * 100);
  const isComplete = stage === "completed";
  const isFailed = stage === "failed";

  return (
    <div style={S.bubbleBot}>
      <div style={S.statusCard}>
        <div style={S.statusHeader}>
          {!isComplete && !isFailed && (
            <div style={S.statusSpinner} />
          )}
          {isComplete && <span style={S.statusCheck}>✓</span>}
          {isFailed && <span style={S.statusFail}>✗</span>}
          <span style={S.statusLabel}>{msg.content}</span>
        </div>
        {!isComplete && !isFailed && (
          <div style={S.statusBarOuter}>
            <div style={{ ...S.statusBarInner, width: `${pct}%` }} />
          </div>
        )}
        {!isComplete && !isFailed && (
          <div style={S.statusPct}>{pct}%</div>
        )}
      </div>
    </div>
  );
}

function SummaryMessage({ msg }) {
  const { level, content, metadata } = msg.summary || {};
  const [expanded, setExpanded] = useState(null);

  return (
    <div style={S.bubbleBot}>
      <div style={S.summaryCard}>
        <div style={S.summaryBadge}>
          {level === "brief" && "Executive Brief"}
          {level === "takeaways" && "Key Takeaways"}
          {level === "chapters" && "Chapter Summaries"}
        </div>

        {metadata?.title && (
          <div style={S.summaryMeta}>
            {metadata.title}
            {metadata.author && ` by ${metadata.author}`}
            {metadata.pages && ` · ${metadata.pages} pages`}
          </div>
        )}

        {/* Brief: single string */}
        {level === "brief" && typeof content === "string" && (
          <p style={S.summaryBody}>{content}</p>
        )}

        {/* Takeaways: numbered string */}
        {level === "takeaways" && typeof content === "string" && (
          <div style={S.takeawaysList}>
            {content
              .split(/\n\n|\n(?=\d+\.)/)
              .filter(Boolean)
              .map((s) => s.replace(/^\d+\.\s*/, "").trim())
              .filter(Boolean)
              .map((item, i) => (
                <div key={i} style={S.takeawayItem}>
                  <span style={S.takeawayNum}>{i + 1}</span>
                  <p style={S.takeawayText}>{item}</p>
                </div>
              ))}
          </div>
        )}

        {/* Chapters: array of {section, content} or object */}
        {level === "chapters" && content && (
          <div style={S.chaptersList}>
            {(Array.isArray(content)
              ? content.map((c) => [c.section, c.content])
              : Object.entries(content)
            ).map(([heading, body], i) => (
              <div key={i} style={S.chapterItem}>
                <button
                  style={S.chapterHead}
                  onClick={() => setExpanded(expanded === i ? null : i)}
                >
                  <span style={S.chapterIdx}>{String(i + 1).padStart(2, "0")}</span>
                  <span style={S.chapterName}>{heading}</span>
                  <span style={{ ...S.chapterArrow, transform: expanded === i ? "rotate(180deg)" : "rotate(0)" }}>▾</span>
                </button>
                {expanded === i && (
                  <div style={S.chapterBody}>
                    <p style={S.summaryBody}>{body}</p>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function QAMessage({ msg }) {
  const { answer, sources } = msg.qa || {};
  return (
    <div style={S.bubbleBot}>
      <p style={S.botText}>{answer}</p>
      {sources?.length > 0 && (
        <div style={S.sourcesList}>
          {sources.map((s, i) => (
            <span key={i} style={S.sourceTag}>
              pp. {s.pages}
              {s.section ? ` — ${s.section}` : ""}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

function StreamingQAMessage({ msg }) {
  const { answer, sources } = msg.qa || {};
  const isStreaming = msg.streaming;

  return (
    <div style={S.bubbleBot}>
      <p style={S.botText}>
        {answer}
        {isStreaming && <BlinkingCursor />}
      </p>
      {!isStreaming && sources?.length > 0 && (
        <div style={{ ...S.sourcesList, animation: "fadeUp 0.3s ease" }}>
          {sources.map((s, i) => (
            <span key={i} style={S.sourceTag}>
              pp. {s.pages}
              {s.section ? ` — ${s.section}` : ""}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

function StreamingSummaryMessage({ msg }) {
  const { level, content, metadata } = msg.summary || {};
  const isStreaming = msg.streaming;

  return (
    <div style={S.bubbleBot}>
      <div style={S.summaryCard}>
        <div style={S.summaryBadge}>
          {level === "brief" && "Executive Brief"}
          {level === "takeaways" && "Key Takeaways"}
          {level === "chapters" && "Chapter Summaries"}
        </div>

        {metadata?.title && (
          <div style={S.summaryMeta}>
            {metadata.title}
            {metadata.author && ` by ${metadata.author}`}
            {metadata.pages && ` · ${metadata.pages} pages`}
          </div>
        )}

        <p style={S.summaryBody}>
          {content}
          {isStreaming && <BlinkingCursor />}
        </p>
      </div>
    </div>
  );
}

function BlinkingCursor() {
  return (
    <span style={S.cursor}>▊</span>
  );
}

function ActionsMessage({ msg, onAction }) {
  return (
    <div style={S.bubbleBot}>
      {msg.content && <p style={{ ...S.botText, marginBottom: 10 }}>{msg.content}</p>}
      <div style={S.actionBtns}>
        {msg.actions.map((a) => (
          <button key={a.id} style={S.actionBtn} onClick={() => onAction(a.id)}>
            {a.label}
          </button>
        ))}
      </div>
    </div>
  );
}

function ErrorMessage({ msg }) {
  return (
    <div style={S.bubbleBot}>
      <div style={S.errorCard}>
        <span style={S.errorIcon}>⚠</span>
        <p style={S.errorText}>{msg.content}</p>
      </div>
    </div>
  );
}

function TypingIndicator() {
  return (
    <div style={{ ...S.msgRow, justifyContent: "flex-start", animation: "fadeUp 0.2s ease" }}>
      <BotAvatar />
      <div style={S.bubbleBot}>
        <div style={S.typing}>
          <span style={S.typingDot} />
          <span style={{ ...S.typingDot, animationDelay: "0.2s" }} />
          <span style={{ ...S.typingDot, animationDelay: "0.4s" }} />
        </div>
      </div>
    </div>
  );
}


// ─── Shared ──────────────────────────────────────────────────────────

function BrandIcon() {
  return (
    <svg width="28" height="28" viewBox="0 0 28 28" fill="none">
      <rect x="2" y="4" width="18" height="22" rx="2" stroke="var(--accent)" strokeWidth="1.8" fill="none" />
      <rect x="8" y="2" width="18" height="22" rx="2" stroke="var(--accent)" strokeWidth="1.8" fill="var(--cream)" />
      <line x1="12" y1="8" x2="22" y2="8" stroke="var(--border)" strokeWidth="1.2" />
      <line x1="12" y1="12" x2="22" y2="12" stroke="var(--border)" strokeWidth="1.2" />
      <line x1="12" y1="16" x2="19" y2="16" stroke="var(--border)" strokeWidth="1.2" />
    </svg>
  );
}

function BotAvatar() {
  return (
    <div style={S.avatar}>
      <svg width="18" height="18" viewBox="0 0 28 28" fill="none">
        <rect x="2" y="4" width="18" height="22" rx="2" stroke="var(--accent)" strokeWidth="1.8" fill="none" />
        <rect x="8" y="2" width="18" height="22" rx="2" stroke="var(--accent)" strokeWidth="1.8" fill="var(--cream)" />
        <line x1="12" y1="8" x2="22" y2="8" stroke="var(--border)" strokeWidth="1.2" />
        <line x1="12" y1="12" x2="22" y2="12" stroke="var(--border)" strokeWidth="1.2" />
      </svg>
    </div>
  );
}


// ─── Styles ──────────────────────────────────────────────────────────

const S = {
  root: {
    display: "flex", flexDirection: "column", height: "100vh",
    maxWidth: 840, margin: "0 auto",
    borderLeft: "1px solid var(--border-light)", borderRight: "1px solid var(--border-light)",
    backgroundColor: "var(--white)",
  },

  // Header
  header: {
    display: "flex", alignItems: "center", justifyContent: "space-between",
    padding: "14px 24px",
    borderBottom: "1px solid var(--border-light)",
    backgroundColor: "var(--cream)",
  },
  headerLeft: { display: "flex", alignItems: "center", gap: 12 },
  headerTitle: { fontSize: 16, fontWeight: 700, color: "var(--ink)", letterSpacing: -0.2 },
  headerSub: { fontSize: 12, color: "var(--ink-light)", marginTop: 1 },
  headerBadge: {
    display: "flex", alignItems: "center", gap: 6,
    fontSize: 11, fontWeight: 600, color: "var(--success)",
    backgroundColor: "rgba(91,140,90,0.08)", padding: "5px 12px", borderRadius: 20,
  },
  headerDot: {
    width: 7, height: 7, borderRadius: "50%", backgroundColor: "var(--success)",
  },

  // Chat area
  chatArea: {
    flex: 1, overflowY: "auto", overflowX: "hidden",
    border: "2px solid transparent", transition: "all 0.2s",
    position: "relative",
  },
  chatInner: {
    padding: "24px 24px 16px",
    display: "flex", flexDirection: "column", gap: 6,
    minHeight: "100%",
  },
  dropOverlay: {
    position: "absolute", inset: 0,
    display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 12,
    backgroundColor: "rgba(253,250,245,0.92)", zIndex: 10,
    borderRadius: 8,
  },
  dropText: { fontSize: 15, fontWeight: 500, color: "var(--accent)" },

  // Message row
  msgRow: { display: "flex", gap: 10, alignItems: "flex-end", marginBottom: 6 },

  // Avatar
  avatar: {
    width: 32, height: 32, borderRadius: "50%",
    backgroundColor: "var(--paper)", border: "1px solid var(--border-light)",
    display: "flex", alignItems: "center", justifyContent: "center",
    flexShrink: 0,
  },

  // Bubbles
  bubbleBot: {
    padding: "14px 18px", borderRadius: "18px 18px 18px 6px",
    backgroundColor: "var(--paper)", border: "1px solid var(--border-light)",
    fontSize: 15, lineHeight: 1.65, color: "var(--ink)",
  },
  bubbleUser: {
    padding: "12px 18px", borderRadius: "18px 18px 6px 18px",
    backgroundColor: "var(--accent)", color: "var(--white)",
    fontSize: 15, lineHeight: 1.6,
  },
  botText: {
    margin: 0, fontFamily: "var(--font-reading)", fontSize: 16, lineHeight: 1.75,
    whiteSpace: "pre-line",
  },
  userText: { margin: 0 },

  // File card
  fileCard: { display: "flex", alignItems: "center", gap: 12 },
  fileIcon: {
    width: 40, height: 40, borderRadius: 10,
    backgroundColor: "rgba(255,255,255,0.2)",
    display: "flex", alignItems: "center", justifyContent: "center",
    flexShrink: 0,
  },
  fileName: { fontSize: 14, fontWeight: 600, color: "var(--white)" },
  fileMeta: { fontSize: 12, color: "rgba(255,255,255,0.7)", marginTop: 2 },

  // Status card
  statusCard: { display: "flex", flexDirection: "column", gap: 8 },
  statusHeader: { display: "flex", alignItems: "center", gap: 10 },
  statusSpinner: {
    width: 16, height: 16,
    border: "2px solid var(--border)", borderTopColor: "var(--accent)",
    borderRadius: "50%", animation: "spin 0.8s linear infinite", flexShrink: 0,
  },
  statusCheck: {
    fontSize: 14, fontWeight: 700, color: "var(--success)",
    width: 20, height: 20, borderRadius: "50%",
    backgroundColor: "rgba(91,140,90,0.12)",
    display: "flex", alignItems: "center", justifyContent: "center",
  },
  statusFail: {
    fontSize: 14, fontWeight: 700, color: "var(--error)",
    width: 20, height: 20, borderRadius: "50%",
    backgroundColor: "rgba(181,69,58,0.12)",
    display: "flex", alignItems: "center", justifyContent: "center",
  },
  statusLabel: { fontSize: 14, fontWeight: 500, color: "var(--ink)", animation: "progressPulse 2s ease-in-out infinite" },
  statusBarOuter: { height: 4, backgroundColor: "var(--paper-dark)", borderRadius: 2, overflow: "hidden" },
  statusBarInner: { height: "100%", backgroundColor: "var(--accent)", borderRadius: 2, transition: "width 0.6s ease" },
  statusPct: { fontSize: 12, fontWeight: 600, color: "var(--accent)", textAlign: "right" },

  // Summary card
  summaryCard: { display: "flex", flexDirection: "column", gap: 10 },
  summaryBadge: {
    display: "inline-block", fontSize: 10, fontWeight: 700,
    textTransform: "uppercase", letterSpacing: 1.5, color: "var(--accent)",
    backgroundColor: "var(--accent-bg)", padding: "4px 10px", borderRadius: 10,
    alignSelf: "flex-start",
  },
  summaryMeta: { fontSize: 12, color: "var(--ink-light)", fontStyle: "italic" },
  summaryBody: {
    margin: 0, fontFamily: "var(--font-reading)", fontSize: 16, lineHeight: 1.8,
    color: "var(--ink)",
  },

  // Takeaways
  takeawaysList: { display: "flex", flexDirection: "column", gap: 12, marginTop: 4 },
  takeawayItem: { display: "flex", gap: 12, alignItems: "flex-start" },
  takeawayNum: {
    fontFamily: "var(--font-reading)", fontSize: 22, fontWeight: 300,
    color: "var(--accent)", lineHeight: 1, minWidth: 22, textAlign: "right", paddingTop: 3,
  },
  takeawayText: {
    margin: 0, fontFamily: "var(--font-reading)", fontSize: 15, lineHeight: 1.7,
    color: "var(--ink)",
  },

  // Chapters
  chaptersList: { display: "flex", flexDirection: "column", gap: 2, marginTop: 4 },
  chapterItem: { borderBottom: "1px solid var(--border-light)" },
  chapterHead: {
    display: "flex", alignItems: "center", gap: 10, width: "100%",
    padding: "12px 4px", textAlign: "left", backgroundColor: "transparent",
  },
  chapterIdx: { fontSize: 12, fontWeight: 600, color: "var(--accent)", fontVariantNumeric: "tabular-nums" },
  chapterName: { fontSize: 14, fontWeight: 500, color: "var(--ink)", flex: 1 },
  chapterArrow: { fontSize: 14, color: "var(--ink-light)", transition: "transform 0.25s ease" },
  chapterBody: { padding: "0 4px 16px 32px" },

  // Sources
  sourcesList: { display: "flex", flexWrap: "wrap", gap: 6, marginTop: 12 },
  sourceTag: {
    fontSize: 11, fontWeight: 500, color: "var(--accent)",
    backgroundColor: "var(--accent-bg)", padding: "3px 10px", borderRadius: 10,
  },

  // Actions
  actionBtns: { display: "flex", flexWrap: "wrap", gap: 8 },
  actionBtn: {
    padding: "8px 16px", fontSize: 13, fontWeight: 500,
    color: "var(--accent)", backgroundColor: "var(--white)",
    border: "1px solid var(--border)", borderRadius: 20,
    transition: "all 0.15s",
  },

  // Error
  errorCard: { display: "flex", gap: 10, alignItems: "flex-start" },
  errorIcon: { fontSize: 16, color: "var(--error)", flexShrink: 0, marginTop: 1 },
  errorText: { margin: 0, fontSize: 14, color: "var(--error)", lineHeight: 1.5 },

  // Typing
  typing: { display: "flex", gap: 5, padding: "4px 0" },
  typingDot: {
    width: 8, height: 8, borderRadius: "50%",
    backgroundColor: "var(--ink-light)",
    animation: "typingBounce 1s ease-in-out infinite",
  },

  // Input bar
  inputBar: {
    padding: "12px 24px 16px",
    borderTop: "1px solid var(--border-light)",
    backgroundColor: "var(--cream)",
  },
  inputRow: { display: "flex", alignItems: "flex-end", gap: 8 },
  attachBtn: {
    width: 42, height: 42, borderRadius: 12,
    backgroundColor: "var(--paper)",
    border: "1px solid var(--border-light)",
    display: "flex", alignItems: "center", justifyContent: "center",
    color: "var(--ink-muted)", transition: "all 0.15s", flexShrink: 0,
  },
  input: {
    flex: 1, padding: "11px 16px", fontSize: 15,
    border: "1.5px solid var(--border)", borderRadius: 14,
    backgroundColor: "var(--white)", color: "var(--ink)",
    fontFamily: "var(--font-body)", resize: "none",
    lineHeight: 1.5, minHeight: 42, maxHeight: 120,
    transition: "border-color 0.2s",
  },
  sendBtn: {
    width: 42, height: 42, borderRadius: 12,
    backgroundColor: "var(--accent)", color: "var(--white)",
    display: "flex", alignItems: "center", justifyContent: "center",
    transition: "opacity 0.15s", flexShrink: 0,
  },
  inputHint: {
    fontSize: 11, color: "var(--ink-light)", marginTop: 6, textAlign: "center",
  },

  // Streaming cursor
  cursor: {
    display: "inline-block",
    color: "var(--accent)",
    fontWeight: 400,
    fontSize: "0.9em",
    marginLeft: 1,
    animation: "cursorBlink 0.8s step-end infinite",
  },
};
