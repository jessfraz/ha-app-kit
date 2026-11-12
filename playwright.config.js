import { defineConfig, devices } from "@playwright/test";

const layouts = [
  { name: "iphone-portrait", use: devices["iPhone 13"] },
  { name: "iphone-landscape", use: devices["iPhone 13 landscape"] },
  { name: "ipad-portrait", use: devices["iPad Air"] },
  { name: "ipad-landscape", use: devices["iPad Air landscape"] },
  {
    name: "desktop-portrait",
    use: { viewport: { width: 1000, height: 1440 } },
  },
  {
    name: "desktop-landscape",
    use: { viewport: { width: 1440, height: 1000 } },
  },
];

/** @type {Array<"chromium" | "webkit">} */
const browsers = ["chromium", "webkit"];

export default defineConfig({
  testDir: "./tests",
  fullyParallel: true,
  use: { baseURL: "http://127.0.0.1:6007", trace: "retain-on-failure" },
  webServer: {
    command:
      "pnpm exec vite preview --outDir storybook-static --host 127.0.0.1 --port 6007 --strictPort",
    url: "http://127.0.0.1:6007",
    reuseExistingServer: !process.env.CI,
  },
  projects: [
    {
      name: "desktop-light",
      testIgnore: "responsive.spec.js",
      use: { viewport: { width: 1440, height: 1000 }, colorScheme: "light" },
    },
    {
      name: "desktop-dark",
      testIgnore: "responsive.spec.js",
      use: { viewport: { width: 1440, height: 1000 }, colorScheme: "dark" },
    },
    {
      name: "mobile-light",
      testIgnore: "responsive.spec.js",
      use: { viewport: { width: 390, height: 844 }, colorScheme: "light" },
    },
    {
      name: "mobile-dark",
      testIgnore: "responsive.spec.js",
      use: { viewport: { width: 390, height: 844 }, colorScheme: "dark" },
    },
    ...layouts.flatMap(({ name, use }) =>
      browsers.map((browserName) => ({
        name: `${name}-${browserName}`,
        testMatch: "responsive.spec.js",
        use: { ...use, browserName },
      })),
    ),
  ],
});
