import { useState, useRef, useEffect, useMemo } from "react";
import { getRuntimeConfig, apiRequest } from "../../lib/api";
import {
    OPENROUTER_RECOMMENDED_MODELS,
    type OpenRouterModelEntry,
    filterOpenRouterModels,
    formatOpenRouterNumber,
    getOpenRouterRecommendedModel,
    normalizeLikelyOpenRouterModelRef,
    parseOpenRouterModels
} from "../../lib/openrouterModels";

interface Message {
    id?: string;
    role: "user" | "assistant" | "system";
    content: string;
    translation?: string;
    isTranslating?: boolean;
}

type StatusTone = "info" | "success" | "warning" | "error";

interface StatusMessage {
    tone: StatusTone;
    message: string;
}

// Browser API fallbacks
const SpeechRecognitionAPI = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
const CHAT_MODEL_STORAGE_KEY = "agent33.chatModel";
const INITIAL_MODEL_CATALOG_STATUS: StatusMessage = {
    tone: "info",
    message: "Use a known-working model below or browse the live catalog."
};

function getInitialChatModel(): string {
    if (typeof window === "undefined") {
        return "";
    }
    return normalizeLikelyOpenRouterModelRef(
        window.localStorage.getItem(CHAT_MODEL_STORAGE_KEY) || ""
    );
}

function extractResultMessage(payload: unknown, fallback: string): string {
    if (!payload || typeof payload !== "object") {
        return fallback;
    }

    const data = payload as Record<string, unknown>;
    const directMessage = [data.message, data.detail, data.error, data.status].find(
        (value) => typeof value === "string" && value.trim() !== ""
    );
    if (typeof directMessage === "string") {
        return directMessage;
    }

    const validationErrors = Array.isArray(data.validation_errors)
        ? data.validation_errors.filter((item): item is string => typeof item === "string" && item.trim() !== "")
        : [];

    return validationErrors.length > 0 ? validationErrors.join(" ") : fallback;
}

interface ChatInterfaceProps {
    token: string;
    apiKey: string;
}

