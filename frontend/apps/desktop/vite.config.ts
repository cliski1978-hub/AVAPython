import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [tailwindcss(), react()],
  envDir: "../../..",
  clearScreen: false,
  server: {
    port: 5174,
    strictPort: true,
  },
});
