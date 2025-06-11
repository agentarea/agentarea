# Static Assets Directory

This directory contains all static assets served by the AgentArea API.

## Structure

```
core/static/
├── README.md
└── icons/
    └── providers/
        ├── README.md
        ├── default.svg
        ├── openai.svg
        ├── anthropic.svg
        └── ... (all provider icons)
```

## Accessing Static Files

All files in this directory are served at the `/static/` endpoint:

- **Icons**: `/static/icons/providers/{icon_name}.svg`
- **Future assets**: `/static/{path}/{filename}`

## Adding New Static Assets

To add new types of static assets:

1. Create a new subdirectory in `core/static/`
2. Add your files
3. Access them via `/static/{subdirectory}/{filename}`

Examples:
- **Images**: `core/static/images/logo.png` → `/static/images/logo.png`
- **CSS**: `core/static/css/styles.css` → `/static/css/styles.css`  
- **JS**: `core/static/js/script.js` → `/static/js/script.js`
- **Documents**: `core/static/docs/api.pdf` → `/static/docs/api.pdf`

## Benefits

✅ **No route configuration needed** - Just add files and they're served  
✅ **Scalable** - Works for any file type  
✅ **Standard web pattern** - Familiar `/static/` convention  
✅ **Automatic MIME types** - FastAPI handles content-type headers  
✅ **Caching friendly** - Standard static file caching applies 