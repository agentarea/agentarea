import { useMemo } from "react";
import { useSearchWithDebounce, useTabState } from "../../../hooks";

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

// Реэкспорт универсальных хуков
export { useSearchWithDebounce, useTabState }; 