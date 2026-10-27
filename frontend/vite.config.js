// Vite settings for the React dashboard. Runs on http://localhost:5173
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: { port: 5173, host: true },
  preview: { port: 5173, host: true },
});
