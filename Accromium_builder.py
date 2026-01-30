import tkinter as tk
from tkinter import messagebox, filedialog, simpledialog
from tkinter.scrolledtext import ScrolledText
import os
import re
import json
import shutil
import tempfile
from datetime import datetime

# ------------------------------
# State
# ------------------------------
accordion_data = {}
current_selection = ""            # e.g., "A > B > C"
selected_image_path = ""
all_paths_cache = []

# Store locks as FULL PATHS (e.g., "A > B > C") so any depth can be locked.
locked_paths = set()

draft_dirty = False               # tracks unsaved editor changes
backup_path = os.path.join(tempfile.gettempdir(), "accordion_backup.json")

# ------------------------------
# Path helpers
# ------------------------------

def get_parent_dict_and_key(path_str):
    """
    Return the dictionary that contains the item and the item's key for a given full path.
    Works for top-level and nested items.
    """
    if not path_str:
        return None, None
    parts = path_str.split(" > ")
    parent = accordion_data
    for part in parts[:-1]:
        if part not in parent:
            return None, None
        parent = parent[part].get("subtitles", {})
    last_key = parts[-1]
    if last_key not in parent:
        return None, None
    return parent, last_key

def get_item_data(path_str):
    parent, key = get_parent_dict_and_key(path_str)
    if parent is None or key not in parent:
        return None
    return parent[key]

def get_siblings(path_str):
    """Return the direct parent dict and ordered list of sibling keys."""
    if not path_str:
        return None, []
    parts = path_str.split(" > ")
    if len(parts) == 1:
        return accordion_data, list(accordion_data.keys())
    parent = accordion_data
    for part in parts[:-1]:
        if part not in parent:
            return None, []
        parent = parent[part].get("subtitles", {})
    return parent, list(parent.keys())

def ensure_parent_path(parts):
    """
    Ensure intermediate parents exist (without creating missing ones).
    Returns the final parent dict for insertion, or None if any parent missing.
    """
    parent = accordion_data
    for part in parts[:-1]:
        if part not in parent:
            return None
        if "subtitles" not in parent[part]:
            parent[part]["subtitles"] = {}
        parent = parent[part]["subtitles"]
    return parent

def any_ancestor_locked(path_str):
    """
    Return the first locked ancestor full path if any, else None.
    Checks path at all depths from root down to self.
    """
    parts = path_str.split(" > ")
    for i in range(len(parts)):
        candidate = " > ".join(parts[:i+1])
        if candidate in locked_paths:
            return candidate
    return None

# ------------------------------
# Backup / Restore
# ------------------------------

