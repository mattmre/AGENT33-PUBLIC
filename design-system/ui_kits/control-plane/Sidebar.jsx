// Sidebar.jsx — workspace session + nav (cyber-techno aesthetic)
function Sidebar({ activeTab, onTab, workspace }) {
  const primary = [
    { id: 'cockpit',   label: 'Operations cockpit', desc: 'Active project · gates' },
    { id: 'sessions',  label: 'Sessions & runs',    desc: 'Traces · blockers · reviews' },
    { id: 'workflows', label: 'Workflows',          desc: 'Starters · execution' },
    { id: 'agents',    label: 'Agents',             desc: 'Invoke · configure · scope' },
  ];
  const tools = [
    { label: 'Build',   tabs: ['Agent builder', 'Workflow starter', 'Pack marketplace'] },
    { label: 'Inspect', tabs: ['Traces', 'Evaluations', 'MCP health'] },
    { label: 'Govern',  tabs: ['Releases', 'Improvement loops', 'Safety center'] },
  ];

  return (
    <aside className="sidebar">
      <div className="session">
        <span className="session-label">Workspace</span>
        <select defaultValue={workspace} onChange={() => {}}>
          <option>Cache metrics rollout</option>
          <option>Onboarding agent v2</option>
          <option>P-PACK v3 evaluation</option>
        </select>
        <div className="stats">
          <div className="stat live"><span>RUN</span><strong>3</strong></div>
          <div className="stat warn"><span>REV</span><strong>2</strong></div>
          <div className="stat err"><span>BLK</span><strong>1</strong></div>
        </div>
      </div>

      <nav className="nav-group">
        <span className="nav-label">Cockpit</span>
        <div className="nav-tabs">
          {primary.map(p => (
            <button key={p.id}
              className={activeTab === p.id ? 'active' : ''}
              onClick={() => onTab(p.id)}>
              {p.label}
              <small>{p.desc}</small>
            </button>
          ))}
        </div>
      </nav>

      {tools.map(g => (
        <nav className="nav-group" key={g.label}>
          <span className="nav-label">{g.label}</span>
          <div className="nav-tabs">
            {g.tabs.map(t => (
              <button key={t} onClick={() => onTab(t)}>{t}</button>
            ))}
          </div>
        </nav>
      ))}
    </aside>
  );
}
window.Sidebar = Sidebar;
