import { useCallback, useEffect, useMemo, useState } from "react";

import type { ApiResult } from "../../types";
import {
  approveReviewAsset,
  asIngestionAssetHistoryResponse,
  asIngestionAssetList,
  fetchAssetHistory,
  fetchReviewQueue,
  rejectReviewAsset
} from "./api";
import { formatTimestamp, getStatusClass, getStatusLabel } from "./helpers";
import type {
  IngestionAssetHistoryEntry,
  IngestionAssetHistoryResponse,
  IngestionAssetSummary
} from "./types";

interface IngestionReviewPanelProps {
  token: string;
  apiKey: string;
  onResult: (label: string, result: ApiResult) => void;
}

type ReviewAction = "approve" | "reject";

function stringifyMetadata(value: Record<string, unknown>): string {
  return JSON.stringify(value, null, 2);
}

function getTimelineTone(entry: IngestionAssetHistoryEntry): string {
  if (entry.event_type === "quarantined" || entry.event_type === "rejected") {
    return "log-error";
  }
  if (entry.event_type === "review_required") {
    return "log-warning";
  }
  return "log-info";
}

function getTimelineLabel(entry: IngestionAssetHistoryEntry): string {
  switch (entry.event_type) {
    case "ingested":
      return "Asset ingested";
    case "review_required":
      return "Marked for review";
    case "quarantined":
      return "Quarantined";
    case "approved":
      return "Approved";
    case "rejected":
      return "Rejected";
    default:
      return `${getStatusLabel(entry.from_status)} → ${getStatusLabel(entry.to_status)}`;
  }
}

