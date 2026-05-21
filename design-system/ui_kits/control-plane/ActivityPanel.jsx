// ActivityPanel.jsx — observation stream + recent calls (vector accents)
function ActivityPanel({ activity }) {
  const observations = [
    { time: '14:02:17', agent: 'orchestrator', type: 'plan', content: 'Drafted 4-step rollout: instrument cache, ship metrics, validate, gate release.' },
    { time: '14:02:31', agent: 'tool:shell',   type: 'exec', content: '$ pytest engine/tests/cache_metrics -q\n4 passed in 1.2s' },
    { time: '14:02:48', agent: 'reviewer',     type: 'gate', content: 'Soft gate held on release step — needs operator approval before rollout.' },
  ];
  return (
    <aside className="activity">
      <section className="observation chamfer-tl-br">
        <h3>OBSERVATION STREAM</h3>
        <div className="obs-list">
          {observations.map((o, i) => (
            <div className="obs-item" key={i}>
              <div className="obs-head">
                <span className="time">{o.time}</span>
                <span className="agent">{o.agent}</span>
                <span className="type">{o.type}</span>
              </div>
              <pre className="obs-content">{o.content}</pre>
            </div>
          ))}
        </div>
      </section>

      <section style={{display:'grid',gap:8}}>
        <h2>RECENT CALLS</h2>
        <div className="recent">
          {activity.map((a, i) => (
            <div className={'recent-item ' + (a.ok ? 'ok' : 'err')} key={i}>
              <div className="recent-head">
                <span className="time">{a.time}</span>
                <span className={'status ' + (a.ok ? 'ok' : 'err')}>{a.status}</span>
              </div>
              <span className="recent-method">{a.method} {a.label}</span>
              <span className="recent-url">{a.url}</span>
            </div>
          ))}
        </div>
      </section>
    </aside>
  );
}
window.ActivityPanel = ActivityPanel;
