import { useCallback, useEffect, useMemo, useState } from "react";

import {
  fetchCurationRecords,
  fetchFeaturedRecords,
  fetchInstalledPackDetail,
  fetchInstalledPacks,
  fetchMarketplaceCategories,
  fetchMarketplacePackDetail,
    fetchMarketplacePacks,
    fetchPackOutcomeManifests,
    fetchPackQualityAssessment,
    fetchPackRecoveryPreview,
    fetchPackTrust,
  installMarketplacePack,
  submitPackForCuration
} from "./api";
import type { StarterKind, WorkflowStarterDraft } from "../workflow-starter/types";
import type {
  CurationRecord,
  InstalledPackDetail,
  InstalledPackSummary,
  MarketplaceCategory,
  MarketplacePackDetail,
  MarketplacePackSummary,
  MarketplacePackVersionInfo,
  OutcomePackManifest,
  PackRecoveryPreviewResponse,
  QualityAssessment,
  PackTrustResponse
} from "./types";

interface PackMarketplacePageProps {
  token: string | null;
  apiKey: string | null;
  onOpenWorkflowStarter?: (draft?: WorkflowStarterDraft) => void;
}

interface CategoryOption {
  slug: string;
  label: string;
  count: number;
  description: string;
}

function recordMap(records: CurationRecord[]): Record<string, CurationRecord> {
  return records.reduce<Record<string, CurationRecord>>((acc, record) => {
    acc[record.pack_name] = record;
    return acc;
  }, {});
}

function installedMap(packs: InstalledPackSummary[]): Record<string, InstalledPackSummary> {
  return packs.reduce<Record<string, InstalledPackSummary>>((acc, pack) => {
    acc[pack.name] = pack;
    return acc;
  }, {});
}

function formatStatus(value: string): string {
  return value.replace(/_/g, " ");
}

function formatTrust(value: string | null): string {
  if (!value) {
    return "Unknown";
  }
  return value
    .replace(/_/g, " ")
    .split(" ")
    .map((part) => `${part.charAt(0).toUpperCase()}${part.slice(1)}`)
    .join(" ");
}

function filterMatches(pack: MarketplacePackSummary, query: string): boolean {
  const haystack = [
    pack.name,
    pack.description,
    pack.author,
    pack.category,
    ...pack.tags
  ]
    .join(" ")
    .toLowerCase();
  return haystack.includes(query.toLowerCase());
}

function buildCategoryOptions(
  packs: MarketplacePackSummary[],
  categories: MarketplaceCategory[]
): CategoryOption[] {
  const counts = packs.reduce<Record<string, number>>((acc, pack) => {
    if (!pack.category) {
      return acc;
    }
    acc[pack.category] = (acc[pack.category] ?? 0) + 1;
    return acc;
  }, {});

  return Object.entries(counts)
    .map(([slug, count]) => {
      const category = categories.find((entry) => entry.slug === slug);
      return {
        slug,
        label: category?.label ?? slug,
        count,
        description: category?.description ?? ""
      };
    })
    .sort((left, right) => left.label.localeCompare(right.label));
}

function versionLabel(version: MarketplacePackVersionInfo): string {
  return `${version.version}${version.trust_level ? ` · ${formatTrust(version.trust_level)}` : ""}`;
}

function qualityLabel(record: CurationRecord | null): string | null {
  if (!record?.quality) {
    return null;
  }
  return `${record.quality.label} quality · ${Math.round(record.quality.overall_score * 100)}%`;
}

function assessmentLabel(assessment: QualityAssessment | null): string | null {
  if (!assessment) {
    return null;
  }
  return `${assessment.label} quality · ${Math.round(assessment.overall_score * 100)}%`;
}

function normalizeBadgeValue(value: string): string {
  return value.trim().toLowerCase().replace(/[^a-z0-9_-]/g, "-");
}

function trustTone(value: string | null | undefined): string {
  const normalized = normalizeBadgeValue(value ?? "unknown");
  if (["official", "verified", "community", "untrusted", "imported"].includes(normalized)) {
    return normalized;
  }
  return "unknown";
}

function qualityTone(value: string | null | undefined): string {
  const normalized = normalizeBadgeValue(value ?? "unknown");
  if (["excellent", "high", "medium", "low"].includes(normalized)) {
    return normalized;
  }
  return "unknown";
}

function versionTrustLevel(pack: MarketplacePackDetail, selectedVersion: string): string | null {
  const selected =
    pack.versions.find((version) => version.version === selectedVersion) ?? pack.versions[0] ?? null;
  return selected?.trust_level ?? null;
}

function versionSkillCount(pack: MarketplacePackDetail, selectedVersion: string): number {
  const selected =
    pack.versions.find((version) => version.version === selectedVersion) ?? pack.versions[0] ?? null;
  return selected?.skills_count ?? 0;
}

