// OperationCard.jsx — bespoke chamfered API operation card with vertical method rail
function OperationCard({ method, title, desc, path, defaultBody, onRun, response }) {
  const m = method.toLowerCase();
  return (
    <article className="op">
      <div className="op-deco">
        <div className="grid"></div>
        <div className="stripes"></div>
      </div>
      <div className="op-grid">
        <div className="rail-left">
          <span className={'method ' + m}>{method}</span>
        </div>
        <div className="op-body">
          <h4>{title}</h4>
          <p>{desc}</p>
          <div className="op-meta">
            <span className="accent">▸ {path}</span>
            <span className="sep">·</span>
            <span>{response ? <span className="ok">200 OK · 412 ms</span> : 'NOT RUN'}</span>
            <span className="sep">·</span>
            <span>SCOPE · {m === 'delete' ? 'ADMIN' : 'OPERATOR'}</span>
          </div>
        </div>
        <div className="rail-right">
          <button className="btn primary" onClick={onRun}>Run</button>
          <button className="btn mono">cURL</button>
        </div>
      </div>
    </article>
  );
}
window.OperationCard = OperationCard;
