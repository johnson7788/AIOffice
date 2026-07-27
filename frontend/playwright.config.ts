import { defineConfig } from "@playwright/test";

// L3 全链路 E2E：需先起 backend:8585 + frontend:3585 + documentserver:8081（挂 ai-rewrite 插件）
export default defineConfig({
  testDir: "./tests",
  timeout: 120_000,
  use: { baseURL: "http://localhost:3585", headless: true, viewport: { width: 1440, height: 900 } },
  reporter: "list",
});
