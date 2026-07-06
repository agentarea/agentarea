import { client } from "@/api/client/client.gen";

export type ServerClient = typeof client;

export function getServerClient(): ServerClient {
  return client;
}