export function IngestionReviewPanel({
  token,
  apiKey,
  onResult
}: IngestionReviewPanelProps): JSX.Element {
  const [assets, setAssets] = useState<IngestionAssetSummary[]>([]);
  const [selectedAssetId, setSelectedAssetId] = useState<string | null>(null);
  const [assetHistory, setAssetHistory] = useState<IngestionAssetHistoryResponse | null>(null);
  const [queueError, setQueueError] = useState("");
  const [historyError, setHistoryError] = useState("");
  const [actionError, setActionError] = useState("");
  const [actionSuccess, setActionSuccess] = useState("");
  const [loadingQueue, setLoadingQueue] = useState(false);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [actionInFlight, setActionInFlight] = useState<ReviewAction | null>(null);
  const [operator, setOperator] = useState("operations-hub");
  const [reason, setReason] = useState("");
  const [confidenceFilter, setConfidenceFilter] = useState("all");
  const [attentionFilter, setAttentionFilter] = useState("all");
  const [textFilter, setTextFilter] = useState("");

  const loadQueue = useCallback(async (): Promise<IngestionAssetSummary[] | null> => {
    if (!token && !apiKey) {
      return null;
    }
    setLoadingQueue(true);
    try {
      const result = await fetchReviewQueue(token, apiKey);
      onResult("Operations Hub - Review Queue", result);
      const queue = asIngestionAssetList(result.data);
      if (!result.ok || queue === null) {
        setQueueError(`Failed to load review queue (${result.status})`);
        return null;
      }
      setQueueError("");
      setAssets(queue);
      if (queue.length === 0) {
        return queue;
      }
      if (selectedAssetId === null || !queue.some((asset) => asset.id === selectedAssetId)) {
        setSelectedAssetId(queue[0].id);
      }
      return queue;
    } catch (error) {
      const message = error instanceof Error ? error.message : "Unknown review queue error";
      setQueueError(message);
      return null;
    } finally {
      setLoadingQueue(false);
    }
  }, [apiKey, onResult, selectedAssetId, token]);

  const loadHistory = useCallback(
    async (assetId: string): Promise<void> => {
      if (!token && !apiKey) {
        return;
      }
      setLoadingHistory(true);
      try {
        const result = await fetchAssetHistory(assetId, token, apiKey);
        onResult(`Operations Hub - Asset History ${assetId}`, result);
        const history = asIngestionAssetHistoryResponse(result.data);
        if (!result.ok || history === null) {
          setHistoryError(`Failed to load asset history (${result.status})`);
          return;
        }
        setHistoryError("");
        setAssetHistory(history);
      } catch (error) {
        const message = error instanceof Error ? error.message : "Unknown asset history error";
        setHistoryError(message);
      } finally {
        setLoadingHistory(false);
      }
    },
    [apiKey, onResult, token]
  );

  useEffect(() => {
    void loadQueue();
    const interval = setInterval(() => {
      void loadQueue();
    }, 5000);
    return () => clearInterval(interval);
  }, [loadQueue]);

  useEffect(() => {
    if (selectedAssetId === null) {
      setAssetHistory(null);
      setHistoryError("");
      return;
    }
    loadHistory(selectedAssetId);
  }, [loadHistory, selectedAssetId]);

  const selectedAsset = useMemo(() => {
    if (selectedAssetId === null) {
      return null;
    }
    if (assetHistory?.asset.id === selectedAssetId) {
      return assetHistory.asset;
    }
    return assets.find((asset) => asset.id === selectedAssetId) ?? null;
  }, [assetHistory, assets, selectedAssetId]);
  const filteredAssets = useMemo(() => {
    const normalizedText = textFilter.trim().toLowerCase();
    return assets.filter((asset) => {
      const matchesConfidence =
        confidenceFilter === "all" || asset.confidence.toLowerCase() === confidenceFilter;
      const matchesAttention =
        attentionFilter === "all" ||
        (attentionFilter === "quarantine" && asset.metadata.quarantine === true) ||
        (attentionFilter === "review_required" && asset.metadata.review_required === true);
      const matchesText =
        normalizedText === "" ||
        asset.name.toLowerCase().includes(normalizedText) ||
        asset.id.toLowerCase().includes(normalizedText) ||
        (asset.source_uri ?? "").toLowerCase().includes(normalizedText);
      return matchesConfidence && matchesAttention && matchesText;
    });
  }, [assets, attentionFilter, confidenceFilter, textFilter]);
  const availableConfidence = useMemo(() => {
    const values = new Set<string>(["all"]);
    assets.forEach((asset) => values.add(asset.confidence.toLowerCase()));
    return [...values];
  }, [assets]);
  const timelineEntries = useMemo(() => {
    if (assetHistory?.asset.id !== selectedAssetId) {
      return [];
    }
    return assetHistory.history;
  }, [assetHistory, selectedAssetId]);

  async function handleAction(action: ReviewAction): Promise<void> {
    if (selectedAsset === null) {
      return;
    }
    const trimmedOperator = operator.trim();
    const trimmedReason = reason.trim();
    if (trimmedOperator === "" || trimmedReason === "") {
      setActionError("Operator and review notes are required.");
      return;
    }

    setActionError("");
    setActionSuccess("");
    setActionInFlight(action);
    try {
      const request = action === "approve" ? approveReviewAsset : rejectReviewAsset;
      const result = await request(selectedAsset.id, trimmedOperator, trimmedReason, token, apiKey);
      onResult(`Operations Hub - ${action}`, result);
      if (!result.ok) {
        setActionError(`${getStatusLabel(action)} failed (${result.status})`);
        return;
      }
      setActionSuccess(
        action === "approve"
          ? `${selectedAsset.name} approved and moved to validated.`
          : `${selectedAsset.name} rejected and revoked.`
      );
      const queue = await loadQueue();
      if (queue !== null && (queue.length === 0 || queue.some((asset) => asset.id === selectedAsset.id))) {
        await loadHistory(selectedAsset.id);
      }
      setReason("");
    } catch (error) {
      const message = error instanceof Error ? error.message : "Unknown review action error";
      setActionError(message);
    } finally {
      setActionInFlight(null);
    }
  }

  return (
    <section className="ingestion-review-panel">
      <header className="review-panel-head">
        <div>
          <h3>Ingestion Review Queue</h3>
          <p>
            Review candidate skills, packs, and assets before they become usable. Quarantined items
            stay visible here until an operator approves or rejects them.
          </p>
        </div>
        <div className="review-panel-meta">
          <span>{filteredAssets.length} shown</span>
          <span>{assets.length} awaiting review</span>
        </div>
      </header>
      <div className="review-panel-toolbar" aria-label="Review queue filters">
        <label>
          Search assets
          <input
            placeholder="Name, id, or source"
            value={textFilter}
            onChange={(event) => setTextFilter(event.target.value)}
          />
        </label>
        <label>
          Confidence
          <select value={confidenceFilter} onChange={(event) => setConfidenceFilter(event.target.value)}>
            {availableConfidence.map((confidence) => (
              <option key={confidence} value={confidence}>
                {confidence === "all" ? "All confidence levels" : getStatusLabel(confidence)}
              </option>
            ))}
          </select>
        </label>
        <label>
          Attention
          <select value={attentionFilter} onChange={(event) => setAttentionFilter(event.target.value)}>
            <option value="all">All review items</option>
            <option value="review_required">Review required</option>
            <option value="quarantine">Quarantined only</option>
          </select>
        </label>
      </div>
      <div className="review-panel-content">
        <div className="review-asset-list">
          {queueError ? <p className="ops-hub-error" role="alert">{queueError}</p> : null}
          {loadingQueue && assets.length === 0 ? (
            <p className="ops-hub-loading">Loading review queue...</p>
          ) : null}
          {assets.length === 0 && !loadingQueue && !queueError ? (
            <p className="ops-hub-empty">No assets currently require review.</p>
          ) : null}
          {assets.length > 0 && filteredAssets.length === 0 ? (
            <p className="ops-hub-empty">No assets match the current filters.</p>
          ) : null}
          {filteredAssets.map((asset) => (
            <article
              key={asset.id}
              className={`ops-hub-process-item ${selectedAssetId === asset.id ? "selected" : ""}`}
              onClick={() => setSelectedAssetId(asset.id)}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  setSelectedAssetId(asset.id);
                }
              }}
              tabIndex={0}
              role="button"
              aria-pressed={selectedAssetId === asset.id}
            >
              <div className="process-item-header">
                <h4>{asset.name}</h4>
                <span className={`process-status ${getStatusClass(asset.status)}`}>
                  {getStatusLabel(asset.status)}
                </span>
              </div>
              <p className="process-item-id">{asset.id}</p>
              <p className="process-item-time">
                {getStatusLabel(asset.asset_type)} • {getStatusLabel(asset.confidence)} confidence
              </p>
              <div className="review-asset-flags">
                {asset.metadata.review_required === true ? (
                  <span className="review-asset-flag">Review required</span>
                ) : null}
                {asset.metadata.quarantine === true ? (
                  <span className="review-asset-flag review-asset-flag-danger">Quarantine</span>
                ) : null}
              </div>
            </article>
          ))}
        </div>

        <div className="ops-hub-detail review-detail">
          {selectedAsset === null ? (
            <p className="ops-hub-placeholder">Select an asset to inspect its history.</p>
          ) : null}
          {loadingHistory ? <p className="ops-hub-loading">Loading asset history...</p> : null}
          {historyError ? <p className="ops-hub-error" role="alert">{historyError}</p> : null}
          {actionError ? <p className="ops-hub-error" role="alert">{actionError}</p> : null}
          {actionSuccess ? <p className="review-action-success">{actionSuccess}</p> : null}
          {selectedAsset !== null && !loadingHistory ? (
            <div className="process-detail">
              <h3>{selectedAsset.name}</h3>
              <div className="detail-field">
                <span className="detail-label">Asset ID</span>
                <span>{selectedAsset.id}</span>
              </div>
              <div className="detail-field">
                <span className="detail-label">Type</span>
                <span>{getStatusLabel(selectedAsset.asset_type)}</span>
              </div>
              <div className="detail-field">
                <span className="detail-label">Status</span>
                <span className={`process-status ${getStatusClass(selectedAsset.status)}`}>
                  {getStatusLabel(selectedAsset.status)}
                </span>
              </div>
              <div className="detail-field">
                <span className="detail-label">Confidence</span>
                <span>{getStatusLabel(selectedAsset.confidence)}</span>
              </div>
              <div className="detail-field">
                <span className="detail-label">Source</span>
                <span>{selectedAsset.source_uri ?? "Unknown"}</span>
              </div>
              <div className="detail-field">
                <span className="detail-label">Created</span>
                <span>{formatTimestamp(selectedAsset.created_at)}</span>
              </div>
              <div className="detail-field">
                <span className="detail-label">Updated</span>
                <span>{formatTimestamp(selectedAsset.updated_at)}</span>
              </div>

              <div className="detail-section">
                <h4>Operator action</h4>
                <div className="review-action-form">
                  <label>
                    Operator
                    <input value={operator} onChange={(event) => setOperator(event.target.value)} />
                  </label>
                  <label>
                    Review notes
                    <textarea
                      rows={3}
                      value={reason}
                      onChange={(event) => setReason(event.target.value)}
                      placeholder="Why are you approving or rejecting this asset?"
                    />
                  </label>
                </div>
                <div className="control-buttons">
                  <button
                    disabled={actionInFlight !== null}
                    onClick={() => handleAction("approve")}
                  >
                    Approve
                  </button>
                  <button
                    className="control-danger"
                    disabled={actionInFlight !== null}
                    onClick={() => handleAction("reject")}
                  >
                    Reject
                  </button>
                </div>
              </div>

              <div className="detail-section">
                <h4>Metadata</h4>
                <pre className="detail-metadata">{stringifyMetadata(selectedAsset.metadata)}</pre>
              </div>

              <div className="detail-section">
                <h4>Timeline</h4>
                <div className="detail-log">
                  {timelineEntries.map((entry) => (
                    <div key={`${entry.event_type}-${entry.occurred_at}`} className={`log-entry ${getTimelineTone(entry)}`}>
                      <span className="log-time">{formatTimestamp(entry.occurred_at)}</span>
                      <strong className="review-timeline-title">{getTimelineLabel(entry)}</strong>
                      <span className="log-message">{entry.reason}</span>
                      <span className="review-timeline-meta">
                        {getStatusLabel(entry.operator)} • {getStatusLabel(entry.event_type)}
                      </span>
                    </div>
                  ))}
                  {timelineEntries.length === 0 ? (
                    <p className="ops-hub-empty">No timeline entries available.</p>
                  ) : null}
                </div>
              </div>
            </div>
          ) : null}
        </div>
      </div>
    </section>
  );
}
