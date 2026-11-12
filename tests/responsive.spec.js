import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

/** @type {Array<"light" | "dark">} */
const themes = ["light", "dark"];

for (const theme of themes) {
  test(`shell remains aligned and usable in ${theme}`, async ({
    page,
  }, testInfo) => {
    await page.emulateMedia({ colorScheme: theme });
    await page.goto(
      "/iframe.html?id=app-shell--long-name&viewMode=story&globals=a11y.manual:!true",
    );
    const home = page.getByRole("link", {
      name: "Property and utility records home",
    });
    const refresh = page.getByRole("button", { name: "Refresh", exact: true });
    await expect(home).toBeVisible();
    await expect(refresh).toBeInViewport({ ratio: 1 });
    const homeBox = await home.boundingBox();
    const headingBox = await page
      .getByRole("heading", { level: 1 })
      .boundingBox();
    expect(homeBox).not.toBeNull();
    expect(headingBox).not.toBeNull();
    expect(
      Math.abs((homeBox?.x ?? 0) - (headingBox?.x ?? 0)),
    ).toBeLessThanOrEqual(1);
    for (const link of await page
      .getByRole("navigation")
      .getByRole("link")
      .all()) {
      await expect(link).toBeInViewport({ ratio: 1 });
      const box = await link.boundingBox();
      expect(box?.height).toBeGreaterThanOrEqual(44);
      expect(box?.width).toBeGreaterThanOrEqual(44);
    }
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
    await page.screenshot({
      path: testInfo.outputPath(`shell-${theme}.png`),
      fullPage: true,
    });
    await page.getByRole("link", { name: "Settings", exact: true }).focus();
    await page.keyboard.press("Enter");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(
      "Settings",
    );
    await refresh.click();
    await expect(page.getByRole("contentinfo").getByRole("status")).toHaveText(
      "Refresh requested",
    );
  });
}

test("form controls stay readable on touch screens and provide press feedback", async ({
  page,
}, testInfo) => {
  await page.goto(
    "/iframe.html?id=components-controls--form&viewMode=story&globals=a11y.manual:!true",
  );
  const select = page.getByRole("combobox", { name: "Mailbox", exact: true });
  const touch = await page.evaluate(
    () => matchMedia("(pointer: coarse)").matches,
  );
  if (touch) {
    expect(
      await select.evaluate((field) =>
        parseFloat(getComputedStyle(field).fontSize),
      ),
    ).toBeGreaterThanOrEqual(16);
  }
  await select.selectOption("example");
  const save = page.getByRole("button", { name: "Save", exact: true });
  await save.scrollIntoViewIfNeeded();
  const normalBackground = await save.evaluate(
    (button) => getComputedStyle(button).backgroundImage,
  );
  const box = await save.boundingBox();
  expect(box).not.toBeNull();
  await page.mouse.move((box?.x ?? 0) + 10, (box?.y ?? 0) + 10);
  await page.mouse.down();
  expect(
    await save.evaluate((button) => getComputedStyle(button).backgroundImage),
  ).not.toEqual(normalBackground);
  await page.mouse.up();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: testInfo.outputPath("form.png"),
    fullPage: true,
  });
});

test("landscape dialog keeps its heading and actions reachable", async ({
  page,
}, testInfo) => {
  await page.goto(
    "/iframe.html?id=components-controls--long-form&viewMode=story&globals=a11y.manual:!true",
  );
  const open = page.getByRole("button", {
    name: "Edit connection",
    exact: true,
  });
  await open.focus();
  await page.keyboard.press("Enter");
  const dialog = page.getByRole("dialog", {
    name: "Edit connection",
    exact: true,
  });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole("heading")).toBeInViewport({ ratio: 1 });
  await expect(
    dialog.getByRole("button", { name: "Save connection", exact: true }),
  ).toBeInViewport({ ratio: 1 });
  const lastField = dialog.getByLabel("Example field 12", { exact: true });
  await lastField.scrollIntoViewIfNeeded();
  await lastField.fill("Fictional edited value");
  await expect(lastField).toBeInViewport({ ratio: 1 });
  await expect(dialog.getByRole("heading")).toBeInViewport({ ratio: 1 });
  await expect(
    dialog.getByRole("button", { name: "Cancel", exact: true }),
  ).toBeInViewport({ ratio: 1 });
  await page.screenshot({ path: testInfo.outputPath("dialog.png") });
  await page.keyboard.press("Escape");
  await expect(open).toBeFocused();
});

test("larger text can reflow without hiding navigation or actions", async ({
  page,
}) => {
  await page.goto(
    "/iframe.html?id=app-shell--long-name&viewMode=story&globals=a11y.manual:!true",
  );
  await page.addStyleTag({
    content:
      ":root { font-size: 200%; } .wordmark, button, .view-switch a { font-size: 1rem; }",
  });
  for (const name of ["Mail", "All mail", "Settings"]) {
    await page.getByRole("link", { name, exact: true }).click();
    await expect(page.getByRole("link", { name, exact: true })).toHaveAttribute(
      "aria-current",
      "page",
    );
  }
  await expect(
    page.getByRole("button", { name: "Refresh", exact: true }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});
