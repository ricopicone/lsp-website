// Bundled (vendored) TipTap document editor for the Workgroup Work tab.
// Built to static/js/vendor/doc-editor.js via `npm run build:js`.
//
// The page calls window.LSPDocEditor.init({...}) with Django-injected values
// (URLs, CSRF token, initial HTML). No network imports at runtime.

import { Editor } from "@tiptap/core";
import StarterKit from "@tiptap/starter-kit";
import Link from "@tiptap/extension-link";
import Placeholder from "@tiptap/extension-placeholder";

function init(opts) {
  const {
    mount,          // #editor element selector
    toolbar,        // #toolbar element selector
    statusEl,       // #save-status element selector
    titleEl,        // #doc-title input selector
    autosaveUrl,
    csrf,
    initialHTML = "",
  } = opts;

  const editor = new Editor({
    element: document.querySelector(mount),
    extensions: [
      StarterKit.configure({ link: false }),
      Link.configure({ openOnClick: false }),
      Placeholder.configure({ placeholder: "Start writing…" }),
    ],
    content: "",
  });
  editor.commands.setContent(initialHTML || "");

  const statusNode = document.querySelector(statusEl);
  const titleNode = document.querySelector(titleEl);
  const tb = document.querySelector(toolbar);

  const buttons = [
    ["Bold", () => editor.chain().focus().toggleBold().run(), () => editor.isActive("bold")],
    ["Italic", () => editor.chain().focus().toggleItalic().run(), () => editor.isActive("italic")],
    ["H1", () => editor.chain().focus().toggleHeading({ level: 1 }).run(), () => editor.isActive("heading", { level: 1 })],
    ["H2", () => editor.chain().focus().toggleHeading({ level: 2 }).run(), () => editor.isActive("heading", { level: 2 })],
    ["H3", () => editor.chain().focus().toggleHeading({ level: 3 }).run(), () => editor.isActive("heading", { level: 3 })],
    ["• List", () => editor.chain().focus().toggleBulletList().run(), () => editor.isActive("bulletList")],
    ["1. List", () => editor.chain().focus().toggleOrderedList().run(), () => editor.isActive("orderedList")],
    ["Quote", () => editor.chain().focus().toggleBlockquote().run(), () => editor.isActive("blockquote")],
    ["Code", () => editor.chain().focus().toggleCodeBlock().run(), () => editor.isActive("codeBlock")],
    ["Link", () => {
      const prev = editor.getAttributes("link").href || "";
      const href = window.prompt("Link URL", prev);
      if (href === null) return;
      if (href === "") { editor.chain().focus().unsetLink().run(); return; }
      editor.chain().focus().extendMarkRange("link").setLink({ href }).run();
    }, () => editor.isActive("link")],
    ["↶", () => editor.chain().focus().undo().run(), () => false],
    ["↷", () => editor.chain().focus().redo().run(), () => false],
  ];
  const els = buttons.map(([label, cmd]) => {
    const b = document.createElement("button");
    b.type = "button";
    b.textContent = label;
    b.className = "pm-btn hover:bg-base-200";
    b.addEventListener("click", () => cmd());
    tb.appendChild(b);
    return b;
  });
  function refreshToolbar() {
    buttons.forEach(([, , active], i) => els[i].classList.toggle("is-active", active()));
  }

  let timer = null;
  let dirty = false;
  async function save() {
    dirty = false;
    statusNode.textContent = "Saving…";
    const body = new URLSearchParams({ content: editor.getHTML() });
    try {
      const r = await fetch(autosaveUrl, {
        method: "POST",
        headers: { "X-CSRFToken": csrf, "Content-Type": "application/x-www-form-urlencoded" },
        body,
      });
      const data = await r.json();
      if (r.status === 409) {
        statusNode.textContent = "Locked — " + data.locked_by + " is editing. Your changes are not being saved.";
        return;
      }
      statusNode.textContent = "Saved " + (data.saved_at || "");
    } catch (e) {
      statusNode.textContent = "Offline — will retry";
      dirty = true;
    }
  }
  function scheduleSave() {
    dirty = true;
    clearTimeout(timer);
    timer = setTimeout(save, 1200);
  }

  editor.on("update", () => { scheduleSave(); refreshToolbar(); });
  editor.on("selectionUpdate", refreshToolbar);
  refreshToolbar();

  // Heartbeat keeps the soft lock alive while idle.
  setInterval(() => { if (!dirty) save(); }, 60000);

  if (titleNode) {
    titleNode.addEventListener("blur", () => {
      const body = new URLSearchParams({ content: editor.getHTML(), title: titleNode.value });
      fetch(autosaveUrl, {
        method: "POST",
        headers: { "X-CSRFToken": csrf, "Content-Type": "application/x-www-form-urlencoded" },
        body,
      });
    });
  }

  window.addEventListener("beforeunload", () => {
    if (dirty) navigator.sendBeacon(autosaveUrl, new URLSearchParams({ content: editor.getHTML() }));
  });

  return editor;
}

window.LSPDocEditor = { init };
