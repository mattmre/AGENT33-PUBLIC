import { describe, expect, it } from "vitest";

import { multimodalDomain } from "./multimodal";

describe("multimodalDomain", () => {
  it("uses mounted multimodal request and tenant-policy routes", () => {
    expect(multimodalDomain.operations.map((operation) => `${operation.method} ${operation.path}`)).toEqual([
      "POST /v1/multimodal/requests",
      "GET /v1/multimodal/requests",
      "POST /v1/multimodal/tenants/{tenant_id}/policy"
    ]);
  });

  it("uses backend enum values in default payloads", () => {
    const create = multimodalDomain.operations.find((operation) => operation.id === "multimodal-create-request");
    const policy = multimodalDomain.operations.find((operation) => operation.id === "multimodal-set-tenant-policy");

    expect(JSON.parse(create?.defaultBody ?? "{}").modality).toBe("vision_analysis");
    expect(JSON.parse(policy?.defaultBody ?? "{}").allowed_modalities).toEqual([
      "vision_analysis",
      "speech_to_text",
      "text_to_speech"
    ]);
  });
});
