/** @type {import('@storybook/html-vite').StorybookConfig} */
const config = {
  stories: ["../packages/ui/stories/**/*.stories.js"],
  framework: "@storybook/html-vite",
  addons: ["@storybook/addon-docs", "@storybook/addon-a11y"],
  core: { disableTelemetry: true },
};

export default config;