function starterKindForOutcomePack(manifest: OutcomePackManifest): StarterKind {
  if (manifest.kind === "improvement-loop") {
    return "improvement-loop";
  }
  if (manifest.kind === "automation-loop") {
    return "automation-loop";
  }

  const searchable = `${manifest.category ?? ""} ${(manifest.tags ?? []).join(" ")}`.toLowerCase();
  if (searchable.includes("research") || searchable.includes("security") || searchable.includes("review")) {
    return "research";
  }
  return "automation-loop";
}

function buildOutcomeWorkflowDraft(
  manifest: OutcomePackManifest,
  pack: MarketplacePackDetail
): WorkflowStarterDraft {
  const primaryWorkflow = manifest.workflows[0];
  const deliverables =
    manifest.presentation.expected_deliverables && manifest.presentation.expected_deliverables.length > 0
      ? manifest.presentation.expected_deliverables.join("; ")
      : (manifest.artifacts ?? []).map((artifact) => artifact.name).join("; ");

  return {
    id: `outcome-${manifest.name}`,
    name: primaryWorkflow?.name ?? manifest.name,
    goal: manifest.presentation.summary || manifest.description,
    kind: starterKindForOutcomePack(manifest),
    output: deliverables || `Artifacts from ${manifest.presentation.title || manifest.name}`,
    schedule: "",
    author: pack.author || manifest.author || "operator",
    sourceLabel: `Outcome pack: ${manifest.presentation.title || manifest.name}`,
    sourcePack: pack.name,
    sourcePackVersion: pack.latest_version,
    sourceOutcomeId: manifest.name
  };
}

function TrustBadge({
  level,
  showUnknown = false
}: {
  level: string | null | undefined;
  showUnknown?: boolean;
}): JSX.Element | null {
  if (!level && !showUnknown) {
    return null;
  }

  return (
    <span className={`marketplace-pill trust-${trustTone(level)}`}>
      {formatTrust(level ?? null)} trust
    </span>
  );
}

function QualityBadge({ assessment }: { assessment: QualityAssessment | null | undefined }): JSX.Element | null {
  if (!assessment) {
    return null;
  }

  return (
    <span className={`marketplace-pill quality-${qualityTone(assessment.label)}`}>
      {assessment.label} quality
    </span>
  );
}

function formatArchiveDate(value: string): string {
  const timestamp = Date.parse(value);
  if (Number.isNaN(timestamp)) {
    return value;
  }
  return new Date(timestamp).toLocaleString();
}

