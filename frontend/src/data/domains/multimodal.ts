import type { DomainConfig } from "../../types";

export const multimodalDomain: DomainConfig = {
  id: "multimodal",
  title: "Multimodal APIs",
  description: "Interact with audio, vision, and speech synthesis endpoints.",
  operations: [
    {
      id: "multimodal-create-request",
      title: "Create Multimodal Request",
      method: "POST",
      path: "/v1/multimodal/requests",
      description: "Create and optionally execute a multimodal request.",
      defaultBody: JSON.stringify(
        {
          modality: "vision_analysis",
          input_text: "Describe the supplied artifact.",
          input_artifact_id: "artifact-demo-image",
          requested_timeout_seconds: 60,
          requested_by: "operator",
          execute_now: false
        },
        null,
        2
      )
    },
    {
      id: "multimodal-list-requests",
      title: "List Multimodal Requests",
      method: "GET",
      path: "/v1/multimodal/requests",
      description: "List recent multimodal requests with optional modality and state filters.",
      defaultQuery: {
        modality: "vision_analysis",
        limit: "25"
      }
    },
    {
      id: "multimodal-set-tenant-policy",
      title: "Set Tenant Policy",
      method: "POST",
      path: "/v1/multimodal/tenants/{tenant_id}/policy",
      description: "Set multimodal limits and provider guardrails for a tenant.",
      defaultPathParams: {
        tenant_id: "default"
      },
      defaultBody: JSON.stringify(
        {
          max_text_chars: 2000,
          max_artifact_bytes: 5000000,
          max_timeout_seconds: 120,
          allowed_modalities: ["vision_analysis", "speech_to_text", "text_to_speech"],
          voice_enabled: true,
          max_voice_concurrent_sessions: 1,
          max_voice_session_seconds: 1800
        },
        null,
        2
      )
    }
  ]
};
