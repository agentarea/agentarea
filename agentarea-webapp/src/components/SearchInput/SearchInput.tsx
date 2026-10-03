"use client";

import { useCallback, useEffect, useRef } from "react";
import { useTranslations } from "next-intl";
import { useSearchParams } from "next/navigation";
import { useWorkspaceRouter } from "@/hooks/useWorkspaceNavigation";
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
  /** URL параметры, которые нужно сбросить при изменении поиска */
  resetParamNames?: string[];
}

export default function SearchInput({
  initialValue = "",
  onDebouncedChange,
  delay = 1000,
  placeholder,
  urlParamName,
  urlPath,
  resetParamNames,
}: SearchInputProps) {
  const commonT = useTranslations("Common");
  const router = useWorkspaceRouter();
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
    resetQuery,
  } = useSearchWithDebounce(urlValue, delay);

  // Значения, которые инпут сам записал в URL и ещё не увидел обратно. Всё
  // остальное, что приходит в URL (ссылка «Сбросить поиск», назад/вперёд,
  // смена таба под шапкой, которая не перемонтируется), пришло извне: инпут
  // принимает это значение, а не пишет свой устаревший запрос поверх.
  const pendingWrites = useRef(new Set<string>());
  const seenUrlValue = useRef(urlValue);
  const lastDebounced = useRef(debouncedQuery);

  useEffect(() => {
    if (!urlParamName || urlValue === seenUrlValue.current) return;
    seenUrlValue.current = urlValue;
    if (pendingWrites.current.delete(urlValue)) return;
    pendingWrites.current.clear();
    resetQuery(urlValue);
  }, [urlParamName, urlValue, resetQuery]);

  // Автоматическое обновление URL если указан urlParamName
  useEffect(() => {
    if (urlParamName) {
      // Пишем только то, что пользователь набрал сам: эффект срабатывает и на
      // смену searchParams, а тогда debouncedQuery ещё старый
      if (debouncedQuery === lastDebounced.current) return;
      lastDebounced.current = debouncedQuery;

      const nextQuery = debouncedQuery.trim() ? debouncedQuery : "";
      if (nextQuery === (searchParams.get(urlParamName) || "")) return;

      const params = new URLSearchParams(searchParams.toString());

      if (debouncedQuery.trim()) {
        params.set(urlParamName, debouncedQuery);
      } else {
        params.delete(urlParamName);
      }
      resetParamNames?.forEach((paramName) => params.delete(paramName));

      const currentString = searchParams.toString();
      const newString = params.toString();

      if (currentString !== newString) {
        const currentPath = urlPath || window.location.pathname;
        const newUrl = newString ? `${currentPath}?${newString}` : currentPath;
        pendingWrites.current.add(nextQuery);
        router.replace(newUrl, { scroll: false });
      }
    }
  }, [
    debouncedQuery,
    urlParamName,
    urlPath,
    resetParamNames,
    router,
    searchParams,
  ]);

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
    <div className="relative w-full">
      <div className="absolute left-0 top-1/2 -translate-y-1/2 transform text-muted-foreground">
        <Search className="h-4 w-4" />
      </div>

      <input
        placeholder={placeholder || commonT("search")}
        className="w-full border-none py-2 pl-6 text-sm font-light hover:border-none focus:border-none focus:outline-none focus:ring-0 dark:bg-zinc-800"
        value={searchQuery}
        onChange={handleSearchChange}
        onKeyDown={handleKeyDown}
      />
    </div>
  );
}