function RecoveryPreviewPanel({
  preview,
  loading,
  error
}: {
  preview: PackRecoveryPreviewResponse | null;
  loading: boolean;
  error: string | null;
}): JSX.Element | null {
  if (loading) {
    return (
      <section className="pack-marketplace-recovery-preview">
        <div className="pack-marketplace-preview-header">
          <h3>Change safety preview</h3>
          <span className="marketplace-pill preview">Checking...</span>
        </div>
        <p>Checking dependents and rollback options before pack changes...</p>
      </section>
    );
  }

  if (error) {
    return (
      <section className="pack-marketplace-recovery-preview warning">
        <div className="pack-marketplace-preview-header">
          <h3>Change safety preview</h3>
          <span className="marketplace-pill trust-untrusted">Unavailable</span>
        </div>
        <p>{error}</p>
      </section>
    );
  }

  if (!preview) {
    return null;
  }

  const hasUpgradeTarget =
    preview.target_version !== "" && preview.target_version !== preview.installed_version;
  const latestArchive = preview.archived_versions[0] ?? null;

  return (
    <section className="pack-marketplace-recovery-preview">
      <div className="pack-marketplace-preview-header">
        <h3>Change safety preview</h3>
        <span className="marketplace-pill preview">Before uninstall / upgrade / rollback</span>
      </div>

      <dl>
        <div>
          <dt>Selected change</dt>
          <dd>
            {hasUpgradeTarget
              ? `Upgrade ${preview.installed_version} -> ${preview.target_version}`
              : `Installed version ${preview.installed_version}`}
          </dd>
        </div>
        <div>
          <dt>Dependents</dt>
          <dd>
            {preview.dependents.length === 0
              ? "No installed packs depend on this pack."
              : `${preview.dependents.length} installed pack(s) depend on this pack.`}
          </dd>
        </div>
        <div>
          <dt>Rollback</dt>
          <dd>
            {preview.can_rollback && latestArchive
              ? `${preview.archived_versions.length} archived version(s); latest ${latestArchive.version} from ${formatArchiveDate(latestArchive.archived_at)}.`
              : "No rollback archive is available yet. Upgrades archive the current version first."}
          </dd>
        </div>
        <div>
          <dt>Safe action</dt>
          <dd>{preview.recommended_action}</dd>
        </div>
      </dl>

      {preview.dependents.length > 0 && (
        <div className="pack-marketplace-dependency-list">
          <strong>Uninstall blockers</strong>
          <ul>
            {preview.dependents.map((dependent) => (
              <li key={dependent.name}>
                {dependent.name} {dependent.version}
                {dependent.version_constraint ? ` requires ${dependent.version_constraint}` : ""}
              </li>
            ))}
          </ul>
        </div>
      )}

      {preview.compatibility_errors.length > 0 && (
        <div className="pack-marketplace-dependency-list warning">
          <strong>Upgrade compatibility issues</strong>
          <ul>
            {preview.compatibility_errors.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </div>
      )}

      {preview.warnings.length > 0 && (
        <ul className="pack-marketplace-recovery-warnings">
          {preview.warnings.map((warning) => (
            <li key={warning}>{warning}</li>
          ))}
        </ul>
      )}
    </section>
  );
}

function canSubmitForCuration(curation: CurationRecord | null): boolean {
  if (!curation) {
    return true;
  }
  return (
    curation.status === "draft" ||
    curation.status === "changes_requested" ||
    curation.status === "unlisted"
  );
}

function submissionActionLabel(curation: CurationRecord | null): string {
  return !curation || curation.status === "draft"
    ? "Submit for curation"
    : "Resubmit for curation";
}

function formatCheckName(value: string): string {
  return value.replace(/_/g, " ");
}

function PackDetailPanel({
  pack,
  installedSummary,
  installed,
  trust,
  curation,
  quality,
  recoveryPreview,
  selectedVersion,
  detailLoading,
  detailError,
  installPending,
  installFeedback,
  installedDetailError,
  submissionPending,
  submissionFeedback,
  submissionFeedbackTone,
  qualityLoading,
  qualityError,
  recoveryLoading,
  recoveryError,
  outcomeLaunchPending,
  outcomeLaunchFeedback,
  canLaunchOutcome,
  onVersionChange,
  onInstall,
  onLaunchOutcome,
  onSubmitForCuration,
  onClose
}: {
  pack: MarketplacePackDetail | null;
  installedSummary: InstalledPackSummary | null;
  installed: InstalledPackDetail | null;
  trust: PackTrustResponse | null;
  curation: CurationRecord | null;
  quality: QualityAssessment | null;
  recoveryPreview: PackRecoveryPreviewResponse | null;
  selectedVersion: string;
  detailLoading: boolean;
  detailError: string | null;
  installPending: boolean;
  installFeedback: string | null;
  installedDetailError: string | null;
  submissionPending: boolean;
  submissionFeedback: string | null;
  submissionFeedbackTone: "success" | "error" | null;
  qualityLoading: boolean;
  qualityError: string | null;
  recoveryLoading: boolean;
  recoveryError: string | null;
  outcomeLaunchPending: boolean;
  outcomeLaunchFeedback: string | null;
  canLaunchOutcome: boolean;
  onVersionChange: (value: string) => void;
  onInstall: () => void;
  onLaunchOutcome: () => void;
  onSubmitForCuration: () => void;
  onClose: () => void;
}): JSX.Element | null {
  if (!pack) {
    return null;
  }

  const isInstalled = Boolean(installedSummary);
  const installedVersion = installed?.version ?? installedSummary?.version ?? null;
  const installedSameVersion = installedVersion === selectedVersion;
  const curationQuality = qualityLabel(curation);
  const canSubmit = isInstalled && canSubmitForCuration(curation);
  const previewQuality = assessmentLabel(quality);
  const selectedTrustLevel = versionTrustLevel(pack, selectedVersion);
  const selectedSkillCount = versionSkillCount(pack, selectedVersion);
  const trustSummary = trust
    ? trust.allowed
      ? "Allowed by installed-pack policy"
      : `Blocked by policy: ${trust.reason || "review required"}`
    : selectedTrustLevel
      ? `${formatTrust(selectedTrustLevel)} marketplace provenance`
      : "No signed provenance published yet";

  return (
    <aside className="pack-marketplace-detail" aria-label={`Details for ${pack.name}`}>
      <header className="pack-marketplace-detail-header">
        <div>
          <h2>{pack.name}</h2>
          <p>{pack.description || "No description available."}</p>
        </div>
        <button type="button" onClick={onClose} aria-label="Close marketplace detail panel">
          Close
        </button>
      </header>

      {detailLoading && <p className="pack-marketplace-loading">Loading pack details...</p>}
      {detailError && <p className="pack-marketplace-error">{detailError}</p>}

      {!detailLoading && !detailError && (
        <div className="pack-marketplace-detail-body">
          <div className="pack-marketplace-badges">
            {curation?.featured && <span className="marketplace-pill featured">Featured</span>}
            {curation?.verified && <span className="marketplace-pill verified">Verified</span>}
            <TrustBadge level={selectedTrustLevel} showUnknown />
            <QualityBadge assessment={curation?.quality ?? quality} />
            {isInstalled && <span className="marketplace-pill installed">Installed</span>}
            <span className="marketplace-pill neutral">{pack.latest_version}</span>
          </div>

          <section className="pack-marketplace-preview">
            <div className="pack-marketplace-preview-header">
              <h3>Beginner preview</h3>
              <span className="marketplace-pill preview">Preview before install</span>
            </div>
            <dl>
              <div>
                <dt>Trust</dt>
                <dd>{trustSummary}</dd>
              </div>
              <div>
                <dt>Setup</dt>
                <dd>
                  Installs {selectedSkillCount} skill{selectedSkillCount !== 1 ? "s" : ""} from{" "}
                  {pack.sources.length > 0 ? pack.sources.join(", ") : "marketplace"}.
                </dd>
              </div>
              <div>
                <dt>Outcome</dt>
                <dd>Install only - no auto-run. Launch workflows after reviewing setup.</dd>
              </div>
              <div>
                <dt>Review</dt>
                <dd>
                  {curationQuality ??
                    previewQuality ??
                    (curation?.verified ? "Verified by marketplace curation" : "Not curated yet")}
                </dd>
              </div>
            </dl>
          </section>

          <dl className="pack-marketplace-metadata">
            <dt>Author</dt>
            <dd>{pack.author || "Unknown"}</dd>

            <dt>Category</dt>
            <dd>{pack.category || "Uncategorized"}</dd>

            <dt>Sources</dt>
            <dd>{pack.sources.length > 0 ? pack.sources.join(", ") : "None published"}</dd>

            <dt>Versions</dt>
            <dd>{pack.versions.length}</dd>

            {curation && (
              <>
                <dt>Curation</dt>
                <dd>{formatStatus(curation.status)}</dd>
              </>
            )}

            {curationQuality && (
              <>
                <dt>Quality</dt>
                <dd>{curationQuality}</dd>
              </>
            )}

            {curation && curation.download_count > 0 && (
              <>
                <dt>Downloads</dt>
                <dd>{curation.download_count}</dd>
              </>
            )}

            {isInstalled && installedVersion && (
              <>
                <dt>Installed</dt>
                <dd>
                  {installedVersion}
                  {installed
                    ? installed.enabled_for_tenant
                      ? " · enabled for tenant"
                      : " · disabled for tenant"
                    : " · installed"}
                </dd>
              </>
            )}

            {trust && (
              <>
                <dt>Trust</dt>
                <dd>{trust.allowed ? "Allowed by policy" : `Blocked: ${trust.reason || "policy"}`}</dd>
              </>
            )}
          </dl>

          {pack.tags.length > 0 && (
            <section>
              <h3>Tags</h3>
              <div className="pack-marketplace-tags">
                {pack.tags.map((tag) => (
                  <span key={tag} className="marketplace-tag">
                    {tag}
                  </span>
                ))}
              </div>
            </section>
          )}

          <section className="pack-marketplace-version-section">
            <div className="pack-marketplace-version-header">
              <h3>Available versions</h3>
              <label>
                <span>Select version</span>
                <select value={selectedVersion} onChange={(event) => onVersionChange(event.target.value)}>
                  {pack.versions.map((version) => (
                    <option key={version.version} value={version.version}>
                      {versionLabel(version)}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <ul className="pack-marketplace-version-list">
              {pack.versions.map((version) => (
                <li key={version.version}>
                  <button
                    type="button"
                    className={`pack-marketplace-version-button ${
                      selectedVersion === version.version ? "active" : ""
                    }`}
                    aria-pressed={selectedVersion === version.version}
                    onClick={() => onVersionChange(version.version)}
                  >
                    <div>
                      <strong>{version.version}</strong>
                      <span>{version.source_name || version.source_type || "marketplace"}</span>
                    </div>
                    <div>
                      <span>{version.skills_count} skill(s)</span>
                      <span>{formatTrust(version.trust_level)}</span>
                    </div>
                  </button>
                </li>
              ))}
            </ul>
          </section>

          {isInstalled && (
            <RecoveryPreviewPanel
              preview={recoveryPreview}
              loading={recoveryLoading}
              error={recoveryError}
            />
          )}

          <div className="pack-marketplace-actions">
            <button
              type="button"
              className="pack-marketplace-primary"
              disabled={installPending || installedSameVersion}
              onClick={onInstall}
            >
              {installedSameVersion
                ? "Installed"
                : installPending
                  ? "Installing..."
                  : "Install selected version"}
            </button>
            {canLaunchOutcome && isInstalled && (
              <button
                type="button"
                className="pack-marketplace-secondary"
                disabled={outcomeLaunchPending}
                onClick={onLaunchOutcome}
              >
                {outcomeLaunchPending ? "Preparing starter..." : "Launch outcome starter"}
              </button>
            )}
            {installFeedback && <p className="pack-marketplace-feedback">{installFeedback}</p>}
            {outcomeLaunchFeedback && (
              <p className="pack-marketplace-feedback">{outcomeLaunchFeedback}</p>
            )}
          </div>

          {installedDetailError && <p className="pack-marketplace-error">{installedDetailError}</p>}

          <section className="pack-marketplace-submission-section">
            <div className="pack-marketplace-submission-header">
              <h3>Community submission</h3>
              {curation ? (
                <span className="marketplace-pill neutral">{formatStatus(curation.status)}</span>
              ) : (
                <span className="marketplace-pill neutral">Not submitted</span>
              )}
            </div>

            {!isInstalled && (
              <p className="pack-marketplace-submission-note">
                Install this pack before submitting it for marketplace curation.
              </p>
            )}

            {isInstalled && (
              <>
                {previewQuality && (
                  <p className="pack-marketplace-submission-note">
                    Quality preview: <strong>{previewQuality}</strong>
                    {!quality?.passed && " — improvements are recommended before review."}
                  </p>
                )}
                {qualityLoading && (
                  <p className="pack-marketplace-submission-note">Loading quality assessment...</p>
                )}
                {qualityError && <p className="pack-marketplace-error">{qualityError}</p>}

                {quality && (quality.checks?.length ?? 0) > 0 && (
                  <ul className="pack-marketplace-quality-list">
                    {(quality.checks ?? []).map((check) => (
                      <li key={check.name}>
                        <span>{formatCheckName(check.name)}</span>
                        <span>{check.passed ? "Pass" : check.reason}</span>
                      </li>
                    ))}
                  </ul>
                )}

                {curation?.review_notes && (
                  <div className="pack-marketplace-review-notes">
                    <strong>Reviewer notes</strong>
                    <p>{curation.review_notes}</p>
                  </div>
                )}

                {submissionFeedback && (
                  <p
                    className={
                      submissionFeedbackTone === "error"
                        ? "pack-marketplace-error"
                        : "pack-marketplace-feedback"
                    }
                  >
                    {submissionFeedback}
                  </p>
                )}

                {canSubmit && (
                  <button
                    type="button"
                    className="pack-marketplace-secondary"
                    disabled={submissionPending}
                    onClick={onSubmitForCuration}
                  >
                    {submissionPending ? "Submitting..." : submissionActionLabel(curation)}
                  </button>
                )}

                {!canSubmit && curation && (
                  <p className="pack-marketplace-submission-note">
                    This pack is already in the curation pipeline. Track its current status here.
                  </p>
                )}
              </>
            )}
          </section>
        </div>
      )}
    </aside>
  );
}

export function PackMarketplacePage({
  token,
  apiKey,
  onOpenWorkflowStarter
}: PackMarketplacePageProps): JSX.Element {
  const [packs, setPacks] = useState<MarketplacePackSummary[]>([]);
  const [categories, setCategories] = useState<MarketplaceCategory[]>([]);
  const [curationByPack, setCurationByPack] = useState<Record<string, CurationRecord>>({});
  const [installedByPack, setInstalledByPack] = useState<Record<string, InstalledPackSummary>>({});
  const [selectedCategory, setSelectedCategory] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedPackName, setSelectedPackName] = useState<string | null>(null);
  const [selectedPackDetail, setSelectedPackDetail] = useState<MarketplacePackDetail | null>(null);
  const [selectedInstalledDetail, setSelectedInstalledDetail] = useState<InstalledPackDetail | null>(null);
  const [selectedTrust, setSelectedTrust] = useState<PackTrustResponse | null>(null);
  const [selectedQuality, setSelectedQuality] = useState<QualityAssessment | null>(null);
  const [selectedRecoveryPreview, setSelectedRecoveryPreview] =
    useState<PackRecoveryPreviewResponse | null>(null);
  const [selectedVersion, setSelectedVersion] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [installPending, setInstallPending] = useState(false);
  const [installFeedback, setInstallFeedback] = useState<string | null>(null);
  const [installedDetailError, setInstalledDetailError] = useState<string | null>(null);
  const [submissionPending, setSubmissionPending] = useState(false);
  const [submissionFeedback, setSubmissionFeedback] = useState<string | null>(null);
  const [submissionFeedbackTone, setSubmissionFeedbackTone] = useState<"success" | "error" | null>(null);
  const [qualityLoading, setQualityLoading] = useState(false);
  const [qualityError, setQualityError] = useState<string | null>(null);
  const [recoveryLoading, setRecoveryLoading] = useState(false);
  const [recoveryError, setRecoveryError] = useState<string | null>(null);
  const [outcomeLaunchPending, setOutcomeLaunchPending] = useState(false);
  const [outcomeLaunchFeedback, setOutcomeLaunchFeedback] = useState<string | null>(null);

  const loadMarketplace = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      const [packResult, categoryResult, featuredResult, curationResult, installedResult] =
        await Promise.allSettled([
          fetchMarketplacePacks(token, apiKey),
          fetchMarketplaceCategories(token, apiKey),
          fetchFeaturedRecords(token, apiKey),
          fetchCurationRecords(token, apiKey),
          fetchInstalledPacks(token, apiKey)
        ]);

      if (packResult.status === "rejected") {
        throw packResult.reason;
      }

      setPacks(packResult.value);
      setCategories(categoryResult.status === "fulfilled" ? categoryResult.value : []);
      setInstalledByPack(
        installedMap(installedResult.status === "fulfilled" ? installedResult.value : [])
      );

      const mergedCuration =
        curationResult.status === "fulfilled" ? recordMap(curationResult.value) : {};

      if (featuredResult.status === "fulfilled") {
        featuredResult.value.forEach((record) => {
          const existing = mergedCuration[record.pack_name];
          if (!existing) {
            mergedCuration[record.pack_name] = record;
            return;
          }

          mergedCuration[record.pack_name] = {
            ...existing,
            ...record,
            featured: true,
            badges: Array.from(new Set([...existing.badges, ...record.badges]))
          };
        });
      }

      setCurationByPack(mergedCuration);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load marketplace");
    } finally {
      setLoading(false);
    }
  }, [apiKey, token]);

  useEffect(() => {
    void loadMarketplace();
  }, [loadMarketplace]);

  useEffect(() => {
    if (!selectedPackName) {
      setSelectedPackDetail(null);
      setSelectedInstalledDetail(null);
      setSelectedTrust(null);
      setSelectedQuality(null);
      setSelectedRecoveryPreview(null);
      setSelectedVersion("");
      setDetailError(null);
      setInstalledDetailError(null);
      setQualityError(null);
      setRecoveryError(null);
      setRecoveryLoading(false);
      return;
    }

    const packName = selectedPackName;
    let cancelled = false;

    async function loadSelectedPack(): Promise<void> {
      setDetailLoading(true);
      setDetailError(null);

      try {
        const detail = await fetchMarketplacePackDetail(token, apiKey, packName);
        if (cancelled) {
          return;
        }
        setSelectedPackDetail(detail);
        setSelectedVersion((current) => current || detail.latest_version);
        setInstalledDetailError(null);

        if (!installedByPack[packName]) {
          setSelectedInstalledDetail(null);
          setSelectedTrust(null);
          setSelectedQuality(null);
          setSelectedRecoveryPreview(null);
          setRecoveryLoading(false);
          setRecoveryError(null);
          setQualityLoading(false);
          return;
        }

        setQualityLoading(true);
        setQualityError(null);
        const [installedResult, trustResult, qualityResult] = await Promise.allSettled([
          fetchInstalledPackDetail(token, apiKey, packName),
          fetchPackTrust(token, apiKey, packName),
          fetchPackQualityAssessment(token, apiKey, packName)
        ]);

        if (cancelled) {
          return;
        }

        setSelectedInstalledDetail(installedResult.status === "fulfilled" ? installedResult.value : null);
        setSelectedTrust(trustResult.status === "fulfilled" ? trustResult.value : null);
        setInstalledDetailError(
          installedResult.status === "rejected"
            ? installedResult.reason instanceof Error
              ? installedResult.reason.message
              : "Installed pack detail failed"
            : null
        );
        setSelectedQuality(qualityResult.status === "fulfilled" ? qualityResult.value : null);
        setQualityError(
          qualityResult.status === "rejected"
            ? qualityResult.reason instanceof Error
              ? qualityResult.reason.message
              : "Quality assessment failed"
            : null
        );
      } catch (err) {
        if (!cancelled) {
          setDetailError(err instanceof Error ? err.message : "Failed to load pack detail");
        }
      } finally {
        if (!cancelled) {
          setDetailLoading(false);
          setQualityLoading(false);
        }
      }
    }

    void loadSelectedPack();

    return () => {
      cancelled = true;
    };
  }, [apiKey, installedByPack, selectedPackName, token]);

  useEffect(() => {
    if (!selectedPackName || !installedByPack[selectedPackName] || !selectedVersion) {
      setSelectedRecoveryPreview(null);
      setRecoveryError(null);
      setRecoveryLoading(false);
      return;
    }

    const packName = selectedPackName;
    let cancelled = false;
    setRecoveryLoading(true);
    setRecoveryError(null);

    async function loadRecoveryPreview(): Promise<void> {
      try {
        const preview = await fetchPackRecoveryPreview(token, apiKey, packName, selectedVersion);
        if (!cancelled) {
          setSelectedRecoveryPreview(preview);
        }
      } catch (err) {
        if (!cancelled) {
          setSelectedRecoveryPreview(null);
          setRecoveryError(err instanceof Error ? err.message : "Pack recovery preview failed");
        }
      } finally {
        if (!cancelled) {
          setRecoveryLoading(false);
        }
      }
    }

    void loadRecoveryPreview();

    return () => {
      cancelled = true;
    };
  }, [apiKey, installedByPack, selectedPackName, selectedVersion, token]);

  const featuredPacks = useMemo(
    () => packs.filter((pack) => Boolean(curationByPack[pack.name]?.featured)).slice(0, 3),
    [curationByPack, packs]
  );

  const categoryOptions = useMemo(
    () => buildCategoryOptions(packs, categories),
    [categories, packs]
  );

  const filteredPacks = useMemo(() => {
    return packs.filter((pack) => {
      if (selectedCategory && pack.category !== selectedCategory) {
        return false;
      }
      if (searchQuery.trim() && !filterMatches(pack, searchQuery.trim())) {
        return false;
      }
      return true;
    });
  }, [packs, searchQuery, selectedCategory]);

  const openPack = (name: string): void => {
    setSelectedPackName(name);
    setSelectedPackDetail(null);
    setSelectedInstalledDetail(null);
    setSelectedTrust(null);
    setSelectedQuality(null);
    setSelectedRecoveryPreview(null);
    setSelectedVersion("");
    setInstallFeedback(null);
    setInstalledDetailError(null);
    setSubmissionFeedback(null);
    setSubmissionFeedbackTone(null);
    setQualityError(null);
    setRecoveryError(null);
    setRecoveryLoading(false);
    setOutcomeLaunchFeedback(null);
  };

  const handleInstall = async (): Promise<void> => {
    if (!selectedPackDetail) {
      return;
    }

    setInstallPending(true);
    setInstallFeedback(null);

    try {
      const result = await installMarketplacePack(
        token,
        apiKey,
        selectedPackDetail.name,
        selectedVersion || selectedPackDetail.latest_version
      );
      const installedVersion = result.version || selectedVersion || selectedPackDetail.latest_version;

      setInstalledByPack((current) => ({
        ...current,
        [selectedPackDetail.name]: {
          name: selectedPackDetail.name,
          version: installedVersion,
          description: selectedPackDetail.description,
          author: selectedPackDetail.author,
          tags: selectedPackDetail.tags,
          category: selectedPackDetail.category,
          skills_count:
            selectedPackDetail.versions.find((item) => item.version === installedVersion)
              ?.skills_count ?? 0,
          status: "installed"
        }
      }));

      setInstallFeedback(`Installed ${result.pack_name} ${installedVersion}`);
    } catch (err) {
      setInstallFeedback(err instanceof Error ? err.message : "Install failed");
    } finally {
      setInstallPending(false);
    }
  };

  const handleLaunchOutcome = async (): Promise<void> => {
    if (!selectedPackDetail || !onOpenWorkflowStarter) {
      return;
    }

    setOutcomeLaunchPending(true);
    setOutcomeLaunchFeedback(null);

    try {
      const outcomeResponse = await fetchPackOutcomeManifests(
        token,
        apiKey,
        selectedPackDetail.name
      );
      const firstOutcome = outcomeResponse.packs[0];
      if (!firstOutcome) {
        setOutcomeLaunchFeedback("This pack does not bundle outcome starters yet.");
        return;
      }

      onOpenWorkflowStarter(buildOutcomeWorkflowDraft(firstOutcome.manifest, selectedPackDetail));
    } catch (err) {
      setOutcomeLaunchFeedback(err instanceof Error ? err.message : "Outcome starter failed");
    } finally {
      setOutcomeLaunchPending(false);
    }
  };

  const handleSubmitForCuration = async (): Promise<void> => {
    if (!selectedPackDetail || !selectedInstalledSummary) {
      return;
    }

    setSubmissionPending(true);
    setSubmissionFeedback(null);
    setSubmissionFeedbackTone(null);

    try {
      const submitted = await submitPackForCuration(
        token,
        apiKey,
        selectedPackDetail.name,
        selectedInstalledDetail?.version ||
          selectedInstalledSummary.version ||
          selectedVersion ||
          selectedPackDetail.latest_version
      );
      setCurationByPack((current) => ({
        ...current,
        [submitted.pack_name]: submitted
      }));
      setSelectedQuality(submitted.quality ?? null);
      setSubmissionFeedback(`Submitted ${submitted.pack_name} for marketplace curation.`);
      setSubmissionFeedbackTone("success");
    } catch (err) {
      setSubmissionFeedback(err instanceof Error ? err.message : "Curation submit failed");
      setSubmissionFeedbackTone("error");
    } finally {
      setSubmissionPending(false);
    }
  };

  const selectedInstalledSummary = selectedPackName ? installedByPack[selectedPackName] ?? null : null;

  return (
    <div className="pack-marketplace-page">
      <header className="pack-marketplace-header">
        <h1>Pack Marketplace</h1>
        <p>
          Browse curated packs, inspect versions and trust posture, and install packs without
          leaving the web UI.
        </p>
      </header>

      {featuredPacks.length > 0 && (
        <section className="pack-marketplace-featured" aria-label="Featured packs">
          <div className="pack-marketplace-section-heading">
            <h2>Featured</h2>
            <span>{featuredPacks.length} highlighted pack(s)</span>
          </div>
          <div className="pack-marketplace-featured-grid">
            {featuredPacks.map((pack) => (
              <button
                key={pack.name}
                type="button"
                className="pack-marketplace-featured-card"
                onClick={() => openPack(pack.name)}
                aria-label={`Open details for ${pack.name}`}
              >
                <strong>{pack.name}</strong>
                <span>{pack.description || "No description available."}</span>
                <div className="pack-marketplace-badges">
                  <span className="marketplace-pill featured">Featured</span>
                  {curationByPack[pack.name]?.verified && (
                    <span className="marketplace-pill verified">Verified</span>
                  )}
                  <TrustBadge level={pack.trust_level} />
                  <QualityBadge assessment={curationByPack[pack.name]?.quality} />
                  <span className="marketplace-pill neutral">{pack.latest_version}</span>
                </div>
              </button>
            ))}
          </div>
        </section>
      )}

      <div className="pack-marketplace-layout">
        <aside className="pack-marketplace-sidebar">
          <div className="pack-marketplace-filter-card">
            <h3>Categories</h3>
            <button
              type="button"
              className={selectedCategory === null ? "active" : ""}
              aria-pressed={selectedCategory === null}
              onClick={() => setSelectedCategory(null)}
            >
              <span>All</span>
              <span>{packs.length}</span>
            </button>
            {categoryOptions.map((category) => (
              <button
                key={category.slug}
                type="button"
                className={selectedCategory === category.slug ? "active" : ""}
                aria-pressed={selectedCategory === category.slug}
                onClick={() =>
                  setSelectedCategory((current) => (current === category.slug ? null : category.slug))
                }
                title={category.description}
              >
                <span>{category.label}</span>
                <span>{category.count}</span>
              </button>
            ))}
          </div>
        </aside>

        <main className="pack-marketplace-main">
          <div className="pack-marketplace-toolbar">
            <label className="pack-marketplace-search">
              <span className="sr-only">Search marketplace packs</span>
              <input
                type="search"
                placeholder="Search packs by name, author, category, or tag..."
                value={searchQuery}
                onChange={(event) => setSearchQuery(event.target.value)}
                aria-label="Search marketplace packs"
              />
            </label>
            <p className="pack-marketplace-count">
              {filteredPacks.length} pack{filteredPacks.length !== 1 ? "s" : ""}
            </p>
          </div>

          {loading && <p className="pack-marketplace-loading">Loading marketplace packs...</p>}
          {error && <p className="pack-marketplace-error">{error}</p>}

          {!loading && !error && filteredPacks.length === 0 && (
            <div className="pack-marketplace-empty">
              <h2>No packs match this filter</h2>
              <p>Try clearing the category filter or broadening the search terms.</p>
            </div>
          )}

          {!loading && !error && filteredPacks.length > 0 && (
            <div className="pack-marketplace-grid">
              {filteredPacks.map((pack) => {
                const curation = curationByPack[pack.name] ?? null;
                const installed = installedByPack[pack.name] ?? null;

                return (
                  <button
                    key={pack.name}
                    type="button"
                    className={`pack-marketplace-card ${
                      selectedPackName === pack.name ? "selected" : ""
                    }`}
                    aria-label={`Open details for ${pack.name}`}
                    onClick={() => openPack(pack.name)}
                  >
                    <div className="pack-marketplace-card-header">
                      <div>
                        <h3>{pack.name}</h3>
                        <p>{pack.author || "Unknown author"}</p>
                      </div>
                      <span className="marketplace-pill neutral">{pack.latest_version}</span>
                    </div>

                    <p className="pack-marketplace-card-description">
                      {pack.description || "No description available."}
                    </p>

                    <div className="pack-marketplace-badges">
                      <span className="marketplace-pill neutral">
                        {pack.category || "Uncategorized"}
                      </span>
                      <span className="marketplace-pill neutral">
                        {pack.versions_count} version{pack.versions_count !== 1 ? "s" : ""}
                      </span>
                      <TrustBadge level={pack.trust_level} />
                      <QualityBadge assessment={curation?.quality} />
                      {installed && <span className="marketplace-pill installed">Installed</span>}
                      {curation?.featured && <span className="marketplace-pill featured">Featured</span>}
                      {curation?.verified && <span className="marketplace-pill verified">Verified</span>}
                      {curation && !curation.featured && (
                        <span className="marketplace-pill neutral">
                          {formatStatus(curation.status)}
                        </span>
                      )}
                    </div>

                    {pack.tags.length > 0 && (
                      <div className="pack-marketplace-tags">
                        {pack.tags.slice(0, 4).map((tag) => (
                          <span key={tag} className="marketplace-tag">
                            {tag}
                          </span>
                        ))}
                      </div>
                    )}
                  </button>
                );
              })}
            </div>
          )}
        </main>

        <PackDetailPanel
          pack={selectedPackDetail}
          installedSummary={selectedInstalledSummary}
          installed={selectedInstalledDetail}
          trust={selectedTrust}
          curation={selectedPackName ? curationByPack[selectedPackName] ?? null : null}
          quality={selectedQuality}
          recoveryPreview={selectedRecoveryPreview}
          selectedVersion={selectedVersion}
          detailLoading={detailLoading}
          detailError={detailError}
          installPending={installPending}
          installFeedback={installFeedback}
          installedDetailError={installedDetailError}
          submissionPending={submissionPending}
          submissionFeedback={submissionFeedback}
          submissionFeedbackTone={submissionFeedbackTone}
          qualityLoading={qualityLoading}
          qualityError={qualityError}
          recoveryLoading={recoveryLoading}
          recoveryError={recoveryError}
          outcomeLaunchPending={outcomeLaunchPending}
          outcomeLaunchFeedback={outcomeLaunchFeedback}
          canLaunchOutcome={Boolean(onOpenWorkflowStarter)}
          onVersionChange={setSelectedVersion}
          onInstall={() => void handleInstall()}
          onLaunchOutcome={() => void handleLaunchOutcome()}
          onSubmitForCuration={() => void handleSubmitForCuration()}
          onClose={() => setSelectedPackName(null)}
        />
      </div>
    </div>
  );
}