def save_backup():
    try:
        payload = {
            "accordion_data": accordion_data,
            "locked_paths": list(locked_paths),
            "selected_image_path": selected_image_path,
            "timestamp": datetime.now().isoformat()
        }
        with open(backup_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("Backup save failed:", e)

def load_backup_if_available():
    if os.path.exists(backup_path):
        resp = messagebox.askyesno("Restore Backup", "A previous backup was found. Restore it?")
        if resp:
            try:
                with open(backup_path, "r", encoding="utf-8") as f:
                    payload = json.load(f)
                if isinstance(payload.get("accordion_data", {}), dict):
                    global accordion_data, locked_paths, selected_image_path
                    accordion_data = payload["accordion_data"]
                    locked_paths = set(payload.get("locked_paths", []))
                    selected_image_path = payload.get("selected_image_path", "")
            except Exception as e:
                messagebox.showwarning("Backup Error", f"Could not restore backup.\n{e}")
        else:
            if messagebox.askyesno("Remove Backup", "Delete backup file?"):
                try:
                    os.remove(backup_path)
                except Exception as e:
                    messagebox.showwarning("Backup Error", f"Could not delete backup.\n{e}")

# ------------------------------
# Bullet normalization and HTML
# ------------------------------

bullet_start_regex = re.compile(r'^\s*(?:[-*+•]|(?:\d+\.))\s+')

def normalize_universal_bullets(text):
    """
    Normalize any leading -, *, +, •, or numbered bullets to '• '.
    Does not alter non-bullet lines.
    """
    lines = text.split("\n")
    normalized = []
    for ln in lines:
        if bullet_start_regex.match(ln):
            content = bullet_start_regex.sub("", ln).strip()
            normalized.append(f"• {content}")
        else:
            normalized.append(ln)
    return "\n".join(normalized)

def content_to_html(content):
    """
    Convert normalized content into HTML.
    - Consecutive '• ' lines become a <ul><li> list.
    - Other lines become <p>.
    """
    content = content.strip()
    if not content:
        return ""
    lines = content.split("\n")
    html_parts = []
    list_buffer = []

    def flush_list():
        if list_buffer:
            html_parts.append("<ul>")
            for item in list_buffer:
                html_parts.append(f"<li>{item}</li>")
            html_parts.append("</ul>")
            list_buffer.clear()

    for ln in lines:
        if ln.startswith("• "):
            list_buffer.append(ln[2:].strip())
        else:
            flush_list()
            if ln.strip():
                html_parts.append(f"<p>{ln.strip()}</p>")
    flush_list()
    return "\n".join(html_parts)

# ------------------------------
# GUI actions
# ------------------------------

def select_image():
    global selected_image_path, draft_dirty
    filepath = filedialog.askopenfilename(
        title="Select Image",
        filetypes=(("Image Files", "*.png;*.jpg;*.jpeg;*.gif;*.bmp"), ("All Files", "*.*"))
    )
    if filepath:
        selected_image_path = filepath
        image_path_label.config(text=os.path.basename(filepath))
        draft_dirty = True
        save_backup()
    else:
        selected_image_path = ""
        image_path_label.config(text="No image selected")

def add_title():
    global selected_image_path, draft_dirty
    title = title_entry.get().strip()
    content = normalize_universal_bullets(content_text.get("1.0", tk.END).strip())

    if not title:
        messagebox.showerror("Error", "Title cannot be empty.")
        return
    if title in accordion_data:
        messagebox.showerror("Error", "This title already exists at the main level.")
        return

    accordion_data[title] = {"content": content, "image_path": selected_image_path, "subtitles": {}}
    clear_inputs()
    update_structure_display(select_path=title)
    selected_image_path = ""
    draft_dirty = False
    save_backup()

def add_subtitle():
    """
    Add a subtitle with universal cascading lock logic:
    - If any ancestor (including selected item) is locked, force insertion under the nearest locked ancestor FULL PATH.
    - If nothing locked, insert under current_selection as usual.
    """
    global selected_image_path, draft_dirty
    title = title_entry.get().strip()
    content = normalize_universal_bullets(content_text.get("1.0", tk.END).strip())

    if not title:
        messagebox.showerror("Error", "Sub-title cannot be empty.")
        return
    if not current_selection:
        messagebox.showerror("Error", "Please select a parent to add a sub-title.")
        return

    locked_ancestor_path = any_ancestor_locked(current_selection)
    parent_path = locked_ancestor_path if locked_ancestor_path else current_selection

    # Get parent dict/key from full path
    parent_dict, parent_key = get_parent_dict_and_key(parent_path)
    if parent_dict is None or parent_key not in parent_dict:
        messagebox.showerror("Error", "Parent not found.")
        return

    # Ensure subtitles dict
    if "subtitles" not in parent_dict[parent_key]:
        parent_dict[parent_key]["subtitles"] = {}
    subs = parent_dict[parent_key]["subtitles"]

    if title in subs:
        messagebox.showerror("Error", "This sub-title already exists under the chosen parent.")
        return

    subs[title] = {"content": content, "image_path": selected_image_path, "subtitles": {}}
    new_path = parent_path + " > " + title
    clear_inputs()
    update_structure_display(select_path=new_path)
    selected_image_path = ""
    draft_dirty = False
    save_backup()

def load_selected_to_editor():
    """Explicit edit/load button: load current_selection into fields without clearing selection."""
    global selected_image_path
    if not current_selection:
        messagebox.showerror("Error", "Please select a title or sub-title to edit.")
        return
    data = get_item_data(current_selection)
    if data is None:
        messagebox.showerror("Error", "Could not find item data to edit.")
        return
    title_entry.delete(0, tk.END)
    title_entry.insert(0, current_selection.split(" > ")[-1])
    content_text.delete("1.0", tk.END)
    content_text.insert("1.0", data.get("content", ""))
    selected_image_path = data.get("image_path", "")
    image_path_label.config(text=os.path.basename(selected_image_path) if selected_image_path else "No image selected")

def save_changes():
    """Explicit save button: apply changes to the selected item."""
    global current_selection, selected_image_path, draft_dirty
    if not current_selection:
        messagebox.showerror("Error", "Please select a title or sub-title to save.")
        return

    # Block editing if any ancestor (including self) is locked
    locked_ancestor = any_ancestor_locked(current_selection)
    if locked_ancestor:
        messagebox.showinfo("Locked", f"'{locked_ancestor}' is locked. Unlock to save changes.")
        return

    parent_dict, old_key = get_parent_dict_and_key(current_selection)
    if parent_dict is None:
        messagebox.showerror("Error", "Could not find item data to save.")
        return
    item_data = parent_dict[old_key]

    new_title = title_entry.get().strip()
    new_content = normalize_universal_bullets(content_text.get("1.0", tk.END).strip())
    new_image_path = selected_image_path if selected_image_path else item_data.get("image_path", "")

    if not new_title:
        messagebox.showerror("Error", "Title field cannot be empty.")
        return
    if new_title != old_key and new_title in parent_dict:
        messagebox.showerror("Error", f"An item named '{new_title}' already exists at this level.")
        return

    # Apply data
    item_data["content"] = new_content
    item_data["image_path"] = new_image_path

    # Rename key preserving order
    if new_title != old_key:
        keys = list(parent_dict.keys())
        if old_key in keys:
            idx = keys.index(old_key)
            keys[idx] = new_title
            new_items = []
            for k in keys:
                if k == new_title:
                    new_items.append((new_title, item_data))
                else:
                    new_items.append((k, parent_dict[k]))
            parent_dict.clear()
            for k, v in new_items:
                parent_dict[k] = v
            path_parts = current_selection.split(" > ")
            path_parts[-1] = new_title
            current_selection = " > ".join(path_parts)
        else:
            messagebox.showerror("Error", "Error updating title - old title not found.")
            return
    else:
        parent_dict[old_key] = item_data

    draft_dirty = False
    save_backup()
    update_structure_display(select_path=current_selection)
    status_bar.config(text="Saved.")

def delete_item():
    global current_selection
    if not current_selection:
        messagebox.showerror("Error", "Please select a title or sub-title to delete.")
        return

    # Block deletion if any ancestor (including self) is locked
    locked_ancestor = any_ancestor_locked(current_selection)
    if locked_ancestor:
        messagebox.showinfo("Locked", f"'{locked_ancestor}' is locked. Unlock to delete.")
        return

    confirm = messagebox.askyesno("Confirm Delete",
                                  f"Delete '{current_selection}' and all its sub-items?")
    if not confirm:
        return
    parent_dict, key_to_delete = get_parent_dict_and_key(current_selection)
    if parent_dict is None or key_to_delete not in parent_dict:
        messagebox.showerror("Error", "Could not find item data to delete.")
        return
    del parent_dict[key_to_delete]
    clear_inputs()
    current_selection = ""
    save_backup()
    update_structure_display()

# ------------------------------
# Reordering
# ------------------------------

def move_item(direction):
    global current_selection
    if not current_selection:
        messagebox.showerror("Error", "Please select an item to move.")
        return

    # Block moving if any ancestor (including self) is locked
    locked_ancestor = any_ancestor_locked(current_selection)
    if locked_ancestor:
        messagebox.showinfo("Locked", f"'{locked_ancestor}' is locked. Unlock to move.")
        return

    parent_dict, siblings = get_siblings(current_selection)
    item_key = current_selection.split(" > ")[-1]
    if parent_dict is None or item_key not in siblings:
        messagebox.showerror("Error", "Could not find item or its siblings.")
        return
    try:
        idx = siblings.index(item_key)
    except ValueError:
        messagebox.showerror("Error", "Selected item not found among siblings.")
        return

    if direction == "up":
        if idx == 0:
            messagebox.showinfo("Info", "Item is already at the top.")
            return
        new_index = idx - 1
    elif direction == "down":
        if idx == len(siblings) - 1:
            messagebox.showinfo("Info", "Item is already at the bottom.")
            return
        new_index = idx + 1
    else:
        return

    siblings.insert(new_index, siblings.pop(idx))
    reordered = [(k, parent_dict[k]) for k in siblings]
    parent_dict.clear()
    for k, v in reordered:
        parent_dict[k] = v

    save_backup()
    update_structure_display(select_path=current_selection)

def move_item_up():
    move_item("up")

def move_item_down():
    move_item("down")

# ------------------------------
# Locking items (any depth, full path)
# ------------------------------

def toggle_lock_selected():
    """
    Toggle lock state for the currently selected item using its FULL PATH.
    Locked items appear red in the Listbox. Lock blocks edit/move/delete/path-change.
    New additions will be forced under the nearest locked ancestor.
    """
    global locked_paths
    if not current_selection:
        messagebox.showerror("Error", "Select an item to lock/unlock.")
        return
    full_path = current_selection
    if full_path in locked_paths:
        locked_paths.remove(full_path)
        lock_button.config(text="Lock Selected", bg="#DDDDDD", fg="black")
        status_bar.config(text=f"Unlocked {full_path}")
    else:
        locked_paths.add(full_path)
        lock_button.config(text="Unlock Selected", bg="#FFCC88", fg="black")
        status_bar.config(text=f"Locked {full_path}")
    save_backup()
    update_structure_display(select_path=current_selection)

# ------------------------------
# Path change (safe move; blocked if any ancestor locked)
# ------------------------------

def change_path():
    global current_selection
    if not current_selection:
        messagebox.showerror("Error", "Select an item to change path.")
        return

    # Block path change if any ancestor (including self) is locked
    locked_ancestor = any_ancestor_locked(current_selection)
    if locked_ancestor:
        messagebox.showinfo("Locked", f"'{locked_ancestor}' is locked. Unlock to change path.")
        return

    new_path = simpledialog.askstring("Change Path",
                                      "Enter new path (e.g., 'Parent > Child'):\nParents must already exist.")
    if not new_path:
        return
    new_parts = [p.strip() for p in new_path.split(" > ") if p.strip()]
    if not new_parts:
        messagebox.showerror("Error", "Invalid path.")
        return

    # Safe move
    src_parent, src_key = get_parent_dict_and_key(current_selection)
    if src_parent is None or src_key not in src_parent:
        messagebox.showerror("Error", "Original item not found.")
        return
    item_copy = src_parent[src_key]

    # Remove from old
    del src_parent[src_key]

    # Insert in new parent
    dest_parent = ensure_parent_path(new_parts)
    if dest_parent is None:
        messagebox.showerror("Error", "Destination parent not found.")
        # restore original
        src_parent[src_key] = item_copy
        return
    dest_key = new_parts[-1]
    if dest_key in dest_parent:
        messagebox.showerror("Error", f"An item named '{dest_key}' already exists at destination.")
        # restore original
        src_parent[src_key] = item_copy
        return

    dest_parent[dest_key] = item_copy
    current_selection = " > ".join(new_parts)
    save_backup()
    update_structure_display(select_path=current_selection)

# ------------------------------
# Editor behaviors
# ------------------------------

def mark_dirty(event=None):
    global draft_dirty
    draft_dirty = True
    save_backup()

def right_click_menu(event):
    menu = tk.Menu(root, tearoff=0)
    menu.add_command(label="Paste", command=lambda: content_text.event_generate("<<Paste>>"))
    menu.add_command(label="Copy", command=lambda: content_text.event_generate("<<Copy>>"))
    menu.add_command(label="Cut", command=lambda: content_text.event_generate("<<Cut>>"))
    try:
        menu.tk_popup(event.x_root, event.y_root)
    finally:
        menu.grab_release()

def clear_inputs():
    global selected_image_path, draft_dirty
    title_entry.delete(0, tk.END)
    content_text.delete("1.0", tk.END)
    selected_image_path = ""
    image_path_label.config(text="No image selected")
    draft_dirty = False

def content_text_edit_normalize():
    # Normalize bullets non-destructively
    text = content_text.get("1.0", tk.END)
    normalized = normalize_universal_bullets(text)
    if normalized != text:
        idx = content_text.index(tk.INSERT)
        content_text.delete("1.0", tk.END)
        content_text.insert("1.0", normalized)
        try:
            content_text.mark_set(tk.INSERT, idx)
        except Exception:
            pass

# ------------------------------
# HTML generation (responsive + dark/light toggle)
# ------------------------------

images_to_copy = []

def generate_html(data, is_sub=False):
    global images_to_copy
    html = ""
    for title, details in data.items():
        content_html = content_to_html(details.get("content", ""))
        image_path = details.get("image_path", "")
        subtitles = details.get("subtitles", {})

        image_html = ""
        if image_path and os.path.exists(image_path):
            img_filename = os.path.basename(image_path)
            image_html = f'<img src="{img_filename}" alt="{title} image" class="acc-image">'
            if image_path not in images_to_copy:
                images_to_copy.append(image_path)
        elif image_path:
            image_html = f'<p class="img-missing">Image not found: {os.path.basename(image_path)}</p>'

        item_class = 'sub-accordion' if is_sub else 'accordion-item'
        header_class = 'sub-accordion-header' if is_sub else 'accordion-header'
        content_class = 'sub-accordion-content' if is_sub else 'accordion-content'

        html += f"""
        <div class="{item_class}">
            <button class="{header_class}" onclick="toggleAccordion(this.parentElement)">
                <span class="{'sub-arrow' if is_sub else 'accordion-arrow'}">➤</span>
                <span class="title-text">{title}</span>
            </button>
            <div class="{content_class}">
                {content_html}
                {image_html}
                {generate_html(subtitles, is_sub=True)}
            </div>
        </div>"""
    return html

def save_html():
    global images_to_copy
    images_to_copy = []
    html_header = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Dynamic Accordion</title>
<style>
    :root {
        --bg: #0f172a;        /* dark bg */
        --panel: #111827;     /* dark panel */
        --muted: #94a3b8;     /* dark muted */
        --text: #e5e7eb;      /* dark text */
        --accent: #38bdf8;    /* accent */
        --border: #1f2937;    /* border */
        --hover: rgba(2,132,199,0.12);
    }
    :root.light {
        --bg: #ffffff;
        --panel: #f8fafc;
        --muted: #334155;
        --text: #111827;
        --accent: #0ea5e9;
        --border: #e5e7eb;
        --hover: rgba(14,165,233,0.12);
    }
    * { box-sizing: border-box; }
    body {
        margin: 0; padding: 24px 16px;
        background: var(--bg);
        color: var(--text);
        font-family: Inter, system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif;
    }
    .wrap { max-width: 960px; margin: 0 auto; }
    .topbar {
        display: flex; gap: 12px; justify-content: space-between; align-items: center; margin-bottom: 16px;
    }
    .topbar h1 { font-size: 22px; margin: 0; }
    .theme-toggle {
        border: 1px solid var(--border); background: var(--panel);
        color: var(--text); padding: 8px 12px; border-radius: 8px; cursor: pointer;
    }
    .theme-toggle:hover { background: var(--hover); }
    .accordion { display: grid; gap: 12px; }
    .accordion-item, .sub-accordion {
        border: 1px solid var(--border); border-radius: 12px; background: var(--panel); overflow: hidden;
    }
    .accordion-header, .sub-accordion-header {
        width: 100%; text-align: left; cursor: pointer; background: transparent; color: var(--text); border: 0;
        padding: 12px 14px; display: flex; align-items: center; gap: 10px; font-weight: 600;
    }
    .accordion-header:hover, .sub-accordion-header:hover { background: var(--hover); }
    .accordion-arrow, .sub-arrow {
        display: inline-block; margin-right: 2px; transition: transform 0.2s ease; color: var(--accent);
    }
    .accordion-item.active .accordion-arrow, .sub-accordion.active .sub-arrow { transform: rotate(90deg); }
    .accordion-content, .sub-accordion-content {
        display: none; padding: 14px 16px 16px; border-top: 1px solid var(--border); color: var(--text);
    }
    .accordion-item.active > .accordion-content, .sub-accordion.active > .sub-accordion-content { display: block; }
    ul { margin: 8px 0 8px 22px; }
    li { margin: 4px 0; }
    p { margin: 8px 0; color: var(--muted); }
    .acc-image {
        max-width: 100%; height: auto; border-radius: 8px; border: 1px solid var(--border); margin-top: 8px;
        box-shadow: 0 6px 16px rgba(0,0,0,0.12);
    }
    .img-missing { color: #ef4444; font-size: 12px; }
    /* Responsive */
    @media (max-width: 640px) {
        .wrap { max-width: 100%; }
        .accordion-header, .sub-accordion-header { padding: 10px 12px; }
        .accordion-content, .sub-accordion-content { padding: 10px 12px; }
        .topbar h1 { font-size: 18px; }
    }
</style>
</head>
<body>
<div class="wrap">
    <div class="topbar">
        <h1>Dynamic Accordion</h1>
        <button class="theme-toggle" onclick="toggleTheme()">Toggle Dark/Light</button>
    </div>
    <div class="accordion">
"""
    full_html = html_header + generate_html(accordion_data) + """
    </div>
</div>
<script>
function toggleAccordion(element) { element.classList.toggle('active'); }
function toggleTheme() {
    const root = document.documentElement;
    const isLight = root.classList.contains('light');
    if (isLight) { root.classList.remove('light'); }
    else { root.classList.add('light'); }
}
</script>
</body>
</html>"""
    save_path = filedialog.asksaveasfilename(
        defaultextension=".html",
        filetypes=[("HTML Files", "*.html"), ("All Files", "*.*")],
        title="Save Accordion HTML"
    )
    if save_path:
        try:
            output_dir = os.path.dirname(save_path)
            with open(save_path, "w", encoding="utf-8") as f:
                f.write(full_html)
            copied = 0
            for img_path in images_to_copy:
                if os.path.exists(img_path):
                    dest_path = os.path.join(output_dir, os.path.basename(img_path))
                    try:
                        same = os.path.exists(dest_path) and os.path.samefile(img_path, dest_path)
                    except Exception:
                        same = False
                    if not same:
                        shutil.copy2(img_path, dest_path)
                    copied += 1
            messagebox.showinfo("Success", f"Generated:\n{save_path}\n\n{copied} image(s) processed.")
        except Exception as e:
            messagebox.showerror("Error Saving File", f"Could not save HTML file.\nError: {e}")
    else:
        messagebox.showinfo("Cancelled", "HTML generation cancelled.")

# ------------------------------
# Structure display and filtering
# ------------------------------

def update_structure_display(select_path=None, filter_term=None):
    global current_selection, all_paths_cache
    structure_display.delete(0, tk.END)
    structure_display.config(exportselection=False)  # keep highlight stable
    selection_index = -1
    all_paths_cache = []

    def recurse(data, path=""):
        nonlocal selection_index
        for key in list(data.keys()):
            value = data[key]
            current_path = f"{path} > {key}" if path else key
            all_paths_cache.append(current_path)

            show = True
            if filter_term:
                term_lower = filter_term.lower()
                if term_lower not in current_path.lower():
                    show = False

            if show:
                idx = structure_display.size()
                structure_display.insert(tk.END, current_path)
                # Locked items in red by full path
                if current_path in locked_paths:
                    try:
                        structure_display.itemconfig(idx, {'fg': 'red'})
                    except Exception:
                        pass
                if select_path and current_path == select_path:
                    selection_index = idx

            subs = value.get("subtitles", {})
            if subs:
                recurse(subs, current_path)

    recurse(accordion_data)

    if selection_index != -1:
        structure_display.select_clear(0, tk.END)
        structure_display.select_set(selection_index)
        structure_display.activate(selection_index)
        structure_display.see(selection_index)
        current_selection = select_path
        reflect_lock_button_state()
    elif not filter_term:
        current_selection = ""
        reflect_lock_button_state()

    if filter_term:
        status_bar.config(text=f"Filtered view ({structure_display.size()} items shown)")
    else:
        status_bar.config(text=f"Ready ({len(all_paths_cache)} total items)")

def filter_structure(event=None):
    update_structure_display(filter_term=search_entry.get().strip())
    # Keep drafts visible; no auto-clear

def on_listbox_select(event):
    global current_selection
    sel = structure_display.curselection()
    if sel:
        new_selection = structure_display.get(sel[0])
        if new_selection != current_selection:
            current_selection = new_selection
            status_bar.config(text=f"Selected: {current_selection}")
            reflect_lock_button_state()

def reflect_lock_button_state():
    """Update lock button UI based on whether current_selection is locked."""
    if not current_selection:
        lock_button.config(text="Lock Selected", bg="#DDDDDD", fg="black")
        return
    if current_selection in locked_paths:
        lock_button.config(text="Unlock Selected", bg="#FFCC88", fg="black")
    else:
        lock_button.config(text="Lock Selected", bg="#DDDDDD", fg="black")

# ------------------------------
# GUI setup
# ------------------------------

root = tk.Tk()
root.title("Accordion Notes Builder - Universal Locking")
root.geometry("840x740")

# Input frame
input_frame = tk.Frame(root)
input_frame.pack(pady=5, padx=10, fill="x")

tk.Label(input_frame, text="Title:").grid(row=0, column=0, sticky="w", padx=5, pady=2)
title_entry = tk.Entry(input_frame, width=70)
title_entry.grid(row=0, column=1, columnspan=3, sticky="ew", padx=5, pady=2)
title_entry.bind("<KeyRelease>", mark_dirty)

tk.Label(input_frame, text="Content:").grid(row=1, column=0, sticky="nw", padx=5, pady=2)
content_text = ScrolledText(input_frame, width=70, height=10, wrap=tk.WORD)
content_text.grid(row=1, column=1, columnspan=3, sticky="ew", padx=5, pady=2)
content_text.bind("<KeyRelease>", lambda e: (mark_dirty(), content_text_edit_normalize()))
content_text.bind("<Button-3>", right_click_menu)  # Right-click menu

tk.Button(input_frame, text="Select Image", command=select_image).grid(row=2, column=0, sticky="w", padx=5, pady=5)
image_path_label = tk.Label(input_frame, text="No image selected", anchor="w", fg="grey", width=60)
image_path_label.grid(row=2, column=1, columnspan=3, sticky="ew", padx=5, pady=2)

# Button frame
button_frame = tk.Frame(root)
button_frame.pack(pady=5, padx=10, fill="x")

tk.Button(button_frame, text="Add Top Level Title", command=add_title).pack(side=tk.LEFT, padx=3)
tk.Button(button_frame, text="Add Sub-Title", command=add_subtitle).pack(side=tk.LEFT, padx=3)

tk.Button(button_frame, text="Edit (Load Selected)", command=load_selected_to_editor).pack(side=tk.LEFT, padx=3)
tk.Button(button_frame, text="Save Changes", command=save_changes, bg="#C0FFC0").pack(side=tk.LEFT, padx=3)

tk.Button(button_frame, text="Delete Selected", command=delete_item, bg="#FFAAAA").pack(side=tk.LEFT, padx=3)

tk.Button(button_frame, text="Move Up ▲", command=move_item_up).pack(side=tk.LEFT, padx=3)
tk.Button(button_frame, text="Move Down ▼", command=move_item_down).pack(side=tk.LEFT, padx=3)

lock_button = tk.Button(button_frame, text="Lock Selected", command=toggle_lock_selected, bg="#DDDDDD")
lock_button.pack(side=tk.LEFT, padx=3)

tk.Button(button_frame, text="Change Path", command=change_path).pack(side=tk.LEFT, padx=3)

# Structure frame with search
structure_frame = tk.Frame(root)
structure_frame.pack(pady=10, padx=10, fill="both", expand=True)

search_frame = tk.Frame(structure_frame)
search_frame.pack(fill="x", pady=(0,5))
tk.Label(search_frame, text="Search:").pack(side=tk.LEFT, padx=(0,5))
search_entry = tk.Entry(search_frame)
search_entry.pack(side=tk.LEFT, fill="x", expand=True)
search_entry.bind("<KeyRelease>", filter_structure)

tk.Label(structure_frame, text="Structure (Select item to work with):").pack(anchor="w")

listbox_frame = tk.Frame(structure_frame)
listbox_frame.pack(fill="both", expand=True)

structure_display = tk.Listbox(listbox_frame, width=80, height=18, exportselection=False)
structure_display.pack(side=tk.LEFT, fill="both", expand=True)
structure_display.bind("<<ListboxSelect>>", on_listbox_select)

scrollbar = tk.Scrollbar(listbox_frame, orient="vertical", command=structure_display.yview)
scrollbar.pack(side=tk.RIGHT, fill="y")
structure_display.config(yscrollcommand=scrollbar.set)

# Generate button
generate_button = tk.Button(root, text="Generate HTML File", command=save_html, bg="#AADDFF", height=2)
generate_button.pack(pady=5, padx=10, fill="x")

# Status bar
status_bar = tk.Label(root, text="Ready", bd=1, relief=tk.SUNKEN, anchor=tk.W)
status_bar.pack(side=tk.BOTTOM, fill=tk.X)

# Startup
load_backup_if_available()
update_structure_display()
reflect_lock_button_state()

root.mainloop()