export function ChatInterface({ token, apiKey }: ChatInterfaceProps): JSX.Element {
    const [messages, setMessages] = useState<Message[]>([
        { role: "system", content: "You are a helpful AI assistant." },
        { role: "assistant", content: "Hello! I am AGENT-33. How can I assist you today?" }
    ]);
    const [input, setInput] = useState("");
    const [loading, setLoading] = useState(false);

    // Voice Generation (TTS) State
    const [voiceEnabled, setVoiceEnabled] = useState(false);
    const [availableVoices, setAvailableVoices] = useState<SpeechSynthesisVoice[]>([]);
    const [selectedVoiceURI, setSelectedVoiceURI] = useState<string>("");
    const [playbackRate, setPlaybackRate] = useState<number>(1.0);
    const [lastSpokenText, setLastSpokenText] = useState<string>("");

    // Translation State
    const [translationEnabled, setTranslationEnabled] = useState(false);
    const [translateFrom, setTranslateFrom] = useState("English");
    const [translateTo, setTranslateTo] = useState("Spanish");

    // Settings Modal State
    const [showSettingsModal, setShowSettingsModal] = useState(false);
    const [activeSettingsTab, setActiveSettingsTab] = useState<'translation' | 'audio' | 'model'>('translation');
    const [selectedModel, setSelectedModel] = useState<string>(getInitialChatModel);
    const [modelCatalogStatus, setModelCatalogStatus] = useState<StatusMessage>(INITIAL_MODEL_CATALOG_STATUS);
    const [modelCatalogLoading, setModelCatalogLoading] = useState(false);
    const [modelCatalogLoaded, setModelCatalogLoaded] = useState(false);
    const [modelCatalog, setModelCatalog] = useState<OpenRouterModelEntry[]>([]);
    const [modelSearch, setModelSearch] = useState("");

    // Voice Dictation (STT) State
    const [isRecording, setIsRecording] = useState(false);
    const recognitionRef = useRef<any>(null);

    const messagesEndRef = useRef<HTMLDivElement>(null);
    const { API_BASE_URL } = getRuntimeConfig();

    // Initialize Voices
    useEffect(() => {
        const loadVoices = () => {
            const voices = window.speechSynthesis.getVoices();
            setAvailableVoices(voices);
            if (voices.length > 0 && !selectedVoiceURI) {
                // Try to find a default English voice
                const defaultVoice = voices.find(v => v.lang.startsWith("en-") && v.default) || voices.find(v => v.lang.startsWith("en-")) || voices[0];
                setSelectedVoiceURI(defaultVoice.voiceURI);
            }
        };

        // Chrome requires this event, Safari/Firefox might load immediately
        window.speechSynthesis.onvoiceschanged = loadVoices;
        loadVoices();

        return () => {
            window.speechSynthesis.cancel(); // Stop playing on unmount
        };
    }, []);

    // Initialize Speech Recognition
    useEffect(() => {
        if (SpeechRecognitionAPI) {
            const recognition = new SpeechRecognitionAPI();
            recognition.continuous = true;
            recognition.interimResults = true;
            recognition.lang = 'en-US';

            recognition.onresult = (event: any) => {
                let finalTranscript = '';
                let interimTranscript = '';

                for (let i = event.resultIndex; i < event.results.length; ++i) {
                    if (event.results[i].isFinal) {
                        finalTranscript += event.results[i][0].transcript;
                    } else {
                        interimTranscript += event.results[i][0].transcript;
                    }
                }

                if (finalTranscript) {
                    setInput((prev) => prev + (prev.endsWith(" ") ? "" : " ") + finalTranscript);
                }
            };

            recognition.onerror = (event: any) => {
                console.error("Speech recognition error", event.error);
                setIsRecording(false);
            };

            recognition.onend = () => {
                setIsRecording(false);
            };

            recognitionRef.current = recognition;
        }
    }, []);

    const toggleRecording = () => {
        if (isRecording) {
            recognitionRef.current?.stop();
            setIsRecording(false);
        } else {
            if (recognitionRef.current) {
                recognitionRef.current.start();
                setIsRecording(true);
            } else {
                alert("Speech recognition is not supported in this browser.");
            }
        }
    };

    const scrollToBottom = () => {
        messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
    };

    useEffect(() => {
        scrollToBottom();
    }, [messages]);

    const filteredModelCatalog = useMemo(
        () => filterOpenRouterModels(modelCatalog, modelSearch),
        [modelCatalog, modelSearch]
    );
    const visibleModelCatalog = filteredModelCatalog.slice(0, 8);
    const trimmedSelectedModel = selectedModel.trim();
    const normalizedSelectedModel = normalizeLikelyOpenRouterModelRef(trimmedSelectedModel);
    const selectedCatalogModel = useMemo(
        () => modelCatalog.find((model) => model.id === normalizedSelectedModel) || null,
        [modelCatalog, normalizedSelectedModel]
    );
    const selectedRecommendedModel = useMemo(
        () => getOpenRouterRecommendedModel(normalizedSelectedModel),
        [normalizedSelectedModel]
    );

    useEffect(() => {
        window.localStorage.setItem(CHAT_MODEL_STORAGE_KEY, normalizedSelectedModel);
    }, [normalizedSelectedModel]);

    useEffect(() => {
        if (showSettingsModal && activeSettingsTab === "model" && !modelCatalogLoaded && !modelCatalogLoading) {
            void loadModelCatalog();
        }
    }, [activeSettingsTab, modelCatalogLoaded, modelCatalogLoading, showSettingsModal, token, apiKey]);

    const modelCatalogEmptyMessage =
        modelCatalogStatus.tone === "error"
            ? "Catalog unavailable right now. Type a model ID manually or refresh the catalog."
            : modelSearch.trim() !== ""
                ? "No OpenRouter models match your current search."
                : "No OpenRouter models are currently available.";

    const speakText = (text: string) => {
        if (!voiceEnabled || !window.speechSynthesis) return;

        // Cancel any ongoing speech
        window.speechSynthesis.cancel();

        setLastSpokenText(text);

        const utterance = new SpeechSynthesisUtterance(text);
        const selectedVoice = availableVoices.find(v => v.voiceURI === selectedVoiceURI);

        if (selectedVoice) {
            utterance.voice = selectedVoice;
        }

        utterance.rate = playbackRate;
        window.speechSynthesis.speak(utterance);
    };

    const buildChatRequestBody = (
        chatMessages: Array<{ role: string; content: string }>,
        temperature: number
    ) => {
        const body: {
            model?: string;
            messages: Array<{ role: string; content: string }>;
            temperature: number;
        } = {
            messages: chatMessages,
            temperature
        };
        const model = normalizeLikelyOpenRouterModelRef(selectedModel);
        if (model) {
            body.model = model;
        }
        return body;
    };

    const loadModelCatalog = async (force = false) => {
        if (modelCatalogLoading || (modelCatalogLoaded && !force)) {
            return;
        }

        setModelCatalogLoading(true);
        setModelCatalogStatus({
            tone: "info",
            message: "Loading OpenRouter model catalog..."
        });

        try {
            const res = await apiRequest({
                method: "GET",
                path: "/v1/openrouter/models",
                token,
                apiKey
            });

            if (!res.ok) {
                throw new Error(
                    extractResultMessage(
                        res.data,
                        "Could not load the OpenRouter model catalog. Manual entry is still available."
                    )
                );
            }

            const parsedModels = parseOpenRouterModels(res.data);
            setModelCatalog(parsedModels);
            setModelCatalogLoaded(true);
            setModelCatalogStatus({
                tone: parsedModels.length > 0 ? "success" : "warning",
                message:
                    parsedModels.length > 0
                        ? `Loaded ${parsedModels.length} models from the live catalog.`
                        : "The OpenRouter catalog is currently empty. Manual entry is still available."
            });
        } catch (error: any) {
            setModelCatalog([]);
            setModelCatalogLoaded(true);
            setModelCatalogStatus({
                tone: "error",
                message:
                    error instanceof Error
                        ? error.message
                        : "Could not load the OpenRouter model catalog. Manual entry is still available."
            });
        } finally {
            setModelCatalogLoading(false);
        }
    };

    const handleSend = async () => {
        if (!input.trim() || loading) return;

        // Stop recording if speaking
        if (isRecording) {
            recognitionRef.current?.stop();
            setIsRecording(false);
        }

        const userMsg: Message = { role: "user", content: input };
        setMessages((prev) => [...prev, userMsg]);
        setInput("");
        setLoading(true);

        try {
            const res = await apiRequest({
                method: "POST",
                path: "/v1/chat/completions",
                token: token,
                apiKey: apiKey,
                body: JSON.stringify(buildChatRequestBody([...messages, userMsg], 0.2))
            });

            if (!res.ok) {
                if (res.status === 401) {
                    throw new Error("Unauthorized (401): Your API token has expired or is invalid. Please go to the Integrations tab and click 'Sign In' to refresh it.");
                }
                throw new Error(`API Error: ${res.status}`);
            }

            // res.data will be the parsed JSON object
            const data = res.data as any;
            const reply = data.choices?.[0]?.message?.content || "No response received.";
            const msgId = Date.now().toString() + Math.random().toString();
            const newMsg: Message = { id: msgId, role: "assistant", content: reply, isTranslating: translationEnabled };

            setMessages((prev) => [...prev, newMsg]);

            if (translationEnabled) {
                // Fire off translation in the background
                (async () => {
                    try {
                        const transRes = await apiRequest({
                            method: "POST",
                            path: "/v1/chat/completions",
                            token: token,
                            apiKey: apiKey,
                            body: JSON.stringify(buildChatRequestBody([
                                    { role: "system", content: `You are a professional translator. Translate the following text from ${translateFrom} to ${translateTo}. Return ONLY the direct translation, nothing else, no quotes, no markdown.` },
                                    { role: "user", content: reply }
                                ], 0.1))
                        });

                        if (transRes.ok) {
                            const tData = transRes.data as any;
                            const tReply = tData.choices?.[0]?.message?.content || "Translation failed.";
                            setMessages(prev => prev.map(m => m.id === msgId ? { ...m, translation: tReply, isTranslating: false } : m));
                        } else {
                            throw new Error("Translation request failed");
                        }
                    } catch (e: any) {
                        console.error("Auto-translation error:", e);
                        setMessages(prev => prev.map(m => m.id === msgId ? { ...m, translation: `[Error: ${e.message}]`, isTranslating: false } : m));
                    }
                })();
            }

            // Auto-speak the response if enabled
            speakText(reply);

        } catch (err: any) {
            console.error(err);
            setMessages((prev) => [...prev, { role: "assistant", content: `Error: ${err.message}` }]);
        } finally {
            setLoading(false);
        }
    };

    const handleTranslate = async (index: number) => {
        const msgToTranslate = messages[index];
        if (!msgToTranslate || !msgToTranslate.content) return;

        setMessages(prev => prev.map((m, i) => i === index ? { ...m, isTranslating: true } : m));

        try {
            const res = await apiRequest({
                method: "POST",
                path: "/v1/chat/completions",
                token: token,
                apiKey: apiKey,
                body: JSON.stringify(buildChatRequestBody([
                        { role: "system", content: `You are a professional translator. Translate the following text from ${translateFrom} to ${translateTo}. Return ONLY the direct translation, nothing else, no quotes, no markdown.` },
                        { role: "user", content: msgToTranslate.content }
                    ], 0.1))
            });

            if (!res.ok) {
                if (res.status === 401) {
                    throw new Error("Unauthorized (401). Please sign in on the Integrations tab.");
                }
                throw new Error(`API Error: ${res.status}`);
            }

            const data = res.data as any;
            const translation = data.choices?.[0]?.message?.content || "Translation failed.";

            setMessages(prev => prev.map((m, i) => i === index ? { ...m, translation, isTranslating: false } : m));

        } catch (err: any) {
            console.error("Translation error:", err);
            setMessages(prev => prev.map((m, i) => i === index ? { ...m, translation: `[Error: ${err.message}]`, isTranslating: false } : m));
        }
    };

    // Retroactively translate the last 3 assistant messages when toggled ON
    useEffect(() => {
        if (translationEnabled && messages.length > 0) {
            // Find the indices of the last 3 assistant messages that don't have a translation yet
            const indicesToTranslate: number[] = [];
            for (let i = messages.length - 1; i >= 0 && indicesToTranslate.length < 3; i--) {
                const msg = messages[i];
                if (msg.role === "assistant" && !msg.translation && !msg.isTranslating) {
                    indicesToTranslate.push(i);
                }
            }
            // Fire off translations for those specific indices
            indicesToTranslate.forEach(index => handleTranslate(index));
        }
    }, [translationEnabled, translateFrom, translateTo]);

    const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            handleSend();
        }
    };

    return (
        <div className="chat-interface" role="region" aria-label="Chat interface">
            <div className="chat-messages" role="log" aria-label="Chat messages" aria-live="polite">
                {messages.map((msg, index) => {
                    if (msg.role === "system") return null;
                    return (
                        <div key={index} className={`chat-bubble-container ${msg.role}`}>
                            {msg.role === "user" && (
                                <div className="chat-bubble-actions">
                                    <button
                                        className="inline-action-btn"
                                        onClick={() => handleTranslate(index)}
                                        aria-label={`Translate from ${translateFrom} to ${translateTo}`}
                                        title={`Translate from ${translateFrom} to ${translateTo}`}
                                        disabled={msg.isTranslating}
                                    >
                                        <span aria-hidden="true">🌐</span>
                                    </button>
                                </div>
                            )}
                            <div className={`chat-bubble ${msg.role}`}>
                                {msg.content}
                                {msg.translation && (
                                    <div className="chat-translation">
                                        <hr />
                                        <i>{msg.translation}</i>
                                    </div>
                                )}
                                {msg.isTranslating && (
                                    <div className="chat-translation translating" aria-live="polite">
                                        <hr />
                                        <i>Translating {translateFrom} to {translateTo}...</i>
                                    </div>
                                )}
                            </div>
                            {msg.role === "assistant" && (
                                <div className="chat-bubble-actions">
                                    {voiceEnabled && (
                                        <button
                                            className="inline-action-btn"
                                            onClick={() => speakText(msg.content)}
                                            aria-label="Read aloud"
                                            title="Read aloud"
                                        >
                                            <span aria-hidden="true">🔊</span>
                                        </button>
                                    )}
                                    <button
                                        className="inline-action-btn"
                                        onClick={() => handleTranslate(index)}
                                        aria-label={`Translate from ${translateFrom} to ${translateTo}`}
                                        title={`Translate from ${translateFrom} to ${translateTo}`}
                                        disabled={msg.isTranslating}
                                    >
                                        <span aria-hidden="true">🌐</span>
                                    </button>
                                </div>
                            )}
                        </div>
                    );
                })}
                {loading && (
                    <div className="chat-bubble-container assistant" aria-live="polite">
                        <div className="chat-bubble assistant typing-indicator" role="status" aria-label="Assistant is typing">
                            <span></span><span></span><span></span>
                        </div>
                    </div>
                )}
                <div ref={messagesEndRef} />
            </div>

            <div className="chat-input-area">
                <button
                    className={`mic-btn ${isRecording ? "recording" : ""}`}
                    onClick={toggleRecording}
                    aria-label={isRecording ? "Stop dictation" : "Start dictation"}
                    aria-pressed={isRecording}
                    title={isRecording ? "Stop dictation" : "Start dictation"}
                >
                    <span aria-hidden="true">🎤</span>
                </button>
                <textarea
                    value={input}
                    onChange={(e) => setInput(e.target.value)}
                    onKeyDown={handleKeyDown}
                    aria-label="Message input"
                    placeholder="Message AGENT-33 (or click the mic to speak)..."
                    rows={1}
                    disabled={loading}
                />
                <button onClick={handleSend} disabled={(!input.trim() && !isRecording) || loading} className="chat-send-bin" aria-label="Send message" title="Send (Enter)">
                    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" width="24" height="24" aria-hidden="true">
                        <path d="M3.478 2.404a.75.75 0 0 0-.926.941l2.432 7.905H13.5a.75.75 0 0 1 0 1.5H4.984l-2.432 7.905a.75.75 0 0 0 .926.94 60.519 60.519 0 0 0 18.445-8.986.75.75 0 0 0 0-1.218A60.517 60.517 0 0 0 3.478 2.404Z" />
                    </svg>
                </button>
                <button
                    className="settings-gear-btn"
                    onClick={() => setShowSettingsModal(prev => !prev)}
                    aria-label="Chat settings"
                    aria-expanded={showSettingsModal}
                    title="Chat Settings"
                >
                    <span aria-hidden="true">⚙️</span>
                </button>

                {showSettingsModal && (
                    <div className="settings-popover" role="dialog" aria-label="Chat settings" aria-modal="false">
                        <div className="settings-popover-header">
                            <h2>Chat Settings</h2>
                            <button className="settings-close-btn" onClick={() => setShowSettingsModal(false)} aria-label="Close settings">✕</button>
                        </div>

                        <div className="chat-tab-group compact">
                            <button
                                className={`chat-tab-btn ${activeSettingsTab === 'translation' ? "active" : ""}`}
                                onClick={() => setActiveSettingsTab('translation')}
                            >
                                Translation Options
                            </button>
                            <button
                                className={`chat-tab-btn ${activeSettingsTab === 'audio' ? "active" : ""}`}
                                onClick={() => setActiveSettingsTab('audio')}
                            >
                                Audio Response
                            </button>
                            <button
                                className={`chat-tab-btn ${activeSettingsTab === 'model' ? "active" : ""}`}
                                onClick={() => setActiveSettingsTab('model')}
                            >
                                Model & Provider
                            </button>
                        </div>

                        <div className="chat-tab-panel compact">
                            {activeSettingsTab === 'translation' && (
                                <div className="translation-lang-selects">
                                    <div className="setting-row">
                                        <span className="setting-label">Auto-Translate</span>
                                        <label className="voice-toggle">
                                            <input
                                                type="checkbox"
                                                checked={translationEnabled}
                                                onChange={(e) => setTranslationEnabled(e.target.checked)}
                                            />
                                            <span className="slider"></span>
                                        </label>
                                    </div>

                                    <span id="translate-from-label">From:</span>
                                    <select className="voice-select inline" aria-labelledby="translate-from-label" value={translateFrom} onChange={(e) => setTranslateFrom(e.target.value)}>
                                        <option value="English">English</option>
                                        <option value="Spanish">Spanish</option>
                                        <option value="French">French</option>
                                        <option value="German">German</option>
                                        <option value="Italian">Italian</option>
                                        <option value="Japanese">Japanese</option>
                                        <option value="Chinese">Chinese</option>
                                        <option value="Russian">Russian</option>
                                        <option value="Arabic">Arabic</option>
                                        <option value="Korean">Korean</option>
                                        <option value="Portuguese">Portuguese</option>
                                    </select>

                                    <span id="translate-to-label">To:</span>
                                    <select className="voice-select inline" aria-labelledby="translate-to-label" value={translateTo} onChange={(e) => setTranslateTo(e.target.value)}>
                                        <option value="English">English</option>
                                        <option value="Spanish">Spanish</option>
                                        <option value="French">French</option>
                                        <option value="German">German</option>
                                        <option value="Italian">Italian</option>
                                        <option value="Japanese">Japanese</option>
                                        <option value="Chinese">Chinese</option>
                                        <option value="Russian">Russian</option>
                                        <option value="Arabic">Arabic</option>
                                        <option value="Korean">Korean</option>
                                        <option value="Portuguese">Portuguese</option>
                                    </select>
                                </div>
                            )}

                            {activeSettingsTab === 'audio' && (
                                <div className="audio-panel-grid">
                                    <div className="setting-row">
                                        <span className="setting-label">Enable TTS (Read Aloud)</span>
                                        <label className="voice-toggle">
                                            <input
                                                type="checkbox"
                                                checked={voiceEnabled}
                                                onChange={(e) => {
                                                    setVoiceEnabled(e.target.checked);
                                                    if (!e.target.checked) window.speechSynthesis.cancel();
                                                }}
                                            />
                                            <span className="slider"></span>
                                        </label>
                                    </div>

                                    {voiceEnabled && (
                                        <div className="audio-actions-row">
                                            <select
                                                className="voice-select"
                                                aria-label="Voice selection"
                                                value={selectedVoiceURI}
                                                onChange={(e) => setSelectedVoiceURI(e.target.value)}
                                            >
                                                {availableVoices.map(voice => (
                                                    <option key={voice.voiceURI} value={voice.voiceURI}>
                                                        {voice.name} ({voice.lang})
                                                    </option>
                                                ))}
                                            </select>

                                            <select
                                                className="voice-select voice-speed inline"
                                                aria-label="Playback speed"
                                                value={playbackRate}
                                                onChange={(e) => {
                                                    const newRate = parseFloat(e.target.value);
                                                    setPlaybackRate(newRate);
                                                    if (window.speechSynthesis.speaking && lastSpokenText) {
                                                        window.speechSynthesis.cancel();
                                                        setTimeout(() => {
                                                            const utterance = new SpeechSynthesisUtterance(lastSpokenText);
                                                            const selectedVoice = availableVoices.find(v => v.voiceURI === selectedVoiceURI);
                                                            if (selectedVoice) {
                                                                utterance.voice = selectedVoice;
                                                            }
                                                            utterance.rate = newRate;
                                                            window.speechSynthesis.speak(utterance);
                                                        }, 50);
                                                    }
                                                }}
                                            >
                                                <option value={0.8}>0.8x</option>
                                                <option value={1.0}>1x</option>
                                                <option value={1.2}>1.2x</option>
                                                <option value={1.5}>1.5x</option>
                                                <option value={2.0}>2x</option>
                                                <option value={2.5}>2.5x</option>
                                                <option value={3.0}>3x</option>
                                            </select>

                                            <button
                                                className="replay-audio-btn"
                                                onClick={() => lastSpokenText && speakText(lastSpokenText)}
                                                aria-label="Replay last audio message"
                                                title="Replay last audio message"
                                                disabled={!lastSpokenText}
                                            >
                                                <span aria-hidden="true">🔄</span>
                                            </button>

                                            <button
                                                className="stop-audio-btn"
                                                onClick={() => window.speechSynthesis.cancel()}
                                                aria-label="Stop playing audio"
                                                title="Stop playing audio"
                                            >
                                                <span aria-hidden="true">⏹️</span>
                                            </button>
                                        </div>
                                    )}
                                </div>
                            )}

                            {activeSettingsTab === 'model' && (
                                <div className="audio-panel-grid">
                                    <div className="setting-row chat-model-summary">
                                        <div className="chat-model-summary__body">
                                            <span className="setting-label">Current selection</span>
                                            <strong className="chat-model-summary__value">
                                                {trimmedSelectedModel
                                                    ? selectedCatalogModel?.name || normalizedSelectedModel
                                                    : "Server default"}
                                            </strong>
                                            <span className="openrouter-model-id">
                                                {trimmedSelectedModel
                                                    ? normalizedSelectedModel
                                                    : "Uses the server default model configured for AGENT-33."}
                                            </span>
                                            {trimmedSelectedModel ? (
                                                <div className="openrouter-model-capabilities openrouter-selection-tags">
                                                    <span
                                                        className={`model-pill ${selectedRecommendedModel ? "model-pill--recommended" : "model-pill--warning"}`}
                                                    >
                                                        {selectedRecommendedModel
                                                            ? selectedRecommendedModel.badgeLabel
                                                            : "Catalog/manual model"}
                                                    </span>
                                                </div>
                                            ) : null}
                                        </div>
                                        <button
                                            type="button"
                                            className="setup-button-secondary chat-model-default-btn"
                                            onClick={() => setSelectedModel("")}
                                            disabled={!trimmedSelectedModel}
                                        >
                                            Use server default
                                        </button>
                                    </div>

                                    <label className="setting-label" htmlFor="chat-model-input">Model override</label>
                                    <input
                                        id="chat-model-input"
                                        className="voice-select"
                                        type="text"
                                        value={selectedModel}
                                        onChange={(e) => setSelectedModel(e.target.value)}
                                        onBlur={(e) =>
                                            setSelectedModel(
                                                normalizeLikelyOpenRouterModelRef(e.target.value)
                                            )
                                        }
                                        placeholder="Server default (e.g. openrouter/qwen/qwen3-coder-flash)"
                                        aria-describedby="chat-model-help"
                                    />
                                    <div id="chat-model-help" className="openrouter-inline-help">
                                        Pick a known-working ref below, browse the public catalog, or type any
                                        OpenRouter model ID manually. Leave the field blank to use the server
                                        default for this browser.
                                    </div>

                                    <div className="integration-status integration-status--warning openrouter-advisory">
                                        Catalog results can still fail for your OpenRouter account or provider
                                        route. If an override fails, clear it or switch to one of the
                                        known-working refs below.
                                    </div>

                                    <div
                                        className="openrouter-recommendations"
                                        role="group"
                                        aria-labelledby="chat-recommended-models-heading"
                                    >
                                        <div className="openrouter-recommendations__header">
                                            <h4 id="chat-recommended-models-heading">Known working models</h4>
                                            <p>Explicit OpenRouter-ready refs verified with this setup.</p>
                                        </div>
                                        <div className="openrouter-recommendation-list">
                                            {OPENROUTER_RECOMMENDED_MODELS.map((model) => {
                                                const isSelected = normalizedSelectedModel === model.id;
                                                return (
                                                    <button
                                                        key={model.id}
                                                        type="button"
                                                        className={`openrouter-recommendation-button${isSelected ? " is-selected" : ""}`}
                                                        onClick={() => setSelectedModel(model.id)}
                                                        aria-pressed={isSelected}
                                                        aria-label={`Use ${model.id} as chat model override`}
                                                    >
                                                        <div className="openrouter-recommendation-button__top">
                                                            <strong className="openrouter-recommendation-button__name">
                                                                {model.name}
                                                            </strong>
                                                            <span className="model-pill model-pill--recommended">
                                                                {model.badgeLabel}
                                                            </span>
                                                        </div>
                                                        <span className="openrouter-model-id openrouter-recommendation-id">
                                                            {model.id}
                                                        </span>
                                                        <p className="openrouter-recommendation-button__description">
                                                            {model.description}
                                                        </p>
                                                    </button>
                                                );
                                            })}
                                        </div>
                                    </div>

                                    {trimmedSelectedModel && !selectedRecommendedModel ? (
                                        <div className="integration-status integration-status--warning openrouter-selection-warning">
                                            This override is still catalog/manual only. Catalog presence does not
                                            guarantee your account/provider can route it. If chat fails, clear the
                                            override or switch to openrouter/qwen/qwen3-coder-flash.
                                        </div>
                                    ) : null}

                                    <div className="chat-model-toolbar">
                                        <label htmlFor="chat-model-search" className="openrouter-search-field">
                                            <span>Search model catalog</span>
                                            <input
                                                id="chat-model-search"
                                                type="search"
                                                value={modelSearch}
                                                onChange={(e) => setModelSearch(e.target.value)}
                                                placeholder="Search models, vendors, or capabilities"
                                            />
                                        </label>
                                        <button
                                            type="button"
                                            className="setup-button-secondary chat-model-refresh-btn"
                                            onClick={() => void loadModelCatalog(true)}
                                            disabled={modelCatalogLoading}
                                        >
                                            {modelCatalogLoading ? "Loading..." : "Refresh catalog"}
                                        </button>
                                    </div>

                                    <div
                                        className={`integration-status integration-status--${modelCatalogStatus.tone}`}
                                        role={modelCatalogStatus.tone === "error" ? "alert" : "status"}
                                        aria-live="polite"
                                    >
                                        {modelCatalogStatus.message}
                                    </div>

                                    <p className="openrouter-catalog-count">
                                        {modelCatalogLoading
                                            ? "Loading models..."
                                            : modelCatalog.length > 0
                                                ? `${filteredModelCatalog.length} of ${modelCatalog.length} model${modelCatalog.length === 1 ? "" : "s"} match${filteredModelCatalog.length === 1 ? "es" : ""} your search. Catalog-listed models can still be unavailable for this account/provider.`
                                                : "Manual entry remains available even when the catalog is empty or unavailable."}
                                    </p>

                                    {visibleModelCatalog.length > 0 ? (
                                        <ul className="openrouter-model-list chat-model-list" aria-label="OpenRouter chat model results">
                                            {visibleModelCatalog.map((model) => {
                                                const isSelected = normalizedSelectedModel === model.id;
                                                const recommendedModel = getOpenRouterRecommendedModel(model.id);
                                                return (
                                                    <li
                                                        key={model.id}
                                                        className={`openrouter-model-item${isSelected ? " is-selected" : ""}`}
                                                    >
                                                        <div className="openrouter-model-item__top">
                                                            <div>
                                                                <h5>{model.name}</h5>
                                                                <p className="openrouter-model-id">{model.id}</p>
                                                            </div>
                                                            <button
                                                                type="button"
                                                                className="setup-button-secondary"
                                                                onClick={() => setSelectedModel(model.id)}
                                                                aria-pressed={isSelected}
                                                                aria-label={isSelected ? `${model.name} selected` : `Use ${model.name}`}
                                                            >
                                                                {isSelected ? "Selected" : "Use model"}
                                                            </button>
                                                        </div>

                                                        {model.description ? <p>{model.description}</p> : null}

                                                        <div className="openrouter-model-metadata">
                                                            {recommendedModel ? (
                                                                <span className="model-pill model-pill--recommended">
                                                                    {recommendedModel.badgeLabel}
                                                                </span>
                                                            ) : null}
                                                            {model.vendor ? (
                                                                <span className="model-pill">{model.vendor}</span>
                                                            ) : null}
                                                            {model.provider && model.provider !== model.vendor ? (
                                                                <span className="model-pill">{model.provider}</span>
                                                            ) : null}
                                                            {model.contextLength !== null ? (
                                                                <span className="model-pill">
                                                                    Context {formatOpenRouterNumber(model.contextLength)}
                                                                </span>
                                                            ) : null}
                                                            {model.maxCompletionTokens !== null ? (
                                                                <span className="model-pill">
                                                                    Max output {formatOpenRouterNumber(model.maxCompletionTokens)}
                                                                </span>
                                                            ) : null}
                                                            {model.promptPrice ? (
                                                                <span className="model-pill">Prompt {model.promptPrice}</span>
                                                            ) : model.isFree ? (
                                                                <span className="model-pill">Free</span>
                                                            ) : null}
                                                            {model.moderated ? (
                                                                <span className="model-pill">Moderated</span>
                                                            ) : null}
                                                        </div>

                                                        {model.capabilities.length > 0 ? (
                                                            <div className="openrouter-model-capabilities">
                                                                {model.capabilities.slice(0, 4).map((capability) => (
                                                                    <span key={capability} className="model-capability-pill">
                                                                        {capability}
                                                                    </span>
                                                                ))}
                                                            </div>
                                                        ) : null}
                                                    </li>
                                                );
                                            })}
                                        </ul>
                                    ) : (
                                        <div className="openrouter-empty-state" role="status" aria-live="polite">
                                            {modelCatalogLoaded ? modelCatalogEmptyMessage : "Load the catalog to browse available models."}
                                        </div>
                                    )}
                                </div>
                            )}
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
}
