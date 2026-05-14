# ABCX Plugin - Aligned Format Support

## Summary

The ABCX plugin has been enhanced to support **aligned ABCX format** (`_aligned.abcx`), a phrase-aligned music notation format.

## What's New

✅ **Format Detection**: Automatically detects aligned ABCX files  
✅ **Syntax Highlighting**: H markers (cyan), M markers (yellow)  
✅ **Preview**: Converts to standard ABC and renders beautifully  
✅ **Lint**: Validates structure and reports errors  
✅ **Export**: MIDI, SVG, and standard ABC export  

## Quick Test

```bash
# Run the test suite
node test_aligned_format.js

# Expected output:
# ✓ Format detection: true
# ✓ Phrases detected: 25
# ✓ Diagnostics: 0
# ✓ ABCJS validation: passed
```

## Documentation

- [QUICKSTART_CN.md](abcx/QUICKSTART_CN.md) - 快速入门指南（中文）
- [ALIGNED_FORMAT_CN.md](abcx/ALIGNED_FORMAT_CN.md) - 完整文档（中文）
- [ALIGNED_FORMAT.md](abcx/ALIGNED_FORMAT.md) - Full documentation (English)
- [CHANGES.md](abcx/CHANGES.md) - Implementation details

## Files Modified

- `abcx/src/abcx.js` - Core parser with aligned format support
- `abcx/src/extension.js` - Extension integration
- `abcx/config/abc.tmGrammar.json` - Syntax highlighting rules
- `abcx/package.json` - Color configuration

## Activation

Reload VS Code window to activate:
1. Press `Ctrl+Shift+P` (or `Cmd+Shift+P` on Mac)
2. Type "Developer: Reload Window"
3. Open an aligned ABCX file to test

Enjoy! 🎵
