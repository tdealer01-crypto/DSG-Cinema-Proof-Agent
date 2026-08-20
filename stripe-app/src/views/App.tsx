import type { ExtensionContextValue } from '@stripe/ui-extension-sdk/context';
import ChargeGate from './ChargeGate';

export default function App({
  extensionContext,
}: {
  extensionContext?: ExtensionContextValue | null;
}) {
  return <ChargeGate extensionContext={extensionContext} />;
}
