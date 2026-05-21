export interface MarketplacePackSummary {
  name: string;
  description: string;
  author: string;
  tags: string[];
  category: string;
  latest_version: string;
  versions_count: number;
  sources: string[];
  trust_level?: string | null;
}

export interface MarketplacePackVersionInfo {
  version: string;
  description: string;
  author: string;
  tags: string[];
  category: string;
  skills_count: number;
  source_name: string;
  source_type: string;
  trust_level: string | null;
}

export interface MarketplacePackDetail {
  name: string;
  description: string;
  author: string;
  tags: string[];
  category: string;
  latest_version: string;
  versions: MarketplacePackVersionInfo[];
  sources: string[];
}

export interface MarketplaceCategory {
  slug: string;
  label: string;
  description: string;
  parent_slug: string;
}

export interface QualityCheck {
  name: string;
  passed: boolean;
  score: number;
  reason: string;
}

export interface QualityAssessment {
  overall_score: number;
  label: string;
  passed: boolean;
  checks?: QualityCheck[];
  assessed_at?: string;
}

export interface CurationRecord {
  pack_name: string;
  version: string;
  status: string;
  quality: QualityAssessment | null;
  badges: string[];
  featured: boolean;
  verified: boolean;
  reviewer_id: string;
  review_notes: string;
  deprecation_reason: string;
  submitted_at: string | null;
  reviewed_at: string | null;
  listed_at: string | null;
  download_count: number;
}

export interface InstalledPackSummary {
  name: string;
  version: string;
  description: string;
  author: string;
  tags: string[];
  category: string;
  skills_count: number;
  status: string;
}

export interface InstalledPackDetail extends InstalledPackSummary {
  license: string;
  loaded_skill_names: string[];
  engine_min_version: string;
  installed_at: string | null;
  source: string;
  source_reference: string;
  checksum: string;
  enabled_for_tenant: boolean;
}

export interface OutcomePackPresentation {
  title: string;
  audience?: string;
  summary: string;
  difficulty?: string;
  estimated_duration?: string;
  expected_deliverables?: string[];
  sample_inputs?: Record<string, unknown>;
}

export interface OutcomePackWorkflowReference {
  name: string;
  description?: string;
  path?: string | null;
  required?: boolean;
}

export interface OutcomePackManifest {
  name: string;
  version: string;
  kind: string;
  description: string;
  author: string;
  category?: string;
  tags?: string[];
  workflows: OutcomePackWorkflowReference[];
  presentation: OutcomePackPresentation;
  artifacts?: Array<{ name: string; description?: string; required?: boolean }>;
}

export interface PackOutcomeManifestRecord {
  entry: { path: string; required: boolean; description: string };
  manifest: OutcomePackManifest;
  workflows: Array<{ name: string; description?: string; inputs?: Record<string, unknown>; outputs?: Record<string, unknown> }>;
}

export interface PackOutcomeManifestResponse {
  packs: PackOutcomeManifestRecord[];
  count: number;
}

export interface PackTrustPolicy {
  require_signature?: boolean;
  min_trust_level?: string | null;
  allowed_signers?: string[];
}

export interface PackTrustResponse {
  pack_name: string;
  installed_version: string;
  source: string;
  source_reference: string;
  allowed: boolean;
  reason: string;
  policy: PackTrustPolicy;
}

export interface PackRecoveryDependent {
  name: string;
  version: string;
  version_constraint: string;
  status: string;
}

export interface PackRecoveryArchive {
  version: string;
  archived_at: string;
}

export interface PackRecoveryPreviewResponse {
  pack_name: string;
  installed_version: string;
  target_version: string;
  affected_skills: string[];
  enabled_tenants: string[];
  dependents: PackRecoveryDependent[];
  compatibility_errors: string[];
  archived_versions: PackRecoveryArchive[];
  can_uninstall_safely: boolean;
  can_upgrade_safely: boolean;
  can_rollback: boolean;
  recommended_action: string;
  warnings: string[];
}

export interface MarketplaceInstallResponse {
  success: boolean;
  pack_name: string;
  version: string;
  skills_loaded: number;
  errors: string[];
  warnings: string[];
}
