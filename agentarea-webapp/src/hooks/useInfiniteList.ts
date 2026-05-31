"use client";

import { useCallback, useEffect, useRef, useState } from "react";

interface PaginatedResult<T> {
  items: T[];
  total: number;
  has_next: boolean;
}

interface UseInfiniteListOptions<T> {
  fetchPage: (params: {
    page: number;
    page_size: number;
    search?: string;
  }) => Promise<PaginatedResult<T>>;
  pageSize?: number;
  search?: string;
  /**
   * Extra serialized state (e.g. active filters) that, when changed,
   * resets pagination and reloads from page 1 — same as a search change.
   */
  resetKey?: string;
}

interface UseInfiniteListReturn<T> {
  items: T[];
  total: number;
  isLoading: boolean;
  isFetchingMore: boolean;
  hasMore: boolean;
  error: string | null;
  sentinelRef: (node: HTMLElement | null) => void;
  reset: () => void;
}

export function useInfiniteList<T>({
  fetchPage,
  pageSize = 50,
  search,
  resetKey,
}: UseInfiniteListOptions<T>): UseInfiniteListReturn<T> {
  const [items, setItems] = useState<T[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [isLoading, setIsLoading] = useState(true);
  const [isFetchingMore, setIsFetchingMore] = useState(false);
  const [hasMore, setHasMore] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const observerRef = useRef<IntersectionObserver | null>(null);
  const fetchPageRef = useRef(fetchPage);
  fetchPageRef.current = fetchPage;

  const isFetchingRef = useRef(false);

  const loadPage = useCallback(
    async (pageNum: number, currentSearch?: string) => {
      if (isFetchingRef.current) return;
      isFetchingRef.current = true;

      const isFirstPage = pageNum === 1;
      if (isFirstPage) {
        setIsLoading(true);
      } else {
        setIsFetchingMore(true);
      }
      setError(null);

      try {
        const result = await fetchPageRef.current({
          page: pageNum,
          page_size: pageSize,
          search: currentSearch || undefined,
        });

        setItems((prev) => (isFirstPage ? result.items : [...prev, ...result.items]));
        setTotal(result.total);
        setHasMore(result.has_next);
        setPage(pageNum);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load data");
      } finally {
        setIsLoading(false);
        setIsFetchingMore(false);
        isFetchingRef.current = false;
      }
    },
    [pageSize]
  );

  // Reset and reload when search or any filter (resetKey) changes
  useEffect(() => {
    setItems([]);
    setPage(1);
    setHasMore(false);
    loadPage(1, search);
  }, [search, resetKey, loadPage]);

  // Load next page when sentinel becomes visible
  const sentinelRef = useCallback(
    (node: HTMLElement | null) => {
      if (observerRef.current) {
        observerRef.current.disconnect();
      }

      if (!node) return;

      observerRef.current = new IntersectionObserver(
        (entries) => {
          if (entries[0]?.isIntersecting && hasMore && !isFetchingRef.current) {
            loadPage(page + 1, search);
          }
        },
        { rootMargin: "200px" }
      );

      observerRef.current.observe(node);
    },
    [hasMore, page, search, loadPage]
  );

  // Cleanup observer on unmount
  useEffect(() => {
    return () => {
      observerRef.current?.disconnect();
    };
  }, []);

  const reset = useCallback(() => {
    setItems([]);
    setPage(1);
    setHasMore(false);
    loadPage(1, search);
  }, [search, loadPage]);

  return {
    items,
    total,
    isLoading,
    isFetchingMore,
    hasMore,
    error,
    sentinelRef,
    reset,
  };
}
