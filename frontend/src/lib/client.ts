import createClient from "openapi-fetch";
import type { paths } from "../api/schema";

const client = createClient<paths>({
  baseUrl: process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000",
});

export default client;
