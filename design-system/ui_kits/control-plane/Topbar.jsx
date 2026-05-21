// Topbar.jsx — sticky brand bar
function Topbar({ workspace, permission }) {
  return (
    <header className="topbar">
      <div className="brand">
        <div className="brand-mark"><div className="core"></div></div>
        <h1>AGENT-33</h1>
        <span className="sub">Control Plane</span>
      </div>
      <div className="top-meta">
        <span className="pill">{permission}</span>
        <div className="field"><span>WS</span><b>{workspace}</b></div>
        <div className="field"><span>HOST</span><b>localhost:8000</b></div>
        <div className="field"><span>v</span><b>0.33.0</b></div>
      </div>
    </header>
  );
}
window.Topbar = Topbar;
