import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { AuthProvider } from "./auth/AuthProvider";
import { loadConfig } from "./config";
import { StartupBoundary, StartupError } from "./StartupError";
import "./styles/tokens.css";

const root = createRoot(document.getElementById("root")!);

// Configuration is read at run time, so a bad value is an ordinary situation.
// Whatever goes wrong, the page says what it was rather than rendering nothing.
try {
  loadConfig();
  root.render(
    <StrictMode>
      <StartupBoundary>
        <AuthProvider>
          <App />
        </AuthProvider>
      </StartupBoundary>
    </StrictMode>,
  );
} catch (error) {
  root.render(<StartupError error={error} />);
}
