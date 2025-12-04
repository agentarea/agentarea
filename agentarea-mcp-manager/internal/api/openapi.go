package api

import (
	"net/http"

	"github.com/gin-gonic/gin"
)

// SetupOpenAPIRoutes sets up OpenAPI documentation routes
func (h *Handler) SetupOpenAPIRoutes(router *gin.Engine) {
	// Serve OpenAPI specification
	router.GET("/openapi.yaml", h.getOpenAPISpec)
	router.GET("/openapi.json", h.getOpenAPISpecJSON)

	// Serve Swagger UI
	router.GET("/docs", h.getSwaggerUI)
	router.GET("/docs/*filepath", h.getSwaggerUIAssets)

	// API documentation redirect
	router.GET("/", func(c *gin.Context) {
		c.Redirect(http.StatusFound, "/docs")
	})
}

// getOpenAPISpec returns the OpenAPI specification in YAML format
func (h *Handler) getOpenAPISpec(c *gin.Context) {
	c.Header("Content-Type", "application/x-yaml")
	c.File("api/openapi.yaml")
}

// getOpenAPISpecJSON returns the OpenAPI specification in JSON format
func (h *Handler) getOpenAPISpecJSON(c *gin.Context) {
	// Convert YAML to JSON if needed
	c.Header("Content-Type", "application/json")
	// For now, redirect to YAML - can implement conversion later if needed
	c.Redirect(http.StatusFound, "/openapi.yaml")
}

// getSwaggerUI serves the Swagger UI HTML page
func (h *Handler) getSwaggerUI(c *gin.Context) {
	html := `<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>MCP Manager API Documentation</title>
    <link rel="stylesheet" type="text/css" href="https://unpkg.com/swagger-ui-dist@5.9.0/swagger-ui.css" />
    <style>
        html {
            box-sizing: border-box;
            overflow: -moz-scrollbars-vertical;
            overflow-y: scroll;
        }
        *, *:before, *:after {
            box-sizing: inherit;
        }
        body {
            margin: 0;
            background: #fafafa;
        }
        .swagger-ui .topbar {
            background-color: #2b3b47;
        }
        .swagger-ui .topbar .download-url-wrapper .select-label {
            color: #fff;
        }
        .custom-header {
            background: #1f2937;
            color: white;
            padding: 1rem;
            text-align: center;
            margin-bottom: 0;
        }
        .custom-header h1 {
            margin: 0;
            font-size: 2rem;
        }
        .custom-header p {
            margin: 0.5rem 0 0 0;
            opacity: 0.8;
        }
    </style>
</head>
<body>
    <div class="custom-header">
        <h1>🔧 MCP Manager API</h1>
        <p>Model Context Protocol Infrastructure Management</p>
    </div>
    <div id="swagger-ui"></div>
    <script src="https://unpkg.com/swagger-ui-dist@5.9.0/swagger-ui-bundle.js"></script>
    <script src="https://unpkg.com/swagger-ui-dist@5.9.0/swagger-ui-standalone-preset.js"></script>
    <script>
        window.onload = function() {
            const ui = SwaggerUIBundle({
                url: window.location.origin + '/openapi.yaml',
                dom_id: '#swagger-ui',
                deepLinking: true,
                presets: [
                    SwaggerUIBundle.presets.apis,
                    SwaggerUIStandalonePreset
                ],
                plugins: [
                    SwaggerUIBundle.plugins.DownloadUrl
                ],
                layout: "StandaloneLayout",
                tryItOutEnabled: true,
                supportedSubmitMethods: ['get', 'post', 'put', 'delete', 'patch'],
                defaultModelsExpandDepth: 1,
                defaultModelExpandDepth: 1,
                docExpansion: 'list',
                filter: true,
                showExtensions: true,
                showCommonExtensions: true,
                validatorUrl: null
            });
        };
    </script>
</body>
</html>`

	c.Data(http.StatusOK, "text/html; charset=utf-8", []byte(html))
}

// getSwaggerUIAssets serves static assets for Swagger UI
func (h *Handler) getSwaggerUIAssets(c *gin.Context) {
	// For simplicity, we're using CDN links in the HTML above
	// This endpoint can serve local assets if needed
	c.Status(http.StatusNotFound)
}
