import { useState, useEffect, useCallback, useMemo } from "react";
import { useCookie } from "../../../hooks/useCookie";

// Кастомный хук для работы с поиском
export function useSearchWithDebounce(initialQuery: string = "", delay: number = 1000) {
    const [searchState, setSearchState] = useState({
        query: initialQuery,
        debouncedQuery: initialQuery,
        isSearching: false
    });

    useEffect(() => {
        setSearchState(prev => ({ ...prev, isSearching: true }));
        
        const timer = setTimeout(() => {
            setSearchState(prev => ({
                ...prev,
                debouncedQuery: prev.query,
                isSearching: false
            }));
        }, delay);

        return () => clearTimeout(timer);
    }, [searchState.query, delay]);

    const updateQuery = useCallback((newQuery: string) => {
        setSearchState(prev => ({ ...prev, query: newQuery }));
    }, []);

    const forceUpdate = useCallback(() => {
        setSearchState(prev => ({
            ...prev,
            debouncedQuery: prev.query,
            isSearching: false
        }));
    }, []);

    return {
        query: searchState.query,
        debouncedQuery: searchState.debouncedQuery,
        isSearching: searchState.isSearching,
        updateQuery,
        forceUpdate
    };
}

// Кастомный хук для работы с табами
export function useTabState(pathname: string, urlTab: string | null) {
    const cookieKey = useMemo(() => {
        const cleanPath = pathname.replace(/^\/+/, '').replace(/\//g, '_');
        return `tab_${cleanPath}`;
    }, [pathname]);

    const [savedTab, setSavedTab] = useCookie(cookieKey, "grid");
    const [isTabLoaded, setIsTabLoaded] = useState(false);

    useEffect(() => {
        setIsTabLoaded(true);
    }, []);

    const currentTab = urlTab || savedTab || "grid";

    const updateTab = useCallback((tab: string) => {
        if (tab === "grid" || tab === "table") {
            setSavedTab(tab);
        }
    }, [setSavedTab]);

    return {
        currentTab,
        isTabLoaded,
        updateTab
    };
}

// Кастомный хук для фильтрации данных
export function useFilteredData<T>(
    data: T[],
    searchQuery: string,
    searchFields: (keyof T | string)[]
) {
    return useMemo(() => {
        if (!searchQuery.trim()) return data;
        
        const query = searchQuery.toLowerCase();
        return data.filter(item => {
            return searchFields.some(field => {
                const value = typeof field === 'string' 
                    ? (item as any)[field] 
                    : (item as any)[field];
                return value?.toLowerCase().includes(query);
            });
        });
    }, [data, searchQuery, searchFields]);
} 