# Provider Icons

This directory contains SVG icons for AI providers. The backend serves these icons via API endpoints, making them accessible to any frontend.

## Structure

```
core/static/icons/providers/
├── openai.svg          # OpenAI icon
├── anthropic.svg       # Anthropic icon  
├── mistral.svg         # Mistral AI icon
├── default.svg         # Fallback icon
└── ...
```

## API Access

Icons are served via: `GET /api/v1/icons/providers/{icon_name}.svg`

Example: `https://your-api.com/api/v1/icons/providers/openai.svg`

## Requirements

- **Format**: SVG only (for scalability)
- **Size**: Recommended 64x64px viewport
- **Naming**: Use the `icon` identifier from `providers.yaml`
- **Background**: Transparent
- **Aspect Ratio**: Square (1:1)

## Adding New Icons

1. Add SVG file to this directory
2. Update provider's `icon` field in `data/providers.yaml`
3. Icon will be automatically served at `/api/v1/icons/providers/{icon_name}.svg`

## Frontend Usage

The provider API includes `icon_url` in responses:

```json
{
  "id": "uuid",
  "name": "OpenAI", 
  "icon_url": "https://api.com/api/v1/icons/providers/openai.svg"
}
```

Frontend simply uses the provided URL - no mapping needed! 