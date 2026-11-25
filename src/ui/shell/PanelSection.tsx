import type { ReactNode } from 'react';

interface PanelSectionProps {
  title: string;
  /** Short availability note shown beside the heading, such as "Not yet available". */
  status?: string;
  children: ReactNode;
}

// Sections are grouped by their headings rather than as named regions, so the panel does not
// add a landmark per section.
export function PanelSection({ title, status, children }: PanelSectionProps) {
  return (
    <div className="panel-section">
      <h3>
        {title}
        {status && <span className="section-status">{status}</span>}
      </h3>
      <div className="section-body">
        {typeof children === 'string' ? <p>{children}</p> : children}
      </div>
    </div>
  );
}
