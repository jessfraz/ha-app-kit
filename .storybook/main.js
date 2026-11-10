/** @type {import('@storybook/html-vite').StorybookConfig} */
const config = {
  stories: ["../packages/ui/stories/**/*.stories.js"],
  framework: "@storybook/html-vite",
  addons: ["@storybook/addon-docs", "@storybook/addon-a11y"],
  core: { disableTelemetry: true },
  viteFinal(config) {
    // Render the CSS embedded by the apps without compatibility rewrites.
    return { ...config, build: { ...config.build, cssMinify: false } };
  },
};

export default config;
