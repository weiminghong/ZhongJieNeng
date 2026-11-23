import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import ModelSettings from "./ModelSettings";
import "./styles/tokens.css";
import "./styles/tailwind-theme.css";
import "./styles/app.css";
import "./styles/settings.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode><ModelSettings /></StrictMode>,
);
