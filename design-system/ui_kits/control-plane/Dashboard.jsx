// Dashboard.jsx — hero + KPI cards + runtime health
function Dashboard({ onTab }) {
  return (
    <>
      <section className="hero chamfer-tl-br">
        <div className="hero-deco">
          <div className="grid"></div>
          <div className="stripes"></div>
        </div>
        <div className="hero-content">
          <div>
            <p className="eyebrow">▸ PROJECT COCKPIT · LIVE</p>
            <h2>Cache metrics rollout</h2>
            <p>Add request-cache observability behind the orchestrator. P-PACK v3 evaluation pending review on the rollout pull request.</p>
            <div className="crumb" style={{marginTop:10}}>
              <span>WS</span> <b>cache-metrics-rollout</b>
              <span className="sep"> · </span>
              <span>BRANCH</span> <b>feat/cache-metrics</b>
              <span className="sep"> · </span>
              <span>RUN</span> <b>r_8af0c2</b>
            </div>
          </div>
          <div className="status">
            <span>STATUS</span>
            <strong>RUNNING · SOFT GATE</strong>
            <span style={{marginTop:6}}>BUDGET</span>
            <strong>78% REMAINING</strong>
          </div>
        </div>
      </section>

      <div className="grid-kpi">
        <article className="kpi chamfer-tl-br">
          <div className="grid-bg"></div>
          <p className="eyebrow">CURRENT RUN</p>
          <h3>3 tasks need attention</h3>
          <p>Inspect live progress, blockers, and review gates on the task board.</p>
          <div className="actions">
            <button className="btn primary" onClick={() => onTab('sessions')}>Review board</button>
            <button className="btn">Export trace</button>
          </div>
        </article>

        <article className="kpi chamfer-tl-br">
          <div className="grid-bg"></div>
          <p className="eyebrow">RECOMMENDED NEXT</p>
          <h3>Use a guided workflow</h3>
          <p>Route this project through a prebuilt starter rather than raw endpoint setup.</p>
          <div className="actions">
            <button className="btn">Browse starters</button>
          </div>
        </article>

        <article className="kpi chamfer-tl-br warn">
          <div className="grid-bg"></div>
          <p className="eyebrow" style={{color:'#f6bd60'}}>▲ SAFETY GATE</p>
          <h3>2 gates open on this run</h3>
          <p>Human approval needed on release rollout. Tool: <b>shell exec</b> · soft gate.</p>
          <div className="actions">
            <button className="btn">Approve</button>
            <button className="btn">Hold</button>
          </div>
        </article>
      </div>

      <section className="health chamfer-tl-br">
        <div className="health-head">
          <div>
            <p className="eyebrow">RUNTIME HEALTH</p>
            <h3 style={{margin:'4px 0 0',fontSize:'1rem',color:'#e2e8f0',fontWeight:600}}>All services responding</h3>
          </div>
          <span style={{color:'#7db6ca',fontFamily:'var(--mono)',fontSize:'10px',letterSpacing:'.18em',textTransform:'uppercase'}}>polled · 5 s</span>
        </div>
        <div className="health-row">
          <div className="health-cell ok"><span>OVERALL</span><strong>HEALTHY</strong></div>
          <div className="health-cell ok"><span>API</span><strong>OK</strong></div>
          <div className="health-cell ok"><span>DATABASE</span><strong>OK</strong></div>
          <div className="health-cell warn"><span>OLLAMA</span><strong>CONFIGURED</strong></div>
          <div className="health-cell ok"><span>QUEUE</span><strong>OK</strong></div>
          <div className="health-cell err"><span>WEBHOOKS</span><strong>DEGRADED</strong></div>
        </div>
      </section>
    </>
  );
}
window.Dashboard = Dashboard;
