import "../packages/ui/src/style.css";

/** @type {import('@storybook/html-vite').Preview} */
const preview = {
  parameters: {
    layout: "fullscreen",
    a11y: { test: "error" },
    docs: { story: { inline: false, iframeHeight: "600px" } },
  },
};

export default preview;
