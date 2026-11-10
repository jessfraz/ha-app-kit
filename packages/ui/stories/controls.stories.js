/** @type {import('@storybook/html-vite').Meta} */
const meta = { title: "Components/Controls", tags: ["autodocs"] };
export default meta;

/** @type {import('@storybook/html-vite').StoryObj} */
export const Form = {
  render: () => {
    const main = document.createElement("main");
    const heading = document.createElement("h1");
    heading.textContent = "Connection settings";
    const form = document.createElement("form");
    form.style.cssText = "display:grid;gap:20px;max-width:440px";
    const label = document.createElement("label");
    label.htmlFor = "location";
    label.textContent = "Mailbox";
    const select = document.createElement("select");
    select.id = "location";
    select.name = "location";
    for (const text of ["Choose a mailbox", "Example mailbox"]) {
      const option = document.createElement("option");
      option.textContent = text;
      option.value = text === "Example mailbox" ? "example" : "";
      select.append(option);
    }
    label.append(select);
    const account = document.createElement("label");
    account.textContent = "Provider account";
    const accountInput = document.createElement("input");
    accountInput.value = "Example provider";
    accountInput.disabled = true;
    account.append(accountInput);
    const requirements = document.createElement("details");
    const summary = document.createElement("summary");
    summary.textContent = "Connection requirements";
    const help = document.createElement("p");
    help.textContent = "Choose a mailbox before saving the connection.";
    requirements.append(summary, help);
    const save = document.createElement("button");
    save.type = "submit";
    save.textContent = "Save";
    save.disabled = true;
    select.addEventListener("change", () => {
      save.disabled = select.value === "";
    });
    form.addEventListener("submit", (event) => event.preventDefault());
    const checkbox = document.createElement("label");
    const check = document.createElement("input");
    check.type = "checkbox";
    checkbox.append(check, document.createTextNode("Enable notifications"));
    const group = document.createElement("fieldset");
    const legend = document.createElement("legend");
    legend.textContent = "Notification detail";
    group.append(legend);
    for (const [value, title] of [
      ["counts", "Counts only"],
      ["sender", "Sender names"],
    ]) {
      const option = document.createElement("label");
      const radio = document.createElement("input");
      radio.type = "radio";
      radio.name = "notification-detail";
      radio.value = value;
      radio.checked = value === "counts";
      option.append(radio, document.createTextNode(title));
      group.append(option);
    }
    const notes = document.createElement("label");
    const textarea = document.createElement("textarea");
    textarea.rows = 3;
    notes.append(document.createTextNode("Notes"), textarea);
    const disabledSecondary = document.createElement("button");
    disabledSecondary.type = "button";
    disabledSecondary.className = "quiet";
    disabledSecondary.textContent = "Reconnect";
    disabledSecondary.disabled = true;
    form.append(
      label,
      account,
      checkbox,
      group,
      notes,
      requirements,
      save,
      disabledSecondary,
    );
    main.append(heading, form);
    return main;
  },
};

/** @type {import('@storybook/html-vite').StoryObj} */
export const Dialog = {
  render: () => {
    const main = document.createElement("main");
    const heading = document.createElement("h1");
    heading.textContent = "Dialogs";
    const open = document.createElement("button");
    open.textContent = "View details";
    open.type = "button";
    const dialog = document.createElement("dialog");
    dialog.setAttribute("aria-labelledby", "detail-title");
    const title = document.createElement("h2");
    title.id = "detail-title";
    title.textContent = "Mail details";
    const description = document.createElement("p");
    description.textContent =
      "This is fictional content for component testing.";
    const close = document.createElement("button");
    close.type = "button";
    close.textContent = "Close";
    close.className = "quiet";
    open.addEventListener("click", () => dialog.showModal());
    close.addEventListener("click", () => dialog.close());
    const header = document.createElement("div");
    header.className = "dialog-heading";
    header.append(title, close);
    dialog.append(header, description);
    main.append(heading, open, dialog);
    return main;
  },
};

/** @type {import('@storybook/html-vite').StoryObj} */
export const LongForm = {
  render: () => {
    const main = document.createElement("main");
    const heading = document.createElement("h1");
    heading.textContent = "Long forms";
    const open = document.createElement("button");
    open.type = "button";
    open.textContent = "Edit connection";
    const dialog = document.createElement("dialog");
    dialog.className = "dialog-panel";
    dialog.setAttribute("aria-labelledby", "connection-title");
    const form = document.createElement("form");
    const header = document.createElement("div");
    header.className = "dialog-heading";
    const title = document.createElement("h2");
    title.id = "connection-title";
    title.textContent = "Edit connection";
    header.append(title);
    const body = document.createElement("div");
    body.className = "dialog-body";
    for (let number = 1; number <= 12; number += 1) {
      const label = document.createElement("label");
      label.textContent = `Example field ${number}`;
      const input = document.createElement("input");
      input.value = `Fictional value ${number}`;
      label.append(input);
      body.append(label);
    }
    body.style.cssText = "display:grid;gap:18px;padding-top:20px";
    const footer = document.createElement("div");
    footer.className = "dialog-footer";
    const actions = document.createElement("div");
    actions.className = "actions";
    const cancel = document.createElement("button");
    cancel.type = "button";
    cancel.className = "quiet";
    cancel.textContent = "Cancel";
    cancel.addEventListener("click", () => dialog.close());
    const save = document.createElement("button");
    save.type = "submit";
    save.textContent = "Save connection";
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      dialog.close();
    });
    actions.append(cancel, save);
    footer.append(actions);
    form.append(header, body, footer);
    dialog.append(form);
    open.addEventListener("click", () => dialog.showModal());
    main.append(heading, open, dialog);
    return main;
  },
};
