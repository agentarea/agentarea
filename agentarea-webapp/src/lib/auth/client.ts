import { Configuration, FrontendApi } from "@ory/client-fetch";
import { env } from "@/env";
import { headers } from "next/headers";

export const serverSideFrontendClient = () =>
    new FrontendApi(
        new Configuration({
            headers: {
                Accept: "application/json",
            },
            basePath: typeof window !== "undefined" ? env.NEXT_PUBLIC_ORY_SDK_URL : env.ORY_SDK_URL,
        }),
    );

export const initOverrides: RequestInit = {
    cache: "no-cache",
};

export async function getPublicUrl() {
    const h = await headers();
    const host = h.get("host");
    const protocol = h.get("x-forwarded-proto") || "http";
    return `${protocol}://${host}`;
}
