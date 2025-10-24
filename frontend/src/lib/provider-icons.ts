/**
 * Maps provider names to their corresponding icon URLs
 * Icons are served from the backend via Next.js proxy
 *
 * Note: We use relative URLs so icons are proxied through Next.js
 * instead of exposing the backend API URL to the browser.
 * Configure Next.js rewrites in next.config.js to proxy /api/static/* to backend.
 */

// Use relative URL that will be proxied by Next.js
const API_BASE_URL = "/api";

// Map of provider names to icon identifiers
const PROVIDER_ICON_MAP: Record<string, string> = {
  // Major providers
  OpenAI: "openai",
  Anthropic: "anthropic",
  "Mistral AI": "mistral",
  Mistral: "mistral",
  Groq: "groq",
  "Hugging Face": "huggingface",
  Ollama: "ollama",
  "Azure OpenAI": "azure_openai",
  "Google VertexAI": "vertexai",
  "AWS Bedrock": "aws_bedrock",
  Meta: "meta",
  GitHub: "github",
  DeepSeek: "deepseek",
  Perplexity: "perplexity",
  Cohere: "cohere",
  "Together AI": "together",
  "Fireworks AI": "fireworks",
  OpenRouter: "openrouter",
  Anyscale: "anyscale",
  Replicate: "replicate",
  Baseten: "baseten",
  "Voyage AI": "voyage",
  "Jina AI": "jina",
  AI21: "ai21",
  "NLP Cloud": "nlp_cloud",
  "Aleph Alpha": "aleph_alpha",
  SambaNova: "sambanova",
  Xinference: "xinference",
  "Cloudflare Workers AI": "cloudflare",
  DeepInfra: "deepinfra",
  "Novita AI": "novita",

  // Add fallback variations
  openai: "openai",
  anthropic: "anthropic",
  mistral: "mistral",
  groq: "groq",
  ollama: "ollama",
  azure: "azure_openai",
  google: "vertexai",
  aws: "aws_bedrock",
  meta: "meta",
  github: "github",
  deepseek: "deepseek",
  perplexity: "perplexity",
  cohere: "cohere",
  together: "together",
  fireworks: "fireworks",
  replicate: "replicate",
  baseten: "baseten",
  voyage: "voyage",
  jina: "jina",
  ai21: "ai21",
  aleph_alpha: "aleph_alpha",
  sambanova: "sambanova",
  xinference: "xinference",
  cloudflare: "cloudflare",
  deepinfra: "deepinfra",
  novita: "novita",
};

/**
 * Gets the icon URL for a provider name
 * @param providerName - The provider name (e.g., "OpenAI", "Anthropic")
 * @returns The full icon URL or null if no icon exists
 */
export function getProviderIconUrl(providerName: string): string | null {
  if (!providerName) return null;

  // Try exact match first
  let iconId = PROVIDER_ICON_MAP[providerName];

  // Try lowercase match
  if (!iconId) {
    iconId = PROVIDER_ICON_MAP[providerName.toLowerCase()];
  }

  // Try partial matches for common patterns
  if (!iconId) {
    const lowerName = providerName.toLowerCase();
    for (const [key, value] of Object.entries(PROVIDER_ICON_MAP)) {
      if (
        lowerName.includes(key.toLowerCase()) ||
        key.toLowerCase().includes(lowerName)
      ) {
        iconId = value;
        break;
      }
    }
  }

  // Return full URL if icon found
  if (iconId) {
    return `${API_BASE_URL}/static/icons/providers/${iconId}.svg`;
  }

  return null;
}

/**
 * Gets a fallback icon URL
 */
export function getDefaultProviderIconUrl(): string {
  return `${API_BASE_URL}/static/icons/providers/default.svg`;
}
