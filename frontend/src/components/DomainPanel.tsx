import { useMemo, useState } from "react";

import type { ApiResult, DomainConfig } from "../types";
import { OperationCard } from "./OperationCard";
import { SecurityDashboard } from "../features/security-dashboard/SecurityDashboard";
import { ImprovementCycleWizard } from "../features/improvement-cycle/ImprovementCycleWizard";

interface DomainPanelProps {
  domain: DomainConfig;
  token: string;
  apiKey: string;
  externalFilter?: string;
  onResult: (label: string, result: ApiResult) => void;
}

export function DomainPanel({
  domain,
  token,
  apiKey,
  externalFilter = "",
  onResult
}: DomainPanelProps): JSX.Element {
  const [filter, setFilter] = useState("");
  const operations = useMemo(() => {
    const terms = [externalFilter, filter]
      .join(" ")
      .trim()
      .toLowerCase()
      .split(/\s+/)
      .filter(Boolean);
    if (terms.length === 0) {
      return domain.operations;
    }
    return domain.operations.filter((op) => {
      const searchable = [
        op.title,
        op.path,
        op.description
      ].join(" ");
      const searchableLower = searchable.toLowerCase();
      return terms.every((term) => searchableLower.includes(term));
    });
  }, [domain.operations, externalFilter, filter]);

  return (
    <section className="domain-panel">
      <header className="domain-head">
        <div>
          <h2>{domain.title}</h2>
          <p>{domain.description}</p>
        </div>
        {externalFilter.trim() !== "" ? (
          <p className="domain-global-filter">Pro search applied: {externalFilter.trim()}</p>
        ) : null}
        <label className="search-field">
          Search
          <input
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="Filter operations"
          />
        </label>
      </header>

      {domain.id === "component-security" && (
        <div className="custom-feature-panel">
          <SecurityDashboard token={token} />
        </div>
      )}

      {domain.id === "workflows" && (
        <div className="custom-feature-panel">
          <ImprovementCycleWizard token={token} apiKey={apiKey} onResult={onResult} />
        </div>
      )}

      <div className="domain-ops">
        {operations.map((operation) => (
          <OperationCard
            key={operation.id}
            operation={operation}
            token={token}
            apiKey={apiKey}
            onResult={onResult}
          />
        ))}
      </div>
    </section>
  );
}
