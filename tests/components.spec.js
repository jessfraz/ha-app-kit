import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { fileURLToPath } from "node:url";

test("shell preserves actions, navigation, safe links and status", async ({
  page,
}) => {
  await page.goto("/iframe.html?id=app-shell--connected&viewMode=story");
  await expect(
    page.getByRole("banner").getByRole("link", { name: "Mail home" }),
  ).toBeVisible();
  await page.getByRole("link", { name: "Settings", exact: true }).click();
  await expect(
    page.getByRole("link", { name: "Settings", exact: true }),
  ).toHaveAttribute("aria-current", "page");
  await expect(
    page.getByRole("link", { name: "Mail", exact: true }),
  ).not.toHaveAttribute("aria-current");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Settings");
  await page.getByRole("button", { name: "Refresh", exact: true }).click();
  await expect(page.getByRole("contentinfo").getByRole("status")).toHaveText(
    "Refresh requested",
  );
  await expect(page.getByRole("main").getByRole("status")).toHaveText("");
  await expect(page.getByRole("contentinfo").getByRole("link")).toHaveAttribute(
    "rel",
    "noopener noreferrer",
  );
});

for (const story of [
  "app-shell--connected",
  "app-shell--stale",
  "app-shell--long-name",
  "components-controls--form",
  "components-controls--dialog",
]) {
  test(`${story} has no accessibility violations or horizontal overflow`, async ({
    page,
  }) => {
    await page.goto(`/iframe.html?id=${story}&viewMode=story`);
    await expect(page.getByRole("main")).toBeVisible();
    expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true);
    await expect(page).toHaveScreenshot(`${story}.png`, { fullPage: true });
  });
}

test("native dialog is accessible while open and returns keyboard focus", async ({
  page,
}) => {
  await page.goto("/iframe.html?id=components-controls--dialog&viewMode=story");
  const open = page.getByRole("button", { name: "View details" });
  await open.focus();
  await page.keyboard.press("Enter");
  await expect(
    page.getByRole("dialog", { name: "Mail details" }),
  ).toBeVisible();
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  await expect(page).toHaveScreenshot("open-dialog.png", { fullPage: true });
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).not.toBeVisible();
  await expect(open).toBeFocused();
});

test("required form choice enables its action", async ({ page }) => {
  await page.goto("/iframe.html?id=components-controls--form&viewMode=story");
  await expect(page.getByRole("button", { name: "Save" })).toBeDisabled();
  await page.getByLabel("Mailbox").selectOption("example");
  await expect(page.getByRole("button", { name: "Save" })).toBeEnabled();
});

test("mount rejects invalid destinations without changing app-owned DOM and creates no IDs", async ({
  page,
}) => {
  await page.route("**/app-kit-contract.js", (route) =>
    route.fulfill({
      path: fileURLToPath(
        new URL("../packages/ui/src/index.js", import.meta.url),
      ),
      contentType: "text/javascript",
    }),
  );
  await page.goto("/iframe.html?id=app-shell--connected&viewMode=story");
  const result = await page.evaluate(async () => {
    const moduleUrl = new URL("/app-kit-contract.js", location.href).href;
    /** @type {typeof import('../packages/ui/src/index.js')} */
    const kit = await import(moduleUrl);
    const failures = [];
    for (const sourceUrl of [
      "",
      "javascript:alert(1)",
      "https://example:example@example.com/",
    ]) {
      const header = document.createElement("header");
      const footer = document.createElement("footer");
      header.textContent = "Existing header";
      footer.textContent = "Existing footer";
      try {
        kit.mountAppShell({ header, footer, name: "Example", sourceUrl });
      } catch (error) {
        failures.push(
          error instanceof TypeError &&
            header.textContent === "Existing header" &&
            footer.textContent === "Existing footer",
        );
      }
    }
    const header = document.createElement("header");
    const footer = document.createElement("footer");
    const options = {
      header,
      footer,
      name: "Example",
      sourceUrl: "https://example.com/",
    };
    Reflect.deleteProperty(options, "sourceUrl");
    try {
      kit.mountAppShell(options);
    } catch (error) {
      failures.push(error instanceof TypeError);
    }
    try {
      kit.mountAppShell({
        header,
        footer: header,
        name: "Example",
        sourceUrl: "https://example.com/",
      });
    } catch (error) {
      failures.push(error instanceof TypeError);
    }
    const shell = kit.mountAppShell({
      header,
      footer,
      name: "<script>Example</script>",
      sourceUrl: "https://example.com/",
    });
    return {
      failures,
      ids:
        header.querySelectorAll("[id]").length +
        footer.querySelectorAll("[id]").length,
      unsafeElements: header.querySelectorAll("script").length,
      renderedName: header.textContent,
      initialKind: shell.status.dataset.kind,
    };
  });
  expect(result).toEqual({
    failures: [true, true, true, true, true],
    ids: 0,
    unsafeElements: 0,
    renderedName: "<script>Example</script>",
    initialKind: "neutral",
  });
});
