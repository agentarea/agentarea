import { useCallback, useEffect, useState } from "react";

// Универсальный хук для работы с поиском с debounce
export function useSearchWithDebounce(
  initialQuery: string = "",
  delay: number = 1000
) {
  const [searchState, setSearchState] = useState({
    query: initialQuery,
    debouncedQuery: initialQuery,
    isSearching: false,
  });

  useEffect(() => {
    setSearchState((prev) => ({ ...prev, isSearching: true }));

    const timer = setTimeout(() => {
      setSearchState((prev) => ({
        ...prev,
        debouncedQuery: prev.query,
        isSearching: false,
      }));
    }, delay);

    return () => clearTimeout(timer);
  }, [searchState.query, delay]);

  const updateQuery = useCallback((newQuery: string) => {
    setSearchState((prev) => ({ ...prev, query: newQuery }));
  }, []);

  const forceUpdate = useCallback(() => {
    setSearchState((prev) => ({
      ...prev,
      debouncedQuery: prev.query,
      isSearching: false,
    }));
  }, []);

  return {
    query: searchState.query,
    debouncedQuery: searchState.debouncedQuery,
    isSearching: searchState.isSearching,
    updateQuery,
    forceUpdate,
  };
}
