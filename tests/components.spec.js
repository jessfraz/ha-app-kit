import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { fileURLToPath } from "node:url";

// The browser assertions own axe runs. Storybook auto-analysis would race them.

test("shell preserves actions, navigation, safe links and status", async ({
  page,
}) => {
  await page.goto(
    "/iframe.html?id=app-shell--connected&viewMode=story&globals=a11y.manual:!true",
  );
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
  "components-controls--selects",
  "components-controls--dialog",
]) {
  test(`${story} has no accessibility violations or horizontal overflow`, async ({
    page,
  }) => {
    if (story === "components-controls--selects") {
      // Match apps that permit only same-origin images in their UI.
      await page.route("**/iframe.html?**", async (route) => {
        const response = await route.fetch();
        await route.fulfill({
          response,
          headers: {
            ...response.headers(),
            "content-security-policy": "img-src 'self'",
          },
        });
      });
    }
    await page.goto(
      `/iframe.html?id=${story}&viewMode=story&globals=a11y.manual:!true`,
    );
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
  await page.goto(
    "/iframe.html?id=components-controls--dialog&viewMode=story&globals=a11y.manual:!true",
  );
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
  await page.goto(
    "/iframe.html?id=components-controls--form&viewMode=story&globals=a11y.manual:!true",
  );
  await expect(page.getByRole("button", { name: "Save" })).toBeDisabled();
  await page.getByLabel("Mailbox").selectOption("example");
  await expect(page.getByRole("button", { name: "Save" })).toBeEnabled();
  const enabledBackground = await page
    .getByLabel("Mailbox")
    .evaluate((field) => getComputedStyle(field).backgroundColor);
  await expect(page.getByLabel("Provider account")).not.toHaveCSS(
    "background-color",
    enabledBackground,
  );
  const requirements = page.getByText("Connection requirements", {
    exact: true,
  });
  const bounds = await requirements.boundingBox();
  expect(bounds?.height).toBeGreaterThanOrEqual(44);
  await requirements.focus();
  await page.keyboard.press("Enter");
  await expect(
    page.getByText("Choose a mailbox before saving the connection."),
  ).toBeVisible();
});

test("selects preserve native keyboard selection and disabled controls", async ({
  page,
}) => {
  await page.goto(
    "/iframe.html?id=components-controls--selects&viewMode=story&globals=a11y.manual:!true",
  );
  const brand = page.getByRole("combobox", { name: "Brand", exact: true });
  await brand.focus();
  await page.keyboard.press("f");
  await page.keyboard.press("Enter");
  await expect(brand).toHaveValue("Fictional label");
  await expect(brand).toBeFocused();
  await expect(brand).toHaveScreenshot("focused-select.png");
  await expect(page.getByRole("combobox", { name: "Disabled" })).toBeDisabled();
  await page
    .getByRole("listbox", { name: "Multiple choices" })
    .selectOption(["Example one", "Example three"]);
  await expect(page.getByRole("listbox")).toHaveValues([
    "Example one",
    "Example three",
  ]);
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
  await page.goto(
    "/iframe.html?id=app-shell--connected&viewMode=story&globals=a11y.manual:!true",
  );
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

test("long dialog keeps actions visible while its fields scroll", async ({
  page,
}) => {
  await page.goto(
    "/iframe.html?id=components-controls--long-form&viewMode=story&globals=a11y.manual:!true",
  );
  const open = page.getByRole("button", { name: "Edit connection" });
  await open.click();
  const dialog = page.getByRole("dialog", { name: "Edit connection" });
  await expect(dialog).toBeVisible();
  const save = dialog.getByRole("button", { name: "Save connection" });
  const cancel = dialog.getByRole("button", { name: "Cancel" });
  await expect(save).toBeInViewport({ ratio: 1 });
  await dialog.locator(".dialog-body").hover();
  await page.mouse.wheel(0, 2000);
  await expect(dialog.getByRole("heading")).toBeInViewport({ ratio: 1 });
  await expect(save).toBeInViewport({ ratio: 1 });
  await expect(cancel).toBeInViewport({ ratio: 1 });
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  await page.mouse.move(0, 0);
  await expect(page).toHaveScreenshot("long-form-dialog.png");
  await cancel.click();
  await expect(open).toBeFocused();
});
