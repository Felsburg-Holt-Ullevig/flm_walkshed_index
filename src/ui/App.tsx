import { NetworkReview } from './network-review/NetworkReview';
import { AppShell } from './shell/AppShell';

export function App() {
  const view = new URLSearchParams(window.location.search).get('view');
  return view === 'network-review' ? <NetworkReview /> : <AppShell />;
}
