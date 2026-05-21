// App.jsx — interactive cockpit demo
const { useState: useS } = React;

function App() {
  const [tab, setTab] = useS('cockpit');
  const [response, setResponse] = useS(null);
  const [activity, setActivity] = useS([
    { time: '14:01:02', method: 'GET', label: 'health', url: '/health',     status: '200 OK', ok: true },
    { time: '14:01:14', method: 'GET', label: 'agents', url: '/v1/agents/', status: '200 OK', ok: true },
  ]);

  function runInvoke() {
    const body = '{ "agent":"orchestrator", "status":"running", "trace_id":"tr_8af0c2" }';
    setResponse(body);
    setActivity([
      { time: new Date().toLocaleTimeString('en-GB'), method: 'POST', label: 'invoke', url: '/v1/agents/orchestrator/invoke', status: '200 OK', ok: true },
      ...activity
    ]);
  }

  return (
    <div className="cockpit">
      <Topbar workspace="cache-metrics-rollout" permission="OPERATOR · SOFT GATE" />
      <div className="layout">
        <Sidebar activeTab={tab} onTab={setTab} workspace="Cache metrics rollout" />
        <main className="workspace">
          {tab === 'cockpit' ? <Dashboard onTab={setTab} /> : (
            <section className="hero chamfer-tl-br">
              <div className="hero-deco"><div className="grid"></div><div className="stripes"></div></div>
              <div className="hero-content">
                <div>
                  <p className="eyebrow">▸ {String(tab).toUpperCase()}</p>
                  <h2>{tab.replace(/-/g,' ')}</h2>
                  <p>This panel mirrors the AGENT-33 cockpit. Switch back to the cockpit tab to see the canonical layout.</p>
                </div>
                <div className="status"><span>VIEW</span><strong>UI KIT</strong></div>
              </div>
            </section>
          )}

          <section className="api-section">
            <div className="api-section-head">
              <div>
                <p className="eyebrow">▸ API SURFACE</p>
                <h3>Agent endpoints</h3>
              </div>
              <span className="count">3 OPERATIONS · ALL GATED</span>
            </div>
            <div className="ops">
              <OperationCard
                method="GET"
                title="List agents"
                desc="Return all registered agents and their scopes."
                path="/v1/agents/"
              />
              <OperationCard
                method="POST"
                title="Invoke orchestrator"
                desc="Run the orchestrator agent on the supplied task with model + temperature override."
                path="/v1/agents/orchestrator/invoke"
                defaultBody={'{ "inputs": { "task": "Add cache metrics" } }'}
                onRun={runInvoke}
                response={response}
              />
              <OperationCard
                method="DELETE"
                title="Cancel run"
                desc="Cancel an in-flight workflow run. Hard gate — admin scope required."
                path="/v1/runs/{run_id}"
                defaultBody={'{ "reason": "operator cancel" }'}
              />
            </div>
          </section>
        </main>
        <ActivityPanel activity={activity} />
      </div>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(<App />);
