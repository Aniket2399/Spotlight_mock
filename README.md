## Project Notes

Thank you for this opportunity! Building this converter was an excellent learning experience that challenged me to solve complex design-to-code translation problems.

### Known Limitations

**Figma API Rate Limiting:**  
During development, I encountered Figma's API rate limits (see screenshot below). To work around this, I used the exported JSON file directly for the provided design assignment.

<img width="679" height="83" alt="Screenshot 2025-11-22 at 6 11 18 AM" src="https://github.com/user-attachments/assets/af6bf18c-9747-42f1-9289-c2ea0fedb528" />

**Current Scope:**  
This converter is optimized for the specific Figma design provided in the assignment. While the architecture is designed to be generalizable, it may require additional edge case handling to work flawlessly with all Figma designs.

### Known Visual Discrepancies

1. **Input Container Border Radius:** The parent frame containing email/password fields doesn't display rounded corners, though individual input frames do. This requires additional border-radius inheritance logic.

2. **Font Weight Appearance:** The "Sign In" text appears lighter than in Figma despite correct CSS (`font-weight: 700`). This is a browser font-rendering issue. **Note:** If you inspect the element in DevTools, you'll see the CSS properties match Figma's specifications exactly—the discrepancy is in how browsers render the font, not in the code.

**Future Enhancements:**  
With more time, these edge cases and visual inconsistencies can be resolved through:
- Improved frame property inheritance handling
- Font preloading and rendering optimization
- Additional testing across different design patterns

## Quick Start
```bash
python softlight_mock.py <YOUR_TOKEN> <YOUR_FILE_KEY>
# Generates: output.html + styles.css
```
** Download the html and css file in same folder and run with your browser.(Without running code)

**Debug Tip:** To verify the font-weight issue, inspect the "Sign In" text in your browser's DevTools and compare the computed styles with Figma's design properties.
