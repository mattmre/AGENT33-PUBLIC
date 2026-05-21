import type { OpenRouterModelEntry } from "../../lib/openrouterModels";
import { getModelCapabilityTags } from "./capabilityLabels";
import type { ProviderModelRecommendation } from "./presets";

interface ModelCapabilityBadgesProps {
  model: OpenRouterModelEntry | ProviderModelRecommendation;
}

export function ModelCapabilityBadges({ model }: ModelCapabilityBadgesProps): JSX.Element | null {
  const tags = getModelCapabilityTags(model);
  if (tags.length === 0) {
    return null;
  }

  return (
    <span className="model-capability-badges" aria-label={`${model.name} capability labels`}>
      {tags.map((tag) => (
        <span
          key={tag.kind}
          className={`model-capability-badge model-capability-badge--${tag.kind}`}
          title={tag.label}
        >
          {tag.label}
        </span>
      ))}
    </span>
  );
}
