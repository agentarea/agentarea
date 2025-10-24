import { useCallback, useState } from "react";
import { deleteCookie, getCookie, setCookie } from "../utils/cookies";

// Кастомный хук для работы с куки
export function useCookie(key: string, defaultValue: string | null = null) {
  const [value, setValue] = useState<string | null>(() => {
    if (typeof window !== "undefined") {
      return getCookie(key) || defaultValue;
    }
    return defaultValue;
  });

  const updateValue = useCallback(
    (newValue: string | null) => {
      if (newValue === null) {
        deleteCookie(key);
      } else {
        setCookie(key, newValue);
      }
      setValue(newValue);
    },
    [key]
  );

  return [value, updateValue] as const;
}
