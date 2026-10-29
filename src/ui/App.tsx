const workflow = [
  { title: 'Add locations', description: 'Create or upload transit stops and station locations.' },
  { title: 'Generate walksheds', description: 'Explore the places connected by the walking network.' },
  { title: 'Review and export', description: 'Compare station-area findings and share planning results.' },
] as const;

export function App() {
  return (
    <>
      <a className="skip-link" href="#main">Skip to content</a>
      <header className="site-header">
        <div className="header-inner">
          <span className="wordmark">FLM <span>Walkshed Index</span></span>
          <span className="status-label">Development preview</span>
        </div>
      </header>
      <main id="main" tabIndex={-1}>
        <section className="introduction" aria-labelledby="page-title">
          <p className="eyebrow">First / last mile planning</p>
          <h1 id="page-title">Understand walking access to transit.</h1>
          <p className="intro-copy">
            The FLM Walkshed Index will help planners explore access around
            Colorado transit stops and stations through connected walking networks.
          </p>
          <div className="development-note">
            <span className="note-marker" aria-hidden="true" />
            <p><strong>The project is taking shape.</strong> This page establishes the
              development foundation. Analysis features will arrive in later stages.</p>
          </div>
        </section>
        <section className="workflow-section" aria-labelledby="workflow-title">
          <div className="section-heading">
            <h2 id="workflow-title">The planned workflow</h2>
            <p>From station locations to useful planning evidence.</p>
          </div>
          <ol className="workflow-list">
            {workflow.map((step, index) => (
              <li key={step.title}>
                <span className="step-number" aria-hidden="true">0{index + 1}</span>
                <h3>{step.title}</h3>
                <p>{step.description}</p>
              </li>
            ))}
          </ol>
        </section>
      </main>
      <footer className="site-footer">
        <p>FLM Walkshed Index <span aria-hidden="true">/</span> Colorado</p>
        <a href="https://github.com/Felsburg-Holt-Ullevig/flm_walkshed_index">Project repository</a>
      </footer>
    </>
  );
}
