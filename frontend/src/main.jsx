import React from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App.tsx";
import "./app.css";
import "./refinements.css";
import "./agent-workspace.css";
import "./studio-polish.css";
import "./landing.css";
import "./landing-agentic.css";
import "./landing-motion.css";
import "./landing-journey.css";
import "./cinematic-home.css";
import "./home-background.css";
import "./auth-artwork.css";
import "./public-polish.css";
import "./themes.css";
import {initializeTheme} from './components/ThemeToggle';

initializeTheme();

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
