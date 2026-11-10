/**
 * @typedef {object} AppShellOptions
 * @property {string} name
 * @property {HTMLElement} header
 * @property {HTMLElement} footer
 * @property {string} sourceUrl
 * @property {string} [homeUrl]
 * @property {string} [icon]
 * @property {string} [darkIcon]
 * @property {readonly (HTMLElement | SVGElement)[]} [brand]
 * @property {readonly HTMLElement[]} [actions]
 * @property {string} [version]
 * @property {string} [status]
 */

/**
 * Mount the common shell into app-owned landmarks. Actions retain their
 * listeners when moved; the app continues to own their behavior and lifecycle.
 *
 * @param {AppShellOptions} options
 */
export function mountAppShell(options) {
  const { header, footer, name } = options;
  if (typeof name !== "string" || !name.trim()) {
    throw new TypeError("The app name is required.");
  }
  if (
    header === footer ||
    header.contains(footer) ||
    footer.contains(header) ||
    header.ownerDocument !== footer.ownerDocument
  ) {
    throw new TypeError("The shell needs separate landmarks in one document.");
  }

  const doc = header.ownerDocument;
  if (
    (options.brand?.length && (options.icon || options.darkIcon)) ||
    (options.darkIcon && !options.icon)
  ) {
    throw new TypeError(
      "Use brand elements or a primary icon with an optional dark icon.",
    );
  }
  // Validate all destinations before replacing app-owned DOM.
  const homeUrl = safeUrl(options.homeUrl ?? "./", doc);
  const sourceUrl = safeUrl(options.sourceUrl, doc);
  const icon = options.icon ? safeUrl(options.icon, doc) : undefined;
  const darkIcon = options.darkIcon
    ? safeUrl(options.darkIcon, doc)
    : undefined;
  const wordmark = doc.createElement("a");
  wordmark.className = "wordmark";
  wordmark.href = homeUrl;
  wordmark.setAttribute("aria-label", `${name} home`);
  for (const { source, className } of [
    { source: icon, className: "brand-light" },
    { source: darkIcon, className: "brand-dark" },
  ]) {
    if (!source) continue;
    const image = doc.createElement("img");
    image.src = source;
    image.className = className;
    image.width = 30;
    image.height = 30;
    image.alt = "";
    wordmark.append(image);
  }
  wordmark.append(...(options.brand ?? []));
  if (options.icon && !options.darkIcon) wordmark.classList.add("single-brand");
  wordmark.append(doc.createTextNode(name));

  const actions = doc.createElement("div");
  actions.className = "header-actions";
  actions.append(...(options.actions ?? []));
  header.classList.add("app-header");
  header.replaceChildren(wordmark, actions);

  const identity = doc.createElement("p");
  const version = doc.createElement("span");
  version.className = "app-version";
  identity.append(doc.createTextNode(`${name} `), version);
  const status = doc.createElement("p");
  status.className = "service-status";
  status.setAttribute("role", "status");
  status.setAttribute("aria-live", "polite");
  const source = doc.createElement("a");
  source.href = sourceUrl;
  source.target = "_blank";
  source.rel = "noopener noreferrer";
  source.textContent = "Source code ↗";
  source.setAttribute("aria-label", `${name} source code (opens in a new tab)`);
  footer.classList.add("app-footer");
  footer.replaceChildren(identity, status, source);

  /** @param {string} value */
  function setVersion(value) {
    if (version.textContent !== value) version.textContent = value;
  }
  /** @param {string} value @param {'neutral' | 'ok' | 'stale' | 'error'} [kind] */
  function setStatus(value, kind = "neutral") {
    if (status.textContent !== value) status.textContent = value;
    status.dataset.kind = kind;
  }
  setVersion(options.version ?? "");
  setStatus(options.status ?? "");
  return { header, footer, version, status, setVersion, setStatus };
}

/**
 * @param {HTMLElement} element
 * @param {string} message
 * @param {'status' | 'error'} [kind]
 */
export function setNotice(element, message, kind = "status") {
  element.classList.add("notice");
  element.classList.toggle("error", kind === "error");
  // Keep a stable, mounted live region. Blocking failures use a separate
  // app-owned alert rather than changing this region's role mid-announcement.
  element.setAttribute("role", "status");
  element.setAttribute("aria-live", "polite");
  element.setAttribute("aria-atomic", "true");
  element.hidden = false;
  element.textContent = message;
}

/**
 * @typedef {object} NavigationItem
 * @property {string} id
 * @property {string} label
 * @property {string} href
 */

/**
 * Native navigation links retain modified-click/open-in-new-tab behavior.
 * An app can intercept ordinary clicks while keeping its own route ownership.
 *
 * @param {HTMLElement} navigation
 * @param {{label: string, items: readonly NavigationItem[], active: string,
 * onNavigate?: (id: string, event: MouseEvent) => void}} options
 */
export function mountNavigation(navigation, options) {
  /** @type {Map<string, HTMLAnchorElement>} */
  const links = new Map();
  const children = options.items.map(({ id, label, href }) => {
    if (!id || links.has(id))
      throw new TypeError("Navigation IDs must be unique.");
    const link = navigation.ownerDocument.createElement("a");
    link.href = safeUrl(href, navigation.ownerDocument);
    link.textContent = label;
    if (options.onNavigate) {
      link.addEventListener("click", (event) => {
        if (
          event.button === 0 &&
          !event.metaKey &&
          !event.ctrlKey &&
          !event.shiftKey &&
          !event.altKey
        ) {
          options.onNavigate?.(id, event);
        }
      });
    }
    links.set(id, link);
    return link;
  });
  if (!links.has(options.active))
    throw new TypeError("The active view must exist.");
  navigation.classList.add("view-switch");
  navigation.setAttribute("aria-label", options.label);
  navigation.replaceChildren(...children);
  /** @param {string} id */
  function setActive(id) {
    if (!links.has(id)) throw new TypeError("The active view must exist.");
    for (const [key, link] of links) {
      if (key === id) link.setAttribute("aria-current", "page");
      else link.removeAttribute("aria-current");
    }
  }
  setActive(options.active);
  return { setActive };
}

/** @param {string} value @param {Document} doc */
function safeUrl(value, doc) {
  if (typeof value !== "string" || !value.trim()) {
    throw new TypeError("App links require a nonempty URL.");
  }
  const url = new URL(value, doc.baseURI);
  if (
    !["https:", "http:"].includes(url.protocol) ||
    url.username ||
    url.password
  ) {
    throw new TypeError(
      "App links must use HTTP or HTTPS without credentials.",
    );
  }
  return url.href;
}
