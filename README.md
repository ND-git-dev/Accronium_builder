# Accordion Notes Builder (Python + Tkinter)

## 🎯 Purpose
This tool was created to help with **theoretical lectures that contain many titles and subtitles**.  
Instead of reading plain text, users can organize lecture notes into a **collapsible accordion structure**.  
This makes it easier to:
- Break down complex topics into smaller sections
- Read and memorize content step by step
- Attach images to support learning
- Export the notes into a clean HTML file with dark/light mode for better readability

In short: it’s designed for **students and lecturers** who want a structured way to study and present theoretical material.

---

## 📖 How to Use

### 1. Run the Program
python Accromium_builder.py

### 2. Add a Title
- Type your lecture topic in the **Title** field.  
- Write notes in the **Content** box (bullets are automatically normalized).  
- Optionally attach an image.  
- Click **Add Title**.

### 3. Add Subtitles
- Select a parent title from the list.  
- Enter a subtitle and content.  
- Click **Add Subtitle**.  
- You can nest subtitles as deeply as needed.

### 4. Edit or Delete Items
- Select an item from the list.  
- Use **Load**, **Save**, or **Delete** buttons to manage it.  
- Locked items cannot be edited until unlocked.

### 5. Reorder Items
- Select an item and use **Move Up/Down** to adjust order.

### 6. Lock/Unlock Items
- Select an item and click **Lock Selected**.  
- Locked items appear in red and cannot be edited, moved, or deleted until unlocked.

### 7. Export to HTML
- Click **Save HTML**.  
- Choose a location to save.  
- The program generates a responsive HTML file with dark/light theme toggle.  
- Attached images are copied automatically.

