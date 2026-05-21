import type { DomainConfig } from "../../types";

export const multimodalDomain: DomainConfig = {
    id: "multimodal",
    title: "Multimodal APIs",
    description: "Interact with audio, vision, and speech synthesis endpoints.",
    operations: [
        {
            id: "multimodal-vision",
            title: "Vision Analysis",
            method: "POST",
            path: "/v1/multimodal/vision",
            description: "Analyze an image and return structured data.",
            defaultBody: JSON.stringify({
                image_url: "https://example.com/sample.jpg",
                prompt: "Describe the image contents."
            }, null, 2)
        },
        {
            id: "multimodal-tenant-policy",
            title: "Get Tenant Policy",
            method: "GET",
            path: "/v1/multimodal/tenant-policy",
            description: "Retrieve multimodal limits and allowed providers for the tenant."
        }
    ]
};
