import createClient from "openapi-fetch";

const client = createClient({
  baseUrl: process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000",
});

export default client;
