import { useEffect, useState } from "react";

import {
  APP_PRIMARY_NAV_ITEMS,
  APP_SECONDARY_NAV_GROUPS,
  getAppTabLabel,
  type AppTab
} from "../data/navigation";

interface AppNavigationProps {
  activeTab: AppTab;
  onNavigate: (tab: AppTab) => void;
}

export function AppNavigation({ activeTab, onNavigate }: AppNavigationProps): JSX.Element {
  const [expandedGroups, setExpandedGroups] = useState<Record<string, boolean>>(() =>
    Object.fromEntries(
      APP_SECONDARY_NAV_GROUPS.map((group) => [
        group.id,
        group.tabs.some((tab) => tab.id === activeTab)
      ])
    )
  );

  useEffect(() => {
    setExpandedGroups((current) => {
      const activeGroup = APP_SECONDARY_NAV_GROUPS.find((group) =>
        group.tabs.some((tab) => tab.id === activeTab)
      );
      if (!activeGroup) {
        return current;
      }
      if (current[activeGroup.id]) {
        return current;
      }
      return { ...current, [activeGroup.id]: true };
    });
  }, [activeTab]);

  return (
    <nav className="main-nav cockpit-sidebar-nav" aria-label="Main navigation">
      <section className="main-nav-primary" aria-label="Core destinations">
        <div className="main-nav-group-head">
          <span className="main-nav-group-label">Primary routes</span>
          <p>Stay in the main operator flow here. Specialized tools stay underneath.</p>
        </div>
        <div className="main-nav-primary-tabs">
          {APP_PRIMARY_NAV_ITEMS.map((item) => (
            <button
              key={item.id}
              type="button"
              className={activeTab === item.id ? "active" : ""}
              onClick={() => onNavigate(item.id)}
              aria-current={activeTab === item.id ? "page" : undefined}
              title={item.description}
            >
              <span className="main-nav-button-label">{getAppTabLabel(item.id)}</span>
            </button>
          ))}
        </div>
      </section>

      <div className="main-nav-secondary" aria-label="Secondary navigation">
        {APP_SECONDARY_NAV_GROUPS.map((group) => {
          const groupIsActive = group.tabs.some((tab) => tab.id === activeTab);
          const isExpanded = expandedGroups[group.id] ?? groupIsActive;

          return (
            <section
              key={group.id}
              className={`main-nav-group${groupIsActive ? " main-nav-group-active" : ""}`}
              aria-label={`${group.label} navigation`}
            >
              <button
                type="button"
                className="main-nav-group-toggle"
                aria-expanded={isExpanded}
                onClick={() =>
                  setExpandedGroups((current) => ({
                    ...current,
                    [group.id]: !current[group.id]
                  }))
                }
              >
                <span>
                  <span className="main-nav-group-label">Task group</span>
                  <strong>{group.label}</strong>
                </span>
                <small>{isExpanded ? "Collapse" : "Expand"}</small>
              </button>
              <p className="main-nav-group-copy">{group.description}</p>
              {isExpanded ? (
                <div className="main-nav-group-tabs">
                  {group.tabs.map((tab) => (
                    <button
                      key={tab.id}
                      type="button"
                      className={activeTab === tab.id ? "active" : ""}
                      onClick={() => onNavigate(tab.id)}
                      aria-current={activeTab === tab.id ? "page" : undefined}
                      title={tab.description}
                    >
                      <span className="main-nav-button-label">{tab.label}</span>
                    </button>
                  ))}
                </div>
              ) : null}
            </section>
          );
        })}
      </div>
    </nav>
  );
}
