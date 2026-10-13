import { createRoot } from "react-dom/client";
import { AppearanceProvider } from "@ava/ui-core";

import "@ava/ui-core/styles.css";
import "./index.css";
import { App } from "./App";

createRoot(document.getElementById("root")!).render(
  <AppearanceProvider><App /></AppearanceProvider>,
);
