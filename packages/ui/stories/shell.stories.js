import { mountAppShell, mountNavigation, setNotice } from "../src/index.js";

/** @type {import('@storybook/html-vite').Meta} */
const meta = { title: "App/Shell", tags: ["autodocs"] };
export default meta;

/** @param {{name?: string, status?: string, error?: boolean}} options */
function example(options = {}) {
  const root = document.createElement("div");
  const header = document.createElement("header");
  const main = document.createElement("main");
  const footer = document.createElement("footer");
  const refresh = document.createElement("button");
  refresh.type = "button";
  refresh.className = "quiet";
  refresh.textContent = "Refresh";
  root.append(header, main, footer);
  const shell = mountAppShell({
    name: options.name ?? "Mail",
    header,
    footer,
    sourceUrl: "https://github.com/jessfraz/ha-app-kit",
    version: "0.1.0",
    status: options.status ?? "Up to date",
    actions: [refresh],
  });
  const navigation = document.createElement("nav");
  const heading = document.createElement("h1");
  const initialView = new URL(location.href).searchParams.get("demo_view");
  const active = ["all", "settings"].includes(initialView ?? "")
    ? (initialView ?? "mail")
    : "mail";
  /** @param {string} id */
  const href = (id) => {
    const url = new URL(location.href);
    url.searchParams.set("demo_view", id);
    return url.href;
  };
  const views = mountNavigation(navigation, {
    label: "Mail views",
    active,
    items: [
      { id: "mail", label: "Mail", href: href("mail") },
      { id: "all", label: "All mail", href: href("all") },
      { id: "settings", label: "Settings", href: href("settings") },
    ],
    onNavigate(id, event) {
      event.preventDefault();
      views.setActive(id);
      showView(id);
    },
  });
  const notice = document.createElement("p");
  setNotice(
    notice,
    options.error
      ? "Mail could not refresh. Previous results are still available."
      : "",
    options.error ? "error" : "status",
  );
  const empty = document.createElement("section");
  empty.className = "empty";
  const emptyTitle = document.createElement("h2");
  emptyTitle.textContent = options.error
    ? "New mail could not be checked"
    : "No new mail";
  const description = document.createElement("p");
  description.className = "muted";
  description.textContent = options.error
    ? "The last successful sync did not find any mail. Try refreshing again."
    : "New arrivals will appear here after the next sync.";
  /** @param {string} id */
  function showView(id) {
    heading.textContent =
      id === "settings" ? "Settings" : id === "all" ? "All mail" : "Mailbox";
    empty.hidden = id === "settings";
  }
  showView(active);
  empty.append(emptyTitle, description);
  main.append(navigation, heading, notice, empty);
  refresh.addEventListener("click", () => {
    setNotice(notice, "");
    shell.setStatus("Refresh requested");
  });
  shell.setStatus(
    options.status ?? "Up to date",
    options.error ? "stale" : "ok",
  );
  return root;
}

/** @type {import('@storybook/html-vite').StoryObj} */
export const Connected = { render: () => example() };

/** @type {import('@storybook/html-vite').StoryObj} */
export const Stale = {
  render: () =>
    example({ status: "Last successful sync: 2 hours ago", error: true }),
};

/** @type {import('@storybook/html-vite').StoryObj} */
export const LongName = {
  render: () => example({ name: "Property and utility records" }),
};
