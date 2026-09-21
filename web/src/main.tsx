import { ClerkProvider } from "@clerk/clerk-react";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { loadConfig } from "./config";
import { StartupBoundary, StartupError } from "./StartupError";
import "./styles/tokens.css";

const root = createRoot(document.getElementById("root")!);

// Configuration is read at run time, so a bad value is an ordinary situation.
// Whatever goes wrong, the page says what it was rather than rendering nothing.
try {
  const config = loadConfig();
  root.render(
    <StrictMode>
      <StartupBoundary>
        <ClerkProvider publishableKey={config.clerkPublishableKey}>
          <App />
        </ClerkProvider>
      </StartupBoundary>
    </StrictMode>,
  );
} catch (error) {
  root.render(<StartupError error={error} />);
}
