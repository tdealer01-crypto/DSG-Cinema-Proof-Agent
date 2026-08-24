import type { ExtensionContextValue } from '@stripe/ui-extension-sdk/context';
import ChargeGate from './ChargeGate';

export default function App(extensionContext: ExtensionContextValue) {
  return <ChargeGate {...extensionContext} />;
}
