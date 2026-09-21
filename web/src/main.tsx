import { ClerkProvider } from "@clerk/clerk-react";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { loadConfig } from "./config";
import "./styles/tokens.css";

const config = loadConfig();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ClerkProvider publishableKey={config.clerkPublishableKey}>
      <App />
    </ClerkProvider>
  </StrictMode>,
);
