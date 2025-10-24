"use client";

import { useCallback, useEffect } from "react";
import { useTranslations } from "next-intl";
import { useRouter, useSearchParams } from "next/navigation";
import { Search } from "lucide-react";
import { useSearchWithDebounce } from "@/hooks";

interface SearchInputProps {
  /** Начальное значение (используется если urlParamName не указан) */
  initialValue?: string;
  /** Callback вызывается при изменении значения после debounce */
  onDebouncedChange?: (value: string) => void;
  /** Задержка debounce в миллисекундах */
  delay?: number;
  /** Placeholder для input */
  placeholder?: string;
  /** Имя URL параметра для автоматической работы с URL (например "search") */
  urlParamName?: string;
  /** Путь для обновления URL (используется только с urlParamName) */
  urlPath?: string;
}

export default function SearchInput({
  initialValue = "",
  onDebouncedChange,
  delay = 1000,
  placeholder,
  urlParamName,
  urlPath,
}: SearchInputProps) {
  const commonT = useTranslations("Common");
  const router = useRouter();
  const searchParams = useSearchParams();

  // Если указан urlParamName, читаем значение из URL
  const urlValue = urlParamName
    ? searchParams.get(urlParamName) || ""
    : initialValue;

  const {
    query: searchQuery,
    debouncedQuery,
    updateQuery,
    forceUpdate,
  } = useSearchWithDebounce(urlValue, delay);

  // Автоматическое обновление URL если указан urlParamName
  useEffect(() => {
    if (urlParamName) {
      const params = new URLSearchParams();

      if (debouncedQuery.trim()) {
        params.set(urlParamName, debouncedQuery);
      }

      const currentPath = urlPath || window.location.pathname;
      const newUrl = params.toString()
        ? `${currentPath}?${params.toString()}`
        : currentPath;
      router.replace(newUrl, { scroll: false });
    }
  }, [debouncedQuery, urlParamName, urlPath, router]);

  // Вызываем callback если он указан
  useEffect(() => {
    if (onDebouncedChange) {
      onDebouncedChange(debouncedQuery);
    }
  }, [debouncedQuery, onDebouncedChange]);

  const handleSearchChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      updateQuery(e.target.value);
    },
    [updateQuery]
  );

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLInputElement>) => {
      if (e.key === "Enter") {
        forceUpdate();
      }
    },
    [forceUpdate]
  );

  return (
    <div className="relative w-full transition-all duration-300">
      <div className="absolute left-0 top-1/2 -translate-y-1/2 transform text-muted-foreground">
        <Search className="h-4 w-4" />
      </div>

      <input
        placeholder={placeholder || commonT("search")}
        className="w-full border-none py-2 pl-6 text-sm font-light hover:border-none focus:border-none focus:outline-none focus:ring-0"
        value={searchQuery}
        onChange={handleSearchChange}
        onKeyDown={handleKeyDown}
      />
    </div>
  );
}
