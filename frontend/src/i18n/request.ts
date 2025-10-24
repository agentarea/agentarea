import { getRequestConfig } from "next-intl/server";
import { cookies, headers } from "next/headers";

export default getRequestConfig(async () => {
  // First try to get locale from cookies
  const cookieStore = await cookies();
  const cookieLocale = cookieStore.get("NEXT_LOCALE")?.value;

  // If no locale in cookies, get from browser preferences
  if (!cookieLocale) {
    const headersList = await headers();
    const acceptLanguage = headersList.get("accept-language");
    const browserLocale = acceptLanguage?.split(",")[0]?.split("-")[0] || "en";

    try {
      // Try to import messages for browser locale
      const messages = (await import(`../../messages/${browserLocale}.json`))
        .default;
      return {
        locale: browserLocale,
        messages,
      };
    } catch {
      // If messages for browser locale don't exist, fall back to 'en'
      return {
        locale: "en",
        messages: (await import(`../../messages/en.json`)).default,
      };
    }
  }

  return {
    locale: cookieLocale,
    messages: (await import(`../../messages/${cookieLocale}.json`)).default,
  };
});
